"""评分模型：S = sign × strength × confidence × source_weight × freshness × novelty。"""
from __future__ import annotations

import math
from datetime import datetime, timezone

HALF_LIFE_HOURS = {
    "intraday": 12,
    "short": 72,
    "medium": 720,   # 30 天
    "long": 4320,    # 180 天
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def freshness(published_at: datetime, horizon: str = "short", now: datetime | None = None) -> float:
    now = now or utc_now()
    delta_hours = max(0.0, (now - published_at).total_seconds() / 3600)
    half_life = HALF_LIFE_HOURS.get(horizon, 72)
    return round(0.5 ** (delta_hours / half_life), 4)


def sign(direction: str) -> int:
    return {"bullish": 1, "bearish": -1}.get(direction, 0)


def compute_score(direction: str, strength: int, confidence: float, source_weight: float,
                  published_at: datetime, horizon: str = "short", novelty: float = 1.0) -> float:
    raw = (
        sign(direction)
        * max(1, min(5, int(strength)))
        * max(0.0, min(1.0, confidence))
        * max(0.0, min(1.0, source_weight))
        * freshness(published_at, horizon)
        * max(0.0, min(1.0, novelty))
    )
    return round(raw, 3)


def sentiment(entries: list[float] | list[object]) -> float:
    """品种情绪指数 [-100, 100]。

    两种用法：
    - sentiment([score_float, ...])：简单均值（旧接口兼容）
    - sentiment([Score, ...])：按 importance 加权（推荐）
    """
    if not entries:
        return 0.0
    first = entries[0]
    if isinstance(first, (int, float)):
        total_abs = sum(abs(s) for s in entries)
        return round(sum(entries) / total_abs * 100, 1) if total_abs else 0.0
    # Score 对象：importance 加权
    total_imp = sum(getattr(s, "importance", abs(getattr(s, "score", 0.0))) for s in entries)
    if total_imp == 0:
        return 0.0
    weighted = sum(getattr(s, "score", 0.0) * getattr(s, "importance", abs(getattr(s, "score", 0.0))) for s in entries)
    val = weighted / total_imp * 100
    return round(max(-100.0, min(100.0, val)), 1)


def bigram_similarity(a: str, b: str) -> float:
    """字符二元组 Jaccard，用于 P0 近似新颖度/标题去重。"""
    def grams(s: str) -> set[str]:
        s = "".join(s.split())
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)
