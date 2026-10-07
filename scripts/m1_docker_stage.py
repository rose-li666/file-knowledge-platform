"""Separate Docker pull/build/verify stages; preserve command logs and exit codes."""
import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from utf8_logs import configure_utf8_io

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT.parent / "m1-docker"


def main():
    configure_utf8_io()
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("pull", "build", "verify"))
    parser.add_argument("--zip", type=Path, default=Path(r"D:\__10_.zip"))
    args = parser.parse_args()
    attempt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.stage + "-" + uuid.uuid4().hex[:6]
    directory = REPORTS / attempt
    directory.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    summary = {"stage": args.stage, "started_utc": datetime.now(timezone.utc).isoformat(),
               "steps": [], "failure": None}

    def run(label, command):
        clock = time.perf_counter()
        code = None
        error = None
        print("Executing: " + subprocess.list2cmdline(command), flush=True)
        with (directory / f"{label}.log").open("w", encoding="utf-8") as log:
            log.write("Command: " + subprocess.list2cmdline(command) + "\n")
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, encoding="utf-8", errors="backslashreplace")
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
        step = {"step": label, "command": command, "exit_code": code, "seconds": seconds,
                "log": str(directory / f"{label}.log")}
        if error:
            step["launch_error"] = error
        summary["steps"].append(step)
        print(f"{label}: exit_code={code}; seconds={seconds}", flush=True)
        return code == 0

    def required(label, command):
        if not run(label, command):
            raise RuntimeError(f"{label} failed; inspect {label}.log. Later steps were not run.")

    try:
        images = re.findall(r"^FROM\s+(\S+)", (ROOT / "Dockerfile").read_text("utf-8"), re.MULTILINE)
        if len(images) != 2 or any("@sha256:" not in image for image in images):
            raise RuntimeError("Expected two digest-pinned base images in Dockerfile")
        summary["images"] = images
        required("01-version", ["docker", "version"])
        if args.stage == "pull":
            # Both pulls are independent; preserve both outcomes before applying the gate.
            outcomes = [run(f"02-pull-{number}", ["docker", "pull", image])
                        for number, image in enumerate(images, 1)]
            if not all(outcomes):
                raise RuntimeError("One or both base-image pulls failed. No build was attempted.")
            gate = {"images": images, "attempt": attempt, "passed": True}
            (REPORTS / "last-successful-pull.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
        elif args.stage == "build":
            gate = REPORTS / "last-successful-pull.json"
            if not gate.exists() or json.loads(gate.read_text("utf-8")).get("images") != images:
                raise RuntimeError("No successful pull evidence for current Dockerfile. Run --stage pull first.")
            for number, image in enumerate(images, 1):
                required(f"02-inspect-{number}", ["docker", "image", "inspect", image])
            required("03-config", ["docker", "compose", "config", "--quiet"])
            required("04-build", ["docker", "compose", "--progress", "plain", "build"])
            required("05-start", ["docker", "compose", "up", "-d", "--no-build"])
            required("06-status", ["docker", "compose", "ps"])
        else:
            required("02-verify", [sys.executable, str(ROOT / "scripts" / "run_m1_docker.py"),
                                   "--skip-build", "--zip", str(args.zip),
                                   "--report-dir", str(directory / "verification")])
    except Exception as error:
        summary["failure"] = str(error)
        print("FAILED: " + str(error), flush=True)
    finally:
        summary["total_seconds"] = round(time.perf_counter() - started, 3)
        summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (directory / "execution-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Evidence saved to: " + str(directory), flush=True)
    if summary["failure"]:
        raise SystemExit(1)
    print(f"{args.stage} completed. No other stage was run.")


if __name__ == "__main__":
    main()
