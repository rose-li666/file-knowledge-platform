"""Persist original bytes independently of the future indexing pipeline."""
import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from .database import Document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
FORM_OVERHEAD_BYTES = 64 * 1024
BODY_LIMIT_MESSAGE = "upload-body-limit"
MEDIA_TYPES = {"pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
               "markdown": "text/markdown"}


class FileError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


class DocumentResponse(BaseModel):
    id: str
    name: str
    extension: str
    mediaType: str
    sizeBytes: int
    sha256: str
    uploadedAt: datetime
    category: None = None
    textStatus: str
    vectorStatus: str
    downloadUrl: str


class DocumentList(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


def serialize(row: Document):
    return DocumentResponse(
        id=row.id, name=row.name, extension=row.extension, mediaType=row.media_type,
        sizeBytes=row.size_bytes, sha256=row.sha256,
        uploadedAt=row.uploaded_at.replace(tzinfo=timezone.utc),
        textStatus=row.text_status, vectorStatus=row.vector_status,
        downloadUrl=f"/api/v1/documents/{row.id}/download",
    )


def sync_directory(directory: Path):
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def save_file(upload: UploadFile, request: Request, extension: str):
    data_dir = request.app.state.data_dir
    limit = request.app.state.max_upload_bytes
    document_id = str(uuid.uuid4())
    storage_key = uuid.uuid4().hex + ".bin"
    temporary = data_dir / "tmp" / f"{document_id}.part"
    intent = data_dir / "tmp" / f"{document_id}.intent.json"
    final = data_dir / "uploads" / storage_key
    landed = False
    try:
        digest = hashlib.sha256()
        size = 0
        upload.file.seek(0)
        with temporary.open("xb") as target:
            while block := upload.file.read(512 * 1024):
                size += len(block)
                if size > limit:
                    raise FileError(413, "FILE_TOO_LARGE", "文件超过允许的大小，请选择较小文件。")
                target.write(block)
                digest.update(block)
            if size == 0:
                raise FileError(400, "EMPTY_FILE", "不能上传空文件。")
            target.flush()
            os.fsync(target.fileno())
        if extension == "pdf":
            with temporary.open("rb") as source:
                if b"%PDF-" not in source.read(1024):
                    raise FileError(415, "INVALID_PDF", "文件没有有效的 PDF 文件头，请核对原文件。")
        uploaded_at = datetime.now(timezone.utc)
        fingerprint = digest.hexdigest()
        with intent.open("x", encoding="utf-8") as target:
            json.dump({"documentId": document_id, "storageKey": storage_key, "name": upload.filename,
                       "sizeBytes": size, "sha256": fingerprint, "uploadedAt": uploaded_at.isoformat()},
                      target, ensure_ascii=False)
            target.flush()
            os.fsync(target.fileno())
        sync_directory(intent.parent)
        os.replace(temporary, final)
        landed = True
        sync_directory(final.parent)
        sync_directory(temporary.parent)
        with Session(request.app.state.document_engine) as session:
            row = Document(id=document_id, name=upload.filename, extension=extension,
                           media_type=MEDIA_TYPES[extension], size_bytes=size, sha256=fingerprint,
                           storage_key=storage_key, uploaded_at=uploaded_at,
                           text_status="not_started", vector_status="not_started")
            session.add(row)
            session.commit()
            result = serialize(row)
        try:
            intent.unlink()
            sync_directory(intent.parent)
        except OSError:
            logger.exception("Committed document %s has a retained upload intent", document_id)
        return result
    except (OSError, SQLAlchemyError) as error:
        logger.exception("Upload failed: document=%s landed=%s", document_id, landed)
        if landed:
            raise FileError(503, "UPLOAD_OUTCOME_UNCERTAIN",
                            "文件已写入存储，但上传未能确认完成。请刷新列表核对后再决定是否重新上传。") from error
        raise FileError(503, "UPLOAD_SAVE_FAILED", "文件保存失败，请稍后重试。", retryable=True) from error
    finally:
        if not landed:
            for path in (temporary, intent):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not remove incomplete upload %s", document_id)


@router.get("/config")
def configuration(request: Request):
    return {"maxUploadBytes": request.app.state.max_upload_bytes,
            "allowedExtensions": list(MEDIA_TYPES)}


@router.post("/documents", status_code=201, response_model=DocumentResponse,
             openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {
                 "schema": {"type": "object", "required": ["file"],
                            "properties": {"file": {"type": "string", "format": "binary"}}}}}}})
