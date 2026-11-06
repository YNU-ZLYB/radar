from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import selectinload

from .. import models
from ..config import settings
from ..db import SessionLocal
from ..models import Analysis, Digest, Factor, Feedback, FetchLog, RawDoc, Score, Source, Variety, VarietyFactor
from ..services import digest as digest_service
from ..services import market as market_service
from ..services import pipeline
from ..services.bus import bus, sse_format
from ..services.linkage import market_linkage_map
from ..services.scoring import sentiment
from ..services.serialize import analysis_dict, article_dict, iso_z, score_dict

CST = ZoneInfo("Asia/Shanghai")
router = APIRouter(prefix="/api/v1")

OIL_CORRELATION = {
    "MA": ("中", "伊朗气头成本与能源情绪传导"),
    "FG": ("中", "窑炉燃料成本与地产情绪"),
    "SA": ("中", "装置能源成本，间接受影响"),
    "SR": ("弱", "运费与宏观情绪，不改变主评分"),
    "CF": ("弱", "运费与宏观情绪，不改变主评分"),
}


def _today_start_utc() -> datetime:
    local = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _article_query():
    return select(RawDoc).options(
        selectinload(RawDoc.analyses).selectinload(Analysis.scores)
    ).join(Analysis, Analysis.doc_id == RawDoc.id)


@router.get("/health")
def health():
    return {"status": "ok", "mode": "deepseek" if settings.llm_available else "rule",
            "time": iso_z(datetime.now(timezone.utc))}


@router.get("/meta")
def meta():
    return {
        "app_name": settings.app_name,
        "mode": "deepseek" if settings.llm_available else "rule",
        "llm_available": settings.llm_available,
        "llm_model": settings.deepseek_model if settings.llm_available else None,
        "intervals": {
            "oil": settings.interval_oil, "jin10": settings.interval_jin10,
            "rss": settings.interval_rss, "czce": settings.interval_czce,
            "fred": settings.interval_fred, "worker": settings.interval_worker,
        },
    }


