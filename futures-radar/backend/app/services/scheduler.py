from __future__ import annotations

import asyncio
import traceback

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import settings
from ..collectors.base import list_collectors
from ..collectors.sina_quotes import collect_quotes
from .daily_summary import refresh_movers, refresh_quote_summaries, summarize_all_active
from .digest import today_str, upsert_digest
from .market import collect_fred_brent, collect_oil

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def run_collect(code: str) -> dict:
    cls = list_collectors().get(code)
    if not cls:
        return {"ok": False, "error": f"未实现的采集器：{code}"}
    return await cls().collect()


async def run_task(task: str) -> dict:
    if task in list_collectors():
        return await run_collect(task)
    if task == "quotes":
        return await collect_quotes()
    if task == "oil":
        return await collect_oil()
    if task == "fred":
        return await collect_fred_brent()
    if task == "digest":
        result = upsert_digest(today_str())
        return {"ok": True, "date": result["date"]}
    if task == "daily_summary":
        codes = await summarize_all_active(days=7)
        return {"ok": True, "varieties": codes, "count": len(codes)}
    return {"ok": False, "error": f"未知任务：{task}"}


async def _safe(coro, label: str) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001
        print(f"[scheduler] {label} 执行失败")
        traceback.print_exc()


async def job_oil() -> None:
    await _safe(collect_oil(), "oil")


async def job_jin10() -> None:
    await _safe(run_collect("jin10_flash"), "jin10")


async def job_rss() -> None:
    await _safe(run_collect("sina_rss"), "rss")


async def job_czce() -> None:
    await _safe(run_collect("czce_announce"), "czce")


async def job_fred() -> None:
    await _safe(collect_fred_brent(), "fred")


async def job_digest() -> None:
    await _safe(_digest_job(), "digest")


async def job_daily_summary() -> None:
    """每天对所有活跃品种跑一次 DeepSeek 汇总研判。"""
    await _safe(summarize_all_active(days=7), "daily_summary")


async def job_quotes() -> None:
    await _safe(collect_quotes(), "quotes")


async def job_quote_summary() -> None:
    """高频刷新无资讯品种的盘面研判（不调 LLM）。"""
    await _safe(refresh_quote_summaries(days=7), "quote_summary")


async def job_summary_movers() -> None:
    """盘中大幅波动品种的研判刷新（含地缘/原油冲击）。"""
    await _safe(refresh_movers(), "summary_movers")


async def job_eastmoney() -> None:
    await _safe(run_collect("eastmoney_flash"), "eastmoney")


async def job_sina7x24() -> None:
    await _safe(run_collect("sina_7x24"), "sina_7x24")


def start_scheduler() -> AsyncIOScheduler:
    if not settings.enable_scheduler:
        return scheduler

    scheduler.add_job(job_quotes, "interval", seconds=settings.interval_quotes,
                      id="quotes", max_instances=1, coalesce=True)
    scheduler.add_job(job_quote_summary, "interval", seconds=settings.interval_quote_summary,
                      id="quote_summary", max_instances=1, coalesce=True)
    scheduler.add_job(job_summary_movers, "interval", seconds=1800,
                      id="summary_movers", max_instances=1, coalesce=True)
    scheduler.add_job(job_eastmoney, "interval", seconds=settings.interval_eastmoney,
                      id="eastmoney", max_instances=1, coalesce=True)
    scheduler.add_job(job_sina7x24, "interval", seconds=settings.interval_sina7x24,
                      id="sina_7x24", max_instances=1, coalesce=True)
    scheduler.add_job(job_oil, "interval", seconds=settings.interval_oil,
                      id="oil", max_instances=1, coalesce=True)
    scheduler.add_job(job_jin10, "interval", seconds=settings.interval_jin10,
                      id="jin10", max_instances=1, coalesce=True)
    scheduler.add_job(job_rss, "interval", seconds=settings.interval_rss,
                      id="rss", max_instances=1, coalesce=True)
    scheduler.add_job(job_czce, "interval", seconds=settings.interval_czce,
                      id="czce", max_instances=1, coalesce=True)
    scheduler.add_job(job_fred, "interval", seconds=settings.interval_fred,
                      id="fred", max_instances=1, coalesce=True)
    scheduler.add_job(job_digest, "interval", seconds=settings.interval_digest,
                      id="digest", max_instances=1, coalesce=True)
    # 每天 17:00 CST，品种资讯基本齐备，适合做日度汇总
    scheduler.add_job(job_daily_summary, "cron", hour=17, minute=0,
                      id="daily_summary", max_instances=1, coalesce=True)

    if not scheduler.running:
        scheduler.start()
    return scheduler


async def _digest_job() -> None:
    await asyncio.to_thread(upsert_digest, today_str())


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