async def upload_document(request: Request):
    maximum_body = request.app.state.max_upload_bytes + FORM_OVERHEAD_BYTES
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise FileError(415, "MULTIPART_REQUIRED", "请使用 multipart/form-data 上传文件。")
    if "content-length" in request.headers:
        try:
            length = int(request.headers["content-length"])
        except ValueError as error:
            raise FileError(400, "INVALID_UPLOAD", "上传请求长度无效。") from error
        if length < 0:
            raise FileError(400, "INVALID_UPLOAD", "上传请求长度无效。")
        if length > maximum_body:
            raise FileError(413, "FILE_TOO_LARGE", "文件超过允许的大小，请选择较小文件。")

    async def bounded_stream():
        count = 0
        async for chunk in request.stream():
            count += len(chunk)
            if count > maximum_body:
                raise MultiPartException(BODY_LIMIT_MESSAGE)
            yield chunk

    parser = MultiPartParser(request.headers, bounded_stream(), max_files=1, max_fields=0,
                             max_part_size=FORM_OVERHEAD_BYTES)
    try:
        form = await parser.parse()
    except (MultiPartException, ValueError, ClientDisconnect) as error:
        # Pinned Starlette 0.48.0 only closes these handles for MultiPartException.
        # Also close partial spool files for malformed requests and disconnects.
        for temporary in parser._files_to_close_on_error:
            temporary.close()
        if isinstance(error, MultiPartException) and error.message == BODY_LIMIT_MESSAGE:
            raise FileError(413, "FILE_TOO_LARGE", "文件超过允许的大小，请选择较小文件。") from error
        raise FileError(400, "INVALID_UPLOAD", "上传请求无效；每次请选择一个文件。", retryable=True) from error
    try:
        values = form.getlist("file")
        if len(form.multi_items()) != 1 or len(values) != 1 or not isinstance(values[0], UploadFile):
            raise FileError(400, "FILE_REQUIRED", "请选择一个 PDF、TXT 或 Markdown 文件。")
        upload = values[0]
        name = upload.filename or ""
        if not name.strip() or len(name) > 255 or re.search(r"[\\/\x00-\x1f\x7f]", name):
            raise FileError(400, "INVALID_FILENAME", "文件名无效；请使用不含路径或控制字符的文件名（最多 255 字）。")
        extension = Path(name).suffix.lower().lstrip(".")
        if extension not in MEDIA_TYPES:
            raise FileError(415, "UNSUPPORTED_FILE_TYPE", "仅支持 PDF、TXT、Markdown（.md / .markdown）。")
        if upload.size is not None and upload.size > request.app.state.max_upload_bytes:
            raise FileError(413, "FILE_TOO_LARGE", "文件超过允许的大小，请选择较小文件。")
        return await asyncio.to_thread(save_file, upload, request, extension)
    finally:
        await form.close()


@router.get("/documents", response_model=DocumentList)
def list_documents(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    try:
        with Session(request.app.state.document_engine) as session:
            total = session.scalar(select(func.count()).select_from(Document))
            rows = session.scalars(select(Document).order_by(Document.uploaded_at.desc(), Document.id.desc())
                                   .offset(offset).limit(limit)).all()
            return {"items": [serialize(row) for row in rows], "total": total, "limit": limit, "offset": offset}
    except SQLAlchemyError as error:
        logger.exception("Document list failed")
        raise FileError(503, "DATABASE_UNAVAILABLE", "无法读取文件列表，请稍后重试。", retryable=True) from error


def find_document(request: Request, document_id: uuid.UUID):
    try:
        with Session(request.app.state.document_engine) as session:
            row = session.get(Document, str(document_id))
            if row is None:
                raise FileError(404, "DOCUMENT_NOT_FOUND", "未找到该文件，请刷新列表。")
            session.expunge(row)
            return row
    except SQLAlchemyError as error:
        logger.exception("Document lookup failed")
        raise FileError(503, "DATABASE_UNAVAILABLE", "无法读取文件信息，请稍后重试。", retryable=True) from error


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def document_detail(request: Request, document_id: uuid.UUID):
    return serialize(find_document(request, document_id))


@router.get("/documents/{document_id}/download")
def download_document(request: Request, document_id: uuid.UUID):
    row = find_document(request, document_id)
    directory = (request.app.state.data_dir / "uploads").resolve()
    if not re.fullmatch(r"[0-9a-f]{32}\.bin", row.storage_key):
        raise FileError(409, "STORAGE_UNAVAILABLE", "原文件存储信息异常，请联系维护人员。")
    source = (directory / row.storage_key).resolve()
    if source.parent != directory:
        raise FileError(409, "STORAGE_UNAVAILABLE", "原文件存储信息异常，请联系维护人员。")
    try:
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as original:
            while block := original.read(512 * 1024):
                size += len(block)
                digest.update(block)
        if size != row.size_bytes or digest.hexdigest() != row.sha256:
            raise FileError(409, "STORAGE_INTEGRITY_ERROR", "原文件完整性校验失败，已停止下载；文件记录仍保留。")
    except OSError as error:
        logger.exception("Stored file unavailable: %s", row.id)
        raise FileError(409, "STORAGE_UNAVAILABLE", "原文件暂不可读取；文件记录仍保留，请联系维护人员。") from error
    return FileResponse(source, filename=row.name, media_type=row.media_type,
                        headers={"X-Content-SHA256": row.sha256, "X-Content-Type-Options": "nosniff"})
