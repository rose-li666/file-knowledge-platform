"""Download only fixed-revision inference files. No document content leaves the host."""
import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "model-spec.json").read_text("utf-8"))
FILES = [
    "config.json", "config_sentence_transformers.json", "modules.json",
    "sentence_bert_config.json", "special_tokens_map.json", "tokenizer.json",
    "tokenizer_config.json", "vocab.txt", "1_Pooling/config.json", "model.safetensors",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=ROOT / "models" / "bge")
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    records = []
    for filename in FILES:
        path = args.destination / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            url = f"https://huggingface.co/{SPEC['id']}/resolve/{SPEC['revision']}/{filename}"
            temporary = path.with_suffix(path.suffix + ".part")
            for attempt in range(3):
                try:
                    request = urllib.request.Request(url, headers={"User-Agent": "knowledge-platform-m1/0.1"})
                    with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                        expected_size = response.headers.get("Content-Length")
                        while block := response.read(1024 * 1024):
                            output.write(block)
                    if expected_size and temporary.stat().st_size != int(expected_size):
                        raise ValueError(f"Truncated model download: {filename}")
                    temporary.replace(path)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = {"name": filename, "size_bytes": path.stat().st_size, "sha256": digest}
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    manifest = {
        "id": SPEC["id"], "revision": SPEC["revision"], "files": records,
        "download_seconds": round(time.perf_counter() - started, 3),
    }
    (args.destination / "download-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"download_seconds": manifest["download_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
