from src.analysis.anomaly_detection import detect_anomalies
from src.analysis.impact_scope import classify_impact
from src.recommendation.hold_recommendation import build_hold_recommendations


def _classify(lot_summary, thresholds):
    result_std = detect_anomalies(lot_summary, "rs_std", thresholds)
    result_mean = detect_anomalies(lot_summary, "rs_mean", thresholds)
    classifications = classify_impact(
        lot_summary, {"rs_std": result_std, "rs_mean": result_mean}, thresholds
    )
    return {c.lot_id: c for c in classifications}


def test_confirmed_abnormal_lots(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    for lot_id in ["LOT-011", "LOT-014", "LOT-017"]:
        assert by_lot[lot_id].category == "Confirmed Abnormal"
        assert by_lot[lot_id].reasons, "근거(reasons)가 비어 있으면 안 됩니다."


def test_high_risk_lots_adjacent_on_same_equipment(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    assert by_lot["LOT-005"].category == "High Risk"
    assert by_lot["LOT-008"].category == "High Risk"


def test_additional_check_same_equipment_not_adjacent(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    assert by_lot["LOT-002"].category == "Additional Check"


def test_additional_check_same_recipe_different_equipment(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    assert by_lot["LOT-016"].category == "Additional Check"


def test_unrelated_lots_are_normal(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    assert by_lot["LOT-003"].category == "Normal"
    assert by_lot["LOT-001"].category == "Normal"


def test_every_lot_is_classified_exactly_once(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    assert len(by_lot) == len(lot_summary)


def test_hold_recommendation_matches_impact_category(lot_summary, thresholds):
    by_lot = _classify(lot_summary, thresholds)
    hold_recs = build_hold_recommendations(list(by_lot.values()))
    hold_by_lot = {r.lot_id: r for r in hold_recs}

    assert hold_by_lot["LOT-011"].recommendation == "HOLD RECOMMENDED"
    assert hold_by_lot["LOT-005"].recommendation == "HOLD RECOMMENDED"
    assert hold_by_lot["LOT-002"].recommendation.startswith("ADDITIONAL CHECK")
    assert hold_by_lot["LOT-001"].recommendation == "NORMAL"
    for r in hold_recs:
        assert any("Recommendation" in reason for reason in r.reasons), \
            "모든 권고에는 '최종 판단은 담당자' 고지가 포함되어야 합니다."
