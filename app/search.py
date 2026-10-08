"""Literal filename/body keyword search with live category and archival filters."""
import logging
import re
import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .database import Chunk, Document, DocumentText, IndexJob
from .embedding import SPEC
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
        from .indexing import queue_document
        with request.app.state.text_lock:
            # Invalidate any in-flight text snapshot before changing the body.
            with Session(request.app.state.document_engine) as session:
                session.execute(text("BEGIN IMMEDIATE"))
                queue_document(session, session.get(Document, str(document_id)), force=True)
                session.commit()
            extract_document(request.app.state.document_engine, request.app.state.data_dir, str(document_id))
        return serialize(find_document(request, document_id))
    except SQLAlchemyError as error:
        logger.exception("Text retry could not commit: %s", document_id)
        raise FileError(503, "TEXT_EXTRACTION_UNAVAILABLE", "正文处理未能确认完成；原文件仍已保存，请刷新核对后重试。", retryable=True) from error


@router.get("/search/semantic")
async def semantic_search(request: Request, q: str = Query(min_length=1, max_length=200),
                          category_id: str | None = None, archived: bool = False,
                          limit: int = Query(5, ge=1, le=25), offset: int = Query(0, ge=0),
                          min_score: float = Query(0.45, ge=0, le=1),
                          score_window: float = Query(0.08, ge=0, le=1),
                          source_window: float = Query(0.08, ge=0, le=1)):
    import asyncio
    import numpy as np
    if not q.strip() or re.search(r"[\x00-\x1f\x7f]", q):
        raise FileError(422, "INVALID_QUERY", "请输入 1–200 字的自然语言问题。")
    if request.app.state.model is None:
        raise FileError(503, "MODEL_UNAVAILABLE", "本地模型未就绪，请检查服务状态；关键词搜索和原文件下载仍可用。", retryable=True)
    try:
        vector = await asyncio.to_thread(request.app.state.model.encode, [q.strip()], query=True)
        def retrieve():
            with Session(request.app.state.document_engine) as session:
                filters = document_filters(session, archived, category_id)
                rows = session.execute(select(Document, Chunk).join(Chunk, Chunk.document_id == Document.id)
                    .join(IndexJob, IndexJob.document_id == Document.id)
                    .where(*filters, Document.text_status == "ready", Document.vector_status == "ready", IndexJob.state == "ready",
                           Chunk.generation == IndexJob.generation, Chunk.model_revision == SPEC["revision"])).all()
                unavailable = session.scalar(select(func.count()).select_from(Document).where(
                    *filters, Document.extension != "pdf", Document.vector_status != "ready"))
                best = {}
                for row, chunk in rows:
                    # A repeated heading alone is not a useful source when body chunks exist.
                    if row.chunk_count > 1 and search_key(chunk.text).strip() == search_key(chunk.heading).strip():
                        continue
                    embedding = np.frombuffer(chunk.embedding, dtype="<f4")
                    if embedding.shape != (SPEC["dimension"],) or not np.isfinite(embedding).all():
                        raise ValueError("Persisted embedding is invalid")
                    score = float(embedding @ vector[0])
                    if score < min_score:
                        continue
                    result = best.setdefault(row.id, {**serialize(row).model_dump(mode="json"), "score": score, "sources": []})
                    result["score"] = max(result["score"], score)
                    result["sources"].append({"ordinal": chunk.ordinal, "generation": chunk.generation,
                        "heading": chunk.heading, "text": chunk.text, "score": round(score, 6)})
                ordered = sorted(best.values(), key=lambda value: (-value["score"], value["id"]))
                candidate_total = len(ordered)
                if ordered:
                    floor = max(min_score, ordered[0]["score"] - score_window)
                    ordered = [result for result in ordered if result["score"] >= floor]
                for result in ordered:
                    result["score"] = round(result["score"], 6)
                    sources = sorted(result["sources"], key=lambda value: (-value["score"], value["ordinal"]))
                    result["sources"] = [source for source in sources
                                         if source["score"] >= result["score"] - source_window][:2]
                return {"items": ordered[offset:offset+limit], "total": len(ordered), "offset": offset,
                        "limit": limit, "query": q.strip(), "minScore": min_score,
                        "candidateTotal": candidate_total, "scoreWindow": score_window,
                        "omittedByWindow": candidate_total - len(ordered),
                        "vectorUnavailableCount": unavailable, "modelRevision": SPEC["revision"]}
        return await asyncio.to_thread(retrieve)
    except FileError:
        raise
    except Exception as error:
        logger.exception("Semantic search failed")
        raise FileError(503, "SEMANTIC_SEARCH_UNAVAILABLE", "向量检索暂不可用，请重试；关键词搜索和下载仍可用。", retryable=True) from error
