from __future__ import annotations

import html
import re
import time as time_lib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from .base import BaseCollector, RawItem

RSS_URL = "https://rss.sina.com.cn/roll/finance/hot_roll.xml"


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


class SinaRssCollector(BaseCollector):
    code = "sina_rss"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        resp = await client.get(RSS_URL)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        items: list[RawItem] = []
        for entry in feed.entries[:40]:
            title = _strip_html(entry.get("title", ""))
            summary = _strip_html(entry.get("summary") or entry.get("description", ""))
            if not title:
                continue
            published = datetime.now(timezone.utc).replace(tzinfo=None)
            for key in ("published", "updated"):
                raw = entry.get(key)
                if raw:
                    try:
                        published = parsedate_to_datetime(raw).astimezone(timezone.utc).replace(tzinfo=None)
                        break
                    except Exception:
                        pass
            if not any(k in (title + summary) for k in ("期货", "糖", "棉", "甲醇", "纯碱", "玻璃", "原油", "商品")):
                # 新浪泛财经流噪声大，先过滤明显无关内容
                continue
            items.append(RawItem(
                title=title,
                content=summary or title,
                url=entry.get("link", ""),
                published_at=published,
                external_id=entry.get("id", entry.get("link", "")),
            ))
        return items
