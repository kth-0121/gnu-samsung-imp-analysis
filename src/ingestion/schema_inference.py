"""
업로드된 데이터의 컬럼 구조를 자동으로 해석한다.

- classify_column_types: 각 컬럼을 numeric / categorical / datetime / text 로 분류
- infer_roles: config/column_roles.yaml의 키워드를 이용해 컬럼명을
  lot_id / equipment_id / recipe_id / timestamp / measurement_value 등의
  '역할'에 매핑 (신뢰도와 함께). 특정 컬럼명을 코드에 하드코딩하지 않는다.

자동 추론은 어디까지나 '제안'이며, UI에서 사용자가 최종 확인/수정할 수 있어야 한다.
"""

from __future__ import annotations

import re
import pandas as pd

from src.config import load_column_roles
from src.schemas.models import ColumnRoleMap


def classify_column_types(df: pd.DataFrame) -> dict:
    """컬럼명 -> 'numeric' | 'categorical' | 'datetime' | 'text'"""
    result = {}
    n = len(df)
    for col in df.columns:
        series = df[col]

        if pd.api.types.is_numeric_dtype(series):
            result[col] = "numeric"
            continue

        # datetime 파싱 시도: 성공 비율이 높으면 datetime으로 분류
        non_null = series.dropna()
        if len(non_null) > 0:
            parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
            success_ratio = parsed.notna().mean()
        else:
            success_ratio = 0.0

        if success_ratio >= 0.8:
            result[col] = "datetime"
            continue

        nunique = series.nunique(dropna=True)
        ratio = nunique / n if n else 0
        if ratio < 0.5 or nunique <= 50:
            result[col] = "categorical"
        else:
            result[col] = "text"

    return result


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def infer_roles(df: pd.DataFrame, column_types: dict | None = None) -> ColumnRoleMap:
    """컬럼명 키워드 매칭으로 역할을 추론한다. 완전 일치가 아니면 신뢰도를 낮춘다."""
    if column_types is None:
        column_types = classify_column_types(df)

    role_defs = load_column_roles()
    role_map = ColumnRoleMap()
    normalized_cols = {col: _normalize(col) for col in df.columns}

    for role, spec in role_defs.items():
        keywords = spec.get("keywords", [])
        expected_type = spec.get("expected_type")

        best_col = None
        best_confidence = None

        for col, norm in normalized_cols.items():
            if expected_type and column_types.get(col) != expected_type:
                # 타입이 안 맞으면 후보에서 제외 (예: measurement_value인데 text인 컬럼)
                continue

            for kw in keywords:
                kw_norm = _normalize(kw)
                if norm == kw_norm:
                    best_col, best_confidence = col, "High"
                    break
                if kw_norm in norm or norm in kw_norm:
                    if best_confidence != "High":
                        best_col, best_confidence = col, "Medium"
            if best_confidence == "High":
                break

        if best_col:
            setattr(role_map, role, best_col)
            role_map.confidence[role] = best_confidence
        else:
            role_map.confidence[role] = "Unmatched"

    return role_map
