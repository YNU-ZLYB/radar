"""异步精判 Worker：LLM 可用时调用 DeepSeek，否则规则引擎补全。"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import Analysis, RawDoc, Score
from . import rules
from .bus import bus
from .llm import analyze_with_llm
from .pipeline import custom_factor_keywords, finalize_queue, _novelty, _recent_docs
from .scoring import compute_score
from .serialize import article_dict


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _replace_scores(db, analysis: Analysis, doc: RawDoc, items: list[dict], novelty: float) -> None:
    db.query(Score).filter(Score.analysis_id == analysis.id).delete(synchronize_session=False)
    db.flush()
    for item in items:
        s = compute_score(
            direction=item["direction"], strength=item["strength"], confidence=item["confidence"],
            source_weight=doc.source_weight, published_at=doc.published_at,
            horizon=item.get("horizon", "short"), novelty=novelty,
        )
        db.add(Score(
            analysis_id=analysis.id, doc_id=doc.id, variety_code=item["code"],
            direction=item["direction"], score=s, importance=abs(s),
            confidence=item["confidence"], factor=item.get("factor", "供需"),
        ))


async def finalize_doc(doc_id: int) -> None:
    with SessionLocal() as db:
        doc = db.get(RawDoc, doc_id)
        if not doc or not doc.analyses:
            return
        analysis = doc.analyses[0]
        if analysis.status != "quick":
            return

        codes = list(doc.matched_varieties or [])
        candidates = []
        from ..models import Variety
        rows = db.execute(select(Variety).where(Variety.code.in_(codes))).scalars().all()
        for v in rows:
            candidates.append({
                "code": v.code, "name": v.name, "aliases": v.aliases or [],
                "factor_names": [vf.factor.name for vf in v.factors],
            })
        ckw = custom_factor_keywords(db, codes)
        recent = _recent_docs(db)
        novelty = _novelty(doc.title, recent, codes)

        started = utc_now()
        used_llm = False
        try:
            if settings.llm_available:
                used_llm = True
                llm = await analyze_with_llm(doc.title, doc.content, candidates)
                results = [r for r in llm.results if r["code"] in codes]
                if not results:
                    analysis.model = llm.model
                    analysis.status = "analyzed"
                    analysis.direction = "neutral"
                    analysis.confidence = 0.3
                    analysis.summary = "AI 判定与候选品种无直接关系"
                    analysis.reasoning = "LLM 未返回有效品种影响"
                    analysis.latency_ms = llm.latency_ms
                    db.query(Score).filter(Score.analysis_id == analysis.id).delete(synchronize_session=False)
                    doc.matched_varieties = []
                    doc.status = "analyzed"
                    db.commit()
                    await bus.publish("analysis_update", article_dict(doc))
                    return

                primary = max(results, key=lambda r: r["strength"] * r["confidence"])
                analysis.model = llm.model
                analysis.status = "analyzed"
                analysis.varieties = [r["code"] for r in results]
                analysis.direction = primary["direction"]
                analysis.strength = primary["strength"]
                analysis.confidence = primary["confidence"]
                analysis.horizon = primary["horizon"]
                analysis.factor = primary["factor"]
                analysis.event_type = primary["event_type"]
                analysis.summary = primary["summary"] or analysis.summary
                analysis.evidence = primary["evidence"] or analysis.evidence
                analysis.reasoning = primary["reasoning"] or analysis.reasoning
                analysis.region = primary.get("region", "")
                analysis.latency_ms = llm.latency_ms
                doc.matched_varieties = [r["code"] for r in results]
                doc.status = "analyzed"
                _replace_scores(db, analysis, doc, results, novelty)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            analysis.status = "failed"
            analysis.reasoning = f"LLM 调用失败，已回退规则：{type(exc).__name__}"
            db.commit()
            used_llm = False

        if not used_llm:
            rr = rules.analyze(f"{doc.title}\n{doc.content}", doc.title, doc.source_weight, ckw,
                               important=False)
            analysis.model = settings.rule_model
            analysis.status = "analyzed"
            analysis.direction = rr.direction
            analysis.strength = rr.strength
            analysis.confidence = rr.confidence
            analysis.horizon = rr.horizons.get("horizon", "short")
            analysis.factor = rr.factor
            analysis.event_type = rr.event_type
            analysis.summary = rr.summary
            analysis.evidence = rr.evidence
            analysis.reasoning = rr.reasoning
            analysis.latency_ms = int((utc_now() - started).total_seconds() * 1000)
            doc.status = "analyzed"
            _replace_scores(db, analysis, doc, [
                {"code": c, "direction": rr.direction, "strength": rr.strength,
                 "confidence": rr.confidence, "factor": rr.factor,
                 "horizon": rr.horizons.get("horizon", "short")}
                for c in codes
            ], novelty)

        analysis.updated_at = utc_now()
        db.commit()
        db.refresh(doc)
        await bus.publish("analysis_update", article_dict(doc))


async def requeue_stuck() -> int:
    with SessionLocal() as db:
        rows = db.execute(
            select(Analysis.doc_id).where(Analysis.status == "quick").limit(200)
        ).scalars().all()
    for doc_id in rows:
        finalize_queue.put_nowait(doc_id)
    return len(rows)


async def worker_loop() -> None:
    await asyncio.sleep(2)
    await requeue_stuck()
    while True:
        doc_id = await finalize_queue.get()
        try:
            await finalize_doc(doc_id)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            finalize_queue.task_done()
