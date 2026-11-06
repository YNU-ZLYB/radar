from __future__ import annotations

import re

import httpx

from .base import BaseCollector, RawItem, to_cst

FLASH_URL = "https://flash-api.jin10.com/get_flash_list?max_time=&channel=-8200"


class Jin10FlashCollector(BaseCollector):
    code = "jin10_flash"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        headers = {
            "x-app-id": "bVBF4FyRTn5NJF5n",
            "x-version": "1.0.0",
            "Referer": "https://www.jin10.com/",
            "Accept": "application/json",
        }
        resp = await client.get(FLASH_URL, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        items: list[RawItem] = []
        for row in payload.get("data") or []:
            data = row.get("data") or {}
            content = (data.get("content") or "").strip()
            if not content:
                continue
            title = (data.get("title") or "").strip()
            if not title:
                m = re.match(r"^【(.{2,40}?)】", content)
                if m:
                    title = m.group(1)
                    content = content[m.end():].strip() or content
            if not title:
                title = content[:60]
            items.append(RawItem(
                title=title,
                content=content,
                url=f"https://flash.jin10.com/detail/{row.get('id', '')}",
                published_at=to_cst(row.get("time")),
                external_id=str(row.get("id", "")),
                important=bool(row.get("important")),
            ))
        return items
