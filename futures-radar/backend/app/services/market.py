"""原油行情采集：Brent / WTI / INE SC（新浪） + FRED Brent 日线。"""
from __future__ import annotations

import asyncio
import csv
import io
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import desc, select

from ..config import settings
from ..db import SessionLocal
from ..models import FetchLog, MarketDaily, MarketQuote, Source
from .bus import bus
from .serialize import iso_z

SINA_URL = (
    "https://hq.sinajs.cn/list=hf_CL,hf_OIL,nf_SC0,"
    "hf_S,hf_SM,hf_BO,hf_CT,hf_SB,hf_C,hf_W,hf_NG,hf_HG,hf_DX"
)
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": settings.user_agent,
}
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"

BENCHMARKS = {
    "WTI": {"symbol": "hf_CL", "name": "WTI 美原油", "unit": "USD/bbl"},
    "Brent": {"symbol": "hf_OIL", "name": "Brent 布伦特", "unit": "USD/bbl"},
    "SC": {"symbol": "nf_SC0", "name": "INE 上海原油", "unit": "CNY/bbl"},
}

# 外盘参考：用于跨市场传导（白糖/棉花/油脂/能化等）
FOREIGN = {
    "SB": {"symbol": "hf_SB", "name": "ICE 原糖", "unit": "美分/磅"},
    "CT": {"symbol": "hf_CT", "name": "ICE 美棉", "unit": "美分/磅"},
    "S": {"symbol": "hf_S", "name": "CBOT 大豆", "unit": "美分/蒲"},
    "SM": {"symbol": "hf_SM", "name": "CBOT 豆粕", "unit": "美元/短吨"},
    "BO": {"symbol": "hf_BO", "name": "CBOT 豆油", "unit": "美分/磅"},
    "C": {"symbol": "hf_C", "name": "CBOT 玉米", "unit": "美分/蒲"},
    "W": {"symbol": "hf_W", "name": "CBOT 小麦", "unit": "美分/蒲"},
    "NG": {"symbol": "hf_NG", "name": "NYMEX 天然气", "unit": "USD/MMBtu"},
    "HG": {"symbol": "hf_HG", "name": "COMEX 铜", "unit": "美分/磅"},
    "DX": {"symbol": "hf_DX", "name": "美元指数", "unit": ""},
}


def _f(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_sina(raw_text: str) -> list[dict]:
    quotes: list[dict] = []
    for line in raw_text.splitlines():
        if "=" not in line:
            continue
        symbol = line.split("=", 1)[0].replace("var hq_str_", "").strip()
        payload = line.split('"')[1] if '"' in line else ""
        fields = payload.split(",")
        if not fields or not fields[0]:
            continue
        if symbol == "nf_SC0":
            price = _f(fields[8]) if len(fields) > 8 else 0.0
            prev_close = _f(fields[5]) if len(fields) > 5 else 0.0
            high = _f(fields[3]) if len(fields) > 3 else 0.0
            low = _f(fields[4]) if len(fields) > 4 else 0.0
            name = fields[16] if len(fields) > 17 else ""
            benchmark = "SC"
            meta = BENCHMARKS["SC"]
        elif symbol in {v["symbol"] for v in BENCHMARKS.values()}:
            price = _f(fields[0])
            prev_close = _f(fields[7]) if len(fields) > 8 else 0.0
            high = _f(fields[4]) if len(fields) > 5 else 0.0
            low = _f(fields[5]) if len(fields) > 6 else 0.0
            name = fields[13] if len(fields) > 14 else ""
            benchmark = "WTI" if symbol == "hf_CL" else "Brent"
            meta = BENCHMARKS[benchmark]
        else:
            code = next((k for k, v in FOREIGN.items() if v["symbol"] == symbol), None)
            if code is None:
                continue
            price = _f(fields[0])
            prev_close = _f(fields[7]) if len(fields) > 8 else 0.0
            high = _f(fields[4]) if len(fields) > 5 else 0.0
            low = _f(fields[5]) if len(fields) > 6 else 0.0
            name = fields[13] if len(fields) > 14 else ""
            benchmark = code
            meta = FOREIGN[code]
        if price <= 0 or prev_close <= 0:
            continue
        if benchmark not in BENCHMARKS and benchmark not in FOREIGN:
            continue
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
        quotes.append({
            "benchmark": benchmark,
            "name": meta["name"],
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "unit": meta["unit"],
            "source": "sina",
            "raw_name": name,
        })
    return quotes


async def collect_oil() -> dict:
    started = time.perf_counter()
    status, error, quotes = "ok", "", []
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout, headers=SINA_HEADERS) as client:
            resp = await client.get(SINA_URL)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="ignore")
        quotes = _parse_sina(text)
        if not quotes:
            raise RuntimeError("行情解析为空")
    except Exception as exc:  # noqa: BLE001
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        for q in quotes:
            db.add(MarketQuote(
                benchmark=q["benchmark"], name=q["name"], price=q["price"],
                prev_close=q["prev_close"], change_pct=q["change_pct"],
                high=q["high"], low=q["low"], quoted_at=now,
                source=q["source"], unit=q["unit"],
            ))
        src = db.execute(select(Source).where(Source.code == "sina_oil")).scalars().first()
        if src:
            src.last_status = status
            src.last_error = error
            src.last_run_at = now
        db.add(FetchLog(
            source_id=src.id if src else None, source_code="sina_oil", status=status, error=error,
            fetched_count=len(quotes), new_count=len(quotes),
            duration_ms=int((time.perf_counter() - started) * 1000),
        ))
        db.commit()

    if quotes:
        await bus.publish("oil_update", {"quotes": quotes, "quoted_at": iso_z(now)})
    return {"ok": status == "ok", "quotes": len(quotes), "error": error}