@router.get("/dashboard")
def dashboard(days: int = Query(7, ge=1, le=90)):
    with SessionLocal() as db:
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        docs_today = db.execute(
            select(func.count(RawDoc.id)).where(RawDoc.first_seen_at >= _today_start_utc())
        ).scalar() or 0
        matched_today = db.execute(
            select(func.count(RawDoc.id)).where(
                RawDoc.first_seen_at >= _today_start_utc(), RawDoc.status.in_(("quick", "analyzed"))
            )
        ).scalar() or 0
        analyzed_today = db.execute(
            select(func.count(Analysis.id)).where(
                Analysis.status == "analyzed", Analysis.created_at >= _today_start_utc()
            )
        ).scalar() or 0
        pending = db.execute(
            select(func.count(Analysis.id)).where(Analysis.status.in_(["quick", "pending"]))
        ).scalar() or 0
        ignored_today = db.execute(
            select(func.count(RawDoc.id)).where(
                RawDoc.first_seen_at >= _today_start_utc(), RawDoc.status == "ignored"
            )
        ).scalar() or 0

        varieties = db.execute(
            select(Variety).order_by(Variety.sort_order)
        ).scalars().all()

        period_scores = db.execute(
            select(Score).join(RawDoc, Score.doc_id == RawDoc.id)
            .where(RawDoc.first_seen_at >= start)
        ).scalars().all()

        # 拉所有品种的最新 DailySummary（SQLite 兼容：先找各品种最大 id）
        ds_max_ids = db.execute(
            select(func.max(models.DailySummary.id)).group_by(models.DailySummary.variety_code)
        ).scalars().all()
        ds_rows = db.execute(
            select(models.DailySummary).where(models.DailySummary.id.in_(ds_max_ids))
        ).scalars().all()
        latest_ds: dict[str, models.DailySummary] = {r.variety_code: r for r in ds_rows}

        quote_rows = db.execute(select(models.VarietyQuote)).scalars().all()
        quotes: dict[str, models.VarietyQuote] = {r.variety_code: r for r in quote_rows}
        linkages = market_linkage_map(db)

        groups = []
        for v in varieties:
            scores = [s for s in period_scores if s.variety_code == v.code]
            bull = sorted([s for s in scores if s.direction == "bullish"], key=lambda s: -s.importance)[:3]
            bear = sorted([s for s in scores if s.direction == "bearish"], key=lambda s: -s.importance)[:3]

            def pick(items):
                if not items:
                    return []
                docs = {d.id: d for d in db.execute(
                    select(RawDoc).options(selectinload(RawDoc.analyses).selectinload(Analysis.scores))
                    .where(RawDoc.id.in_([s.doc_id for s in items]))
                ).scalars().all()}
                out = []
                for s in items:
                    d = docs.get(s.doc_id)
                    if d:
                        a = d.analyses[0] if d.analyses else None
                        out.append({
                            "doc_id": d.id, "title": d.title,
                            "summary": a.summary if a else "",
                            "importance": round(s.importance, 2), "score": s.score,
                            "direction": s.direction, "factor": s.factor,
                            "source_name": d.source_name, "published_at": iso_z(d.published_at),
                        })
                return out

            ds = latest_ds.get(v.code)
            summary_out = None
            if ds and ds.status == "ok" and ds.summary:
                summary_out = {
                    "date": ds.date, "direction": ds.direction,
                    "sentiment_llm": ds.sentiment_llm, "confidence": ds.confidence,
                    "summary": ds.summary, "reasoning": ds.reasoning[:200],
                    "primary_factor": ds.primary_factor,
                    "factor_weights": ds.factor_weights or {},
                    "model": ds.model, "article_count": ds.article_count,
                    "updated_at": iso_z(ds.created_at),
                }

            q = quotes.get(v.code)
            quote_out = None
            if q:
                quote_out = {
                    "price": round(q.price, 2), "change_pct": round(q.change_pct, 2),
                    "direction": q.direction, "strength": q.strength,
                    "open_interest": int(q.open_interest or 0), "volume": int(q.volume or 0),
                    "high": round(q.high, 2), "low": round(q.low, 2),
                    "quoted_at": iso_z(q.quoted_at),
                }

            # 每张卡自己的更新时间：行情或研判的最新时间
            stamps = [x for x in [
                q.quoted_at if q else None,
                ds.created_at if ds else None,
            ] if x]
            card_updated = iso_z(max(stamps)) if stamps else None

            groups.append({
                "code": v.code, "name": v.name, "sector": v.sector,
                "is_active": v.is_active,
                "updated_at": card_updated,
                "sentiment": sentiment(scores) if scores else 0.0,
                "count": len(scores),
                "bullish_count": len([s for s in scores if s.direction == "bullish"]),
                "bearish_count": len([s for s in scores if s.direction == "bearish"]),
                "bull_score": round(sum(abs(s.score) for s in scores if s.direction == "bullish"), 2),
                "bear_score": round(sum(abs(s.score) for s in scores if s.direction == "bearish"), 2),
                "top_bullish": pick(bull),
                "top_bearish": pick(bear),
                "quote": quote_out,
                "linkage": linkages.get(v.code),
                "daily_summary": summary_out,
            })

        latest = db.execute(
            _article_query().order_by(desc(RawDoc.first_seen_at)).limit(12)
        ).scalars().all()

        sources = db.execute(select(Source).order_by(Source.priority)).scalars().all()
        return {
            "date": datetime.now(CST).strftime("%Y-%m-%d"),
            "generated_at": iso_z(datetime.now(timezone.utc).replace(tzinfo=None)),
            "stats": {
                "docs_today": docs_today, "matched_today": matched_today,
                "analyzed_today": analyzed_today, "pending": pending, "ignored_today": ignored_today,
            },
            "oil": market_service.latest_quotes(db),
            "varieties": groups,
            "latest": [article_dict(d) for d in latest],
            "sources": [{
                "code": s.code, "name": s.name, "level": s.level, "status": s.last_status,
                "enabled": s.enabled, "last_run_at": iso_z(s.last_run_at),
                "last_error": s.last_error, "total_docs": s.total_docs,
            } for s in sources],
            "mode": "deepseek" if settings.llm_available else "rule",
        }


