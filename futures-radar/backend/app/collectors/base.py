from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import FetchLog, Source
from ..services.pipeline import ingest_items

CST = ZoneInfo("Asia/Shanghai")


@dataclass
class RawItem:
    title: str
    content: str
    url: str
    published_at: datetime
    external_id: str = ""
    important: bool = False


def to_cst(text: str | None) -> datetime:
    """把常见的源站时间字符串解析为北京时间，最终统一存 UTC naive。"""
    if not text:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    text = text.strip()
    fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]
    parsed = None
    for fmt in fmts:
        try:
            parsed = datetime.strptime(text[:19], fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    local = parsed.replace(tzinfo=CST)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


class BaseCollector(ABC):
    code: str = ""
    timeout: int = settings.request_timeout

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        ...

    async def collect(self) -> dict:
        started = time.perf_counter()
        with SessionLocal() as db:
            source = db.execute(select(Source).where(Source.code == self.code)).scalars().first()
            if not source:
                return {"ok": False, "error": f"source {self.code} not found"}
            if not source.enabled:
                return {"ok": False, "error": "disabled", "skipped": True}
            source.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            source_id = source.id

        status, error, items, new_count = "ok", "", [], 0
        new_ids: list[int] = []
        try:
            headers = {"User-Agent": settings.user_agent}
            async with httpx.AsyncClient(timeout=self.timeout, headers=headers, follow_redirects=True) as client:
                items = await self.fetch(client)
            result = await ingest_items(items, source, new_ids)
            new_count = result.created
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"[:500]
            print(f"[collector] {self.code} 采集失败：{error}")

        duration = int((time.perf_counter() - started) * 1000)
        with SessionLocal() as db:
            src = db.get(Source, source_id)
            if src:
                src.last_status = status
                src.last_error = error
                src.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(FetchLog(
                source_id=source_id, source_code=self.code, status=status, error=error,
                fetched_count=len(items), new_count=new_count, duration_ms=duration,
            ))
            db.commit()
        return {"ok": status == "ok", "fetched": len(items), "new": new_count,
                "error": error, "duration_ms": duration}


# 通用快讯源（东财、新浪 7×24）里大量是科技股新闻，入库前先做一次期货相关性粗筛
FUTURES_HINTS = (
    "期货", "主力", "合约", "仓单", "现货", "交割", "郑商所", "交易所", "涨跌",
    "涨停", "跌停", "库存", "开工", "产量", "检修", "停产", "限仓", "升贴水",
    "白糖", "棉花", "棉纱", "甲醇", "纯碱", "玻璃", "苹果", "红枣", "花生",
    "菜油", "菜粕", "菜籽", "PTA", "PX", "瓶片", "短纤", "尿素", "烧碱",
    "硅铁", "锰硅", "动力煤", "小麦", "原木", "丙烯",
    "原油", "OPEC", "油价", "天然气", "煤炭", "有色", "钢材", "铁矿", "大豆",
)


def is_futures_related(text: str) -> bool:
    return any(h in text for h in FUTURES_HINTS)


def list_collectors() -> dict[str, type[BaseCollector]]:
    from .czce import CzceAnnouncementCollector
    from .eastmoney import EastmoneyFlashCollector
    from .jin10 import Jin10FlashCollector
    from .sina7x24 import Sina7x24Collector
    from .sina_rss import SinaRssCollector

    return {
        Jin10FlashCollector.code: Jin10FlashCollector,
        EastmoneyFlashCollector.code: EastmoneyFlashCollector,
        Sina7x24Collector.code: Sina7x24Collector,
        SinaRssCollector.code: SinaRssCollector,
        CzceAnnouncementCollector.code: CzceAnnouncementCollector,
    }
