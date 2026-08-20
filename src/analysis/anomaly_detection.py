"""
'정상 상태 대비 이상'을 탐지한다 (섹션 9).

방법: 각 장비(equipment_id)별로, 처리 순서(시간순)를 따라가며
직전 최대 N개의 "정상으로 판정된" Lot만을 baseline으로 사용하는
rolling z-score + rolling IQR 두 방법을 함께 사용한다.
이상으로 판정된 Lot은 이후 baseline 계산에서 제외한다 (self-masking 방지 -
그렇지 않으면 이상이 지속될수록 baseline 자체가 오염되어 탐지 민감도가 떨어진다).
control limit이 config에 제공되면 추가로 반영한다.

가장 중요한 구분: "이상치 하나(point anomaly)"와
"연속으로 이어지는 지속적 변화(shift)"를 구분해서 리턴한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.schemas.models import AnomalyPoint, AnomalyResult


def detect_anomalies(lot_summary: pd.DataFrame, metric_col: str, thresholds: dict,
                      group_col: str = "equipment_id") -> AnomalyResult:
    cfg = thresholds["anomaly"]
    z_thresh = cfg["z_score_threshold"]
    iqr_mult = cfg["iqr_multiplier"]
    consec = cfg["consecutive_points_for_shift"]
    window = cfg["baseline_window_lots"]
    cl = cfg.get("control_limits", {}).get(metric_col, {}) or {}
    ucl, lcl = cl.get("ucl"), cl.get("lcl")

    if group_col in lot_summary.columns and lot_summary[group_col].notna().any():
        groups = list(lot_summary.groupby(group_col, sort=False))
    else:
        groups = [(None, lot_summary)]

    all_points: list[AnomalyPoint] = []

    for _, g in groups:
        g = g.sort_values("timestamp", na_position="last", kind="stable").reset_index(drop=True)
        metric = g[metric_col]

        baseline_buffer: list[float] = []  # 이상으로 판정되지 않은 값만 누적 (self-masking 방지)
        flags = []

        for i in range(len(g)):
            val = float(metric.iloc[i])
            has_baseline = len(baseline_buffer) >= 3

            z = None
            z_flag = False
            iqr_flag = False
            bm = bs = None

            if has_baseline:
                window_vals = np.array(baseline_buffer[-window:])
                bm = float(window_vals.mean())
                bs = float(window_vals.std(ddof=1)) if len(window_vals) > 1 else 0.0
                if bs > 0:
                    z = (val - bm) / bs
                    z_flag = abs(z) > z_thresh
                q1, q3 = np.percentile(window_vals, [25, 75])
                iqr = q3 - q1
                if iqr > 0:
                    lower, upper = q1 - iqr_mult * iqr, q3 + iqr_mult * iqr
                    iqr_flag = val < lower or val > upper

            cl_flag = False
            if ucl is not None and val > ucl:
                cl_flag = True
            if lcl is not None and val < lcl:
                cl_flag = True

            flagged = (has_baseline and (z_flag or iqr_flag)) or cl_flag

            flags.append({
                "lot_id": g.loc[i, "lot_id"],
                "timestamp": g.loc[i, "timestamp"],
                "value": val,
                "baseline_mean": bm,
                "baseline_std": bs,
                "z": z,
                "iqr_flag": iqr_flag,
                "cl_flag": cl_flag,
                "flagged": bool(flagged),
                "is_shift": False,
            })

            if not flagged:
                baseline_buffer.append(val)

        # 연속 flagged 구간(run)을 찾아 consec 이상이면 shift로 표시
        run_start = None
        for i, f in enumerate(flags + [{"flagged": False}]):  # sentinel to close trailing run
            if f["flagged"]:
                if run_start is None:
                    run_start = i
            else:
                if run_start is not None:
                    if i - run_start >= consec:
                        for j in range(run_start, i):
                            flags[j]["is_shift"] = True
                    run_start = None

        for f in flags:
            if not f["flagged"]:
                continue
            all_points.append(AnomalyPoint(
                lot_id=str(f["lot_id"]),
                timestamp=str(f["timestamp"]) if pd.notna(f["timestamp"]) else None,
                metric_name=metric_col,
                value=float(f["value"]),
                baseline_mean=f["baseline_mean"],
                baseline_std=f["baseline_std"],
                z_score=float(f["z"]) if f["z"] is not None else None,
                iqr_flag=f["iqr_flag"],
                control_limit_flag=f["cl_flag"],
                is_point_anomaly=not f["is_shift"],
                is_shift_member=f["is_shift"],
            ))

    shift_points = [p for p in all_points if p.is_shift_member]
    shift_points_sorted = sorted(
        shift_points, key=lambda p: (p.timestamp is None, p.timestamp or "")
    )
    shift_lots = [p.lot_id for p in shift_points_sorted]
    anomaly_start = shift_points_sorted[0].timestamp if shift_points_sorted else None
    if anomaly_start is None and shift_points_sorted:
        anomaly_start = shift_points_sorted[0].lot_id

    method_notes = (
        f"장비별 처리 순서를 따라가며, 이상으로 판정되지 않은 직전 최대 {window}개 Lot "
        f"(최소 3개 필요)을 baseline으로 사용해 평균/표준편차를 계산 (이상 판정된 값은 baseline에서 제외). "
        f"Z-score(|z|>{z_thresh}) 및 IQR({iqr_mult}x, 선형보간) 두 방법 중 하나라도 초과하면 이상점 후보로 표시. "
        f"{consec}개 이상 연속으로 이상점이 나타나면 '지속적 변화(Shift)', "
        f"그렇지 않으면 '단일 이상치(Point Anomaly)'로 구분."
    )
    if ucl is not None or lcl is not None:
        method_notes += f" 관리상한/하한(UCL={ucl}, LCL={lcl})도 함께 반영."

    return AnomalyResult(
        metric_name=metric_col,
        points=all_points,
        shift_lots=shift_lots,
        anomaly_start=anomaly_start,
        method_notes=method_notes,
    )
