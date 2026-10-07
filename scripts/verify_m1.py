"""Verify M1 HTTP contract and real SQLite writes; identify transport explicitly."""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(client, data_dir):
    checks = []
    response = client.get("/api/v1/health")
    assert response.status_code == 200, response.text
    health = response.json()
    assert health["database"]["status"] == "ready", health
    assert health["model"]["status"] == "ready", health
    checks.append({"check": "health_and_local_model", "passed": True, "response": health})
    value = f"M1 actual probe {uuid.uuid4()}"
    started = time.perf_counter()
    saved = client.post("/api/v1/m1/probes", json={"value": value})
    assert saved.status_code == 201, saved.text
    item = saved.json()
    read = client.get("/api/v1/m1/probes")
    assert read.status_code == 200, read.text
    assert item in read.json()["items"], read.json()
    with sqlite3.connect(data_dir / "db" / "diagnostics.sqlite3") as connection:
        disk_value = connection.execute("SELECT value FROM m1_probes WHERE id=?", (item["id"],)).fetchone()[0]
    assert disk_value == value
    checks.append({"check": "database_write_read_disk", "passed": True, "id": item["id"],
                   "seconds": round(time.perf_counter() - started, 4)})
    page = client.get("/")
    assert page.status_code == 200, page.text
    assert "知识文件库" in page.text
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page.text)
    assert len(assets) >= 2, page.text
    for path in assets:
        resource = client.get(path)
        assert resource.status_code == 200 and len(resource.content) > 100, path
    checks.append({"check": "built_html_js_css_served", "passed": True, "assets": assets,
                   "limitation": "Serving assets is not a browser render/click test."})
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--base-url", help="Use real TCP HTTP instead of application-local ASGI transport")
    args = parser.parse_args()
    os.environ["DATA_DIR"] = str(args.data_dir.resolve())
    os.environ.setdefault("MODEL_DIR", str(ROOT / "models" / "bge"))
    started = time.perf_counter()
    if args.base_url:
        import httpx
        with httpx.Client(base_url=args.base_url, timeout=15, trust_env=False) as client:
            checks = verify(client, args.data_dir)
        transport = "real TCP HTTP"
    else:
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            checks = verify(client, args.data_dir)
        transport = "in-process ASGI TestClient; does not prove TCP/browser access"
    report = {"transport": transport, "checks": checks,
              "total_seconds": round(time.perf_counter() - started, 3)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
