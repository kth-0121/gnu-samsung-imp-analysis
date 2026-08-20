"""
Root Cause Candidate Analysis + Evidence 기반 Priority Ranking (섹션 12~16).

원인을 직접 단정하지 않는다. Impact Scope 결과(어떤 Lot이 이상인지)와
Event Log(장비 Alarm/PM, 계측 Event, Recipe/Process 변경 이력)에서 관찰되는
패턴을 수치화한 뒤, 그 수치(Evidence)를 근거로 카테고리별 점수를 계산한다.
점수가 높을수록 "우선 검증이 필요한 후보"이며, 원인의 확정이 아니다.

지원 카테고리: Equipment / Measurement / Process/Recipe / Material/Lot / Other

Evidence 신호 (모두 0.0~1.0으로 정규화):
  Equipment
    - concentration: 이상 Lot이 특정 장비 하나에 얼마나 집중되어 있는가
    - event_match:   그 장비에서 이상 발생 시점 근처 Alarm/PM 이력이 있는가
  Measurement
    - equipment_diversity: 이상 Lot이 여러 장비에 걸쳐 나타나는가 (집중의 반대)
    - event_match:          이상 발생 시점 근처 계측 Event/Calibration 이력이 있는가
    - process_stability:    같은 기간 Recipe/Process 변경 이력이 없는가
  Process/Recipe
    - cross_equipment_recipe_match: 이상 Lot이 동일 Recipe를 공유하며 여러 장비에 걸쳐 있는가
    - event_match:                   그 Recipe에 이상 발생 시점 근처 변경 이력이 있는가
  Material/Lot, Other
    - 현재 스키마에 관련 데이터가 없어 낮은 baseline 점수만 부여 (섹션15 - 근거 없는 확정 금지)

가중치는 config/weights.yaml에 있으며 임의로 설정한 값임을 명시한다.
"""

from __future__ import annotations

import pandas as pd

from src.schemas.models import LotClassification, EvidenceSignal, CandidateCause

CATEGORIES = ["Equipment", "Measurement", "Process/Recipe", "Material/Lot", "Other"]

RECOMMENDED_VERIFICATION = {
    "Equipment": "해당 장비의 Alarm/PM/Calibration 이력을 확인하고, 설비팀과 함께 장비 상태를 점검한다.",
    "Measurement": "계측 장비의 최근 Calibration/Event 이력을 확인하고, 다른 계측기로 교차검증(재측정)을 수행한다.",
    "Process/Recipe": "Recipe/Process Parameter 변경 이력을 확인하고, 변경 전후 Lot의 Rs 데이터를 비교한다.",
    "Material/Lot": "Lot/Wafer 소재 특성(입고 이력, 배치 정보 등)을 확인한다 (현재 데이터에는 포함되어 있지 않음).",
    "Other": "위 범주로 설명되지 않는 요인에 대해 유관부서와 추가로 논의한다.",
}


def _abnormal_rows(lot_summary: pd.DataFrame, classifications: list[LotClassification]) -> pd.DataFrame:
    abnormal_ids = {c.lot_id for c in classifications if c.category in ("Confirmed Abnormal", "High Risk")}
    ls = lot_summary.copy()
    ls["lot_id"] = ls["lot_id"].astype(str)
    return ls[ls["lot_id"].isin(abnormal_ids)]


def _dominant_share(values: list) -> tuple[float, object]:
    """values 중 가장 흔한 값의 비율과 그 값을 반환한다."""
    if not values:
        return 0.0, None
    counts = pd.Series(values).value_counts()
    top = counts.index[0]
    return float(counts.iloc[0] / len(values)), top


def _events_near(events_df: pd.DataFrame | None, anchor_time, window_hours: float,
                  event_types: set, equipment_id=None, recipe_id=None) -> list[dict]:
    """anchor_time 이전 window_hours 시간 이내에 발생한 event_types 이벤트를 찾는다."""
    if events_df is None or events_df.empty or anchor_time is None:
        return []
    anchor = pd.to_datetime(anchor_time, errors="coerce")
    if pd.isna(anchor):
        return []
    window_start = anchor - pd.Timedelta(hours=window_hours)

    mask = (
        events_df["EVENT_TYPE"].isin(event_types)
        & events_df["EVENT_TIMESTAMP"].notna()
        & (events_df["EVENT_TIMESTAMP"] >= window_start)
        & (events_df["EVENT_TIMESTAMP"] <= anchor)
    )
    if equipment_id is not None:
        mask &= events_df["EQUIPMENT_ID"] == equipment_id
    if recipe_id is not None:
        mask &= events_df["RECIPE_ID"] == recipe_id

    return events_df[mask].to_dict("records")


