"""重算历史资讯的品种匹配，并补齐分析/评分。

用途：调整品种关键词或匹配规则后，对已入库的历史 raw_docs 重新识别品种，
不必重新抓取。重复执行安全：已有分析的文档不会重复生成。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Analysis, RawDoc, Score  # noqa: E402
from app.services import rules, scoring  # noqa: E402
from app.services.pipeline import (  # noqa: E402
    active_varieties, custom_factor_keywords, _is_divergent,
)


def main() -> None:
    with SessionLocal() as db:
        varieties = active_varieties(db)
        docs = db.execute(select(RawDoc).order_by(RawDoc.id)).scalars().all()
        created = rematched = 0
        for doc in docs:
            text = f"{doc.title}\n{doc.content}"
            codes = rules.detect_varieties(text, varieties)
            doc.matched_varieties = codes
            if not codes:
                if doc.status == "quick":
                    doc.status = "ignored"
                continue
            if doc.status == "ignored":
                doc.status = "quick"
            rematched += 1

            if db.execute(select(Analysis.id).where(Analysis.doc_id == doc.id)).first():
                continue

            ckw = custom_factor_keywords(db, codes)
            rr = rules.analyze(text, doc.title, doc.source_weight, ckw, important=doc.is_manual)
            analysis = Analysis(
                doc_id=doc.id, model="rule-rebuild", prompt_version="v1", status="quick",
                varieties=codes, direction=rr.direction, strength=rr.strength,
                confidence=0.55, horizon=rr.horizons.get("horizon", "short"),
                factor=rr.factor, event_type=rr.event_type, summary=rr.summary,
                evidence=rr.evidence, reasoning=rr.reasoning,
            )
            db.add(analysis)
            db.flush()
            for c in codes:
                s = scoring.compute_score(
                    direction=rr.direction, strength=rr.strength, confidence=0.55,
                    source_weight=doc.source_weight, published_at=doc.published_at,
                    horizon=rr.horizons.get("horizon", "short"), novelty=0.8,
                )
                db.add(Score(
                    analysis_id=analysis.id, doc_id=doc.id, variety_code=c,
                    direction=rr.direction, score=s, importance=abs(s), confidence=0.55,
                    factor=rr.factor, is_divergent=_is_divergent(db, c, rr.direction),
                ))
            created += 1
        db.commit()
        print(f"[rebuild] 文档 {len(docs)} 条，匹配到品种 {rematched} 条，新增分析 {created} 条")

    with SessionLocal() as db:
        print("\n各品种命中数：")
        from collections import Counter
        cnt: Counter = Counter()
        for (mv,) in db.execute(select(RawDoc.matched_varieties)).all():
            for code in (mv or []):
                cnt[code] += 1
        for code, n in cnt.most_common():
            print(f"  {code:<5} {n}")


if __name__ == "__main__":
    main()
