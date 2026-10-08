"""Build M4 once, then verify keyword search, category/archive consistency and extraction isolation."""
import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    configure_utf8_io()
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=Path(r"D:\__10_.zip"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    fixture = args.zip.resolve(strict=True)
    reports = ROOT.parent / "m4-docker" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    reports.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    summary = {"started_utc": datetime.now(timezone.utc).isoformat(), "steps": [], "failure": None,
               "browser_interaction": "not verified by this runner"}

    def snapshot():
        client = TcpClient("http://127.0.0.1:8000")
        def get(path):
            code, raw, _ = client.request("GET", path)
            if code != 200:
                raise RuntimeError(f"Snapshot {path}: HTTP {code}")
            return json.loads(raw)
        documents = {}
        for archived in ("false", "true"):
            offset = 0
            while True:
                page = get(f"/api/v1/documents?archived={archived}&limit=100&offset={offset}")
                for row in page["items"]:
                    documents[row["id"]] = {key: row[key] for key in ("name", "sha256", "category", "archivedAt")}
                offset += len(page["items"])
                if offset >= page["total"]:
                    break
                if not page["items"]:
                    raise RuntimeError("Snapshot pagination incomplete")
        return {"documents": documents, "categories": {row["id"]: row["name"] for row in get('/api/v1/categories')["items"]}}

    def run(label, command, required=True):
        clock = time.perf_counter()
        code = None
        error = None
        print("Executing: " + subprocess.list2cmdline(command), flush=True)
        with (reports / f"{label}.log").open("w", encoding="utf-8") as log:
            log.write("Command: " + subprocess.list2cmdline(command) + "\n")
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           encoding="utf-8", errors="backslashreplace")
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                code = process.wait()
            except Exception as exception:
                error = str(exception)
                log.write("Launch failure: " + error + "\n")
            seconds = round(time.perf_counter() - clock, 3)
            log.write(f"\nExit code: {code}; seconds: {seconds}\n")
        summary["steps"].append({"step": label, "command": command, "exit_code": code,
                                 "seconds": seconds, "launch_error": error})
        if required and code != 0:
            raise RuntimeError(f"{label} failed (exit_code={code}); later steps were not run")

    try:
        before = None
        try:
            before = snapshot()
            (reports / "before-build.json").write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as error:
            summary["before_build_snapshot_error"] = str(error)
            print("Existing app snapshot unavailable; no upgrade-persistence pass will be claimed.", flush=True)
        if not args.skip_build:
            run("01-build-start", [sys.executable, str(ROOT / "scripts/m1_docker_stage.py"), "--stage", "build"])
        run("02-health-and-hashes", ["docker", "compose", "run", "--rm", "--no-deps",
                                     "-v", f"{fixture}:/fixtures/test-documents.zip:ro",
                                     "-v", f"{reports}:/reports", "app", "python", "scripts/verify_m4.py",
                                     "--base-url", "http://app:8000", "--zip", "/fixtures/test-documents.zip",
                                     "--data-dir", "/data", "--report", "/reports/m4-results.json"])
        if before is not None:
            after = snapshot()
            (reports / "after-checks.json").write_text(json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8")
            preserved = all(after["documents"].get(key) == value for key, value in before["documents"].items())
            categories_preserved = all(after["categories"].get(key) == value for key, value in before["categories"].items())
            summary["upgrade_persistence"] = {"passed": preserved and categories_preserved,
                "existing_document_count": len(before["documents"]), "existing_category_count": len(before["categories"]),
                "scope": "Before-build and after-verification HTTP snapshots; originals/hash/category/archive metadata"}
            if not preserved or not categories_preserved:
                raise RuntimeError("Existing document/category metadata changed during M4 upgrade")
    except Exception as error:
        summary["failure"] = str(error)
        print("FAILED: " + str(error), flush=True)
    finally:
        run("03-app-logs", ["docker", "compose", "logs", "--tail=100", "app"], required=False)
        summary["total_seconds"] = round(time.perf_counter() - started, 3)
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (reports / "execution-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Evidence saved to: " + str(reports), flush=True)
    if summary["failure"]:
        raise SystemExit(1)
    print("M4 container checks passed. Browser category/archival/refresh interactions need separate verification.")


if __name__ == "__main__":
    main()
