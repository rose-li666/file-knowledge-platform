"""Literal filename/body keyword search with live category and archival filters."""
import logging
import re
import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .database import Document, DocumentText
from .files import FileError, document_filters, find_document, serialize
from .text_normalization import search_key
from .texts import extract_document

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def snippet(content, term):
    # Snippets use the same normalized text as matching, so highlight offsets are exact.
    at = content.index(term)
    start, end = max(0, at - 65), min(len(content), at + len(term) + 115)
    prefix, suffix = "…" if start else "", "…" if end < len(content) else ""
    return {"text": prefix + content[start:end] + suffix,
            "highlightStart": len(prefix) + at - start,
            "highlightEnd": len(prefix) + at - start + len(term)}


@router.get("/search/keyword")
def keyword_search(request: Request, q: str = Query(min_length=1, max_length=200),
                   category_id: str | None = None, archived: bool = False,
                   limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
    term = search_key(q).strip()
    if not term or len(term) > 200 or re.search(r"[\x00-\x1f\x7f]", term):
        raise FileError(422, "INVALID_KEYWORD", "请输入 1–200 字的关键词，不能包含控制字符。")
    try:
        with Session(request.app.state.document_engine) as session:
            filters = document_filters(session, archived, category_id)
            name_hit = func.instr(func.search_key(Document.name), term) > 0
            body_hit = (Document.text_status == "ready") & (func.instr(DocumentText.search_content, term) > 0)
            matching = or_(name_hit, body_hit)
            query = select(Document, DocumentText.search_content, name_hit, body_hit).outerjoin(
                DocumentText, DocumentText.document_id == Document.id).where(*filters, matching)
            total = session.scalar(select(func.count()).select_from(Document).outerjoin(
                DocumentText, DocumentText.document_id == Document.id).where(*filters, matching))
            rows = session.execute(query.order_by(name_hit.desc(), Document.uploaded_at.desc(), Document.id.desc())
                                   .offset(offset).limit(limit)).all()
            items = []
            for row, body, named, textual in rows:
                fields = (["name"] if named else []) + (["body"] if textual else [])
                items.append({**serialize(row).model_dump(mode="json"),
                              "hit": {"fields": fields, **snippet(body if textual else search_key(row.name), term)}})
            unavailable = session.scalar(select(func.count()).select_from(Document).where(
                *filters, Document.extension != "pdf", Document.text_status != "ready"))
            return {"items": items, "total": total, "limit": limit, "offset": offset,
                    "query": q.strip(), "bodyUnavailableCount": unavailable}
    except SQLAlchemyError as error:
        logger.exception("Keyword search failed")
        raise FileError(503, "SEARCH_UNAVAILABLE", "搜索暂不可用，请稍后重试。", retryable=True) from error


@router.post("/documents/{document_id}/text/retry")
def retry_text(request: Request, document_id: uuid.UUID):
    row = find_document(request, document_id)
    if row.extension == "pdf":
        raise FileError(409, "TEXT_NOT_SUPPORTED", "PDF 本轮仅支持文件名搜索。")
    try:
        with request.app.state.text_lock:
            extract_document(request.app.state.document_engine, request.app.state.data_dir, str(document_id))
        return serialize(find_document(request, document_id))
    except SQLAlchemyError as error:
        logger.exception("Text retry could not commit: %s", document_id)
        raise FileError(503, "TEXT_EXTRACTION_UNAVAILABLE", "正文处理未能确认完成；原文件仍已保存，请刷新核对后重试。", retryable=True) from error
