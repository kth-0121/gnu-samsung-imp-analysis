"""
Impact Scope 분류 결과를 Hold 권고로 변환한다 (섹션 11).

이 모듈은 실제 생산 판단을 대신하지 않는다 - 항상 'RECOMMENDED' / 'REVIEW REQUIRED'
형태로만 표현한다.
"""

from __future__ import annotations

from src.schemas.models import LotClassification, HoldRecommendation

_CATEGORY_TO_RECOMMENDATION = {
    "Confirmed Abnormal": "HOLD RECOMMENDED",
    "High Risk": "HOLD RECOMMENDED",
    "Additional Check": "ADDITIONAL CHECK (Review Required)",
    "Normal": "NORMAL",
}

_DISCLAIMER = "본 결과는 권고(Recommendation)이며, 실제 Hold/투입 여부는 담당자가 최종 판단해야 합니다."


def build_hold_recommendations(classifications: list[LotClassification]) -> list[HoldRecommendation]:
    recs = []
    for c in classifications:
        recommendation = _CATEGORY_TO_RECOMMENDATION.get(c.category, "ADDITIONAL CHECK (Review Required)")
        reasons = list(c.reasons) + [_DISCLAIMER]
        recs.append(HoldRecommendation(
            lot_id=c.lot_id,
            recommendation=recommendation,
            reasons=reasons,
        ))
    return recs
