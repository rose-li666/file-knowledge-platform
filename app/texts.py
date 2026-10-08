"""Extract searchable text after original-file commit, without changing its bytes."""
import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Document, DocumentText
from .text_normalization import search_key

logger = logging.getLogger(__name__)


def decode_text(raw: bytes):
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        content, encoding = raw.decode("utf-16"), "utf-16"
    else:
        try:
            content, encoding = raw.decode("utf-8-sig"), "utf-8"
        except UnicodeError:
            content, encoding = raw.decode("gb18030"), "gb18030"
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", content):
        raise ValueError("Text contains binary control characters")
    return content, encoding


def extract_document(engine, directory: Path, document_id: str):
    # A separate metadata transaction cannot roll back the already-committed upload.
    with Session(engine) as session:
        row = session.get(Document, document_id)
        if row is None:
            raise ValueError("Document no longer exists")
        content, encoding, error = None, None, None
        if row.extension == "pdf":
            status = "not_supported"
        else:
            try:
                if not re.fullmatch(r"[0-9a-f]{32}\.bin", row.storage_key):
                    raise OSError("Invalid storage key")
                path = (directory / "uploads" / row.storage_key).resolve()
                if path.parent != (directory / "uploads").resolve():
                    raise OSError("Storage path outside uploads")
                raw = path.read_bytes()
                if len(raw) != row.size_bytes or hashlib.sha256(raw).hexdigest() != row.sha256:
                    raise OSError("Original file integrity mismatch")
                content, encoding = decode_text(raw)
                status = "ready"
            except (UnicodeError, ValueError):
                status, error = "failed", "正文编码无效或含二进制控制字符；请使用 UTF-8、带 BOM 的 UTF-16 或 GB18030 文本。原文件仍保留，可下载。"
            except OSError:
                logger.exception("Text extraction storage failure: %s", document_id)
                status, error = "failed", "正文暂不可读取，请核对存储后重试；原文件记录仍保留。"
        body = session.get(DocumentText, document_id)
        if content is not None:
            if body is None:
                body = DocumentText(document_id=document_id)
                session.add(body)
            body.content, body.search_content = content, search_key(content)
        elif body is not None:
            session.delete(body)
        row.text_status, row.text_error, row.text_encoding = status, error, encoding
        session.commit()
        return {"textStatus": status, "textError": error, "textEncoding": encoding}


def backfill_texts(engine, directory, lock):
    # M3 data never had text extraction. This is initial backfill, not task recovery.
    with Session(engine) as session:
        ids = list(session.scalars(select(Document.id).where(Document.text_status == "not_started")))
    summary = {"ready": 0, "failed": 0, "not_supported": 0, "unconfirmed": 0}
    for document_id in ids:
        try:
            with lock:
                result = extract_document(engine, directory, document_id)
            summary[result["textStatus"]] += 1
        except Exception:
            logger.exception("Initial text backfill could not be committed: %s", document_id)
            summary["unconfirmed"] += 1
    return summary
