"""Real ZIP upload/download verification; record hashes and identify transport."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from utf8_logs import configure_utf8_io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def multipart(filename, content):
    boundary = "m2-" + uuid.uuid4().hex
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8")
    return header + content + f"\r\n--{boundary}--\r\n".encode(), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


class TcpClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, body=None, headers=None):
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers or {}, method=method)
        try:
            response = self.opener.open(request, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), dict(response.headers)


def verify(client, fixture, report, data_dir=None):
    def get(path):
        status, body, _ = client.request("GET", path)
        assert status == 200, (status, body[:300])
        return json.loads(body)

    def upload(filename, content):
        body, headers = multipart(filename, content)
        status, response, returned_headers = client.request("POST", "/api/v1/documents", body, headers)
        return status, json.loads(response), returned_headers

    config = get("/api/v1/config")
    assert config["maxUploadBytes"] > 0
    report["config"] = config
    before = get("/api/v1/documents?limit=100")
    report["initial_total"] = before["total"]
    with zipfile.ZipFile(fixture) as archive:
        fixtures = [entry for entry in archive.infolist() if not entry.is_dir()
                    and Path(entry.filename).suffix.lower() in (".pdf", ".txt", ".md", ".markdown")]
        assert len(fixtures) >= 10, len(fixtures)
        for entry in fixtures:
            original = archive.read(entry)
            name = Path(entry.filename).name
            clock = time.perf_counter()
            original_hash = hashlib.sha256(original).hexdigest()
            status, saved, _ = upload(name, original)
            assert status == 201, (status, saved)
            assert saved["name"] == name and saved["sizeBytes"] == len(original), saved
            assert saved["sha256"] == original_hash and saved["category"] is None, saved
            assert saved["textStatus"] == "not_started" and saved["vectorStatus"] == "not_started"
            assert saved["uploadedAt"].endswith(("Z", "+00:00")), saved
            detail = get(f'/api/v1/documents/{saved["id"]}')
            assert detail == saved, (detail, saved)
            status, downloaded, headers = client.request("GET", saved["downloadUrl"])
            downloaded_hash = hashlib.sha256(downloaded).hexdigest()
            assert status == 200 and downloaded == original, (status, name)
            assert downloaded_hash == original_hash
            normalized_headers = {key.lower(): value for key, value in headers.items()}
            assert "attachment" in normalized_headers["content-disposition"]
            disposition = normalized_headers["content-disposition"]
            assert urllib.parse.quote(name) in disposition or f'filename="{name}"' in disposition
            assert normalized_headers["x-content-sha256"] == original_hash
            report["files"].append({"name": name, "extension": saved["extension"], "id": saved["id"],
                                    "size_bytes": len(original), "upload_http": 201, "detail_http": 200,
                                    "download_http": status, "original_sha256": original_hash,
                                    "download_sha256": downloaded_hash, "equal": True,
                                    "seconds": round(time.perf_counter() - clock, 4)})
            print(f'PASS {len(report["files"]):02d} {Path(name).suffix} SHA-256={original_hash}', flush=True)
    after = get("/api/v1/documents?limit=100")
    assert after["total"] == before["total"] + len(report["files"])
    assert {row["id"] for row in report["files"]}.issubset({row["id"] for row in after["items"]})
    first = get("/api/v1/documents?limit=2&offset=0")
    second = get("/api/v1/documents?limit=2&offset=2")
    assert len(first["items"]) == len(second["items"]) == 2
    assert not ({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
    report["checks"].append({"check": "list_metadata_and_pagination", "passed": True, "total": after["total"]})
    negatives = [
        ("empty_file", "empty.txt", b"", 400, "EMPTY_FILE"),
        ("unsupported_type", "bad.exe", b"content", 415, "UNSUPPORTED_FILE_TYPE"),
        ("invalid_pdf", "fake.pdf", b"plain text", 415, "INVALID_PDF"),
        ("invalid_filename", "../escape.txt", b"content", 400, "INVALID_FILENAME"),
        ("oversized_file", "large.txt", b"x" * (config["maxUploadBytes"] + 1), 413, "FILE_TOO_LARGE"),
    ]
    for check, name, body, expected_status, expected_code in negatives:
        status, error, _ = upload(name, body)
        assert status == expected_status and error["error"]["code"] == expected_code, (check, status, error)
        report["checks"].append({"check": check, "passed": True, "http": status, "error": error})
    for check, path, expected in [("unknown_file", f"/api/v1/documents/{uuid.uuid4()}", 404),
                                   ("unknown_download", f"/api/v1/documents/{uuid.uuid4()}/download", 404),
                                   ("invalid_pagination", "/api/v1/documents?limit=0", 422)]:
        status, body, _ = client.request("GET", path)
        assert status == expected, (check, status, body[:300])
        report["checks"].append({"check": check, "passed": True, "http": status})
    status, body, _ = client.request("POST", "/api/v1/documents", b"invalid", {"Content-Type": "multipart/form-data"})
    assert status == 400, (status, body[:300])
    report["checks"].append({"check": "missing_multipart_boundary", "passed": True, "http": status})
    assert get("/api/v1/documents")["total"] == after["total"], "Rejected uploads created records"
    report["checks"].append({"check": "rejected_uploads_do_not_create_records", "passed": True})
    if data_dir:
        with sqlite3.connect(data_dir / "db" / "platform.sqlite3") as connection:
            for saved in report["files"]:
                row = connection.execute("SELECT storage_key, sha256, size_bytes FROM documents WHERE id=?", (saved["id"],)).fetchone()
                assert row[1] == saved["original_sha256"] and row[2] == saved["size_bytes"]
                assert hashlib.sha256((data_dir / "uploads" / row[0]).read_bytes()).hexdigest() == row[1]
        assert not list((data_dir / "tmp").glob("*.part")) and not list((data_dir / "tmp").glob("*.intent.json"))
        report["checks"].append({"check": "independent_sqlite_and_storage_hashes", "passed": True})
    report["final_total"] = after["total"]


def main():
    configure_utf8_io()
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.data_dir and (args.data_dir.resolve() / "db/platform.sqlite3").exists():
        raise RuntimeError("Use a new empty test data directory")
    started = time.perf_counter()
    report = {"files": [], "checks": [], "failure": None, "browser_interaction": "not verified by this script"}
    try:
        if args.base_url:
            if not os.environ.get("ACCEPTANCE_TEST_RUN"):
                raise RuntimeError("External HTTP verification requires an isolated test runner marker")
            report["transport"] = "real TCP HTTP " + args.base_url
            client = TcpClient(args.base_url)
            deadline = time.perf_counter() + 120
            last_error = None
            while time.perf_counter() < deadline:
                try:
                    status, body, _ = client.request("GET", "/api/v1/health")
                    health = json.loads(body)
                    if status == 200 and health.get("database", {}).get("status") == "ready":
                        if health.get("milestone") != "M2":
                            raise ValueError("Running service is not M2; rebuild the application first")
                        report["checks"].append({"check": "real_tcp_health", "passed": True, "response": health})
                        break
                    last_error = f"HTTP {status}: {body[:200]!r}"
                except (OSError, ValueError) as error:
                    last_error = str(error)
                time.sleep(2)
            else:
                raise RuntimeError(f"M2 readiness timed out: {last_error}")
            verify(client, args.zip, report)
        else:
            if not args.data_dir:
                parser.error("--data-dir is required for in-process verification")
            data_dir = args.data_dir.resolve()
            os.environ["DATA_DIR"] = str(data_dir)
            from fastapi.testclient import TestClient
            from app.main import app

            class AsgiClient:
                def request(self, method, path, body=None, headers=None):
                    response = client.request(method, path, content=body, headers=headers)
                    return response.status_code, response.content, dict(response.headers)

            report["transport"] = "in-process ASGI TestClient; not TCP/browser proof"
            with TestClient(app) as client:
                verify(AsgiClient(), args.zip, report, data_dir)
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
        print("FAILED: " + report["failure"], flush=True)
    finally:
        report["total_seconds"] = round(time.perf_counter() - started, 3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["failure"]:
        raise SystemExit(1)
    print(f'PASS {len(report["files"])} original/download SHA-256 comparisons; {len(report["checks"])} additional checks.', flush=True)


if __name__ == "__main__":
    main()
