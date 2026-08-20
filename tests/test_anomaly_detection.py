from src.analysis.anomaly_detection import detect_anomalies
from tests.conftest import EXPECTED_ABNORMAL_LOT_IDS


def test_detects_injected_shift_on_rs_std(lot_summary, thresholds):
    result = detect_anomalies(lot_summary, "rs_std", thresholds)
    assert result.shift_lots == EXPECTED_ABNORMAL_LOT_IDS


def test_anomaly_start_is_set_when_shift_found(lot_summary, thresholds):
    result = detect_anomalies(lot_summary, "rs_std", thresholds)
    assert result.anomaly_start is not None


def test_normal_metric_has_no_shift(lot_summary, thresholds):
    # rs_mean은 이상 시나리오에서 소폭만 이동하도록 설계했으므로
    # 최소한 rs_std보다 훨씬 적거나 없는 shift가 나와야 한다 (과탐지 방지 확인).
    result_std = detect_anomalies(lot_summary, "rs_std", thresholds)
    result_mean = detect_anomalies(lot_summary, "rs_mean", thresholds)
    assert len(result_mean.shift_lots) <= len(result_std.shift_lots)


def test_flagged_points_have_method_metadata(lot_summary, thresholds):
    result = detect_anomalies(lot_summary, "rs_std", thresholds)
    assert result.points, "이상점이 하나도 탐지되지 않았습니다."
    for p in result.points:
        assert p.metric_name == "rs_std"
        assert p.is_point_anomaly != p.is_shift_member
