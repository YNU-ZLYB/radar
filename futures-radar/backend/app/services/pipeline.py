"""入库流水线：清洗 → 去重 → 品种识别 → 规则快判 → 入库 → SSE 推送 → 异步精判队列。"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select

from ..config import settings
from ..db import SessionLocal
from ..models import Analysis, RawDoc, Score, Source, Variety, VarietyFactor
from . import rules, scoring
from .bus import bus
from .serialize import article_dict

finalize_queue: asyncio.Queue[int] = asyncio.Queue()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def content_hash(title: str, content: str) -> str:
    payload = normalize(title) + "|" + normalize(content)[:3000]
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@dataclass
class IngestResult:
    created: int = 0
    matched: int = 0
    duplicated: int = 0


def active_varieties(db) -> list[dict]:
    rows = db.execute(select(Variety).where(Variety.is_active.is_(True)).order_by(Variety.sort_order)).scalars().all()
    out = []
    for v in rows:
        factor_names = [vf.factor.name for vf in v.factors]
        out.append({
            "code": v.code, "name": v.name, "sector": v.sector,
            "aliases": v.aliases or [], "keywords": v.keywords or [],
            "factor_names": factor_names,
        })
    return out


def custom_factor_keywords(db, codes: list[str]) -> dict[str, list[str]]:
    if not codes:
        return {}
    rows = db.execute(
        select(VarietyFactor).join(Variety).where(Variety.code.in_(codes))
    ).scalars().all()
    merged: dict[str, list[str]] = {}
    for vf in rows:
        if vf.keywords:
            merged.setdefault(vf.factor.name, []).extend(vf.keywords)
    return {k: list(dict.fromkeys(v)) for k, v in merged.items()}


def _recent_docs(db, days: int = 7, limit: int = 300) -> list[RawDoc]:
    since = utc_now() - timedelta(days=days)
    return db.execute(
        select(RawDoc).where(RawDoc.first_seen_at >= since)
        .order_by(desc(RawDoc.first_seen_at)).limit(limit)
    ).scalars().all()


def _novelty(doc_title: str, recent: list[RawDoc], codes: list[str]) -> float:
    max_sim = 0.0
    sel_codes = set(codes)
    for other in recent:
        if not other.matched_varieties or not (sel_codes & set(other.matched_varieties)):
            continue
        max_sim = max(max_sim, scoring.bigram_similarity(doc_title, other.title))
    return round(max(0.2, 1.0 - min(0.8, max_sim)), 3)


def _is_divergent(db, code: str, direction: str) -> bool:
    if direction == "neutral":
        return False
    opposite = "bearish" if direction == "bullish" else "bullish"
    since = utc_now() - timedelta(days=3)
    found = db.execute(
        select(Score.id).where(
            Score.variety_code == code,
            Score.direction == opposite,
            Score.importance >= 2.0,
            Score.created_at >= since,
        ).limit(1)
    ).first()
    return bool(found)


def _add_scores(db, analysis: Analysis, doc: RawDoc, items: list[dict], novelty: float) -> None:
    for item in items:
        code = item["code"]
        direction = item["direction"]
        s = scoring.compute_score(
            direction=direction,
            strength=item["strength"],
            confidence=item["confidence"],
            source_weight=doc.source_weight,
            published_at=doc.published_at,
            horizon=item.get("horizon", "short"),
            novelty=novelty,
        )
        db.add(Score(
            analysis_id=analysis.id,
            doc_id=doc.id,
            variety_code=code,
            direction=direction,
            score=s,
            importance=abs(s),
            confidence=item["confidence"],
            factor=item.get("factor", "供需"),
            is_divergent=_is_divergent(db, code, direction),
        ))


def _ingest_single(item, source_id: int, varieties: list[dict], is_manual: bool = False) -> tuple[int | None, int, dict | None]:
    """返回 (doc_id, 命中品种数, SSE payload)。"""
    title = (item.title or "").strip()
    content = (item.content or "").strip()
    if not title and not content:
        return None, 0, None
    if not title:
        title = content[:60]
    text = f"{title}\n{content}"
    chash = content_hash(title, content)

    with SessionLocal() as db:
        source = db.get(Source, source_id)
        if not source:
            return None, 0, None
        dup = db.execute(select(RawDoc.id).where(RawDoc.content_hash == chash).limit(1)).first()
        if dup:
            return None, 0, None

        recent = _recent_docs(db)
        if any(
            scoring.bigram_similarity(title, d.title) >= 0.92 and d.source_id == source.id
            for d in recent if d.title
        ):
            return None, 0, None

        codes = rules.detect_varieties(text, varieties)
        doc = RawDoc(
            source_id=source.id,
            source_name=source.name,
            source_weight=source.weight,
            url=item.url,
            title=title[:500],
            content=content[:8000],
            published_at=item.published_at,
            first_seen_at=utc_now(),
            content_hash=chash,
            matched_varieties=codes,
            is_manual=is_manual,
            status="ignored" if not codes else "quick",
        )
        db.add(doc)
        db.flush()
        source.total_docs = (source.total_docs or 0) + 1

        if not codes:
            db.commit()
            return doc.id, 0, None

        ckw = custom_factor_keywords(db, codes)
        novelty = _novelty(title, recent, codes)
        rr = rules.analyze(text, title, source.weight, ckw, important=getattr(item, "important", False))

        analysis = Analysis(
            doc_id=doc.id,
            model=settings.quick_model,
            prompt_version="v1",
            status="quick",
            varieties=codes,
            direction=rr.direction,
            strength=rr.strength,
            confidence=settings.candidate_confidence,
            horizon=rr.horizons.get("horizon", "short"),
            factor=rr.factor,
            event_type=rr.event_type,
            summary=rr.summary,
            evidence=rr.evidence,
            reasoning=rr.reasoning,
        )
        db.add(analysis)
        db.flush()
        _add_scores(db, analysis, doc, [
            {"code": c, "direction": rr.direction, "strength": rr.strength,
             "confidence": settings.candidate_confidence, "factor": rr.factor,
             "horizon": rr.horizons.get("horizon", "short")}
            for c in codes
        ], novelty)
        db.commit()
        db.refresh(doc)
        db.refresh(analysis)
        payload = article_dict(doc)
        return doc.id, len(codes), payload


async def ingest_items(items, source: Source, log_new: list[int] | None = None) -> IngestResult:
    result = IngestResult()
    source_snapshot = source
    with SessionLocal() as db:
        varieties = active_varieties(db)
    for item in items:
        doc_id, matched, payload = _ingest_single(item, source_snapshot.id, varieties)
        if doc_id is None:
            result.duplicated += 1
            continue
        result.created += 1
        if matched and payload:
            result.matched += 1
            await bus.publish("article_new", payload)
            finalize_queue.put_nowait(doc_id)
            if log_new is not None:
                log_new.append(doc_id)
    return result


def create_manual_doc(title: str, content: str, url: str = "",
                      published_at: datetime | None = None) -> dict | None:
    with SessionLocal() as db:
        source = db.execute(select(Source).where(Source.code == "manual")).scalars().first()
        if not source:
            source = Source(code="manual", name="手工录入", type="manual", level="E", weight=0.8)
            db.add(source)
            db.commit()
            db.refresh(source)
        source_id = source.id
        varieties = active_varieties(db)
    item = type("Item", (), {
        "title": title, "content": content, "url": url,
        "published_at": published_at or utc_now(), "external_id": "", "important": True,
    })()
    doc_id, matched, payload = _ingest_single(item, source_id, varieties, is_manual=True)
    if doc_id and matched:
        finalize_queue.put_nowait(doc_id)
    return payload
