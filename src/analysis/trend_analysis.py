"""
Lot 단위 요약(Rs 평균/산포)과 시간/장비/Recipe 기준 Trend를 생성한다.

핵심: 원본 데이터가 wafer/site 단위(측정 여러 건)로 들어온다고 가정하고,
Lot 내 산포(표준편차)를 직접 계산한다. 특정 'RS_STD' 같은 컬럼이 미리 있다고
가정하지 않는다 - measurement_value 역할 컬럼 하나만 있으면 동작한다.
"""

from __future__ import annotations

import pandas as pd

from src.schemas.models import ColumnRoleMap


def build_lot_summary(df: pd.DataFrame, role_map: ColumnRoleMap) -> pd.DataFrame:
    """
    Lot 단위로 groupby 하여 다음 컬럼을 가진 DataFrame을 반환한다.
      lot_id, equipment_id, recipe_id, timestamp, rs_mean, rs_std, n_measurements
    equipment_id/recipe_id/timestamp가 Lot 내에서 여러 값이면 최빈값(mode)을 사용하고
    불일치 개수를 별도로 표시한다 (완전한 검증은 validation 단계 책임).
    """
    missing = role_map.missing_required_roles()
    if missing:
        raise ValueError(f"Trend 분석에 필요한 역할 컬럼이 없습니다: {missing}")

    work = df.copy()
    work = work.dropna(subset=[role_map.lot_id, role_map.measurement_value])

    if role_map.timestamp:
        work["_ts"] = pd.to_datetime(work[role_map.timestamp], errors="coerce", format="mixed")
    else:
        work["_ts"] = pd.NaT

    def _mode_or_none(s: pd.Series):
        s = s.dropna()
        if s.empty:
            return None
        return s.mode().iloc[0]

    records = []
    for lot_id, g in work.groupby(role_map.lot_id):
        rs = g[role_map.measurement_value]
        records.append({
            "lot_id": lot_id,
            "equipment_id": _mode_or_none(g[role_map.equipment_id]) if role_map.equipment_id else None,
            "recipe_id": _mode_or_none(g[role_map.recipe_id]) if role_map.recipe_id else None,
            "timestamp": g["_ts"].min() if g["_ts"].notna().any() else pd.NaT,
            "rs_mean": rs.mean(),
            "rs_std": rs.std(ddof=1) if len(rs) > 1 else 0.0,
            "n_measurements": len(rs),
        })

    lot_summary = pd.DataFrame.from_records(records)
    lot_summary = lot_summary.sort_values(
        by="timestamp", na_position="last", kind="stable"
    ).reset_index(drop=True)
    return lot_summary


def trend_by_equipment(lot_summary: pd.DataFrame) -> pd.DataFrame:
    if "equipment_id" not in lot_summary or lot_summary["equipment_id"].isna().all():
        return pd.DataFrame(columns=["equipment_id", "rs_mean_avg", "rs_std_avg", "n_lots"])
    grouped = lot_summary.groupby("equipment_id").agg(
        rs_mean_avg=("rs_mean", "mean"),
        rs_std_avg=("rs_std", "mean"),
        n_lots=("lot_id", "count"),
    ).reset_index()
    return grouped


def trend_by_recipe(lot_summary: pd.DataFrame) -> pd.DataFrame:
    if "recipe_id" not in lot_summary or lot_summary["recipe_id"].isna().all():
        return pd.DataFrame(columns=["recipe_id", "rs_mean_avg", "rs_std_avg", "n_lots"])
    grouped = lot_summary.groupby("recipe_id").agg(
        rs_mean_avg=("rs_mean", "mean"),
        rs_std_avg=("rs_std", "mean"),
        n_lots=("lot_id", "count"),
    ).reset_index()
    return grouped
