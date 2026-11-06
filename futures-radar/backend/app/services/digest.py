"""每日简报：按品种分组，多空 Top 与情绪。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..config import settings
from ..db import SessionLocal
from ..models import Analysis, Digest, RawDoc, Score, Variety
from .market import latest_quotes
from .scoring import sentiment
from .serialize import iso_z

CST = ZoneInfo("Asia/Shanghai")


def _day_range(date_str: str) -> tuple[datetime, datetime]:
    local_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=CST)
    start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def _item(score: Score, doc: RawDoc, analysis: Analysis) -> dict:
    return {
        "doc_id": doc.id,
        "title": doc.title,
        "summary": analysis.summary,
        "direction": score.direction,
        "importance": round(score.importance, 2),
        "score": score.score,
        "factor": score.factor,
        "source_name": doc.source_name,
        "url": doc.url,
        "published_at": iso_z(doc.published_at),
        "status": analysis.status,
    }


def build_digest(date_str: str, top_n: int | None = None) -> dict:
    top_n = top_n or settings.top_n
    start, end = _day_range(date_str)
    # 当天数据太少（例如凌晨刚开工）时，回退到最近 24 小时，避免简报空白
    if date_str == today_str():
        with SessionLocal() as db:
            n = db.execute(
                select(func.count(Score.id)).join(RawDoc, Score.doc_id == RawDoc.id)
                .where(RawDoc.first_seen_at >= start, RawDoc.first_seen_at < end)
            ).scalar() or 0
        if n < 5:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            start, end = now - timedelta(hours=24), now + timedelta(minutes=10)
    with SessionLocal() as db:
        varieties = db.execute(
            select(Variety).where(Variety.is_active.is_(True)).order_by(Variety.sort_order)
        ).scalars().all()
        groups = []
        for v in varieties:
            rows = db.execute(
                select(Score, RawDoc, Analysis)
                .join(RawDoc, Score.doc_id == RawDoc.id)
                .join(Analysis, Score.analysis_id == Analysis.id)
                .where(Score.variety_code == v.code, RawDoc.first_seen_at >= start, RawDoc.first_seen_at < end)
                .order_by(Score.importance.desc())
            ).all()
            all_scores = [r[0].score for r in rows]
            bullish = [_item(s, d, a) for s, d, a in rows if s.direction == "bullish"][:top_n]
            bearish = [_item(s, d, a) for s, d, a in rows if s.direction == "bearish"][:top_n]
            groups.append({
                "code": v.code, "name": v.name, "sector": v.sector,
                "sentiment": sentiment(all_scores) if rows else 0.0,
                "count": len(rows),
                "bullish": bullish, "bearish": bearish,
            })
        oil = latest_quotes(db)
    return {
        "date": date_str,
        "generated_at": iso_z(datetime.now(timezone.utc).replace(tzinfo=None)),
        "mode": "deepseek" if settings.llm_available else "rule",
        "oil": oil,
        "varieties": groups,
    }


def render_markdown(payload: dict) -> str:
    lines = [f"# 郑商所期货资讯简报 · {payload['date']}", ""]
    mode = "DeepSeek 精判" if payload.get("mode") == "deepseek" else "规则引擎（免费模式）"
    oil_txt = " / ".join(
        f"{q['name']} {q['price']}{'（%+.2f%%）' % q['change_pct'] if q.get('change_pct') is not None else ''}"
        for q in payload.get("oil", []) if q.get("price")
    )
    lines += [f"> 生成时间：{payload.get('generated_at', '')} ｜ 研判模式：{mode}", ""]
    if oil_txt:
        lines += [f"**原油参考**：{oil_txt}", ""]

    for g in payload.get("varieties", []):
        lines.append(f"## {g['name']} {g['code']}（情绪 {g['sentiment']:+.0f}｜{g['count']} 条）")
        for label, key in (("利多", "bullish"), ("利空", "bearish")):
            items = g.get(key, [])
            lines.append(f"### {label} Top {len(items)}")
            if not items:
                lines.append("- 暂无")
            for it in items:
                lines.append(
                    f"- **{it['title']}**（重要性 {it['importance']}｜{it['factor']}｜{it['source_name']}）"
                    f"\n  - {it['summary'] or '—'}"
                    + (f"\n  - 原文：{it['url']}" if it.get("url") else "")
                )
        lines.append("")
    lines += ["---", "> 本简报仅用于个人信息整理与研判辅助，不构成投资建议。", ""]
    return "\n".join(lines)


def upsert_digest(date_str: str) -> dict:
    payload = build_digest(date_str)
    markdown = render_markdown(payload)
    with SessionLocal() as db:
        row = db.execute(select(Digest).where(Digest.date == date_str)).scalars().first()
        if row:
            row.payload = payload
            row.markdown = markdown
        else:
            db.add(Digest(date=date_str, payload=payload, markdown=markdown))
        db.commit()
    return {"date": date_str, "payload": payload, "markdown": markdown}


def today_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")
