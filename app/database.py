"""Separate SQLite databases for diagnostics and business metadata."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentBase(DeclarativeBase):
    pass


class Category(DocumentBase):
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(240), unique=True)


class Document(DocumentBase):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(10))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(40), unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    text_status: Mapped[str] = mapped_column(String(20), default="not_started")
    vector_status: Mapped[str] = mapped_column(String(20), default="not_started")
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("categories.id", ondelete="RESTRICT"))
    category: Mapped[Category | None] = relationship(lazy="selectin")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Probe(Base):
    __tablename__ = "m1_probes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ProbeVector(Base):
    __tablename__ = "m1_vectors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[str] = mapped_column(String(255))
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    index_key: Mapped[str] = mapped_column(String(64))


def open_database(path: Path, *, metadata=None, initialize=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path.resolve().as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")

    if initialize:
        (metadata if metadata is not None else Base.metadata).create_all(engine)
    return engine


def open_document_database(path: Path):
    """Upgrade the original M2 table transactionally; never recreate or discard it."""
    engine = open_database(path, initialize=False)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version > 1:
                raise ValueError("Business database schema is newer than this application")
            columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(documents)")}
            if columns:
                required = {"id", "name", "extension", "media_type", "size_bytes", "sha256",
                            "storage_key", "uploaded_at", "text_status", "vector_status"}
                if not required.issubset(columns):
                    raise ValueError("Unsupported documents schema; existing data was not modified")
                Category.__table__.create(connection, checkfirst=True)
                if "category_id" not in columns:
                    connection.exec_driver_sql("ALTER TABLE documents ADD COLUMN category_id VARCHAR(36) REFERENCES categories(id) ON DELETE RESTRICT")
                if "archived_at" not in columns:
                    connection.exec_driver_sql("ALTER TABLE documents ADD COLUMN archived_at DATETIME")
            DocumentBase.metadata.create_all(connection)
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_documents_category_archive ON documents(category_id, archived_at)")
            connection.exec_driver_sql("PRAGMA user_version=1")
            connection.commit()
    except Exception:
        engine.dispose()
        raise
    return engine
