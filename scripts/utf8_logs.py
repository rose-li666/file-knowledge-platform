"""Use UTF-8 for runner output and nested Python pipes, including Windows GBK shells."""
import os
import sys


def configure_utf8_io():
    # Process-local settings, not PowerShell policy or persistent system changes.
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8:backslashreplace"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
