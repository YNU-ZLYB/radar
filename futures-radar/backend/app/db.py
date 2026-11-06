from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def _normalize_url(url: str) -> str:
    """Supabase / Render / 常见云平台给的 postgres URL 统一成 SQLAlchemy 能用的形式。"""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


_db_url = _normalize_url(settings.database_url)

if _db_url.startswith("sqlite"):
    engine = create_engine(
        _db_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    # 云端免费 PostgreSQL 连接数有限，池子开小一点
    engine = create_engine(
        _db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
        pool_timeout=20,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