@router.get("/varieties")
def list_varieties(days: int = Query(7, ge=1, le=90)):
    with SessionLocal() as db:
        rows = db.execute(select(Variety).order_by(Variety.sort_order)).scalars().all()
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        scores = db.execute(
            select(Score).join(RawDoc, Score.doc_id == RawDoc.id).where(RawDoc.first_seen_at >= start)
        ).scalars().all()
        out = []
        for v in rows:
            ss = [s for s in scores if s.variety_code == v.code]
            out.append({
                "code": v.code, "name": v.name, "sector": v.sector,
                "is_active": v.is_active, "aliases": v.aliases,
                "sentiment": sentiment(ss) if ss else 0.0,
                "count": len(ss),
                "factors": [{"name": vf.factor.name, "weight": vf.weight,
                             "color": vf.factor.color} for vf in v.factors],
            })
        return out


@router.get("/varieties/{code}")
def variety_detail(code: str, days: int = Query(7, ge=1, le=90)):
    with SessionLocal() as db:
        v = db.execute(select(Variety).where(Variety.code == code.upper())).scalars().first()
        if not v:
            raise HTTPException(404, "品种不存在")
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        scores = db.execute(
            select(Score).join(RawDoc, Score.doc_id == RawDoc.id)
            .where(Score.variety_code == v.code, RawDoc.first_seen_at >= start)
            .order_by(desc(Score.importance))
        ).scalars().all()
        corr = OIL_CORRELATION.get(v.code, ("弱", "间接影响"))
        oil = [q for q in market_service.latest_quotes(db) if q.get("price")]

        ds = db.execute(
            select(models.DailySummary).where(models.DailySummary.variety_code == v.code)
            .order_by(desc(models.DailySummary.created_at)).limit(1)
        ).scalar_one_or_none()
        summary_out = None
        if ds and ds.status == "ok" and ds.summary:
            summary_out = {
                "date": ds.date, "direction": ds.direction,
                "sentiment_llm": ds.sentiment_llm, "confidence": ds.confidence,
                "summary": ds.summary, "reasoning": ds.reasoning,
                "primary_factor": ds.primary_factor,
                "factor_weights": ds.factor_weights or {},
                "model": ds.model, "article_count": ds.article_count,
                "updated_at": iso_z(ds.created_at),
            }

        q = db.execute(
            select(models.VarietyQuote).where(models.VarietyQuote.variety_code == v.code)
        ).scalars().first()
        quote_out = None
        if q:
            quote_out = {
                "price": round(q.price, 2), "change_pct": round(q.change_pct, 2),
                "direction": q.direction, "strength": q.strength,
                "open_interest": int(q.open_interest or 0), "volume": int(q.volume or 0),
                "high": round(q.high, 2), "low": round(q.low, 2),
                "quoted_at": iso_z(q.quoted_at),
            }

        def _top(items, limit=3):
            ids = [s.doc_id for s in items[:limit]]
            docs = {d.id: d for d in db.execute(
                select(RawDoc).where(RawDoc.id.in_(ids))
            ).scalars().all()} if ids else {}
            return [{
                "doc_id": s.doc_id, "title": docs[s.doc_id].title,
                "importance": round(s.importance, 2), "score": s.score,
                "direction": s.direction, "factor": s.factor,
                "published_at": iso_z(docs[s.doc_id].published_at),
            } for s in items[:limit] if s.doc_id in docs]

        bull = sorted([s for s in scores if s.direction == "bullish"], key=lambda s: -s.importance)
        bear = sorted([s for s in scores if s.direction == "bearish"], key=lambda s: -s.importance)

        return {
            "code": v.code, "name": v.name, "sector": v.sector, "description": v.description,
            "is_active": v.is_active,
            "sentiment": sentiment(scores) if scores else 0.0,
            "count": len(scores),
            "factors": [{"name": vf.factor.name, "weight": vf.weight,
                         "keywords": vf.keywords, "color": vf.factor.color} for vf in v.factors],
            "oil_correlation": {"level": corr[0], "note": corr[1]},
            "oil": oil,
            "quote": quote_out,
            "daily_summary": summary_out,
            "top_bullish": _top(bull),
            "top_bearish": _top(bear),
            "linkage": market_linkage_map(db).get(v.code),
        }