async def collect_fred_brent() -> dict:
    """FRED 布伦特日线，用于历史序列。"""
    status, error, rows = "ok", "", []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(FRED_URL)
            resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            value = row.get("DCOILBRENTEU", "").strip()
            if value and value != ".":
                try:
                    rows.append((row["observation_date"], float(value)))
                except ValueError:
                    continue
        rows = rows[-120:]
    except Exception as exc:  # noqa: BLE001
        status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]

    with SessionLocal() as db:
        for d, close in rows:
            existing = db.execute(
                select(MarketDaily).where(MarketDaily.benchmark == "Brent", MarketDaily.trade_date == d)
            ).scalars().first()
            if existing:
                existing.close = close
            else:
                db.add(MarketDaily(benchmark="Brent", trade_date=d, close=close))
        src = db.execute(select(Source).where(Source.code == "fred_brent")).scalars().first()
        if src:
            src.last_status = status
            src.last_error = error
            src.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(FetchLog(source_id=src.id if src else None, source_code="fred_brent",
                        status=status, error=error, fetched_count=len(rows), new_count=0))
        db.commit()
    return {"ok": status == "ok", "rows": len(rows), "error": error}


def _latest_since(db, benchmark: str, cutoff):
    return db.execute(
        select(MarketQuote).where(
            MarketQuote.benchmark == benchmark, MarketQuote.quoted_at >= cutoff
        ).order_by(desc(MarketQuote.quoted_at)).limit(1)
    ).scalars().first()


def foreign_latest(db, max_age_min: int = 30) -> dict[str, dict]:
    """外盘最新报价（近 30 分钟内有更新才算有效）。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=max_age_min)
    out: dict[str, dict] = {}
    for code, meta in FOREIGN.items():
        q = _latest_since(db, code, cutoff)
        if q:
            out[code] = {"price": q.price, "change_pct": q.change_pct, "name": meta["name"]}
    # 布伦特作为能化传导基准，用 OIL 别名（linkage 里能化权重都指向它）
    q = _latest_since(db, "Brent", cutoff)
    if q:
        out["OIL"] = {"price": q.price, "change_pct": q.change_pct, "name": "布伦特原油"}
    return out


def latest_quotes(db) -> list[dict]:
    out = []
    for code, meta in BENCHMARKS.items():
        q = db.execute(
            select(MarketQuote).where(MarketQuote.benchmark == code).order_by(desc(MarketQuote.quoted_at)).limit(1)
        ).scalars().first()
        if not q:
            out.append({"benchmark": code, "name": meta["name"], "unit": meta["unit"],
                        "price": None, "change_pct": None, "high": None, "low": None,
                        "quoted_at": None})
            continue
        # 迷你图只取最近 6 小时，避免跨日断崖让走势图失真
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=6)
        hist = db.execute(
            select(MarketQuote).where(
                MarketQuote.benchmark == code, MarketQuote.quoted_at >= cutoff
            )
            .order_by(desc(MarketQuote.quoted_at)).limit(40)
        ).scalars().all()
        if not hist:
            hist = db.execute(
                select(MarketQuote).where(MarketQuote.benchmark == code)
                .order_by(desc(MarketQuote.quoted_at)).limit(40)
            ).scalars().all()
        spark = [round(x.price, 2) for x in reversed(hist)]
        out.append({
            "benchmark": q.benchmark, "name": q.name, "unit": q.unit,
            "price": q.price, "prev_close": q.prev_close, "change_pct": q.change_pct,
            "high": q.high, "low": q.low, "quoted_at": iso_z(q.quoted_at),
            "spark": spark, "source": q.source,
        })
    # Oman 暂无免费实时源
    out.append({"benchmark": "Oman", "name": "Oman/Dubai 阿曼", "unit": "USD/bbl",
                "price": None, "change_pct": None, "high": None, "low": None,
                "quoted_at": None, "available": False,
                "note": "免费实时源暂缺，P1 接入"})
    return out


def brent_history(db, limit: int = 60) -> list[dict]:
    rows = db.execute(
        select(MarketDaily).where(MarketDaily.benchmark == "Brent")
        .order_by(desc(MarketDaily.trade_date)).limit(limit)
    ).scalars().all()
    return [{"date": r.trade_date, "close": r.close} for r in reversed(rows)]
