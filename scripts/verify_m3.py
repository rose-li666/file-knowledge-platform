"""Verify classification, archival, persisted refresh state and download integrity."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path

from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient, multipart

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def snapshot(directory):
    path = directory / "db/platform.sqlite3"
    if not path.exists():
        return {"exists": False}
    with sqlite3.connect(path) as connection:
        return {"exists": True, "version": connection.execute("PRAGMA user_version").fetchone()[0],
                "columns": [row[1] for row in connection.execute("PRAGMA table_info(documents)")],
                "hashes_by_id": dict(connection.execute("SELECT id,sha256 FROM documents"))}


def verify(client, fixture, report, data_dir=None):
    def api(method, path, body=None, expected=200):
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        status, raw, _ = client.request(method, path, payload, headers)
        assert status == expected, (method, path, status, raw[:600])
        return json.loads(raw)

    def record(name, **details):
        report["checks"].append({"check": name, "passed": True, **details})
        print("PASS " + name, flush=True)

    def documents(archived=False, category=None):
        rows = []
        offset = 0
        while True:
            parameters = {"limit": 100, "offset": offset, "archived": str(archived).lower()}
            if category is not None:
                parameters["category_id"] = category
            page = api("GET", "/api/v1/documents?" + urllib.parse.urlencode(parameters))
            assert all(bool(row["archivedAt"]) == archived for row in page["items"]), page
            rows.extend(page["items"])
            offset += len(page["items"])
            if offset >= page["total"]:
                return rows
            assert page["items"], "Pagination stopped before total"

    active = documents()
    with zipfile.ZipFile(fixture) as archive:
        fixtures = [(Path(entry.filename).name, archive.read(entry)) for entry in archive.infolist()
                    if not entry.is_dir() and Path(entry.filename).suffix.lower() in (".pdf", ".txt", ".md", ".markdown")]
    assert len(fixtures) >= 10
    matched = []
    for name, original in fixtures:
        digest = hashlib.sha256(original).hexdigest()
        row = next((row for row in active if row["name"] == name and row["sha256"] == digest), None)
        if row is None:
            payload, headers = multipart(name, original)
            status, body, _ = client.request("POST", "/api/v1/documents", payload, headers)
            assert status == 201, (status, body[:400])
            row = json.loads(body)
            active.append(row)
        status, downloaded, _ = client.request("GET", row["downloadUrl"])
        assert status == 200 and downloaded == original and hashlib.sha256(downloaded).hexdigest() == digest
        matched.append((row, original))
        report["original_files"].append({"id": row["id"], "name": name, "sha256": digest, "equal": True})
    record("existing_original_files_download_unchanged", count=len(matched))
    pdf, original = next(pair for pair in matched if pair[0]["extension"] == "pdf")
    text, _ = next(pair for pair in matched if pair[0]["extension"] in ("txt", "md"))
    suffix = uuid.uuid4().hex[:8]
    name_a, name_b = "M3验收-A-" + suffix, "M3验收-B-" + suffix
    category_a = api("POST", "/api/v1/categories", {"name": " " + name_a + " "}, 201)
    category_b = api("POST", "/api/v1/categories", {"name": name_b}, 201)
    assert category_a["name"] == name_a and category_a["activeCount"] == category_a["archivedCount"] == 0
    report["categories"] = {"a": category_a["id"], "b": category_b["id"]}
    report["document_id"] = pdf["id"]
    record("create_flat_categories")
    duplicate = api("POST", "/api/v1/categories", {"name": name_a.swapcase()}, 409)
    assert duplicate["error"]["code"] == "CATEGORY_NAME_EXISTS"
    for name in (" ", "未分类", "bad\nname", "x" * 81):
        api("POST", "/api/v1/categories", {"name": name}, 422)
    record("duplicate_and_invalid_category_feedback")
    moved = api("PATCH", f'/api/v1/documents/{pdf["id"]}/category', {"categoryId": category_a["id"]})
    api("PATCH", f'/api/v1/documents/{text["id"]}/category', {"categoryId": category_b["id"]})
    assert moved["category"]["id"] == category_a["id"] and moved["sha256"] == pdf["sha256"]
    assert {row["id"] for row in documents(category=category_a["id"])} == {pdf["id"]}
    assert {row["id"] for row in documents(category=category_b["id"])} == {text["id"]}
    record("move_documents_and_combined_category_filters")
    renamed_name = "M3验收-规范-" + suffix
    api("PATCH", f'/api/v1/categories/{category_a["id"]}', {"name": renamed_name})
    assert api("GET", f'/api/v1/documents/{pdf["id"]}')["category"]["name"] == renamed_name
    assert documents(category=category_a["id"])[0]["category"]["name"] == renamed_name
    api("PATCH", f'/api/v1/categories/{category_a["id"]}', {"name": name_b}, 409)
    assert api("GET", f'/api/v1/documents/{pdf["id"]}')["category"]["name"] == renamed_name
    record("rename_reflected_in_detail_and_list_and_conflict_preserves_name")
    api("PATCH", f'/api/v1/documents/{pdf["id"]}/category', {"categoryId": category_b["id"]})
    assert not documents(category=category_a["id"])
    assert {row["id"] for row in documents(category=category_b["id"])} == {pdf["id"], text["id"]}
    detail = api("GET", f'/api/v1/documents/{pdf["id"]}')
    assert detail["category"]["id"] == category_b["id"]
    record("move_refresh_preserves_new_category")
    archived = api("POST", f'/api/v1/documents/{pdf["id"]}/archive')
    assert archived["archivedAt"] and archived["category"]["id"] == category_b["id"]
    again = api("POST", f'/api/v1/documents/{pdf["id"]}/archive')
    assert again["archivedAt"] == archived["archivedAt"]
    assert pdf["id"] not in {row["id"] for row in documents()}
    assert pdf["id"] not in {row["id"] for row in api("GET", "/api/v1/documents")["items"]}
    assert pdf["id"] not in {row["id"] for row in documents(category=category_b["id"])}
    assert pdf["id"] in {row["id"] for row in documents(True)}
    assert {row["id"] for row in documents(True, category_b["id"])} == {pdf["id"]}
    record("default_and_category_lists_exclude_archive_while_archive_zone_includes_it")
    fresh = api("GET", f'/api/v1/documents/{pdf["id"]}')
    categories = api("GET", "/api/v1/categories")
    bucket = next(row for row in categories["items"] if row["id"] == category_b["id"])
    assert fresh["archivedAt"] == archived["archivedAt"] and bucket["activeCount"] == bucket["archivedCount"] == 1
    if data_dir:
        with sqlite3.connect(data_dir / "db/platform.sqlite3") as connection:
            value = connection.execute("SELECT category_id,archived_at FROM documents WHERE id=?", (pdf["id"],)).fetchone()
            assert value[0] == category_b["id"] and value[1]
        record("independent_disk_read_preserves_archived_state_and_category")
    record("fresh_requests_preserve_archive_and_category_counts")
    status, content, _ = client.request("GET", fresh["downloadUrl"])
    assert status == 200 and content == original
    record("archived_document_still_downloads_original_bytes")
    restored = api("POST", f'/api/v1/documents/{pdf["id"]}/restore')
    api("POST", f'/api/v1/documents/{pdf["id"]}/restore')
    refreshed = api("GET", f'/api/v1/documents/{pdf["id"]}')
    assert restored["archivedAt"] is None and refreshed["category"]["id"] == category_b["id"]
    assert pdf["id"] in {row["id"] for row in documents()}
    assert pdf["id"] in {row["id"] for row in documents(category=category_b["id"])}
    assert pdf["id"] not in {row["id"] for row in documents(True)}
    status, downloaded, headers = client.request("GET", refreshed["downloadUrl"])
    digest = hashlib.sha256(downloaded).hexdigest()
    assert status == 200 and downloaded == original and digest == pdf["sha256"]
    for key in ("name", "sizeBytes", "uploadedAt", "sha256", "textStatus", "vectorStatus"):
        assert restored[key] == pdf[key], (key, restored, pdf)
    report["restored_download"] = {"id": pdf["id"], "http": status, "original_sha256": pdf["sha256"],
                                   "download_sha256": digest, "equal": True}
    record("restore_refresh_returns_to_category_and_download_sha256_matches")
    api("PATCH", f'/api/v1/documents/{text["id"]}/category', {"categoryId": None})
    assert text["id"] in {row["id"] for row in documents(category="unclassified")}
    assert api("GET", f'/api/v1/documents/{text["id"]}')["category"] is None
    record("move_to_unclassified_and_filter")
    unknown = str(uuid.uuid4())
    api("PATCH", f'/api/v1/documents/{text["id"]}/category', {"categoryId": unknown}, 404)
    api("GET", f"/api/v1/documents?category_id={unknown}", expected=404)
    api("GET", "/api/v1/documents?category_id=invalid", expected=422)
    api("PATCH", f"/api/v1/categories/{unknown}", {"name": "missing"}, 404)
    for operation in ("archive", "restore"):
        api("POST", f"/api/v1/documents/{unknown}/{operation}", expected=404)
    assert api("GET", f'/api/v1/documents/{text["id"]}')["category"] is None
    record("invalid_targets_and_filters_return_clear_errors_without_changing_assignment")
    if data_dir:
        after = snapshot(data_dir)
        report["database_after"] = after
        assert after["version"] == 1 and {"category_id", "archived_at"}.issubset(after["columns"])
        before = report.get("database_before_startup", {}).get("hashes_by_id", {})
        assert all(after["hashes_by_id"].get(key) == value for key, value in before.items())
        record("schema_upgrade_preserves_all_existing_ids_and_hashes", existing=len(before))


def main():
    configure_utf8_io()
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--base-url")
    args = parser.parse_args()
    if args.data_dir and (args.data_dir.resolve() / "db/platform.sqlite3").exists():
        raise RuntimeError("Use a new empty test data directory")
    started = time.perf_counter()
    report = {"checks": [], "original_files": [], "failure": None,
              "browser_refresh": "not proved by API script; separate browser verification required"}
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
                    if status == 200 and health.get("milestone") == "M3":
                        report["health"] = health
                        break
                    last_error = f"HTTP {status}, milestone={health.get('milestone')}"
                except (OSError, ValueError) as error:
                    last_error = str(error)
                time.sleep(2)
            else:
                raise RuntimeError(f"M3 readiness timed out: {last_error}")
            verify(client, args.zip, report, args.data_dir)
        else:
            if not args.data_dir:
                parser.error("--data-dir is required for ASGI verification")
            directory = args.data_dir.resolve()
            report["database_before_startup"] = snapshot(directory)
            os.environ["DATA_DIR"] = str(directory)
            from fastapi.testclient import TestClient
            from app.main import app

            class AsgiClient:
                def request(self, method, path, body=None, headers=None):
                    response = client.request(method, path, content=body, headers=headers)
                    return response.status_code, response.content, dict(response.headers)

            report["transport"] = "in-process ASGI TestClient; not TCP/browser proof"
            with TestClient(app) as client:
                verify(AsgiClient(), args.zip, report, directory)
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
        print("FAILED: " + report["failure"], flush=True)
    finally:
        report["total_seconds"] = round(time.perf_counter() - started, 3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["failure"]:
        raise SystemExit(1)
    print(f'PASS {len(report["checks"])} M3 checks; restored original/download SHA-256 matched.', flush=True)


if __name__ == "__main__":
    main()