def _confidence(score: float, thresholds: dict) -> str:
    if score >= thresholds["high"]:
        return "High"
    if score >= thresholds["medium"]:
        return "Medium"
    return "Low"


def _build_candidate(category: str, signals: list[EvidenceSignal], confidence_thresholds: dict) -> CandidateCause:
    score = sum(s.value * s.weight for s in signals)
    summary = " / ".join(s.description for s in signals)
    return CandidateCause(
        category=category,
        score=score * 100,
        confidence=_confidence(score, confidence_thresholds),
        verification_priority=0,  # 아래에서 정렬 후 채움
        signals=signals,
        association_summary=summary,
        recommended_verification=RECOMMENDED_VERIFICATION[category],
    )


def generate_candidate_causes(
    lot_summary: pd.DataFrame,
    classifications: list[LotClassification],
    events_df: pd.DataFrame | None,
    anomaly_start,
    weights_cfg: dict,
) -> list[CandidateCause]:
    cfg = weights_cfg["root_cause"]
    window_hours = cfg["event_window_hours"]
    ct = cfg["confidence_thresholds"]
    cw = cfg["category_weights"]
    baseline = cfg["baseline_scores"]

    abn = _abnormal_rows(lot_summary, classifications)
    n_abnormal = len(abn)

    equipment_values = abn["equipment_id"].dropna().tolist() if "equipment_id" in abn else []
    recipe_values = abn["recipe_id"].dropna().tolist() if "recipe_id" in abn else []

    eq_share, dominant_eq = _dominant_share(equipment_values)
    n_distinct_eq = len(set(equipment_values))
    recipe_share, dominant_recipe = _dominant_share(recipe_values)

    if dominant_recipe is not None and "equipment_id" in abn:
        n_distinct_recipe_eq = abn.loc[abn["recipe_id"] == dominant_recipe, "equipment_id"].dropna().nunique()
    else:
        n_distinct_recipe_eq = 0

    candidates = []

    # ---------------- Equipment ----------------
    eq_events = _events_near(events_df, anomaly_start, window_hours,
                              {"EQUIPMENT_ALARM", "EQUIPMENT_PM"}, equipment_id=dominant_eq)
    eq_event_match = 1.0 if eq_events else 0.0
    concentration_desc = (
        f"이상 확인 Lot {n_abnormal}건 중 {eq_share:.0%}가 장비 '{dominant_eq}'에 집중됨"
        if dominant_eq else "이상 Lot이 없어 장비 집중도를 계산할 수 없음"
    )
    event_desc = (
        f"장비 '{dominant_eq}'에서 이상 발생 시점 기준 {window_hours}시간 이내 Alarm/PM 이력 {len(eq_events)}건 발견"
        if eq_events else
        (f"장비 '{dominant_eq}'에서 이상 발생 시점 기준 {window_hours}시간 이내 Alarm/PM 이력 없음"
         if dominant_eq else "이력을 조회할 대상 장비가 없음")
    )
    candidates.append(_build_candidate("Equipment", [
        EvidenceSignal("concentration", eq_share, cw["equipment"]["concentration"], concentration_desc),
        EvidenceSignal("event_match", eq_event_match, cw["equipment"]["event_match"], event_desc),
    ], ct))

    # ---------------- Measurement ----------------
    eq_diversity = min(1.0, max(0.0, (n_distinct_eq - 1) / 2))
    meas_events = _events_near(events_df, anomaly_start, window_hours,
                                {"MEASUREMENT_EVENT", "MEASUREMENT_CALIBRATION"})
    meas_event_match = 1.0 if meas_events else 0.0
    recipe_events_any = _events_near(events_df, anomaly_start, window_hours,
                                      {"RECIPE_CHANGE", "PROCESS_PARAM_CHANGE"})
    process_stability = 0.0 if recipe_events_any else 1.0

    diversity_desc = (
        f"이상 Lot이 서로 다른 장비 {n_distinct_eq}개에 걸쳐 나타남 (특정 장비에 집중되지 않음)"
        if n_distinct_eq > 1 else "이상 Lot이 단일 장비에 집중되어 있어 계측 요인 가능성은 상대적으로 낮음"
    )
    meas_event_desc = (
        f"이상 발생 시점 기준 {window_hours}시간 이내 계측 관련 Event/Calibration 이력 {len(meas_events)}건 발견"
        if meas_events else f"이상 발생 시점 기준 {window_hours}시간 이내 계측 관련 이력 없음"
    )
    stability_desc = (
        "같은 기간 Recipe/Process 변경 이력이 없어 공정 요인과는 구분됨"
        if process_stability else "같은 기간 Recipe/Process 변경 이력이 존재해 공정 요인과의 구분이 필요함"
    )
    candidates.append(_build_candidate("Measurement", [
        EvidenceSignal("equipment_diversity", eq_diversity, cw["measurement"]["equipment_diversity"], diversity_desc),
        EvidenceSignal("event_match", meas_event_match, cw["measurement"]["event_match"], meas_event_desc),
        EvidenceSignal("process_stability", process_stability, cw["measurement"]["process_stability"], stability_desc),
    ], ct))

    # ---------------- Process/Recipe ----------------
    if recipe_share >= 0.6 and n_distinct_recipe_eq >= 2:
        cross_eq_recipe = 1.0
    elif recipe_share >= 0.6:
        cross_eq_recipe = 0.5
    else:
        cross_eq_recipe = 0.0
    rec_events = _events_near(events_df, anomaly_start, window_hours,
                               {"RECIPE_CHANGE", "PROCESS_PARAM_CHANGE"}, recipe_id=dominant_recipe)
    rec_event_match = 1.0 if rec_events else 0.0

    recipe_desc = (
        f"이상 Lot의 {recipe_share:.0%}가 Recipe '{dominant_recipe}'를 사용하며, "
        f"서로 다른 장비 {n_distinct_recipe_eq}개에서 공통으로 나타남"
        if dominant_recipe else "Recipe 정보가 없어 계산할 수 없음"
    )
    rec_event_desc = (
        f"Recipe '{dominant_recipe}'에 대해 이상 발생 시점 기준 {window_hours}시간 이내 변경 이력 {len(rec_events)}건 발견"
        if rec_events else f"이상 발생 시점 기준 {window_hours}시간 이내 Recipe/Process 변경 이력 없음"
    )
    candidates.append(_build_candidate("Process/Recipe", [
        EvidenceSignal("cross_equipment_recipe_match", cross_eq_recipe,
                        cw["process_recipe"]["cross_equipment_recipe_match"], recipe_desc),
        EvidenceSignal("event_match", rec_event_match, cw["process_recipe"]["event_match"], rec_event_desc),
    ], ct))

    # ---------------- Material/Lot ----------------
    candidates.append(_build_candidate("Material/Lot", [
        EvidenceSignal("data_availability", baseline["material_lot"], 1.0,
                        "현재 데이터에는 Lot/Wafer 소재 특성 정보가 포함되어 있지 않아 근거를 생성할 수 없음"),
    ], ct))

    # ---------------- Other ----------------
    candidates.append(_build_candidate("Other", [
        EvidenceSignal("residual_uncertainty", baseline["other"], 1.0,
                        "Equipment/Measurement/Process/Material로 설명되지 않는 잔여 불확실성"),
    ], ct))

    candidates.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(candidates, start=1):
        c.verification_priority = i

    return candidates


def build_verification_plan(candidates: list[CandidateCause]) -> list[str]:
    ordered = sorted(candidates, key=lambda c: c.verification_priority)
    return [
        f"{c.verification_priority}. [{c.category}] (Confidence: {c.confidence}, Score: {c.score:.0f}/100) "
        f"{c.recommended_verification}"
        for c in ordered
    ]


def flatten_evidence(candidates: list[CandidateCause]) -> list[str]:
    """카테고리별 Evidence 문장을 하나의 리스트로 평탄화 (AnalysisResult.evidence용)."""
    lines = []
    for c in candidates:
        for s in c.signals:
            lines.append(f"[{c.category}] {s.description}")
    return lines
