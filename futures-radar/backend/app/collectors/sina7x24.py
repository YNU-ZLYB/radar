from __future__ import annotations

import re

import httpx

from .base import BaseCollector, RawItem, is_futures_related, to_cst

FEED_URL = ("https://zhibo.sina.com.cn/api/zhibo/feed"
            "?page=1&page_size=40&zhibo_id=152&tag_id=0&dire=f&dpc=1")


class Sina7x24Collector(BaseCollector):
    """新浪财经 7×24 直播：宏观与商品现货资讯，作为金十/东财的补充。"""

    code = "sina_7x24"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        headers = {"Referer": "https://finance.sina.com.cn/"}
        resp = await client.get(FEED_URL, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        rows = (((payload.get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
        items: list[RawItem] = []
        for row in rows:
            rich = (row.get("rich_text") or "").strip()
            if not rich:
                continue
            title, content = "", rich
            m = re.match(r"^【(.{2,40}?)】", rich)
            if m:
                title = m.group(1)
                content = rich[m.end():].strip() or rich
            if not title:
                title = rich[:60]
            if not is_futures_related(rich):
                continue
            items.append(RawItem(
                title=title,
                content=content,
                url=str(row.get("docurl") or ""),
                published_at=to_cst(str(row.get("create_time") or "")),
                external_id=str(row.get("id") or ""),
            ))
        return items
