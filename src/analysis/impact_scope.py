"""
이상 Lot을 찾는 데서 끝나지 않고, 영향 가능 범위를 분석한다 (섹션 10).

판단 기준 (Must 단계에서 구현):
  1. 동일 장비
  2. 동일 Recipe
  3. 시간 인접성 (동일 장비 처리 순서 기준 앞/뒤 N개 Lot)
  4. Rs Trend(anomaly_detection 결과, 여러 metric 가능)

분류: Confirmed Abnormal / High Risk / Additional Check / Normal
각 Lot에는 반드시 사람이 검증 가능한 근거 문장을 함께 남긴다.
"""

from __future__ import annotations

import pandas as pd

from src.schemas.models import AnomalyResult, LotClassification


def classify_impact(lot_summary: pd.DataFrame, anomaly_results: dict[str, AnomalyResult],
                     thresholds: dict) -> list[LotClassification]:
    adjacency = thresholds["impact_scope"]["time_adjacency_lots"]

    # metric별 shift_lots를 하나의 lot_id -> [ (metric, point) ] 맵으로 통합
    confirmed_reasons: dict[str, list[str]] = {}
    for metric_name, result in anomaly_results.items():
        for p in result.points:
            if not p.is_shift_member:
                continue
            baseline_str = f"{p.baseline_mean:.3g}" if p.baseline_mean is not None else "N/A"
            reason = f"'{metric_name}' 값이 baseline 대비 지속적 변화(Shift) 구간에 포함됨 (값={p.value:.3g}, baseline 평균={baseline_str}"
            if p.z_score is not None:
                reason += f", z-score={p.z_score:.2f}"
            reason += ")"
            confirmed_reasons.setdefault(p.lot_id, []).append(reason)

    confirmed_lot_ids = set(confirmed_reasons.keys())

    lot_summary = lot_summary.copy()
    lot_summary["lot_id"] = lot_summary["lot_id"].astype(str)

    # 장비별 처리순서(시간순) 시퀀스 구성 -> 인접성 판단용
    equip_sequences: dict[str, list[str]] = {}
    if "equipment_id" in lot_summary.columns:
        for eqp, g in lot_summary.groupby("equipment_id", sort=False):
            g = g.sort_values("timestamp", na_position="last", kind="stable")
            equip_sequences[eqp] = g["lot_id"].tolist()

    # 각 confirmed lot 기준 High Risk(인접) 후보 lot_id 집합과 근거
    high_risk_reasons: dict[str, list[str]] = {}
    equip_of_confirmed: dict[str, set] = {}  # equipment_id -> confirmed lot_ids on it

    for eqp, seq in equip_sequences.items():
        confirmed_positions = [i for i, lid in enumerate(seq) if lid in confirmed_lot_ids]
        if confirmed_positions:
            equip_of_confirmed[eqp] = {seq[i] for i in confirmed_positions}
        for pos in confirmed_positions:
            lo, hi = max(0, pos - adjacency), min(len(seq), pos + adjacency + 1)
            for j in range(lo, hi):
                lid = seq[j]
                if lid in confirmed_lot_ids:
                    continue
                distance = j - pos
                high_risk_reasons.setdefault(lid, []).append(
                    f"장비 '{eqp}'에서 이상 확인 Lot('{seq[pos]}')과 처리 순서상 {abs(distance)}단계 인접 "
                    f"(동일 장비, 시간 인접성 기준 충족)."
                )

    high_risk_lot_ids = set(high_risk_reasons.keys()) - confirmed_lot_ids

    # 동일 Recipe(다른 장비) -> Additional Check 근거
    recipe_of_confirmed = {}
    if "recipe_id" in lot_summary.columns:
        for _, row in lot_summary[lot_summary["lot_id"].isin(confirmed_lot_ids)].iterrows():
            if pd.notna(row.get("recipe_id")):
                recipe_of_confirmed.setdefault(row["recipe_id"], set()).add(row["lot_id"])

    classifications: list[LotClassification] = []
    for _, row in lot_summary.iterrows():
        lot_id = row["lot_id"]
        eqp = row.get("equipment_id")
        recipe = row.get("recipe_id")
        ts = row.get("timestamp")
        ts_str = str(ts) if pd.notna(ts) else None

        if lot_id in confirmed_lot_ids:
            classifications.append(LotClassification(
                lot_id=lot_id, category="Confirmed Abnormal",
                reasons=confirmed_reasons[lot_id],
                equipment_id=eqp, recipe_id=recipe, timestamp=ts_str,
            ))
            continue

        if lot_id in high_risk_lot_ids:
            classifications.append(LotClassification(
                lot_id=lot_id, category="High Risk",
                reasons=high_risk_reasons[lot_id],
                equipment_id=eqp, recipe_id=recipe, timestamp=ts_str,
            ))
            continue

        reasons = []
        if eqp is not None and eqp in equip_of_confirmed:
            reasons.append(
                f"장비 '{eqp}'에서 이상이 확인되었으나, 이 Lot은 시간 인접성 기준(앞/뒤 {adjacency}개 Lot)을 "
                f"벗어나 있어 직접적 연관 근거는 부족합니다. 데이터 기반 추가 확인이 필요합니다."
            )
        if recipe is not None and recipe in recipe_of_confirmed and lot_id not in recipe_of_confirmed[recipe]:
            reasons.append(
                f"이상 확인 Lot과 동일 Recipe('{recipe}')를 사용했으나 장비가 다릅니다. "
                f"Recipe 관련 요인 가능성을 배제하기 위해 추가 확인을 권고합니다."
            )

        if reasons:
            classifications.append(LotClassification(
                lot_id=lot_id, category="Additional Check",
                reasons=reasons, equipment_id=eqp, recipe_id=recipe, timestamp=ts_str,
            ))
        else:
            classifications.append(LotClassification(
                lot_id=lot_id, category="Normal",
                reasons=["이상 확인 Lot과 장비/Recipe/시간 연관성이 낮습니다."],
                equipment_id=eqp, recipe_id=recipe, timestamp=ts_str,
            ))

    return classifications
