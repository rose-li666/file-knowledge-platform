"""Durable, one-at-a-time business indexing; publish chunks in one transaction."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .chunking import split_document
from .database import Chunk, Document, DocumentText, IndexJob
from .embedding import SPEC
from .texts import extract_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def now():
    return datetime.now(timezone.utc)


def queue_document(session, row, *, force=False):
    """Caller owns a transaction. Repeated queued/running requests are idempotent."""
    if row.extension == "pdf":
        row.vector_status = "not_supported"
        return False
    job = session.get(IndexJob, row.id)
    if job and job.state in {"pending", "processing"} and not force:
        return False
    if job is None:
        job = IndexJob(document_id=row.id, generation=1, attempts=0, state="pending", updated_at=now())
        session.add(job)
    else:
        job.generation += 1
        job.state, job.updated_at = "pending", now()
    row.vector_status, row.vector_error, row.chunk_count = "pending", None, 0
    # Previous generation is unavailable until the next atomic publication.
    return True


def recover_jobs(engine):
    summary = {"requeued": 0, "scheduled": 0}
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        for row in session.scalars(select(Document)).all():
            job = session.get(IndexJob, row.id)
            if job and job.state == "processing":
                job.state, job.updated_at = "pending", now()
                row.vector_status, row.vector_error = "pending", None
                summary["requeued"] += 1
            elif job is None:
                summary["scheduled"] += int(queue_document(session, row))
        session.commit()
    return summary


def process_next(state):
    engine = state.document_engine
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        job = session.scalar(select(IndexJob).where(IndexJob.state == "pending")
                             .order_by(IndexJob.updated_at, IndexJob.document_id).limit(1))
        if job is None:
            session.rollback()
            return False
        document_id, generation = job.document_id, job.generation
        job.state, job.updated_at = "processing", now()
        job.attempts += 1
        session.get(Document, document_id).vector_status = "processing"
        session.commit()
    chunks, vectors, failure = [], None, None
    try:
        with state.text_lock:
            with Session(engine) as session:
                row = session.get(Document, document_id)
                needs_text = row.text_status != "ready"
            if needs_text:
                extract_document(engine, state.data_dir, document_id)
            with Session(engine) as session:
                row = session.get(Document, document_id)
                body = session.get(DocumentText, document_id)
                if row.text_status != "ready" or body is None:
                    raise ValueError("正文提取失败，请查看正文错误并重试。")
                name, content = row.name, body.content
        if state.model is None:
            raise ValueError("本地向量模型未能加载；正文仍可搜索。修复模型后重试索引。")
        chunks = split_document(name, content, state.model.model.tokenizer)
        if not chunks:
            raise ValueError("正文没有可索引的文本；原文件仍可下载。")
        if len(chunks) > 2000:
            raise ValueError("正文超过 2000 个片段的索引限制，请拆分文档后上传。")
        lengths = [len(state.model.model.tokenizer.encode(c["input"], add_special_tokens=True)) for c in chunks]
        if max(lengths) > state.model.model.max_seq_length:
            raise ValueError("文档标题或片段过长，无法完整生成向量。")
        vectors = state.model.encode([c["input"] for c in chunks])
    except ValueError as error:
        logger.exception("Index failed: %s generation=%s", document_id, generation)
        failure = str(error)[:300]
    except Exception:
        logger.exception("Index failed: %s generation=%s", document_id, generation)
        failure = "向量生成失败；原文件已保存，正文就绪时仍可关键词搜索。请重试索引。"
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        job = session.get(IndexJob, document_id)
        # Fence late publication; do not publish results from an obsolete task.
        if job is None or job.generation != generation or job.state != "processing":
            session.rollback()
            return True
        row = session.get(Document, document_id)
        if failure:
            job.state = row.vector_status = "failed"
            row.vector_error = failure
        else:
            session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            session.add_all([Chunk(document_id=document_id, ordinal=c["ordinal"], generation=generation,
                                   heading=c["heading"], text=c["text"], embedding=v.tobytes(),
                                   model_revision=SPEC["revision"]) for c, v in zip(chunks, vectors)])
            job.state = row.vector_status = "ready"
            row.chunk_count, row.vector_error = len(chunks), None
        job.updated_at = now()
        session.commit()
    return True


async def index_loop(state):
    while not state.index_stop.is_set():
        try:
            worked = await asyncio.to_thread(process_next, state)
        except Exception:
            logger.exception("Index transaction could not complete; recovering outstanding claim")
            # A failed DB transaction leaves the claim durable; retry after a short pause.
            await asyncio.sleep(1)
            try:
                await asyncio.to_thread(recover_jobs, state.document_engine)
            except Exception:
                logger.exception("Index claim recovery unavailable")
            worked = False
        if not worked:
            try:
                await asyncio.wait_for(state.index_stop.wait(), timeout=0.5)
            except TimeoutError:
                pass


@router.post("/documents/{document_id}/index/retry", status_code=202)
def retry_index(request: Request, document_id: uuid.UUID):
    from .files import FileError, serialize
    from sqlalchemy.exc import SQLAlchemyError
    try:
        with Session(request.app.state.document_engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(Document, str(document_id))
            if row is None:
                raise FileError(404, "DOCUMENT_NOT_FOUND", "未找到该文件。")
            if row.extension == "pdf":
                raise FileError(409, "INDEX_NOT_SUPPORTED", "PDF 当前仅支持名称搜索。")
            queue_document(session, row)
            session.commit()
            return serialize(row)
    except SQLAlchemyError as error:
        raise FileError(503, "INDEX_RETRY_UNAVAILABLE", "任务未能确认提交，请刷新详情后重试。", retryable=True) from error
