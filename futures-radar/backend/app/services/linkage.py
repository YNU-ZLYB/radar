"""跨市场传导：用外盘价格波动推断国内品种的同向压力。

例：ICE 美棉大涨 → 郑棉偏多；CBOT 豆油大涨 → 菜油偏多；布伦特走强 → 能化偏多。
权重是经验值，可按需调整；最终由 AI 在日度研判中综合资讯与外盘。
"""
from __future__ import annotations

from ..db import SessionLocal
from ..models import MarketQuote
from .market import FOREIGN, foreign_latest

# 品种 -> [(外盘代码, 权重, 说明)]，权重之和不超过 1
LINKAGE: dict[str, list[tuple[str, float, str]]] = {
    # ICE 原糖实时源缺失时，布伦特作为巴西乙醇联动的代理
    "SR": [("SB", 0.65, "ICE 原糖"), ("OIL", 0.3, "布伦特(乙醇联动)")],
    "CF": [("CT", 0.65, "ICE 美棉")],
    "CY": [("CT", 0.5, "ICE 美棉")],
    "MA": [("OIL", 0.45, "布伦特"), ("NG", 0.3, "NYMEX 天然气")],
    "TA": [("OIL", 0.55, "布伦特"), ("NG", 0.1, "NYMEX 天然气")],
    "PX": [("OIL", 0.65, "布伦特")],
    "PR": [("OIL", 0.55, "布伦特")],
    "PF": [("OIL", 0.5, "布伦特")],
    "PL": [("OIL", 0.5, "布伦特"), ("NG", 0.2, "NYMEX 天然气")],
    "SH": [("OIL", 0.25, "布伦特"), ("NG", 0.25, "NYMEX 天然气")],
    "UR": [("NG", 0.45, "NYMEX 天然气"), ("C", 0.15, "CBOT 玉米")],
    "SA": [("NG", 0.3, "NYMEX 天然气"), ("OIL", 0.15, "布伦特")],
    "FG": [("NG", 0.3, "NYMEX 天然气"), ("OIL", 0.15, "布伦特")],
    "OI": [("BO", 0.65, "CBOT 豆油"), ("S", 0.2, "CBOT 大豆")],
    "RM": [("SM", 0.65, "CBOT 豆粕"), ("S", 0.2, "CBOT 大豆")],
    "RS": [("S", 0.35, "CBOT 大豆"), ("BO", 0.25, "CBOT 豆油")],
    "WH": [("W", 0.6, "CBOT 小麦")],
    "SF": [("HG", 0.15, "COMEX 铜(工业情绪)")],
    "SM": [("HG", 0.15, "COMEX 铜(工业情绪)")],
}


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def compute_linkage(code: str, foreign: dict[str, dict]) -> dict | None:
    """返回某品种的外盘传导结论；无映射或无外盘数据时返回 None。"""
    rules = LINKAGE.get(code)
    if not rules:
        return None
    contributors = []
    impact = 0.0
    for ext_code, weight, label in rules:
        q = foreign.get(ext_code)
        if not q:
            continue
        pct = q.get("change_pct") or 0.0
        contrib = pct * weight
        impact += contrib
        contributors.append({
            "code": ext_code,
            "name": label,
            "price": q.get("price"),
            "change_pct": pct,
            "weight": weight,
            "impact": round(contrib, 2),
        })
    if not contributors:
        return None
    signal = _clamp(impact * 22)
    direction = "bullish" if signal >= 12 else "bearish" if signal <= -12 else "neutral"
    label = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}[direction]
    head = contributors[0]
    summary = f"{head['name']} {head['change_pct']:+.2f}% → 传导{label}"
    return {
        "signal": round(signal, 1),
        "direction": direction,
        "summary": summary,
        "contributors": contributors,
        "available": True,
    }


def market_linkage_map(db=None) -> dict[str, dict]:
    """一次性算出所有品种的外盘传导，供 dashboard 批量使用。"""
    if db is None:
        with SessionLocal() as session:
            foreign = foreign_latest(session)
    else:
        foreign = foreign_latest(db)
    if not foreign:
        return {}
    return {code: compute_linkage(code, foreign) for code in LINKAGE}


def foreign_names() -> dict[str, str]:
    return {k: v["name"] for k, v in FOREIGN.items()}