@router.get("/varieties/{code}/trend")
def variety_trend(code: str, days: int = Query(60, ge=1, le=365),
                  bucket: str = Query("day", pattern="^(day|week)$")):
    """品种历史趋势：按日/周聚合的 sentiment 和累计 importance。"""
    with SessionLocal() as db:
        v = db.execute(select(Variety).where(Variety.code == code.upper())).scalars().first()
        if not v:
            raise HTTPException(404, "品种不存在")
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        rows = db.execute(
            select(Score.score, Score.importance, Score.direction, RawDoc.first_seen_at)
            .join(RawDoc, Score.doc_id == RawDoc.id)
            .where(Score.variety_code == v.code, RawDoc.first_seen_at >= start)
            .order_by(RawDoc.first_seen_at)
        ).all()

        def _bucket_key(ts: datetime) -> str:
            ts_local = ts.replace(tzinfo=timezone.utc).astimezone(CST)
            if bucket == "week":
                # ISO 周起始（周一）
                wk = ts_local.isocalendar()
                return f"{wk.year}-W{wk.week:02d}"
            return ts_local.strftime("%Y-%m-%d")

        buckets: dict[str, list] = {}
        for score_val, imp, direction, ts in rows:
            key = _bucket_key(ts)
            buckets.setdefault(key, []).append({
                "score": score_val, "importance": imp, "direction": direction, "ts": ts,
            })

        series = []
        running = 0.0  # 累计 sentiment（importance 加权，模拟"净情绪积分"）
        for key in sorted(buckets.keys()):
            items = buckets[key]
            total_imp = sum(it["importance"] for it in items)
            if total_imp > 0:
                sent = round(sum(it["score"] * it["importance"] for it in items) / total_imp * 100, 1)
            else:
                sent = 0.0
            running += sent * total_imp  # 重要的日子权重更大
            series.append({
                "bucket": key,
                "sentiment": sent,
                "sentiment_running": round(running, 1),
                "importance_total": round(total_imp, 3),
                "bullish": sum(1 for it in items if it["direction"] == "bullish"),
                "bearish": sum(1 for it in items if it["direction"] == "bearish"),
                "total": len(items),
            })
        return {"code": v.code, "name": v.name, "bucket": bucket, "days": days, "series": series}


@router.get("/varieties/{code}/feed")
def variety_feed(code: str, direction: str = Query("all"), min_score: float = 0.0,
                 days: int = 7, page: int = 1, page_size: int = 20):
    return _query_articles(page=page, page_size=page_size, variety=code.upper(),
                           direction=direction, min_score=min_score, days=days)


def _query_articles(page: int = 1, page_size: int = 20, variety: str | None = None,
                    direction: str | None = None, factor: str | None = None,
                    source: str | None = None, q: str | None = None,
                    status: str | None = None, days: int | None = 30,
                    min_score: float = 0.0, sort: str = "importance"):
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    with SessionLocal() as db:
        stmt = _article_query()
        if variety:
            stmt = stmt.join(Score, Score.doc_id == RawDoc.id).where(Score.variety_code == variety)
        if days:
            stmt = stmt.where(RawDoc.first_seen_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days))
        if direction and direction != "all":
            if variety:
                stmt = stmt.where(Score.direction == direction)
            else:
                stmt = stmt.where(Analysis.direction == direction)
        if factor:
            stmt = stmt.where(Analysis.factor == factor)
        if source:
            stmt = stmt.where(RawDoc.source_name == source)
        if status:
            stmt = stmt.where(Analysis.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(RawDoc.title.ilike(like), RawDoc.content.ilike(like)))
        if min_score > 0:
            if variety:
                stmt = stmt.where(Score.importance >= min_score)
            else:
                stmt = stmt.join(Score, Score.doc_id == RawDoc.id).where(Score.importance >= min_score)

        if sort == "time":
            stmt = stmt.order_by(desc(RawDoc.published_at))
        elif variety:
            stmt = stmt.order_by(desc(Score.importance))
        else:
            stmt = stmt.order_by(desc(RawDoc.first_seen_at))

        rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().unique().all()
        items = [article_dict(d) for d in rows]
        return {"items": items, "page": page, "page_size": page_size,
                "has_more": len(items) == page_size}


