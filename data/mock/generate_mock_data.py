"""
EDUCATIONAL MOCK DATA GENERATOR — NOT REAL FAB DATA

이 스크립트가 생성하는 모든 수치(Rs 값, 장비/Recipe ID, 시각 등)는
GNU IC-PBL 교육용 Business Challenge를 위해 임의로 만든 것이며,
실제 삼성전자 Foundry 공정 데이터/기밀 Recipe 값과 무관하다.

시나리오: EQ-02 장비에서 처리된 마지막 3개 연속 Lot의 Rs 산포(Lot 내 site 간 편차)가
baseline 대비 크게 증가한 상황을 모사한다 (Business Challenge 문제 상황과 동일한 패턴).
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

SEED = 42
N_LOTS = 18
N_WAFERS = 5
N_SITES = 5
START_TIME = pd.Timestamp("2026-08-20 05:30:00")
LOT_INTERVAL_MIN = 11

EQUIPMENTS = ["EQ-01", "EQ-02", "EQ-03"]
DEFAULT_RECIPE = {"EQ-01": "RCP-B", "EQ-02": "RCP-A", "EQ-03": "RCP-B"}

BASELINE_MEAN = 120.0
BASELINE_SITE_STD = 1.8

# EQ-02 자체 시퀀스 기준(0-indexed) 마지막 3개 Lot을 이상으로 설정
ABNORMAL_EQ = "EQ-02"
ABNORMAL_EQ_POSITIONS = {3, 4, 5}
ABNORMAL_WAFER_OFFSET_STD = 6.0
ABNORMAL_MEAN_SHIFT = 3.0

# Recipe 연관성(Additional Check) 데모용: EQ-01의 특정 lot만 EQ-02와 동일 Recipe 사용
RECIPE_OVERRIDE_LOT_INDEX = 16  # 1-indexed overall lot number
RECIPE_OVERRIDE_VALUE = "RCP-A"


def generate_mock_dataframe() -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(SEED)

    eq_position_counter = {eq: 0 for eq in EQUIPMENTS}
    rows = []
    abnormal_lot_ids = []
    lot_meta = []

    for i in range(1, N_LOTS + 1):
        equipment = EQUIPMENTS[(i - 1) % len(EQUIPMENTS)]
        recipe = DEFAULT_RECIPE[equipment]
        if i == RECIPE_OVERRIDE_LOT_INDEX:
            recipe = RECIPE_OVERRIDE_VALUE

        eq_pos = eq_position_counter[equipment]
        eq_position_counter[equipment] += 1

        lot_id = f"LOT-{i:03d}"
        timestamp = START_TIME + pd.Timedelta(minutes=LOT_INTERVAL_MIN * (i - 1))

        is_abnormal = (equipment == ABNORMAL_EQ) and (eq_pos in ABNORMAL_EQ_POSITIONS)
        if is_abnormal:
            abnormal_lot_ids.append(lot_id)

        lot_meta.append({
            "lot_id": lot_id, "equipment_id": equipment, "recipe_id": recipe,
            "timestamp": timestamp, "is_abnormal": is_abnormal,
        })

        for w in range(1, N_WAFERS + 1):
            wafer_id = f"W{w:02d}"
            wafer_offset = 0.0
            if is_abnormal:
                wafer_offset = rng.normal(0, ABNORMAL_WAFER_OFFSET_STD)
            for s in range(1, N_SITES + 1):
                site_id = f"S{s}"
                mean = BASELINE_MEAN + (ABNORMAL_MEAN_SHIFT if is_abnormal else 0.0) + wafer_offset
                site_noise_std = BASELINE_SITE_STD if not is_abnormal else BASELINE_SITE_STD * 1.2
                rs_value = rng.normal(mean, site_noise_std)
                rows.append({
                    "LOT_ID": lot_id,
                    "WAFER_ID": wafer_id,
                    "SITE_ID": site_id,
                    "EQUIPMENT_ID": equipment,
                    "RECIPE_ID": recipe,
                    "PROCESS_TIMESTAMP": timestamp,
                    "RS_OHM_SQ": round(float(rs_value), 3),
                })

    df = pd.DataFrame(rows)
    metadata = {
        "abnormal_lot_ids": abnormal_lot_ids,
        "lot_meta": lot_meta,
        "note": "EDUCATIONAL MOCK DATA — NOT REAL FAB DATA",
    }
    return df, metadata


def main():
    df, metadata = generate_mock_dataframe()

    out_path = Path(__file__).parent / "mock_imp_rs_data.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")
    print("EDUCATIONAL MOCK DATA - NOT REAL FAB DATA")
    print("Abnormal lots:", metadata["abnormal_lot_ids"])

    fixture_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "mock_lots.csv"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(fixture_path, index=False)
    print(f"Wrote test fixture to {fixture_path}")


if __name__ == "__main__":
    main()
