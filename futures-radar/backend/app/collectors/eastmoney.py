from __future__ import annotations

import json
import re

import httpx

from .base import BaseCollector, RawItem, is_futures_related, to_cst

FLASH_URL = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html"


class EastmoneyFlashCollector(BaseCollector):
    """东方财富 7×24 快讯：含商品期货夜盘、现货、产业资讯，覆盖面比金十更偏国内商品。"""

    code = "eastmoney_flash"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        headers = {
            "Referer": "https://finance.eastmoney.com/",
            "Accept": "*/*",
        }
        resp = await client.get(FLASH_URL, headers=headers)
        resp.raise_for_status()
        text = resp.text
        start, end = text.find("{"), text.rfind("}")
        payload = json.loads(text[start:end + 1])
        items: list[RawItem] = []
        for row in payload.get("LivesList") or []:
            title = (row.get("title") or "").strip()
            digest = (row.get("digest") or "").strip()
            if not title and not digest:
                continue
            if not title:
                title = digest[:60]
                digest = ""
            title = re.sub(r"【[^】]*】", "", title).strip(" ：:") or title
            if not is_futures_related(f"{title}{digest}"):
                continue
            items.append(RawItem(
                title=title,
                content=digest,
                url=str(row.get("url_w") or row.get("url_unique") or ""),
                published_at=to_cst(str(row.get("showtime") or "")),
                external_id=str(row.get("id") or ""),
            ))
        return items