@router.get("/articles")
def articles(page: int = 1, page_size: int = 20, variety: str | None = None,
             direction: str | None = "all", factor: str | None = None,
             source: str | None = None, q: str | None = None,
             status: str | None = None, days: int | None = 30,
             min_score: float = 0.0, sort: str = "importance"):
    return _query_articles(page=page, page_size=page_size, variety=variety, direction=direction,
                           factor=factor, source=source, q=q, status=status, days=days,
                           min_score=min_score, sort=sort)


@router.get("/articles/{doc_id}")
def article_detail(doc_id: int):
    with SessionLocal() as db:
        doc = db.execute(
            _article_query().where(RawDoc.id == doc_id)
        ).scalars().first()
        if not doc:
            raise HTTPException(404, "信息不存在")
        data = article_dict(doc)
        analysis = doc.analyses[0] if doc.analyses else None
        data["feedback"] = [
            {"id": f.id, "label": f.label, "note": f.note,
             "corrected_fields": f.corrected_fields, "created_at": iso_z(f.created_at)}
            for f in (analysis.feedback if analysis else [])
        ]
        variant_rows = db.execute(select(Variety)).scalars().all()
        data["variety_names"] = {v.code: v.name for v in variant_rows}
        return data


class ManualDocIn(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    content: str = Field(default="", max_length=8000)
    url: str = ""


@router.post("/articles/manual")
async def create_manual(payload: ManualDocIn):
    result = await asyncio.to_thread(
        pipeline.create_manual_doc, payload.title, payload.content, payload.url
    )
    if not result:
        raise HTTPException(400, "未识别到相关品种或内容重复")
    await bus.publish("article_new", result)
    with SessionLocal() as db:
        doc = db.execute(select(RawDoc).where(RawDoc.id == result["id"])).scalars().first()
        if doc and doc.analyses and doc.analyses[0].status == "quick":
            pipeline.finalize_queue.put_nowait(doc.id)
    return result


class FeedbackIn(BaseModel):
    label: str = "adjust"
    note: str = ""
    direction: str | None = None
    strength: int | None = None
    factor: str | None = None
    summary: str | None = None


@router.post("/articles/{doc_id}/feedback")
async def submit_feedback(doc_id: int, payload: FeedbackIn):
    with SessionLocal() as db:
        doc = db.execute(
            _article_query().where(RawDoc.id == doc_id)
        ).scalars().first()
        if not doc or not doc.analyses:
            raise HTTPException(404, "信息不存在")
        analysis = doc.analyses[0]
        corrected = {k: v for k, v in payload.model_dump().items()
                     if k in ("direction", "strength", "factor", "summary") and v is not None}
        if payload.direction in ("bullish", "bearish", "neutral"):
            analysis.direction = payload.direction
        if payload.strength is not None:
            analysis.strength = max(1, min(5, payload.strength))
        if payload.factor:
            analysis.factor = payload.factor
        if payload.summary:
            analysis.summary = payload.summary
        analysis.confidence = max(analysis.confidence, 0.8)

        for s in analysis.scores:
            s.direction = analysis.direction
            s.factor = analysis.factor
            s.confidence = analysis.confidence
            s.score = pipeline.scoring.compute_score(
                analysis.direction, analysis.strength, analysis.confidence,
                doc.source_weight, doc.published_at, analysis.horizon, novelty=1.0,
            )
            s.importance = abs(s.score)

        db.add(Feedback(analysis_id=analysis.id, label=payload.label,
                        note=payload.note, corrected_fields=corrected))
        db.commit()
        db.refresh(doc)
        data = article_dict(doc)
    await bus.publish("analysis_update", data)
    return data


@router.get("/factors")
def factors():
    with SessionLocal() as db:
        fs = db.execute(select(Factor).order_by(Factor.id)).scalars().all()
        matrix = db.execute(select(VarietyFactor).join(Variety).where(Variety.is_active.is_(True))).scalars().all()
        return {
            "factors": [{"name": f.name, "category": f.category, "description": f.description,
                         "color": f.color} for f in fs],
            "matrix": [{"variety": vf.variety.code, "factor": vf.factor.name,
                        "weight": vf.weight, "keywords": vf.keywords} for vf in matrix],
        }


@router.get("/sources")
def sources():
    with SessionLocal() as db:
        rows = db.execute(select(Source).order_by(Source.priority)).scalars().all()
        logs = db.execute(
            select(FetchLog).order_by(desc(FetchLog.created_at)).limit(30)
        ).scalars().all()
        return {
            "sources": [{
                "id": s.id, "code": s.code, "name": s.name, "type": s.type, "level": s.level,
                "url": s.url, "weight": s.weight, "interval_sec": s.interval_sec,
                "enabled": s.enabled, "last_run_at": iso_z(s.last_run_at),
                "last_status": s.last_status, "last_error": s.last_error, "total_docs": s.total_docs,
            } for s in rows],
            "logs": [{
                "id": l.id, "source_code": l.source_code, "status": l.status, "error": l.error,
                "fetched_count": l.fetched_count, "new_count": l.new_count,
                "duration_ms": l.duration_ms, "created_at": iso_z(l.created_at),
            } for l in logs],
        }


@router.post("/sources/{source_id}/toggle")
def toggle_source(source_id: int):
    with SessionLocal() as db:
        s = db.get(Source, source_id)
        if not s:
            raise HTTPException(404, "数据源不存在")
        s.enabled = not s.enabled
        db.commit()
        return {"id": s.id, "enabled": s.enabled}


class TaskResult(BaseModel):
    ok: bool
    detail: dict | None = None


@router.post("/tasks/run/{task}")
async def run_task(task: str):
    from ..services.scheduler import run_task as scheduler_run_task
    result = await scheduler_run_task(task)
    return {"ok": result.get("ok", False), "task": task, "result": result}


@router.get("/market/oil")
def oil_market():
    with SessionLocal() as db:
        return {"quotes": market_service.latest_quotes(db),
                "brent_daily": market_service.brent_history(db)}


@router.get("/digests")
def list_digests(limit: int = 10):
    with SessionLocal() as db:
        rows = db.execute(select(Digest).order_by(desc(Digest.date)).limit(limit)).scalars().all()
        return [{"date": d.date, "created_at": iso_z(d.created_at),
                 "payload": d.payload} for d in rows]


@router.post("/digests/generate")
async def generate_digest(date: str | None = None):
    target = date or digest_service.today_str()
    result = await asyncio.to_thread(digest_service.upsert_digest, target)
    return {"date": result["date"], "markdown": result["markdown"]}


@router.get("/digests/{date}/markdown", response_class=PlainTextResponse)
def digest_markdown(date: str):
    with SessionLocal() as db:
        row = db.execute(select(Digest).where(Digest.date == date)).scalars().first()
        if not row:
            raise HTTPException(404, "该日期暂无简报，请先生成")
        return PlainTextResponse(row.markdown, media_type="text/markdown; charset=utf-8")


@router.get("/stream")
async def stream(request: Request):
    queue = await bus.subscribe()

    async def event_gen():
        yield ": connected\n\n"
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    if await request.is_disconnected():
                        break
                    continue
                yield sse_format(payload["event"], payload)
                if await request.is_disconnected():
                    break
        finally:
            await bus.unsubscribe(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
