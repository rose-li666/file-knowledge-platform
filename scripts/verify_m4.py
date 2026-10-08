"""Real-corpus literal keyword, category/archive consistency and extraction isolation checks."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import unicodedata
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
                "documents": dict(connection.execute("SELECT id,sha256 FROM documents"))}


def verify(client, fixture, report, data_dir=None):
    def api(method, path, body=None, expected=200):
        payload = json.dumps(body).encode() if body is not None else None
        status, raw, _ = client.request(method, path, payload, {"Content-Type": "application/json"} if body is not None else {})
        assert status == expected, (method, path, status, raw[:600])
        return json.loads(raw)

    def record(name, **details):
        report["checks"].append({"check": name, "passed": True, **details})
        print("PASS " + name, flush=True)

    def search(term, category=None, archived=False, limit=100, offset=0):
        parameters = {"q": term, "archived": str(archived).lower(), "limit": limit, "offset": offset}
        if category is not None:
            parameters["category_id"] = category
        return api("GET", "/api/v1/search/keyword?" + urllib.parse.urlencode(parameters))

    def all_documents():
        rows, offset = [], 0
        while True:
            page = api("GET", f"/api/v1/documents?limit=100&offset={offset}")
            rows.extend(page["items"])
            offset += len(page["items"])
            if offset >= page["total"]:
                return rows
            assert page["items"]

    existing = all_documents()
    fixtures = []
    with zipfile.ZipFile(fixture) as archive:
        for entry in archive.infolist():
            name = Path(entry.filename).name
            if not entry.is_dir() and Path(name).suffix.lower() in (".pdf", ".txt", ".md", ".markdown"):
                original = archive.read(entry)
                digest = hashlib.sha256(original).hexdigest()
                row = next((r for r in existing if r["name"] == name and r["sha256"] == digest), None)
                if row is None:
                    payload, headers = multipart(name, original)
                    status, raw, _ = client.request("POST", "/api/v1/documents", payload, headers)
                    assert status == 201, (status, raw[:500])
                    row = json.loads(raw)
                detail = api("GET", f'/api/v1/documents/{row["id"]}')
                assert detail["textStatus"] == ("not_supported" if name.endswith(".pdf") else "ready"), detail
                status, downloaded, _ = client.request("GET", detail["downloadUrl"])
                assert status == 200 and downloaded == original
                content = "" if name.endswith(".pdf") else original.decode("utf-8-sig")
                fixtures.append({"document": detail, "name": name, "raw": original, "content": content})
                report["original_files"].append({"id": detail["id"], "name": name, "sha256": digest, "equal": True, "textStatus": detail["textStatus"]})
    assert len(fixtures) == 10
    record("zip_7_texts_ready_3_pdfs_name_only_and_10_downloads_unchanged")

    def normalized(value):
        return unicodedata.normalize("NFKC", value).casefold()

    fixture_ids = {f["document"]["id"] for f in fixtures}
    queries = ["代码提交规范", "最终版", "幂等", "ENG-014", "API-032", "REL-20260918", "INC-20260921", "RUN-008", "04_星桥项目_需求与范围_v1.0.pdf"]
    for term in queries:
        response = search(term)
        expected = {f["document"]["id"] for f in fixtures if normalized(term) in normalized(f["name"]) or normalized(term) in normalized(f["content"])}
        observed = {r["id"] for r in response["items"]} & fixture_ids
        assert observed == expected and expected, (term, expected, observed)
        assert response["total"] <= 100, "Fixture query needs extra pagination"
        for row in response["items"]:
            hit = row["hit"]
            assert hit["text"][hit["highlightStart"]:hit["highlightEnd"]] == normalized(term)
            if row["extension"] == "pdf":
                assert hit["fields"] == ["name"]
        report["queries"].append({"query": term, "total": response["total"], "hits": [{"name": r["name"], "fields": r["hit"]["fields"], "snippet": r["hit"]["text"]} for r in response["items"]]})
    record("chinese_keywords_complete_identifiers_and_pdf_filename_return_expected_zip_files_with_snippets")
    lower = search("eng-014")
    assert {r["id"] for r in lower["items"]} == {r["id"] for r in search("ENG-014")["items"]}
    literal = search("03_")
    assert any(r["name"].startswith("03_") for r in literal["items"])
    assert search("%")['total'] == 0
    record("identifier_case_insensitive_and_underscore_percent_are_literal_not_wildcards")
    assert search("不存在的检索词-M4-" + uuid.uuid4().hex)["total"] == 0
    for keyword in (" ", "x" * 201, "bad\nquery"):
        api("GET", "/api/v1/search/keyword?" + urllib.parse.urlencode({"q": keyword}), expected=422)
    record("empty_results_and_invalid_query_feedback")
    full = search("发布")
    first, second = search("发布", limit=1), search("发布", limit=1, offset=1)
    assert first["total"] == second["total"] == full["total"] and full["total"] >= 2
    assert first["items"][0]["id"] == full["items"][0]["id"] and second["items"][0]["id"] == full["items"][1]["id"]
    record("search_count_and_pagination_are_consistent")

    selected = next(f for f in fixtures if f["name"].startswith("01_"))
    row, original = selected["document"], selected["raw"]
    old_category = row["category"]["id"] if row["category"] else None
    suffix = uuid.uuid4().hex[:8]
    a = api("POST", "/api/v1/categories", {"name": "M4检索-A-" + suffix}, 201)
    b = api("POST", "/api/v1/categories", {"name": "M4检索-B-" + suffix}, 201)
    report["categories"] = {"a": a["id"], "b": b["id"]}
    flow = []
    for target in (a, b):
        api("PATCH", f'/api/v1/documents/{row["id"]}/category', {"categoryId": target["id"]})
        result = search("DOC-238", target["id"])
        assert {r["id"] for r in result["items"]} == {row["id"]}
        flow.append({"action": "move_then_search", "category": target["id"], "total": result["total"]})
    assert search("DOC-238", a["id"])["total"] == 0
    api("POST", f'/api/v1/documents/{row["id"]}/archive')
    assert row["id"] not in {r["id"] for r in search("DOC-238")["items"]}
    assert search("DOC-238", b["id"])["total"] == 0
    assert {r["id"] for r in search("DOC-238", b["id"], True)["items"]} == {row["id"]}
    flow.append({"action": "archive_then_search", "default_contains_document": False, "category_total": 0, "archive_total": 1})
    api("POST", f'/api/v1/documents/{row["id"]}/restore')
    restored = search("DOC-238", b["id"])
    assert {r["id"] for r in restored["items"]} == {row["id"]}
    assert row["id"] in {r["id"] for r in search("DOC-238")["items"]}
    assert search("DOC-238", b["id"], True)["total"] == 0
    status, downloaded, _ = client.request("GET", row["downloadUrl"])
    assert status == 200 and downloaded == original
    flow.append({"action": "restore_then_search", "category_total": 1, "download_http": status, "download_sha256": hashlib.sha256(downloaded).hexdigest()})
    api("PATCH", f'/api/v1/documents/{row["id"]}/category', {"categoryId": old_category})
    report["consistency_flow"] = flow
    record("move_search_archive_search_restore_search_and_download_consistency")
    unknown = str(uuid.uuid4())
    api("GET", "/api/v1/search/keyword?" + urllib.parse.urlencode({"q": "ENG-014", "category_id": unknown}), expected=404)
    api("GET", "/api/v1/search/keyword?q=ENG-014&category_id=invalid", expected=422)
    record("invalid_category_search_has_clear_feedback")

    # Real malformed text bytes, not a mocked exception/fault-injection hook.
    bad = b"\xff\xfeX"
    filename = "M4-正文失败-" + suffix + ".txt"
    payload, headers = multipart(filename, bad)
    status, raw, _ = client.request("POST", "/api/v1/documents", payload, headers)
    failed = json.loads(raw)
    assert status == 201 and failed["textStatus"] == "failed" and failed["textError"]
    assert {r["id"] for r in search(filename)["items"]} == {failed["id"]}
    assert search(filename)["bodyUnavailableCount"] >= 1
    status, downloaded, _ = client.request("GET", failed["downloadUrl"])
    assert status == 200 and downloaded == bad
    retry = api("POST", f'/api/v1/documents/{failed["id"]}/text/retry')
    assert retry["textStatus"] == "failed" and retry["textError"]
    assert api("GET", f'/api/v1/documents/{failed["id"]}')["sha256"] == hashlib.sha256(bad).hexdigest()
    report["extraction_failure"] = {"id": failed["id"], "name": filename, "upload_http": 201, "textStatus": failed["textStatus"], "error": failed["textError"], "retryStatus": retry["textStatus"], "download_http": status, "original_sha256": hashlib.sha256(bad).hexdigest(), "download_sha256": hashlib.sha256(downloaded).hexdigest(), "equal": True}
    record("actual_invalid_encoding_fails_extraction_but_upload_name_search_retry_and_original_download_work")
    pdf = next(f for f in fixtures if f["name"].endswith('.pdf'))
    api("POST", f'/api/v1/documents/{pdf["document"]["id"]}/text/retry', expected=409)
    api("POST", f'/api/v1/documents/{unknown}/text/retry', expected=404)
    record("pdf_extraction_not_supported_and_missing_document_retry_feedback")
    if data_dir:
        after = snapshot(data_dir)
        report["database_after"] = after
        assert after["version"] == 2
        before = report.get("database_before_startup")
        if before and before.get("exists"):
            assert all(after["documents"].get(k) == v for k, v in before["documents"].items())
            record("schema_upgrade_preserves_existing_document_ids_and_hashes", count=len(before["documents"]))
        with sqlite3.connect(data_dir / "db/platform.sqlite3") as connection:
            for f in fixtures:
                body = connection.execute("SELECT content FROM document_texts WHERE document_id=?", (f["document"]["id"],)).fetchone()
                assert (body is None) if f["name"].endswith('.pdf') else body[0] == f["content"]
            assert connection.execute("SELECT COUNT(*) FROM document_texts WHERE document_id=?", (failed['id'],)).fetchone()[0] == 0
        record("independent_database_read_has_original_texts_and_no_pdf_or_failed_text_rows")


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
    report = {"checks": [], "queries": [], "original_files": [], "failure": None,
              "browser": "not proved by this script"}
    try:
        if args.base_url:
            if not os.environ.get("ACCEPTANCE_TEST_RUN"):
                raise RuntimeError("External HTTP verification requires an isolated test runner marker")
            report["transport"] = "real TCP HTTP " + args.base_url
            client = TcpClient(args.base_url)
            deadline = time.perf_counter() + 120
            while time.perf_counter() < deadline:
                try:
                    status, raw, _ = client.request("GET", "/api/v1/health")
                    health = json.loads(raw)
                    if status == 200 and health.get("milestone") == "M4":
                        report["health"] = health
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("M4 readiness timed out")
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
                report["health"] = client.get('/api/v1/health').json()
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
    print(f'PASS {len(report["checks"])} M4 checks; real corpus keyword matches and original hashes verified.', flush=True)


if __name__ == "__main__":
    main()
