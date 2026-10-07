"""M1 offline experiment, not a business upload/index/retry implementation."""
import argparse
import hashlib
import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import psutil
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import ProbeVector, open_database
from app.embedding import LocalEmbedder, SPEC

QUERIES = [
    ("我改完功能准备交给同事看，怎样证明这次修改已经检查过，还有哪些东西要一起交代？", "01_代码提交规范_v2.1.md"),
    ("网络卡了一下，我把刚才那个上传请求又发了一遍，怎样保证列表里不会多出一份？", "03_文件服务接口约定_v1.2.md"),
    ("下一次把新版本部署给用户，启动之后要做哪些实际操作，才能确认它真的能用？", "02_发布检查清单_v1.4.md"),
    ("文件能取回来，后台也接到了处理工作，但上游把正文放进了另一层数据里，怎样恢复搜索而不用用户重传？", "06_星桥项目_故障复盘_2026-09-21.md"),
    ("我重新创建了容器，以前上传的资料突然不见了，应该先检查哪里，怎样避免把旧数据也清掉？", "09_本地部署故障排查_v1.3.txt"),
]


def read_corpus(path):
    documents, manifest = [], []
    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
            raise ValueError("M1 fixture archive exceeds 50 MiB uncompressed")
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = item.filename
            if not item.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("gb18030")
                except UnicodeError:
                    pass
            payload = archive.read(item)
            manifest.append({"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            if Path(name).suffix.lower() not in {".md", ".txt"}:
                continue
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = payload.decode("gb18030")
            documents.append((name, text.replace("\r\n", "\n")))
    return documents, manifest


def split_document(name, text, tokenizer):
    """Preserve headings/paragraphs; token-budgeted windows for long paragraphs."""
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    title = text.splitlines()[0].lstrip("# ").strip()
    heading = title
    chunks = []
    buffer = []

    def flush():
        if buffer:
            body = "\n\n".join(buffer)
            chunks.append({"document": name, "ordinal": len(chunks), "heading": heading,
                           "text": body, "input": f"{title}\n{heading}\n{body}"})
            buffer.clear()

    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        first = lines[0]
        if first.startswith("#") or re.match(r"^[一二三四五六七八九十]+、", first):
            flush()
            heading = first.lstrip("# ").strip()
            paragraph = "\n".join(lines[1:]).strip()
            if not paragraph:
                continue
        candidate = "\n\n".join(buffer + [paragraph])
        if len(tokenizer.encode(f"{title}\n{heading}\n{candidate}", add_special_tokens=True)) > 320:
            flush()
        prefix = f"{title}\n{heading}\n"
        budget = min(300, 480 - len(tokenizer.encode(prefix, add_special_tokens=True)))
        if budget < 40:
            raise ValueError("Fixture heading too long")
        tokens = tokenizer(paragraph, add_special_tokens=False, return_offsets_mapping=True)
        offsets = tokens["offset_mapping"]
        if len(offsets) > budget:
            flush()
            start = 0
            while start < len(offsets):
                end = min(start + budget, len(offsets))
                body = paragraph[offsets[start][0]:offsets[end - 1][1]]
                chunks.append({"document": name, "ordinal": len(chunks), "heading": heading,
                               "text": body, "input": prefix + body})
                if end == len(offsets):
                    break
                start = end - 30
        else:
            buffer.append(paragraph)
            flush()  # One semantic paragraph per chunk; avoid diluting rules with adjacent JSON/examples.
    flush()
    return chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models" / "bge")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    process = psutil.Process()
    load_started = time.perf_counter()
    embedder = LocalEmbedder(args.model_dir)
    load_with_imports = time.perf_counter() - load_started
    documents, manifest = read_corpus(args.zip)
    chunks = [chunk for name, text in documents for chunk in split_document(name, text, embedder.model.tokenizer)]
    lengths = [len(embedder.model.tokenizer.encode(chunk["input"], add_special_tokens=True)) for chunk in chunks]
    if max(lengths) > embedder.model.max_seq_length:
        raise ValueError("Chunk would be silently truncated")
    encode_started = time.perf_counter()
    embeddings = embedder.encode([chunk["input"] for chunk in chunks])
    corpus_encode_seconds = time.perf_counter() - encode_started
    index_key = hashlib.sha256(json.dumps({"model": SPEC, "splitter": "m1-paragraph-token-v2", "files": manifest}, sort_keys=True).encode()).hexdigest()
    database_path = args.data_dir / "db" / "m1-evaluation.sqlite3"
    write_started = time.perf_counter()
    engine = open_database(database_path)
    with Session(engine) as session:
        session.execute(delete(ProbeVector))  # Replace the isolated experiment dataset, not business data.
        session.add_all([ProbeVector(document=chunk["document"], ordinal=chunk["ordinal"],
                                    heading=chunk["heading"], text=chunk["text"],
                                    embedding=vector.tobytes(), index_key=index_key)
                         for chunk, vector in zip(chunks, embeddings)])
        session.commit()
    engine.dispose()
    engine = open_database(database_path)
    with Session(engine) as session:
        rows = session.scalars(select(ProbeVector).order_by(ProbeVector.id)).all()
    matrix = np.stack([np.frombuffer(row.embedding, dtype="<f4") for row in rows])
    persisted_equal = bool(np.array_equal(matrix, embeddings))
    database_seconds = time.perf_counter() - write_started
    if not persisted_equal:
        raise ValueError("Reloaded SQLite vectors differ from generated vectors")
    results = []
    for number, (query, expected) in enumerate(QUERIES, 1):
        query_started = time.perf_counter()
        vector = embedder.encode([query], query=True)[0]
        scores = matrix @ vector
        best = {}
        for position in np.argsort(-scores):
            row = rows[int(position)]
            if row.document not in best:
                best[row.document] = {"document": row.document, "score": round(float(scores[position]), 6),
                                      "chunk_ordinal": row.ordinal, "heading": row.heading, "snippet": row.text, "top_snippets": []}
            if len(best[row.document]["top_snippets"]) < 2:
                best[row.document]["top_snippets"].append({"score": round(float(scores[position]), 6),
                                                         "chunk_ordinal": row.ordinal, "heading": row.heading, "text": row.text})
        rankings = list(best.values())
        for rank, hit in enumerate(rankings, 1):
            hit["rank"] = rank
        expected_rank = next(hit["rank"] for hit in rankings if hit["document"] == expected)
        result = {"number": number, "query": query, "expected_document": expected,
                  "expected_rank": expected_rank, "target_in_top3": expected_rank <= 3,
                  "query_seconds": round(time.perf_counter() - query_started, 4), "rankings": rankings}
        results.append(result)
        print(json.dumps({"query": number, "expected_rank": expected_rank, "query_seconds": result["query_seconds"],
                          "top3": [{"document": hit["document"], "score": hit["score"]} for hit in rankings[:3]]}, ensure_ascii=False), flush=True)
    engine.dispose()
    report = {
        "environment": {"system": platform.platform(), "python": platform.python_version(), "logical_cpus": psutil.cpu_count(),
                        "physical_memory_gib": round(psutil.virtual_memory().total / 1024 ** 3, 2)},
        "model": SPEC, "method": "CPU normalized embeddings; SQLite BLOB reload; exact dot product; document max aggregation; no keyword fallback/reranker",
        "splitter_version": "m1-paragraph-token-v2",
        "archive_sha256": hashlib.sha256(args.zip.read_bytes()).hexdigest(), "archive_manifest": manifest,
        "document_count": len(documents), "chunk_count": len(chunks), "max_input_tokens": max(lengths),
        "vector_shape": list(embeddings.shape), "sqlite_reload_equal": persisted_equal,
        "timings": {"model_load_with_imports_seconds": round(load_with_imports, 3), "model_construct_seconds": round(embedder.load_seconds, 3),
                    "corpus_encode_seconds": round(corpus_encode_seconds, 3), "database_write_reload_seconds": round(database_seconds, 3),
                    "total_seconds": round(time.perf_counter() - started, 3)},
        "rss_at_end_mib": round(process.memory_info().rss / 1024 ** 2, 1),
        "queries": results,
        "top3_pass_count": sum(result["target_in_top3"] for result in results),
        "limitations": ["M1 experiment only; no business upload/search APIs, task recovery, deduplication or fault injection.",
                        "Top3 recall only; human snippet review required; not a general relevance benchmark.",
                        "RSS is a single end-of-run observation, not peak memory."],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(args.report.resolve()), "top3_pass_count": report["top3_pass_count"], "timings": report["timings"]}, ensure_ascii=False), flush=True)
    if report["top3_pass_count"] != len(QUERIES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
