"""LLM 研判：DeepSeek Chat Completions，严格 JSON 输出 + evidence 校验。

未配置 DEEPSEEK_API_KEY 时不会调用本模块，由规则引擎兜底。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import httpx

from ..config import settings

SYSTEM_PROMPT = """你是一名专注中国期货市场（郑商所品种）的资深研究员。
你的任务是判断一条资讯对指定期货品种的价格影响，并输出严格 JSON。

要求：
1. 只依据原文，不得编造数据；evidence 必须逐字摘自原文（可截取片段，不得改写）。
2. 判断方向 bullish(利多) / bearish(利空) / neutral(中性)，strength 1-5，confidence 0-1。
3. factor 只能取：供给、需求、库存、成本、政策、天气、宏观、资金/结构。
4. horizon 只能取：intraday、short、medium、long。
5. 如果信息与该品种无关，不要输出该品种。
6. 输出必须是合法 JSON，不要 Markdown 代码块，不要额外说明。

JSON 结构：
{
  "results": [
    {
      "code": "SR",
      "direction": "bullish",
      "strength": 3,
      "confidence": 0.8,
      "factor": "供给",
      "horizon": "short",
      "event_type": "天气",
      "summary": "一句话结论（40字内）",
      "evidence": "原文逐字片段",
      "reasoning": "影响逻辑（80字内）",
      "region": "广西"
    }
  ]
}"""


@dataclass
class LLMResult:
    results: list[dict]
    model: str
    latency_ms: int


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def evidence_valid(evidence: str, source_text: str) -> bool:
    ev = _normalize(evidence)
    if not ev:
        return False
    src = _normalize(source_text)
    if ev in src:
        return True
    # 允许模型截取时省略首尾少量字符
    if len(ev) > 12:
        core = ev[2:-2]
        return core in src
    return False


def _build_user_prompt(title: str, content: str, candidates: list[dict]) -> str:
    variety_desc = "\n".join(
        f"- {c['code']} {c['name']}（{'、'.join((c.get('aliases') or [])[:4])}；重点因子："
        f"{'、'.join(c.get('factor_names') or [])}）"
        for c in candidates
    )
    return f"""【资讯标题】{title or '（无标题）'}

【资讯正文】
{content[:3000]}

【候选品种】
{variety_desc}

请逐个判断上述品种是否受该资讯影响。若均不相关，返回 {{"results": []}}。"""


async def analyze_with_llm(title: str, content: str, candidates: list[dict]) -> LLMResult:
    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    started = time.perf_counter()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(title, content, candidates)},
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    parsed = json.loads(raw)
    results = []
    for item in parsed.get("results", []):
        code = str(item.get("code", "")).upper()
        if code not in {c["code"] for c in candidates}:
            continue
        ev = str(item.get("evidence", ""))
        if not evidence_valid(ev, f"{title}\n{content}"):
            ev = ""
            item["confidence"] = min(float(item.get("confidence", 0.5)), 0.4)
            item["evidence_invalid"] = True
        direction = item.get("direction")
        if direction not in ("bullish", "bearish", "neutral"):
            direction = "neutral"
        try:
            strength = max(1, min(5, int(item.get("strength", 1))))
        except (TypeError, ValueError):
            strength = 1
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        results.append({
            "code": code,
            "direction": direction,
            "strength": strength,
            "confidence": round(confidence, 2),
            "factor": item.get("factor") or "供需",
            "horizon": item.get("horizon") if item.get("horizon") in
            ("intraday", "short", "medium", "long") else "short",
            "event_type": str(item.get("event_type") or "其他")[:32],
            "summary": str(item.get("summary") or "")[:200],
            "evidence": ev[:300],
            "reasoning": str(item.get("reasoning") or "")[:300],
            "region": str(item.get("region") or "")[:64],
        })
    latency = int((time.perf_counter() - started) * 1000)
    return LLMResult(results=results, model=data.get("model", settings.deepseek_model), latency_ms=latency)
