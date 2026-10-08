"""Isolated verification child only. No production API/environment fault hooks."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utf8_logs import configure_utf8_io
configure_utf8_io()

from app import files
from app.embedding import LocalEmbedder

mode = os.environ.get("M5_TEST_MODE", "normal")
checkpoint = Path(os.environ["DATA_DIR"]) / "test-checkpoint"
original_encode = LocalEmbedder.encode
original_sync = files.sync_directory


def encode(self, texts, *, query=False):
    if not query:
        if mode == "encode_failure":
            raise RuntimeError("M5 injected inference failure after real text extraction")
        if mode == "worker_crash":
            checkpoint.write_text("processing claim committed; crash before encode", encoding="utf-8")
            os._exit(75)
        if mode == "hold":
            checkpoint.write_text("processing claim committed", encoding="utf-8")
            deadline = time.monotonic() + 90
            while not (checkpoint.parent / "release-index").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Test release was not supplied")
                time.sleep(.1)
    return original_encode(self, texts, query=query)


def sync(directory):
    original_sync(directory)
    if mode == "landed_crash" and directory.name == "uploads":
        os._exit(74)


LocalEmbedder.encode = encode
files.sync_directory = sync
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=int(sys.argv[1]), workers=1, log_level="info")
