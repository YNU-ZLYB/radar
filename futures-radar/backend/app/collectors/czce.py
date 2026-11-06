from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import httpx

from .base import BaseCollector, RawItem, to_cst

CZCE_URL = "https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/H770319index_1.htm"
LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{4,120})</a>', re.I)


class CzceAnnouncementCollector(BaseCollector):
    """郑商所公告。官网有瑞数反爬，412 时记录失败日志，不影响其它源。"""
    code = "czce_announce"

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        resp = await client.get(CZCE_URL)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}（官网可能有反爬）")
        raw = resp.content.decode("utf-8", errors="ignore")
        items: list[RawItem] = []
        for href, text in LINK_RE.findall(raw):
            title = html.unescape(text).strip()
            if not re.search(r"(公告|通知|仓单|交割|持仓|风险提示|调整|细则|办法)", title):
                continue
            items.append(RawItem(
                title=title,
                content=title,
                url=urljoin(CZCE_URL, href),
                published_at=to_cst(None),
                external_id=href,
            ))
        return items[:30]
