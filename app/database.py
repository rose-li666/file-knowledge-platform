"""Separate SQLite databases for diagnostics and business metadata."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DocumentBase(DeclarativeBase):
    pass


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


def open_database(path: Path, *, metadata=None):
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

    (metadata if metadata is not None else Base.metadata).create_all(engine)
    return engine
