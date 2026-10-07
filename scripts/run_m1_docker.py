"""Stdlib-only Docker M1 evidence runner; execute in a normal user terminal.

Does not modify PowerShell execution policy, firewall, Docker API settings or data volumes.
"""
import argparse
import json
import re
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, default=ROOT.parent / "m1-docker")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    fixture = args.zip.resolve(strict=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    reports = args.report_dir.resolve()
    started = time.perf_counter()
    summary = {"started_utc": datetime.now(timezone.utc).isoformat(), "steps": [],
               "failure": None, "browser_render": "not verified by this runner",
               "deferred": ["M5 task recovery", "M5 deduplication", "M5 fault injection"]}

    def docker_step(label, arguments):
        command = ["docker", *arguments]
        clock = time.perf_counter()
        print("Executing: " + subprocess.list2cmdline(command), flush=True)
        with (reports / f"{label}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       encoding="utf-8", errors="replace")
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
        summary["steps"].append({"step": label, "command": command, "exit_code": code,
                                 "seconds": round(time.perf_counter() - clock, 3)})
        if code:
            raise RuntimeError(f"{label} exited {code}; inspect {label}.log")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://127.0.0.1:{args.port}"

    def request(path, body=None):
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base_url + path, data=payload,
                                     headers={"Content-Type": "application/json"} if payload else {})
        with opener.open(req, timeout=5) as response:
            return response.status, response.read()

    try:
        docker_step("01-version", ["version"])
        docker_step("02-config", ["compose", "config", "--quiet"])
        if not args.skip_build:
            docker_step("03-build-start", ["compose", "up", "--build", "-d"])
        docker_step("04-status", ["compose", "ps"])
        deadline = time.perf_counter() + 120
        last_error = None
        health = None
        while time.perf_counter() < deadline:
            try:
                _, response = request("/api/v1/health")
                health = json.loads(response)
                break
            except Exception as error:
                last_error = str(error)
                time.sleep(2)
        if health is None:
            raise RuntimeError(f"Health endpoint unavailable: {last_error}")
        (reports / "health.json").write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
        if health["status"] != "ready":
            raise RuntimeError("Health is not ready; inspect health.json")
        summary["steps"].append({"step": "real_tcp_health_and_model", "passed": True})
        value = "M1 Docker actual probe " + str(uuid.uuid4())
        status, response = request("/api/v1/m1/probes", {"value": value})
        assert status == 201
        saved = json.loads(response)
        _, response = request("/api/v1/m1/probes")
        assert saved in json.loads(response)["items"]
        summary["steps"].append({"step": "database_write_read", "passed": True, "id": saved["id"]})
        status, response = request("/")
        page = response.decode("utf-8")
        assert status == 200 and "知识文件库" in page
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page)
        assert len(assets) >= 2
        for asset in assets:
            asset_status, resource = request(asset)
            assert asset_status == 200 and len(resource) > 100
        summary["steps"].append({"step": "frontend_assets_real_tcp", "passed": True, "assets": assets})
        docker_step("05-container-semantic", [
            "compose", "run", "--rm", "--no-deps",
            "-v", f"{fixture}:/fixtures/test-documents.zip:ro",
            "-v", f"{reports}:/reports", "app", "python", "scripts/evaluate_m1.py",
            "--zip", "/fixtures/test-documents.zip", "--model-dir", "/opt/models/bge",
            "--data-dir", "/data", "--report", "/reports/semantic-results.json",
        ])
    except Exception as error:
        summary["failure"] = str(error)
        print("FAILED: " + str(error), flush=True)
    finally:
        try:
            logs = subprocess.run(["docker", "compose", "logs", "--tail=100", "app"], cwd=ROOT,
                                  capture_output=True, encoding="utf-8", errors="replace", timeout=30)
            (reports / "app.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        except Exception as error:
            summary["log_collection_error"] = str(error)
        summary["total_seconds"] = round(time.perf_counter() - started, 3)
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (reports / "execution-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Evidence saved to: " + str(reports), flush=True)
    if summary["failure"]:
        raise SystemExit(1)
    print(f"Open {base_url} and verify the actual page and database button; this runner does not claim browser verification.")


if __name__ == "__main__":
    main()
