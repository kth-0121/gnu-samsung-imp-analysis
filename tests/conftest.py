from pathlib import Path
import pandas as pd
import pytest

from src.ingestion.schema_inference import infer_roles
from src.analysis.trend_analysis import build_lot_summary
from src.config import load_thresholds

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mock_lots.csv"

# data/mock/generate_mock_data.py 실행 시 생성되는 값과 일치해야 한다.
EXPECTED_ABNORMAL_LOT_IDS = ["LOT-011", "LOT-014", "LOT-017"]


@pytest.fixture
def raw_df():
    return pd.read_csv(FIXTURE_PATH)


@pytest.fixture
def role_map(raw_df):
    return infer_roles(raw_df)


@pytest.fixture
def lot_summary(raw_df, role_map):
    return build_lot_summary(raw_df, role_map)


@pytest.fixture
def thresholds():
    return load_thresholds()
