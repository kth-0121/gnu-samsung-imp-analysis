"""
파이프라인의 각 단계 결과를 하나의 구조화 결과(AnalysisResult)로 합치고,
섹션 18 형식의 최종 보고서(Markdown)를 생성한다.

이 모듈은 새로운 판단을 만들어내지 않는다 - 이미 계산된 결과를 정리/서술할 뿐이다.
LLM을 붙이더라도 이 구조화 결과(to_dict())만 입력으로 사용해야 한다 (섹션 20).
"""

from __future__ import annotations

import pandas as pd

from src.schemas.models import (
    AnalysisResult, LotClassification, HoldRecommendation, ActionItem,
    ValidationReport, AnomalyResult, CandidateCause,
)
from src.analysis.root_cause import build_verification_plan, flatten_evidence


def build_analysis_result(
    lot_summary: pd.DataFrame,
    classifications: list[LotClassification],
    anomaly_results: dict[str, AnomalyResult],
    hold_recs: list[HoldRecommendation],
    actions: list[ActionItem],
    validation: ValidationReport,
    candidate_causes: list[CandidateCause] | None = None,
    events_available: bool = False,
    data_source: str = "unknown",
    primary_metric: str = "rs_std",
) -> AnalysisResult:
    candidate_causes = candidate_causes or []

    equipment_association: dict = {}
    for c in classifications:
        if c.equipment_id is None:
            continue
        bucket = equipment_association.setdefault(str(c.equipment_id), {
            "Confirmed Abnormal": [], "High Risk": [], "Additional Check": [], "Normal": [],
        })
        bucket[c.category].append(c.lot_id)

    trend_changes = {name: result.to_dict() for name, result in anomaly_results.items()}

    anomaly_start = None
    if primary_metric in anomaly_results and anomaly_results[primary_metric].anomaly_start:
        anomaly_start = anomaly_results[primary_metric].anomaly_start
    else:
        for result in anomaly_results.values():
            if result.anomaly_start:
                anomaly_start = result.anomaly_start
                break

    notes = [
        "본 결과는 상관관계 기반 분석이며, 인과관계를 단정하지 않습니다. "
        "제시된 원인 후보(candidate_causes)는 Priority가 가장 높더라도 '원인 확정'이 아니라 "
        "'우선 검증 대상'이며, 반드시 추가 검증이 필요합니다.",
        "모든 Hold/조치 권고는 'Recommendation'이며, 최종 판단은 담당 엔지니어가 수행해야 합니다.",
    ]
    if candidate_causes:
        notes.append(
            "Root Cause Priority는 config/weights.yaml에 명시된 임의 가중치로 계산된 점수이며, "
            "실제 관리기준을 반영한 값이 아닙니다."
        )
        if not events_available:
            notes.append(
                "Event Log(장비 Alarm/PM, 계측 Event, Recipe 변경 이력)가 제공되지 않아 이력 기반 "
                "근거(event_match)는 반영되지 않았습니다. 장비/Recipe 집중도 등 통계적 근거만 반영된 "
                "점수이므로 참고용으로만 활용하세요."
            )
    else:
        notes.append("Lot 데이터가 부족해 Root Cause Candidate Analysis를 계산하지 못했습니다.")
    if data_source.startswith("mock"):
        notes.append("EDUCATIONAL MOCK DATA — NOT REAL FAB DATA 기반 결과입니다 (실제 Fab 데이터 아님).")
    if validation.overall_confidence != "High":
        notes.append(f"데이터 품질 신뢰도: {validation.overall_confidence} - {validation.confidence_reason}")

    return AnalysisResult(
        anomaly_start=anomaly_start,
        affected_lots=classifications,
        equipment_association=equipment_association,
        trend_changes=trend_changes,
        candidate_causes=candidate_causes,
        evidence=flatten_evidence(candidate_causes),
        recommended_actions=actions,
        validation=validation,
        verification_plan=build_verification_plan(candidate_causes) if candidate_causes else [],
        data_source=data_source,
        notes=notes,
    )


