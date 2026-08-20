"""
장비 Alarm/PM, 계측 Event/Calibration, Recipe/Process 변경 이력을 담는
보조 Event Log 로더.

측정 데이터(main measurement table)는 컬럼명에 의존하지 않도록 schema_inference로
역할을 추론하지만, Event Log는 Root Cause Evidence 생성을 위해 새로 도입한
전용 입력이라 아래의 고정된 컬럼 계약을 사용한다:

    EVENT_TIMESTAMP, EVENT_TYPE, EQUIPMENT_ID, RECIPE_ID, DESCRIPTION

EVENT_TYPE 값은 다음 중 하나를 기대한다:
    EQUIPMENT_ALARM, EQUIPMENT_PM,
    MEASUREMENT_EVENT, MEASUREMENT_CALIBRATION,
    RECIPE_CHANGE, PROCESS_PARAM_CHANGE

Event Log가 없거나 이 컬럼들이 없으면 None을 반환한다 - 이 경우 Root Cause
분석에서 이벤트 기반 Evidence만 비활성화되고 나머지 분석은 정상 동작한다
(하드 실패하지 않는다).
"""

from __future__ import annotations

import pandas as pd

from src.ingestion.loader import load_data, DataLoadError

EXPECTED_COLUMNS = ["EVENT_TIMESTAMP", "EVENT_TYPE", "EQUIPMENT_ID", "RECIPE_ID", "DESCRIPTION"]

EQUIPMENT_EVENT_TYPES = {"EQUIPMENT_ALARM", "EQUIPMENT_PM"}
MEASUREMENT_EVENT_TYPES = {"MEASUREMENT_EVENT", "MEASUREMENT_CALIBRATION"}
RECIPE_EVENT_TYPES = {"RECIPE_CHANGE", "PROCESS_PARAM_CHANGE"}


def load_events(file, filename: str | None = None) -> pd.DataFrame | None:
    if file is None:
        return None
    try:
        df = load_data(file, filename=filename)
    except DataLoadError:
        return None

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        return None

    df = df.copy()
    df["EVENT_TIMESTAMP"] = pd.to_datetime(df["EVENT_TIMESTAMP"], errors="coerce", format="mixed")
    df["EVENT_TYPE"] = df["EVENT_TYPE"].astype(str).str.strip().str.upper()
    return df
