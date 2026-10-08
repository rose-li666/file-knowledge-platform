"""Flat categories and reversible document archival; original bytes remain untouched."""
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .database import Category, Document
from .files import DocumentResponse, FileError, serialize

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


class CategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80, strict=True)


class CategoryResponse(BaseModel):
    id: str
    name: str
    activeCount: int
    archivedCount: int


class MoveRequest(BaseModel):
    categoryId: uuid.UUID | None


class BatchMoveRequest(MoveRequest):
    documentIds: list[uuid.UUID] = Field(min_length=1, max_length=100)


def normalized_name(value: str):
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise FileError(422, "INVALID_CATEGORY_NAME", "分类名称不能包含控制字符。")
    name = unicodedata.normalize("NFKC", value).strip()
    if not name or len(name) > 80:
        raise FileError(422, "INVALID_CATEGORY_NAME", "分类名称不能为空且最多为 80 字。")
    if name == "未分类":
        raise FileError(422, "RESERVED_CATEGORY_NAME", "未分类是系统默认分组，请使用其他名称。")
    return name, name.casefold()


def counts(session, category_id):
    result = {}
    for archived, count in session.execute(select(Document.archived_at.is_not(None), func.count(Document.id))
                                          .where(Document.category_id == category_id)
                                          .group_by(Document.archived_at.is_not(None))):
        result[bool(archived)] = count
    return {"activeCount": result.get(False, 0), "archivedCount": result.get(True, 0)}


def category_result(row, session):
    return {"id": row.id, "name": row.name, **counts(session, row.id)}


def database_error(error):
    logger.exception("Organization database operation failed")
    return FileError(503, "DATABASE_UNAVAILABLE", "操作未能确认完成，请刷新核对后重试。", retryable=True)


@router.get("/categories")
def list_categories(request: Request):
    try:
        with Session(request.app.state.document_engine) as session:
            grouped = {(category_id, bool(archived)): count for category_id, archived, count in session.execute(
                select(Document.category_id, Document.archived_at.is_not(None), func.count(Document.id))
                .group_by(Document.category_id, Document.archived_at.is_not(None)))}
            rows = session.scalars(select(Category).order_by(Category.name, Category.id)).all()
            items = [{"id": row.id, "name": row.name,
                      "activeCount": grouped.get((row.id, False), 0),
                      "archivedCount": grouped.get((row.id, True), 0)} for row in rows]
            return {"items": items, "unclassified": {"activeCount": grouped.get((None, False), 0),
                                                       "archivedCount": grouped.get((None, True), 0)}}
    except SQLAlchemyError as error:
        raise database_error(error) from error


@router.post("/categories", status_code=201, response_model=CategoryResponse)
def create_category(request: Request, body: CategoryRequest):
    name, key = normalized_name(body.name)
    try:
        with Session(request.app.state.document_engine) as session:
            row = Category(id=str(uuid.uuid4()), name=name, name_key=key)
            session.add(row)
            session.commit()
            return category_result(row, session)
    except IntegrityError as error:
        raise FileError(409, "CATEGORY_NAME_EXISTS", "分类名称已存在，请使用其他名称。") from error
    except SQLAlchemyError as error:
        raise database_error(error) from error


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
def rename_category(request: Request, category_id: uuid.UUID, body: CategoryRequest):
    name, key = normalized_name(body.name)
    try:
        with Session(request.app.state.document_engine) as session:
            row = session.get(Category, str(category_id))
            if row is None:
                raise FileError(404, "CATEGORY_NOT_FOUND", "分类不存在，请刷新分类列表。")
            row.name, row.name_key = name, key
            session.commit()
            return category_result(row, session)
    except IntegrityError as error:
        raise FileError(409, "CATEGORY_NAME_EXISTS", "分类名称已存在，请使用其他名称。") from error
    except SQLAlchemyError as error:
        raise database_error(error) from error


def change_document(request, document_id, action, category_id=None):
    try:
        with Session(request.app.state.document_engine) as session:
            row = session.get(Document, str(document_id))
            if row is None:
                raise FileError(404, "DOCUMENT_NOT_FOUND", "未找到该文件，请刷新列表。")
            if action == "move":
                category = session.get(Category, str(category_id)) if category_id else None
                if category_id is not None and category is None:
                    raise FileError(404, "CATEGORY_NOT_FOUND", "目标分类不存在，请刷新分类列表。")
                row.category = category
            elif action == "archive":
                if row.archived_at is None:
                    row.archived_at = datetime.now(timezone.utc)
            elif action == "restore":
                row.archived_at = None
            session.commit()
            return serialize(row)
    except SQLAlchemyError as error:
        raise database_error(error) from error


@router.patch("/documents/batch/category")
def batch_move_documents(request: Request, body: BatchMoveRequest):
    """One transaction for existing files; missing IDs yield per-file failures.

    Assigning the same category again is safe if an earlier response was lost.
    Database/commit errors abort the transaction and return an unconfirmed 503.
    Register before the UUID route so 'batch' is not parsed as a document ID.
    """
    identities = list(dict.fromkeys(str(value) for value in body.documentIds))
    target = str(body.categoryId) if body.categoryId else None
    try:
        with Session(request.app.state.document_engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            if target is not None and session.get(Category, target) is None:
                raise FileError(404, "CATEGORY_NOT_FOUND", "目标分类不存在，请刷新分类列表。")
            rows = {row.id: row for row in session.scalars(select(Document).where(Document.id.in_(identities)))}
            items = []
            for identity in identities:
                row = rows.get(identity)
                if row is None:
                    items.append({"documentId": identity, "name": None, "success": False,
                                  "error": {"code": "DOCUMENT_NOT_FOUND", "message": "文件不存在，请刷新列表核对。", "retryable": False}})
                else:
                    changed = row.category_id != target
                    row.category_id = target
                    items.append({"documentId": identity, "name": row.name, "success": True, "changed": changed})
            session.commit()
            return {"categoryId": target, "items": items,
                    "succeededCount": sum(item['success'] for item in items),
                    "failedCount": sum(not item['success'] for item in items)}
    except SQLAlchemyError as error:
        raise database_error(error) from error


@router.patch("/documents/{document_id}/category", response_model=DocumentResponse)
def move_document(request: Request, document_id: uuid.UUID, body: MoveRequest):
    return change_document(request, document_id, "move", body.categoryId)


@router.post("/documents/{document_id}/archive", response_model=DocumentResponse)
def archive_document(request: Request, document_id: uuid.UUID):
    return change_document(request, document_id, "archive")


@router.post("/documents/{document_id}/restore", response_model=DocumentResponse)
def restore_document(request: Request, document_id: uuid.UUID):
    return change_document(request, document_id, "restore")