def render_report_markdown(result: AnalysisResult) -> str:
    hold_lots = [l for l in result.affected_lots if l.category in ("Confirmed Abnormal", "High Risk")]
    check_lots = [l for l in result.affected_lots if l.category == "Additional Check"]

    lines = []
    lines.append("# IMP Rs 산포 이상 대응 보고서\n")

    lines.append("## 01. 현재 상황")
    lines.append(f"- 이상 발생(추정) 시점: **{result.anomaly_start or '판정 불가 (데이터 부족)'}**")
    for metric, trend in result.trend_changes.items():
        lines.append(f"- `{metric}` 지표: 지속적 변화(Shift)로 판정된 Lot {len(trend['shift_lots'])}건")
        lines.append(f"  - 판정 방법: {trend['method_notes']}")
    lines.append("")

    lines.append("## 02. 영향 범위")
    lines.append(f"- HOLD 권고 대상: **{len(hold_lots)}건**")
    for l in hold_lots:
        lines.append(f"  - `{l.lot_id}` ({l.category}, 장비={l.equipment_id}, Recipe={l.recipe_id})")
        for r in l.reasons:
            lines.append(f"    - {r}")
    lines.append(f"- 추가 확인 대상: **{len(check_lots)}건**")
    for l in check_lots:
        lines.append(f"  - `{l.lot_id}` (장비={l.equipment_id}, Recipe={l.recipe_id})")
        for r in l.reasons:
            lines.append(f"    - {r}")
    lines.append("")

    lines.append("## 03. 원인 가설 (Root Cause Candidates — Priority 순)")
    if not result.candidate_causes:
        lines.append("- Event Log가 제공되지 않아 원인 후보 Priority를 계산하지 못했습니다. "
                      "섹션13 기준 일반 검증 순서(계측 확인 → 시점 확인 → 동일 장비 집중 여부 → "
                      "Alarm/PM/Calibration → Recipe 이력 → Lot 특성 → 유관부서 확인)를 따르세요.")
    else:
        for c in result.candidate_causes:
            lines.append(f"### {c.verification_priority}순위. {c.category} — {c.score:.0f}/100 (Confidence: {c.confidence})")
            for s in c.signals:
                lines.append(f"  - {s.description} (value={s.value:.2f}, weight={s.weight:.2f})")
            lines.append(f"  - **권고**: {c.recommended_verification}")
    lines.append("")

    lines.append("## 04. 검증 및 조치")
    for stage, title in [("Immediate", "즉시조치 (RTP 투입 전)"), ("Follow-up", "후속조치 (원인 확인 후)")]:
        lines.append(f"### {title}")
        for a in [x for x in result.recommended_actions if x.stage == stage]:
            lines.append(f"- **{a.action}**")
            lines.append(f"  - 근거: {a.rationale}")
            if a.evidence_ref:
                lines.append(f"  - 관련 Lot/장비: {', '.join(map(str, a.evidence_ref))}")
    lines.append("")

    lines.append("## 05. 재발방지")
    for a in [x for x in result.recommended_actions if x.stage == "Preventive"]:
        lines.append(f"- **{a.action}** — {a.rationale}")
    lines.append("")

    lines.append("## 06. 최종 제안")
    if hold_lots:
        lot_ids = ", ".join(l.lot_id for l in hold_lots)
        lines.append(f"- RTP 투입 전 **{len(hold_lots)}건 Lot({lot_ids}) HOLD를 권고**합니다.")
    else:
        lines.append("- 현재 데이터 기준 HOLD 권고 대상 Lot은 없습니다. (추가 확인 대상은 있을 수 있음)")
    lines.append("- 본 보고서는 의사결정 지원 참고 자료이며, 최종 Hold/투입 여부 및 원인 확정은 "
                  "담당 엔지니어/팀장의 검토가 필요합니다.")
    lines.append("")

    lines.append("## 불확실성 및 제약사항")
    for n in result.notes:
        lines.append(f"- {n}")

    return "\n".join(lines)
