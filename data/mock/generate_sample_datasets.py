"""
EDUCATIONAL MOCK DATA GENERATOR — NOT REAL FAB DATA

3개의 교육용 Sample Dataset을 생성한다. 목적은 IMP Quality Response 시스템이
"이상 패턴 + 이력(Event Log)"만 보고, 서로 다른 상황에서 서로 다른 영향범위/원인
검증 우선순위를 제시할 수 있음을 보여주는 것이다.

이 스크립트가 만드는 모든 수치(Rs 값, 장비/Recipe ID, Alarm 코드, 시각 등)는
GNU IC-PBL 교육용 Business Challenge를 위해 임의로 만든 것이며, 실제 삼성전자
Foundry 공정 데이터/기밀 Recipe 값과 무관하다.

중요: 데이터 어디에도 "root_cause = 'Equipment'" 같은 정답 라벨을 직접 넣지 않는다.
각 Sample은 아래 패턴만 다르게 구성하고, 원인 후보 점수(Priority)는
src/analysis/root_cause.py가 이 패턴을 관찰해서 계산한다.

    Sample 1 (Equipment-focused):
        이상 Lot이 장비 하나(EQ-02)에 집중되고, 그 장비에 Alarm 이력이 있음.
    Sample 2 (Measurement-focused):
        이상이 특정 시점부터 장비 3대 모두에서 동시에 나타나고(장비 집중 없음),
        그 시점에 계측(Metrology) 관련 이력이 있으며 Recipe 변경 이력은 없음.
    Sample 3 (Process/Recipe-focused):
        이상 Lot이 서로 다른 두 장비(EQ-01, EQ-03)에서 나타나지만 동일 Recipe를
        공유하고, 그 Recipe에 대한 변경 이력이 있음.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

SEED = 7
N_LOTS = 18
N_WAFERS = 5
N_SITES = 5
START_TIME = pd.Timestamp("2026-08-20 05:30:00")
LOT_INTERVAL_MIN = 11

EQUIPMENTS = ["EQ-01", "EQ-02", "EQ-03"]  # offset 0, 1, 2 in round-robin order
BASELINE_MEAN = 120.0
BASELINE_SITE_STD = 1.8
ABNORMAL_WAFER_OFFSET_STD = 6.0
ABNORMAL_MEAN_SHIFT = 3.0

OUT_DIR = Path(__file__).parent / "samples"


def _generate_measurements(recipe_map: dict, abnormal_predicate, seed: int, recipe_overrides: dict | None = None):
    """
    recipe_map: {equipment_id: recipe_id} 기본 Recipe 배정
    abnormal_predicate(equipment_id, eq_pos, overall_index) -> bool
    recipe_overrides: {overall_index(1-based): recipe_id} 특정 Lot만 다른 Recipe로 override
    """
    rng = np.random.default_rng(seed)
    recipe_overrides = recipe_overrides or {}

    eq_position_counter = {eq: 0 for eq in EQUIPMENTS}
    rows = []
    lot_meta = []
    abnormal_lot_ids = []

    for i in range(1, N_LOTS + 1):
        equipment = EQUIPMENTS[(i - 1) % len(EQUIPMENTS)]
        recipe = recipe_overrides.get(i, recipe_map[equipment])
        eq_pos = eq_position_counter[equipment]
        eq_position_counter[equipment] += 1

        lot_id = f"LOT-{i:03d}"
        timestamp = START_TIME + pd.Timedelta(minutes=LOT_INTERVAL_MIN * (i - 1))
        is_abnormal = abnormal_predicate(equipment, eq_pos, i)
        if is_abnormal:
            abnormal_lot_ids.append(lot_id)

        lot_meta.append({
            "lot_id": lot_id, "equipment_id": equipment, "recipe_id": recipe,
            "timestamp": timestamp, "is_abnormal": is_abnormal,
        })

        for w in range(1, N_WAFERS + 1):
            wafer_id = f"W{w:02d}"
            wafer_offset = rng.normal(0, ABNORMAL_WAFER_OFFSET_STD) if is_abnormal else 0.0
            for s in range(1, N_SITES + 1):
                site_id = f"S{s}"
                mean = BASELINE_MEAN + (ABNORMAL_MEAN_SHIFT if is_abnormal else 0.0) + wafer_offset
                site_noise_std = BASELINE_SITE_STD * (1.2 if is_abnormal else 1.0)
                rs_value = rng.normal(mean, site_noise_std)
                rows.append({
                    "LOT_ID": lot_id, "WAFER_ID": wafer_id, "SITE_ID": site_id,
                    "EQUIPMENT_ID": equipment, "RECIPE_ID": recipe,
                    "PROCESS_TIMESTAMP": timestamp, "RS_OHM_SQ": round(float(rs_value), 3),
                })

    measurements_df = pd.DataFrame(rows)
    return measurements_df, lot_meta, abnormal_lot_ids


def _events_df(rows: list[dict]) -> pd.DataFrame:
    cols = ["EVENT_TIMESTAMP", "EVENT_TYPE", "EQUIPMENT_ID", "RECIPE_ID", "DESCRIPTION"]
    return pd.DataFrame(rows, columns=cols)


def build_sample1_equipment():
    """이상 Lot이 EQ-02에 집중, EQ-02에 이상 발생 직전 Alarm 이력 존재."""
    recipe_map = {"EQ-01": "RCP-B", "EQ-02": "RCP-A", "EQ-03": "RCP-B"}
    overrides = {16: "RCP-A"}  # EQ-01의 한 Lot만 EQ-02와 동일 Recipe 사용 (Additional Check 데모)

    def abnormal(equipment, eq_pos, overall_index):
        return equipment == "EQ-02" and eq_pos in (3, 4, 5)

    measurements, lot_meta, abnormal_lots = _generate_measurements(recipe_map, abnormal, SEED, overrides)
    anchor = START_TIME + pd.Timedelta(minutes=LOT_INTERVAL_MIN * 10)  # LOT-011 시각

    events = _events_df([
        {"EVENT_TIMESTAMP": anchor - pd.Timedelta(minutes=20), "EVENT_TYPE": "EQUIPMENT_ALARM",
         "EQUIPMENT_ID": "EQ-02", "RECIPE_ID": "", "DESCRIPTION": "Alarm code A-12: particle sensor 임계치 초과"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=2), "EVENT_TYPE": "EQUIPMENT_PM",
         "EQUIPMENT_ID": "EQ-02", "RECIPE_ID": "", "DESCRIPTION": "정기 PM 수행 완료"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=3), "EVENT_TYPE": "MEASUREMENT_CALIBRATION",
         "EQUIPMENT_ID": "", "RECIPE_ID": "", "DESCRIPTION": "계측기 정기 Calibration 수행"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=5), "EVENT_TYPE": "RECIPE_CHANGE",
         "EQUIPMENT_ID": "", "RECIPE_ID": "RCP-B", "DESCRIPTION": "RCP-B 파라미터 미세 조정"},
    ])
    return measurements, events, abnormal_lots


def build_sample2_measurement():
    """이상이 특정 시점부터 장비 3대 모두에서 동시 발생, 계측 이력과 시간 일치."""
    recipe_map = {"EQ-01": "RCP-A", "EQ-02": "RCP-B", "EQ-03": "RCP-C"}

    def abnormal(equipment, eq_pos, overall_index):
        return overall_index >= 10

    measurements, lot_meta, abnormal_lots = _generate_measurements(recipe_map, abnormal, SEED + 1)
    anchor = START_TIME + pd.Timedelta(minutes=LOT_INTERVAL_MIN * 9)  # LOT-010 시각

    events = _events_df([
        {"EVENT_TIMESTAMP": anchor - pd.Timedelta(minutes=30), "EVENT_TYPE": "MEASUREMENT_EVENT",
         "EQUIPMENT_ID": "", "RECIPE_ID": "", "DESCRIPTION": "Metrology 계측기 Cross-Calibration 편차 감지"},
        {"EVENT_TIMESTAMP": anchor - pd.Timedelta(minutes=90), "EVENT_TYPE": "MEASUREMENT_CALIBRATION",
         "EQUIPMENT_ID": "", "RECIPE_ID": "", "DESCRIPTION": "계측 Recipe 재설정 수행"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=2), "EVENT_TYPE": "EQUIPMENT_PM",
         "EQUIPMENT_ID": "EQ-01", "RECIPE_ID": "", "DESCRIPTION": "정기 PM 수행 완료"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=2), "EVENT_TYPE": "EQUIPMENT_PM",
         "EQUIPMENT_ID": "EQ-03", "RECIPE_ID": "", "DESCRIPTION": "정기 PM 수행 완료"},
    ])
    return measurements, events, abnormal_lots


def build_sample3_recipe():
    """이상 Lot이 서로 다른 두 장비(EQ-01/EQ-03)에서 나타나지만 동일 Recipe(RCP-A) 공유."""
    recipe_map = {"EQ-01": "RCP-A", "EQ-02": "RCP-B", "EQ-03": "RCP-A"}

    def abnormal(equipment, eq_pos, overall_index):
        return equipment != "EQ-02" and overall_index >= 10

    measurements, lot_meta, abnormal_lots = _generate_measurements(recipe_map, abnormal, SEED + 2)
    anchor = START_TIME + pd.Timedelta(minutes=LOT_INTERVAL_MIN * 9)  # LOT-010 시각

    events = _events_df([
        {"EVENT_TIMESTAMP": anchor - pd.Timedelta(minutes=15), "EVENT_TYPE": "RECIPE_CHANGE",
         "EQUIPMENT_ID": "", "RECIPE_ID": "RCP-A", "DESCRIPTION": "Recipe RCP-A dose_time 파라미터 변경 적용"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=2), "EVENT_TYPE": "EQUIPMENT_ALARM",
         "EQUIPMENT_ID": "EQ-01", "RECIPE_ID": "", "DESCRIPTION": "경미한 Alarm 발생 후 자동 복구"},
        {"EVENT_TIMESTAMP": START_TIME - pd.Timedelta(days=4), "EVENT_TYPE": "MEASUREMENT_CALIBRATION",
         "EQUIPMENT_ID": "", "RECIPE_ID": "", "DESCRIPTION": "계측기 정기 Calibration 수행"},
    ])
    return measurements, events, abnormal_lots


SAMPLES = {
    "sample1_equipment": {
        "title": "Sample 1 — Equipment-focused anomaly",
        "description": "Equipment 관련 이상 상황 (특정 장비에 이상 Lot 집중 + Alarm 이력)",
        "builder": build_sample1_equipment,
    },
    "sample2_measurement": {
        "title": "Sample 2 — Measurement-focused anomaly",
        "description": "Measurement 관련 이상 상황 (여러 장비 동시 이상 + 계측 이력)",
        "builder": build_sample2_measurement,
    },
    "sample3_recipe": {
        "title": "Sample 3 — Process/Recipe-focused anomaly",
        "description": "Recipe/Process 관련 이상 상황 (동일 Recipe 공유 + 변경 이력)",
        "builder": build_sample3_recipe,
    },
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("EDUCATIONAL MOCK DATA - NOT REAL FAB DATA")
    for sample_id, spec in SAMPLES.items():
        measurements, events, abnormal_lots = spec["builder"]()
        sample_dir = OUT_DIR / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        measurements.to_csv(sample_dir / "measurements.csv", index=False)
        events.to_csv(sample_dir / "events.csv", index=False)
        print(f"[{sample_id}] {len(measurements)} rows, abnormal lots: {abnormal_lots}")


if __name__ == "__main__":
    main()
