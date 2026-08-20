"""
3개 교육용 Sample Dataset(Equipment/Measurement/Process-Recipe)에 대해
전체 파이프라인을 실행하고, Root Cause Priority가 의도한 카테고리로
서로 다르게 나오는지 검증한다.

주의: 여기서 "기대 카테고리"는 Sample 생성 시나리오의 의도(테스트 목적)일 뿐,
분석 엔진(src/analysis/root_cause.py)은 이 값을 전혀 참조하지 않는다.
엔진은 오직 lot_summary/classifications/events로부터 계산한 Evidence만 사용한다.
"""

from pathlib import Path
import pandas as pd
import pytest

from src.ingestion.loader import load_data
from src.ingestion.event_loader import load_events
from src.ingestion.schema_inference import infer_roles
from src.validation.data_validation import run_validation
from src.analysis.trend_analysis import build_lot_summary
from src.analysis.anomaly_detection import detect_anomalies
from src.analysis.impact_scope import classify_impact
from src.analysis.root_cause import generate_candidate_causes
from src.recommendation.hold_recommendation import build_hold_recommendations
from src.recommendation.action_recommendation import build_action_recommendations
from src.reporting.report_builder import build_analysis_result
from src.config import load_thresholds, load_weights

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "mock" / "samples"

# 테스트 전용 기대값 (생성 시나리오 의도) - 분석 엔진은 이 값을 참조하지 않는다.
EXPECTED_TOP_CATEGORY = {
    "sample1_equipment": "Equipment",
    "sample2_measurement": "Measurement",
    "sample3_recipe": "Process/Recipe",
}


def _run_pipeline(sample_id, thresholds, weights):
    d = SAMPLES_DIR / sample_id
    df = load_data(str(d / "measurements.csv"))
    events_df = load_events(str(d / "events.csv"))
    role_map = infer_roles(df)
    validation = run_validation(df, role_map)
    lot_summary = build_lot_summary(df, role_map)
    anomaly_results = {
        "rs_std": detect_anomalies(lot_summary, "rs_std", thresholds),
        "rs_mean": detect_anomalies(lot_summary, "rs_mean", thresholds),
    }
    classifications = classify_impact(lot_summary, anomaly_results, thresholds)
    hold_recs = build_hold_recommendations(classifications)
    anomaly_start = anomaly_results["rs_std"].anomaly_start or anomaly_results["rs_mean"].anomaly_start
    candidates = generate_candidate_causes(lot_summary, classifications, events_df, anomaly_start, weights)
    actions = build_action_recommendations(hold_recs, classifications, validation, candidates)
    result = build_analysis_result(
        lot_summary, classifications, anomaly_results, hold_recs, actions, validation,
        candidate_causes=candidates, events_available=events_df is not None,
        data_source=f"mock:{sample_id}",
    )
    return lot_summary, classifications, events_df, candidates, actions, result


@pytest.fixture(scope="module")
def sample_results():
    thresholds = load_thresholds()
    weights = load_weights()
    return {
        sample_id: _run_pipeline(sample_id, thresholds, weights)
        for sample_id in EXPECTED_TOP_CATEGORY
    }


def test_all_sample_files_exist():
    for sample_id in EXPECTED_TOP_CATEGORY:
        d = SAMPLES_DIR / sample_id
        assert (d / "measurements.csv").exists()
        assert (d / "events.csv").exists()


def test_each_sample_has_a_detected_shift(sample_results):
    for sample_id, (lot_summary, classifications, events_df, candidates, actions, result) in sample_results.items():
        confirmed = [c for c in classifications if c.category == "Confirmed Abnormal"]
        assert confirmed, f"{sample_id}: 이상 Lot이 하나도 탐지되지 않았습니다."


def test_events_loaded_for_all_samples(sample_results):
    for sample_id, (lot_summary, classifications, events_df, candidates, actions, result) in sample_results.items():
        assert events_df is not None, f"{sample_id}: Event Log 로드 실패"
        assert len(events_df) > 0


@pytest.mark.parametrize("sample_id,expected_top", list(EXPECTED_TOP_CATEGORY.items()))
def test_top_priority_category_matches_scenario_intent(sample_results, sample_id, expected_top):
    _, _, _, candidates, _, _ = sample_results[sample_id]
    top = min(candidates, key=lambda c: c.verification_priority)
    assert top.category == expected_top, (
        f"{sample_id}: 기대한 top category는 '{expected_top}'이지만 실제로는 '{top.category}'였습니다 "
        f"(전체 점수: {[(c.category, round(c.score, 1)) for c in candidates]})"
    )
    assert top.confidence in ("High", "Medium"), (
        f"{sample_id}: top category의 Confidence가 너무 낮습니다 ({top.confidence})"
    )


def test_three_samples_produce_different_top_categories(sample_results):
    tops = set()
    for sample_id, (_, _, _, candidates, _, _) in sample_results.items():
        top = min(candidates, key=lambda c: c.verification_priority)
        tops.add(top.category)
    assert len(tops) == 3, (
        f"세 Sample의 top category가 서로 달라야 하는데 {tops}로 겹칩니다. "
        "Mock Data 패턴 또는 root_cause.py 채점 로직을 재검토해야 합니다."
    )


def test_candidate_causes_cover_all_categories(sample_results):
    expected_categories = {"Equipment", "Measurement", "Process/Recipe", "Material/Lot", "Other"}
    for sample_id, (_, _, _, candidates, _, _) in sample_results.items():
        assert {c.category for c in candidates} == expected_categories


def test_every_candidate_has_evidence_and_verification(sample_results):
    for sample_id, (_, _, _, candidates, _, _) in sample_results.items():
        for c in candidates:
            assert c.signals, f"{sample_id}/{c.category}: signals(evidence)가 비어 있습니다."
            assert c.recommended_verification, f"{sample_id}/{c.category}: 권고 검증 문구가 비어 있습니다."


def test_follow_up_actions_reference_top_candidate(sample_results):
    for sample_id, (_, _, _, candidates, actions, _) in sample_results.items():
        top = min(candidates, key=lambda c: c.verification_priority)
        followups = [a for a in actions if a.stage == "Follow-up"]
        assert any(top.category in a.action for a in followups), (
            f"{sample_id}: Follow-up action이 top 후보({top.category})를 참조하지 않습니다."
        )


def test_analysis_result_marks_mock_data_source(sample_results):
    for sample_id, (_, _, _, _, _, result) in sample_results.items():
        assert result.data_source == f"mock:{sample_id}"
        assert any("EDUCATIONAL MOCK DATA" in n for n in result.notes), (
            f"{sample_id}: AnalysisResult.notes에 mock 데이터 표시가 없습니다."
        )


def test_verification_plan_is_priority_ordered(sample_results):
    for sample_id, (_, _, _, candidates, _, result) in sample_results.items():
        assert len(result.verification_plan) == len(candidates)
        assert result.verification_plan[0].startswith("1.")
