"""统一的序列化，供 API 与 SSE 复用。"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import models

VARIETY_NAMES = {
    "SR": "白糖", "CF": "棉花", "CY": "棉纱", "AP": "苹果", "CJ": "红枣", "PK": "花生",
    "OI": "菜籽油", "RM": "菜籽粕", "RS": "油菜籽", "MA": "甲醇", "TA": "PTA",
    "FG": "玻璃", "SA": "纯碱", "UR": "尿素", "PF": "短纤", "PR": "瓶片", "SH": "烧碱",
    "PX": "对二甲苯", "SF": "硅铁", "SM": "锰硅", "ZC": "动力煤", "WH": "小麦",
    "JR": "粳稻", "LR": "晚籼稻", "RI": "早籼稻", "PM": "普麦",
}


def iso_z(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def score_dict(s: models.Score) -> dict:
    return {
        "id": s.id,
        "variety_code": s.variety_code,
        "direction": s.direction,
        "score": s.score,
        "importance": s.importance,
        "confidence": s.confidence,
        "factor": s.factor,
        "is_divergent": s.is_divergent,
    }


def analysis_dict(a: models.Analysis, with_scores: bool = True) -> dict:
    data = {
        "id": a.id,
        "model": a.model,
        "status": a.status,
        "varieties": a.varieties,
        "direction": a.direction,
        "strength": a.strength,
        "confidence": a.confidence,
        "horizon": a.horizon,
        "factor": a.factor,
        "event_type": a.event_type,
        "summary": a.summary,
        "evidence": a.evidence,
        "reasoning": a.reasoning,
        "region": a.region,
        "latency_ms": a.latency_ms,
        "updated_at": iso_z(a.updated_at),
    }
    if with_scores:
        data["scores"] = [score_dict(s) for s in a.scores]
    return data


def doc_dict(doc: models.RawDoc, analysis: models.Analysis | None = None) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content,
        "url": doc.url,
        "source_name": doc.source_name,
        "source_weight": doc.source_weight,
        "published_at": iso_z(doc.published_at),
        "first_seen_at": iso_z(doc.first_seen_at),
        "matched_varieties": doc.matched_varieties,
        "status": doc.status,
        "is_manual": doc.is_manual,
        "analysis": analysis_dict(analysis) if analysis else None,
    }


def article_dict(doc: models.RawDoc) -> dict:
    analysis = doc.analyses[0] if doc.analyses else None
    data = doc_dict(doc, analysis)
    if analysis:
        scores = list(analysis.scores)
        data["scores"] = [score_dict(s) for s in scores]
        primary = max(scores, key=lambda s: s.importance) if scores else None
        code = primary.variety_code if primary else (doc.matched_varieties[0] if doc.matched_varieties else "")
        data["primary_variety"] = {"code": code, "name": VARIETY_NAMES.get(code, code)} if code else None
        data["direction"] = primary.direction if primary else analysis.direction
        data["importance"] = max((s.importance for s in scores), default=0.0)
        # 顶层便捷字段，供前端列表/卡片直接读取
        data["model"] = analysis.model
        data["strength"] = analysis.strength
        data["confidence"] = analysis.confidence
        data["factor"] = analysis.factor
        data["event_type"] = analysis.event_type
        data["summary"] = analysis.summary
        data["evidence"] = analysis.evidence
        data["reasoning"] = analysis.reasoning
        data["horizon"] = analysis.horizon
        data["latency_ms"] = analysis.latency_ms
    else:
        data["scores"] = []
        data["primary_variety"] = None
        data["importance"] = 0.0
        data["model"] = None
        data["strength"] = None
        data["confidence"] = None
        data["factor"] = None
        data["event_type"] = None
        data["summary"] = None
        data["evidence"] = None
        data["reasoning"] = None
        data["horizon"] = None
        data["latency_ms"] = None
    return data
