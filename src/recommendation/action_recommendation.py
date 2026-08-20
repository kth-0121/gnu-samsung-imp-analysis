"""
Immediate / Follow-up / Preventive 3단계 대응안을 생성한다 (섹션 17).

Hold 결과와 Validation 결과에서 규칙 기반으로 도출 가능한 Immediate Action을
중심으로 구현한다. Follow-up/Preventive는 candidate_causes(Root Cause Candidate
Analysis 결과)가 주어지면 Priority가 높은 후보를 참조해 구체화하고, 없으면
원인을 단정하지 않는 범위 내에서 일반화된 절차를 제시한다.
"""

from __future__ import annotations

from src.schemas.models import HoldRecommendation, LotClassification, ValidationReport, ActionItem, CandidateCause


def build_action_recommendations(
    hold_recs: list[HoldRecommendation],
    classifications: list[LotClassification],
    validation: ValidationReport,
    candidate_causes: list[CandidateCause] | None = None,
) -> list[ActionItem]:
    actions: list[ActionItem] = []
    candidate_causes = candidate_causes or []
    top_candidates = sorted(candidate_causes, key=lambda c: c.verification_priority)[:2]

    hold_lots = [r.lot_id for r in hold_recs if r.recommendation == "HOLD RECOMMENDED"]
    check_lots = [r.lot_id for r in hold_recs if r.recommendation.startswith("ADDITIONAL CHECK")]
    confirmed_lots = [c.lot_id for c in classifications if c.category == "Confirmed Abnormal"]
    equipments = sorted({c.equipment_id for c in classifications
                          if c.category in ("Confirmed Abnormal", "High Risk") and c.equipment_id})

    # ---- Immediate ----
    if hold_lots:
        actions.append(ActionItem(
            stage="Immediate",
            action=f"영향 가능 Lot {len(hold_lots)}건 RTP 투입 전 HOLD",
            rationale="Impact Scope 분석에서 'Confirmed Abnormal' 또는 'High Risk'로 분류된 Lot입니다. "
                       "다음 공정(RTP) 투입 전 격리하여 확산을 방지합니다 (Containment 원칙).",
            evidence_ref=hold_lots,
        ))
    if check_lots:
        actions.append(ActionItem(
            stage="Immediate",
            action=f"추가 확인 대상 Lot {len(check_lots)}건에 대해 데이터 재검토",
            rationale="동일 장비 또는 동일 Recipe 연관성은 있으나 시간 인접성 등 근거가 부족하여 "
                       "즉시 Hold 대신 우선 재검토가 필요합니다.",
            evidence_ref=check_lots,
        ))
    if confirmed_lots:
        actions.append(ActionItem(
            stage="Immediate",
            action="이상 확인 Lot에 대해 Rs 재계측 실시",
            rationale="계측 오차 가능성을 배제하기 위해, 원인 판단 전 재계측으로 값을 재확인합니다 "
                       "(DATA FIRST 원칙 - 계측 이상 여부를 가장 먼저 확인).",
            evidence_ref=confirmed_lots,
        ))
    if equipments:
        actions.append(ActionItem(
            stage="Immediate",
            action=f"장비({', '.join(map(str, equipments))}) 현재 상태/Alarm 확인",
            rationale="이상 Lot이 특정 장비에 시간적으로 연결되어 있어, 장비 상태를 우선 확인합니다.",
            evidence_ref=list(equipments),
        ))
    actions.append(ActionItem(
        stage="Immediate",
        action="설비팀에 영향 장비/시간대 공유, 수율팀에 영향 Lot 목록 공유",
        rationale="설비팀은 장비 Alarm/PM 이력 확인이, 수율팀은 품질 영향 평가가 필요합니다 "
                   "(COLLABORATION 원칙).",
        evidence_ref=hold_lots + check_lots,
    ))
    if validation.overall_confidence != "High":
        actions.append(ActionItem(
            stage="Immediate",
            action="분석에 사용된 원본 데이터 품질 이슈 재확인",
            rationale=f"Data Validation 결과 신뢰도 '{validation.overall_confidence}' - {validation.confidence_reason} "
                       "데이터 품질 문제가 분석 결과의 신뢰도에 영향을 줄 수 있습니다.",
            evidence_ref=[],
        ))

    # ---- Follow-up (원인 확인 이후 수행) ----
    if top_candidates:
        for c in top_candidates:
            actions.append(ActionItem(
                stage="Follow-up",
                action=f"[Priority {c.verification_priority}] {c.category} 원인 후보 검증 — {c.recommended_verification}",
                rationale=f"Root Cause Candidate Analysis 결과 Score {c.score:.0f}/100, "
                          f"Confidence {c.confidence}. 근거: {c.association_summary} "
                          "(상관관계 기반 우선순위이며 원인 확정이 아님 - ROOT CAUSE 원칙).",
                evidence_ref=confirmed_lots,
            ))
    else:
        actions.append(ActionItem(
            stage="Follow-up",
            action="원인 후보(장비/계측/Recipe/Lot 특성)에 대한 근거 기반 검증 수행",
            rationale="Event Log가 없어 Priority를 계산하지 못했습니다. 상관관계만으로 원인을 단정하지 "
                       "않고, Trend/장비 이력/계측 이력 등 Evidence를 확보한 뒤 종합 검증합니다 "
                       "(ROOT CAUSE 원칙).",
            evidence_ref=confirmed_lots,
        ))
    if equipments:
        actions.append(ActionItem(
            stage="Follow-up",
            action="관련 장비 PM/Calibration 이력 및 최근 변경 이력 확인 - 설비팀 협의",
            rationale="장비 관련 원인 가능성을 검증하기 위한 근거 자료 확보 단계입니다.",
            evidence_ref=list(equipments),
        ))
    actions.append(ActionItem(
        stage="Follow-up",
        action="Hold Lot 재측정 결과와 최초 계측 결과 비교, 품질/수율 영향 평가",
        rationale="재현성 확인 및 실제 영향도 파악을 위해 필요합니다 (YIELD & QUALITY 원칙).",
        evidence_ref=hold_lots,
    ))

    # ---- Preventive (재발 방지) ----
    actions.append(ActionItem(
        stage="Preventive",
        action="Rs 산포에 대한 Monitoring/Control Chart 기준 강화 검토",
        rationale="이번 이상이 조기에 탐지되었는지 점검하고, 탐지 민감도를 재검토합니다.",
        evidence_ref=[],
    ))
    actions.append(ActionItem(
        stage="Preventive",
        action="관리 상한/Alarm 기준 및 장비 점검 주기 재검토",
        rationale="동일 유형의 이상이 재발하지 않도록 기준 자체의 타당성을 재검토합니다.",
        evidence_ref=[],
    ))
    actions.append(ActionItem(
        stage="Preventive",
        action="장비/Recipe 변경관리 프로세스 강화 검토",
        rationale="원인이 변경 이력과 관련된 것으로 확인될 경우, 변경관리 절차 보완이 필요합니다.",
        evidence_ref=[],
    ))
    if top_candidates and top_candidates[0].confidence != "Low":
        top = top_candidates[0]
        actions.append(ActionItem(
            stage="Preventive",
            action=f"{top.category} 관련 재발방지 대책 우선 검토",
            rationale=f"현재 데이터 기준 가장 우선순위가 높은 원인 후보({top.category}, "
                      f"Score {top.score:.0f}/100)에 대해, 검증 결과가 확정되면 그에 맞는 "
                      "재발방지 대책(모니터링/기준/주기)을 구체화합니다.",
            evidence_ref=[],
        ))

    return actions
