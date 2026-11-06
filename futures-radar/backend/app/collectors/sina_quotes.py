"""郑商所品种主力连续合约行情（新浪财经 nf_ 接口）。

资讯对红枣、花生、硅铁这类品种天然稀缺，行情则是全覆盖的。
用它给每个品种算出方向与强度，保证 22 个品种都有研判。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Variety, VarietyQuote

QUOTE_URL = "https://hq.sinajs.cn/list="

# 新浪字段位：2开盘 3最高 4最低 5昨收 8最新 10昨结算 13持仓 14成交
_ROWS = re.compile(r'hq_str_nf_(\w+?)0="([^"]*)"')


def _f(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def fetch_quotes(client: httpx.AsyncClient, codes: list[str]) -> list[dict]:
    symbols = ",".join(f"nf_{c}0" for c in codes)
    resp = await client.get(
        QUOTE_URL + symbols,
        headers={"Referer": "https://finance.sina.com.cn"},
    )
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="ignore")
    out: list[dict] = []
    for code, payload in _ROWS.findall(text):
        f = payload.split(",")
        if len(f) < 15:
            continue
        price = _f(f[8])
        prev = _f(f[10]) or _f(f[5])
        if price <= 0 or prev <= 0:
            continue
        out.append({
            "code": code,
            "name": f[16] if len(f) > 16 else f[0],
            "price": price,
            "prev_settle": prev,
            "open": _f(f[2]),
            "high": _f(f[3]),
            "low": _f(f[4]),
            "change_pct": round((price - prev) / prev * 100, 2),
            "open_interest": _f(f[13]),
            "volume": _f(f[14]),
        })
    return out


def _direction_from_pct(pct: float) -> tuple[str, int]:
    """把涨跌幅映射为方向与强度(1-5)。"""
    a = abs(pct)
    if a < 0.25:
        return "neutral", 1
    strength = 2 if a < 0.8 else 3 if a < 1.6 else 4 if a < 3 else 5
    return ("bullish" if pct > 0 else "bearish"), strength


async def collect_quotes() -> dict:
    with SessionLocal() as db:
        codes = [c for (c,) in db.execute(
            select(Variety.code).where(Variety.is_active.is_(True))
        ).all()]
    if not codes:
        return {"ok": False, "error": "no active varieties"}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        quotes = await fetch_quotes(client, codes)
    if not quotes:
        return {"ok": False, "error": "empty quotes"}

    with SessionLocal() as db:
        for q in quotes:
            row = db.execute(
                select(VarietyQuote).where(VarietyQuote.variety_code == q["code"])
            ).scalars().first()
            direction, strength = _direction_from_pct(q["change_pct"])
            if row is None:
                row = VarietyQuote(variety_code=q["code"])
                db.add(row)
            row.name = q["name"]
            row.price = q["price"]
            row.prev_settle = q["prev_settle"]
            row.open = q["open"]
            row.high = q["high"]
            row.low = q["low"]
            row.change_pct = q["change_pct"]
            row.direction = direction
            row.strength = strength
            row.open_interest = q["open_interest"]
            row.volume = q["volume"]
            row.quoted_at = now
            row.source = "sina"
        db.commit()
    return {"ok": True, "count": len(quotes), "quoted_at": now.isoformat()}
