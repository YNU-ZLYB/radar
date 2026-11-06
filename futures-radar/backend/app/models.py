from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Variety(Base):
    __tablename__ = "varieties"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(32))
    sector: Mapped[str] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(32), default="CZCE")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    factors: Mapped[list["VarietyFactor"]] = relationship(back_populates="variety")


class Factor(Base):
    __tablename__ = "factors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(16), unique=True)
    category: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="#64748b")


class VarietyFactor(Base):
    __tablename__ = "variety_factors"
    __table_args__ = (UniqueConstraint("variety_id", "factor_id", name="uq_variety_factor"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    variety_id: Mapped[int] = mapped_column(ForeignKey("varieties.id"))
    factor_id: Mapped[int] = mapped_column(ForeignKey("factors.id"))
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    keywords: Mapped[list] = mapped_column(JSON, default=list)

    variety: Mapped[Variety] = relationship(back_populates="factors")
    factor: Mapped[Factor] = relationship()


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))  # official / industry / news / market / manual
    level: Mapped[str] = mapped_column(String(2), default="C")  # A/B/C/E/F
    url: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float, default=0.65)
    interval_sec: Mapped[int] = mapped_column(Integer, default=300)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="idle")
    last_error: Mapped[str] = mapped_column(Text, default="")
    total_docs: Mapped[int] = mapped_column(Integer, default=0)


class RawDoc(Base):
    __tablename__ = "raw_docs"
    __table_args__ = (
        Index("ix_raw_docs_published", "published_at"),
        Index("ix_raw_docs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    source_name: Mapped[str] = mapped_column(String(64), default="")
    source_weight: Mapped[float] = mapped_column(Float, default=0.65)
    url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    matched_varieties: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="doc", cascade="all, delete-orphan")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("raw_docs.id"), index=True)
    model: Mapped[str] = mapped_column(String(64), default="rule-quick")
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    status: Mapped[str] = mapped_column(String(16), default="quick")  # quick / analyzed / pending / failed
    varieties: Mapped[list] = mapped_column(JSON, default=list)
    direction: Mapped[str] = mapped_column(String(12), default="neutral")
    strength: Mapped[int] = mapped_column(Integer, default=1)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    horizon: Mapped[str] = mapped_column(String(16), default="short")
    factor: Mapped[str] = mapped_column(String(16), default="供需")
    event_type: Mapped[str] = mapped_column(String(32), default="其他")
    summary: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    region: Mapped[str] = mapped_column(String(64), default="")
    effective_date: Mapped[str] = mapped_column(String(16), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    doc: Mapped[RawDoc] = relationship(back_populates="analyses")
    scores: Mapped[list["Score"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    feedback: Mapped[list["Feedback"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("analysis_id", "variety_code", name="uq_analysis_variety"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), index=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("raw_docs.id"), index=True)
    variety_code: Mapped[str] = mapped_column(String(8), index=True)
    direction: Mapped[str] = mapped_column(String(12), default="neutral")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    factor: Mapped[str] = mapped_column(String(16), default="供需")
    is_divergent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    analysis: Mapped[Analysis] = relationship(back_populates="scores")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id"), index=True)
    label: Mapped[str] = mapped_column(String(16), default="correct")  # correct / wrong / adjust
    note: Mapped[str] = mapped_column(Text, default="")
    corrected_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    analysis: Mapped[Analysis] = relationship(back_populates="feedback")


class FetchLog(Base):
    __tablename__ = "fetch_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    source_code: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok / failed / skipped
    error: Mapped[str] = mapped_column(Text, default="")
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class MarketQuote(Base):
    __tablename__ = "market_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(32))
    price: Mapped[float] = mapped_column(Float)
    prev_close: Mapped[float] = mapped_column(Float, default=0.0)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    quoted_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    source: Mapped[str] = mapped_column(String(32), default="sina")
    unit: Mapped[str] = mapped_column(String(16), default="USD/bbl")


class MarketDaily(Base):
    __tablename__ = "market_daily"
    __table_args__ = (UniqueConstraint("benchmark", "trade_date", name="uq_benchmark_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    close: Mapped[float] = mapped_column(Float, default=0.0)


class Digest(Base):
    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("date", name="uq_digest_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    markdown: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class VarietyQuote(Base):
    """品种主力连续合约最新行情快照（每个品种一条，实时覆盖）。"""

    __tablename__ = "variety_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    variety_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(32), default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    prev_settle: Mapped[float] = mapped_column(Float, default=0.0)
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    direction: Mapped[str] = mapped_column(String(12), default="neutral")
    strength: Mapped[int] = mapped_column(Integer, default=1)
    open_interest: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    quoted_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    source: Mapped[str] = mapped_column(String(32), default="sina")


class DailySummary(Base):
    """品种日度 DeepSeek 汇总研判：每天一次，把该品种近 N 天资讯综合判断并写一句话总结。"""

    __tablename__ = "daily_summaries"
    __table_args__ = (UniqueConstraint("variety_code", "date", name="uq_daily_summary_code_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    variety_code: Mapped[str] = mapped_column(String(8), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # CST 日期 YYYY-MM-DD
    model: Mapped[str] = mapped_column(String(32), default="rule")
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok / failed / skipped
    direction: Mapped[str] = mapped_column(String(16), default="neutral")
    sentiment_llm: Mapped[float] = mapped_column(Float, default=0.0)  # LLM 专家 sentiment -100~100
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    horizon: Mapped[str] = mapped_column(String(16), default="short")
    primary_factor: Mapped[str] = mapped_column(String(32), default="")
    factor_weights: Mapped[dict] = mapped_column(JSON, default=dict)  # {因子名: 权重} 由 LLM 给出
    summary: Mapped[str] = mapped_column(Text, default="")             # 一句话结论（卡片下方展示）
    reasoning: Mapped[str] = mapped_column(Text, default="")           # 完整推理链
    evidence: Mapped[list] = mapped_column(JSON, default=list)         # 关键资讯标题列表
    article_count: Mapped[int] = mapped_column(Integer, default=0)     # 汇总时纳入的资讯条数
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
