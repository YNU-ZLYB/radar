"""规则引擎：品种/因子识别、方向粗判、事件类型。用于快通道与无 LLM 时的兜底研判。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BULLISH = [
    "减产", "停产", "停车", "检修", "限产", "限气", "去库", "库存下降", "库存减少", "库存去化",
    "供应紧张", "供应偏紧", "短缺", "紧缺", "需求回暖", "需求增加", "需求好转", "订单增加",
    "提价", "涨价", "上调", "上涨", "走高", "反弹", "收储", "补贴", "出口增加", "进口减少",
    "干旱", "霜冻", "暴雨", "台风", "高温", "寒潮", "封航", "事故", "火灾", "爆炸", "起火", "罢工",
    "降息", "刺激", "利好", "超预期", "旺季",
    # 地缘政治：供给中断型事件，对能化/原油链条通常是强利多
    "霍尔木兹", "地缘冲突", "地缘紧张", "中东局势", "红海袭击", "俄乌冲突", "制裁", "禁运", "封锁", "断供",
]

BEARISH = [
    "增产", "复产", "扩产", "恢复生产", "累库", "库存增加", "库存上升", "库存累积", "供应宽松",
    "供应增加", "供应过剩", "过剩", "需求疲软", "需求下降", "需求走弱", "订单减少", "需求不佳",
    "降价", "下调", "下跌", "走低", "回落", "抛储", "出口减少", "进口增加", "取消订单",
    "淡季", "利空", "不及预期", "检修结束", "装置重启", "投产", "新产能",
    # 地缘缓和：风险溢价回吐
    "停火", "和谈", "局势缓和", "解除制裁", "冲突降级",
]

EVENT_RULES = [
    ("装置检修", ["检修", "停车", "停产"]),
    ("复产", ["复产", "重启", "恢复生产", "检修结束"]),
    ("减产", ["减产", "限产", "限气"]),
    ("增产", ["增产", "扩产", "投产", "新产能"]),
    ("库存", ["库存", "仓单", "去库", "累库"]),
    ("地缘", ["地缘", "中东", "霍尔木兹", "伊朗", "红海", "俄乌", "制裁", "禁运", "封锁", "OPEC", "停火"]),
    ("政策", ["政策", "关税", "配额", "收储", "抛储", "补贴", "环保", "发改委", "限价"]),
    ("天气", ["天气", "干旱", "霜冻", "暴雨", "台风", "高温", "寒潮", "降雨"]),
    ("进出口", ["进口", "出口", "到港", "离港", "封航"]),
    ("需求", ["需求", "消费", "订单", "产销", "采购"]),
    ("成本", ["成本", "原油", "煤炭", "天然气", "电力", "加工费", "石脑油"]),
    ("宏观", ["美联储", "利率", "汇率", "通胀", "GDP", "PMI", "降息", "加息", "美元"]),
    ("资金", ["持仓", "基差", "资金", "多头", "空头", "价差"]),
]

# 因子关键词（通用，品种专属关键词在数据库 variety_factors.keywords 中）
FACTOR_KEYWORDS = {
    "供给": ["产量", "减产", "增产", "检修", "停产", "复产", "开工", "装置", "扩产", "限产", "供应", "产能", "进口"],
    "需求": ["需求", "消费", "订单", "产销", "采购", "下游", "终端", "出口", "开工率"],
    "库存": ["库存", "仓单", "去库", "累库", "港口库存", "厂库", "社会库存"],
    "成本": ["成本", "原油", "煤炭", "煤价", "天然气", "电力", "加工费", "石脑油", "PX"],
    "政策": ["政策", "关税", "配额", "收储", "抛储", "补贴", "环保", "发改委", "证监会", "限价",
             "制裁", "禁运", "封锁", "OPEC"],
    "天气": ["天气", "干旱", "霜冻", "暴雨", "台风", "高温", "寒潮", "降雨", "气候"],
    "宏观": ["美联储", "利率", "汇率", "通胀", "GDP", "PMI", "降息", "加息", "美元", "宏观",
             "地缘", "中东", "霍尔木兹", "伊朗", "红海", "俄乌", "停火", "冲突"],
    "资金/结构": ["持仓", "基差", "资金", "多头", "空头", "价差", "跨期", "仓单"],
}


def _count_hits(text: str, words: list[str]) -> int:
    return sum(text.count(w) for w in words)


def detect_varieties(text: str, varieties: list[dict]) -> list[str]:
    """按品种主名/别名/关键词识别品种。

    规则：
    - 命中品种主名或别名（强词）即视为相关，1 个即可；
    - 只命中泛关键词时，需要至少 2 个不同关键词，避免「伊朗」「配额」这类词造成误匹配。
    """
    hits: list[str] = []
    for v in varieties:
        core = [w for w in [v.get("name", "")] + list(v.get("aliases") or []) if w]
        if any(w in text for w in core):
            hits.append(v["code"])
            continue
        keywords = [w for w in (v.get("keywords") or []) if w]
        kw_hits = {k for k in keywords if k in text}
        if len(kw_hits) >= 2:
            hits.append(v["code"])
    return hits


def detect_factor(text: str, custom_keywords: dict[str, list[str]] | None = None) -> str:
    best, best_score = "供需", 0
    for name, words in FACTOR_KEYWORDS.items():
        score = _count_hits(text, words)
        if custom_keywords:
            score += _count_hits(text, custom_keywords.get(name, []))
        if score > best_score:
            best, best_score = name, score
    return best


def detect_event_type(text: str) -> str:
    for name, words in EVENT_RULES:
        if any(w in text for w in words):
            return name
    return "其他"


def detect_direction(text: str) -> tuple[str, int]:
    bull = _count_hits(text, BULLISH)
    bear = _count_hits(text, BEARISH)
    if bull == 0 and bear == 0:
        return "neutral", 1
    strength = min(5, max(1, (bull + bear) // 2 + 1))
    if bull > bear:
        return "bullish", strength
    if bear > bull:
        return "bearish", strength
    return "neutral", 2


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[。；;！!？?\n]", text) if s.strip()]


def pick_evidence(text: str, limit: int = 120) -> str:
    for s in _sentences(text):
        if any(w in s for w in BULLISH + BEARISH):
            return s[:limit]
    return (text.strip()[:limit]) if text.strip() else ""


def make_summary(title: str, content: str, limited: int = 70) -> str:
    base = title.strip() or content.strip()
    base = re.sub(r"【[^】]*】", "", base).strip(" ：:")
    return base[:limited]


@dataclass
class RuleResult:
    direction: str
    strength: int
    confidence: float
    factor: str
    event_type: str
    summary: str
    evidence: str
    reasoning: str
    horizons: dict[str, str] = field(default_factory=dict)


def analyze(text: str, title: str, source_weight: float, custom_keywords: dict | None = None,
            important: bool = False) -> RuleResult:
    direction, strength = detect_direction(text)
    if important and direction != "neutral":
        strength = min(5, strength + 1)
    factor = detect_factor(text, custom_keywords)
    event = detect_event_type(text)
    confidence = 0.62 if direction != "neutral" else 0.45
    if len(text) > 300 and direction != "neutral":
        confidence += 0.03
    confidence = round(min(0.9, confidence), 2)

    horizon = "short"
    if event in ("库存", "需求", "成本"):
        horizon = "medium"
    if event in ("政策", "宏观"):
        horizon = "medium"
    if event in ("天气", "装置检修", "减产", "复产", "增产"):
        horizon = "short"

    name = {"bullish": "利多", "bearish": "利空", "neutral": "中性"}[direction]
    reasoning = f"规则识别到{factor}相关信号（{event}），方向倾向{name}，强度{strength}。"

    return RuleResult(
        direction=direction,
        strength=strength,
        confidence=confidence,
        factor=factor,
        event_type=event,
        summary=make_summary(title, text),
        evidence=pick_evidence(text),
        reasoning=reasoning,
        horizons={"horizon": horizon},
    )
