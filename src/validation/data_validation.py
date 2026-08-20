"""
분석 전 데이터 품질 검사.

여기서 나오는 ValidationReport는 이후 모든 분석 단계의 신뢰도 판단 근거로 쓰인다.
품질 문제가 있으면 분석을 막지는 않되, UI에 명확히 경고를 표시한다 (섹션 7).
"""

from __future__ import annotations

import pandas as pd

from src.config import load_thresholds
from src.schemas.models import ValidationIssue, ValidationReport
from src.schemas.models import ColumnRoleMap


def run_validation(df: pd.DataFrame, role_map: ColumnRoleMap) -> ValidationReport:
    thresholds = load_thresholds()["validation"]
    max_missing_ratio_warn = thresholds["max_missing_ratio_warn"]

    issues: list[ValidationIssue] = []
    n = len(df)

    # 1. 결측치 (컬럼별)
    for col in df.columns:
        missing = df[col].isna().sum()
        if missing == 0:
            continue
        ratio = missing / n
        severity = "High" if ratio > max_missing_ratio_warn * 4 else (
            "Medium" if ratio > max_missing_ratio_warn else "Low"
        )
        issues.append(ValidationIssue(
            issue_type="missing_value",
            column=col,
            severity=severity,
            count=int(missing),
            detail=f"'{col}' 컬럼에 결측치 {missing}개 ({ratio:.1%})",
        ))

    # 2. 완전 중복 행
    dup_rows = df.duplicated().sum()
    if dup_rows > 0:
        issues.append(ValidationIssue(
            issue_type="duplicate_row",
            column=None,
            severity="Medium",
            count=int(dup_rows),
            detail=f"완전히 동일한 행이 {dup_rows}개 존재합니다.",
        ))

    # 3. LOT ID 관련 중복/누락
    if role_map.lot_id:
        lot_col = role_map.lot_id
        missing_lot = df[lot_col].isna().sum()
        if missing_lot > 0:
            issues.append(ValidationIssue(
                issue_type="missing_lot_id",
                column=lot_col,
                severity="High",
                count=int(missing_lot),
                detail=f"Lot ID가 없는 행이 {missing_lot}개 있습니다. 해당 행은 Lot 단위 분석에서 제외됩니다.",
            ))

        # 측정 단위 중복 체크: lot(+wafer+site)가 완전히 동일한데 measurement_value가 다르면
        # 중복 측정/입력 오류 가능성
        key_cols = [c for c in [role_map.lot_id, role_map.wafer_id, role_map.site_id] if c]
        if len(key_cols) >= 1:
            dup_keys = df.duplicated(subset=key_cols).sum()
            if dup_keys > 0:
                issues.append(ValidationIssue(
                    issue_type="duplicate_measurement_key",
                    column=",".join(key_cols),
                    severity="Medium",
                    count=int(dup_keys),
                    detail=f"{key_cols} 조합이 중복되는 행이 {dup_keys}개 있습니다 (중복 측정/입력 오류 가능).",
                ))
    else:
        issues.append(ValidationIssue(
            issue_type="missing_role",
            column=None,
            severity="High",
            count=n,
            detail="Lot ID로 추정되는 컬럼을 찾지 못했습니다. Lot 단위 분석이 불가능합니다.",
        ))

    # 4. 장비/Recipe 정보 누락
    if role_map.equipment_id:
        missing_eqp = df[role_map.equipment_id].isna().sum()
        if missing_eqp > 0:
            issues.append(ValidationIssue(
                issue_type="missing_equipment_info",
                column=role_map.equipment_id,
                severity="High",
                count=int(missing_eqp),
                detail=f"장비 정보가 없는 행이 {missing_eqp}개 있습니다. Impact Scope 분석 정확도가 낮아질 수 있습니다.",
            ))
    else:
        issues.append(ValidationIssue(
            issue_type="missing_role",
            column=None,
            severity="High",
            count=n,
            detail="장비(Equipment) ID로 추정되는 컬럼을 찾지 못했습니다. 영향범위 분석이 제한됩니다.",
        ))

    if role_map.recipe_id is None:
        issues.append(ValidationIssue(
            issue_type="missing_role",
            column=None,
            severity="Medium",
            count=0,
            detail="Recipe ID로 추정되는 컬럼을 찾지 못했습니다. Recipe 기준 영향범위 분석은 제한됩니다.",
        ))

    # 5. Timestamp 오류
    if role_map.timestamp:
        ts_col = role_map.timestamp
        parsed = pd.to_datetime(df[ts_col], errors="coerce", format="mixed")
        invalid_ts = parsed.isna().sum() - df[ts_col].isna().sum()
        if invalid_ts > 0:
            issues.append(ValidationIssue(
                issue_type="invalid_timestamp",
                column=ts_col,
                severity="Medium",
                count=int(invalid_ts),
                detail=f"'{ts_col}' 값 중 {invalid_ts}개를 날짜/시간으로 해석하지 못했습니다.",
            ))
    else:
        issues.append(ValidationIssue(
            issue_type="missing_role",
            column=None,
            severity="Medium",
            count=0,
            detail="시간(Timestamp) 컬럼을 찾지 못했습니다. 시간 인접성 기반 분석이 제한됩니다.",
        ))

    # 6. 측정값(예: Rs) 이상 값 (0 이하 등 물리적으로 불가능한 값)
    if role_map.measurement_value:
        mv_col = role_map.measurement_value
        impossible = df[mv_col].dropna()
        impossible_count = (impossible <= 0).sum()
        if impossible_count > 0:
            issues.append(ValidationIssue(
                issue_type="impossible_value",
                column=mv_col,
                severity="High",
                count=int(impossible_count),
                detail=f"'{mv_col}' 값이 0 이하로 물리적으로 불가능한 값이 {impossible_count}개 있습니다.",
            ))
    else:
        issues.append(ValidationIssue(
            issue_type="missing_role",
            column=None,
            severity="High",
            count=n,
            detail="측정값(예: Rs)으로 추정되는 숫자형 컬럼을 찾지 못했습니다. Trend/이상탐지가 불가능합니다.",
        ))

    overall_confidence, reason = _summarize_confidence(issues)

    return ValidationReport(
        row_count=n,
        issues=issues,
        overall_confidence=overall_confidence,
        confidence_reason=reason,
    )


def _summarize_confidence(issues: list[ValidationIssue]) -> tuple[str, str]:
    high_count = sum(1 for i in issues if i.severity == "High")
    medium_count = sum(1 for i in issues if i.severity == "Medium")

    if high_count > 0:
        return "Low", f"High 심각도 이슈 {high_count}건 발견 - 분석 결과의 신뢰도가 낮을 수 있습니다."
    if medium_count > 0:
        return "Medium", f"Medium 심각도 이슈 {medium_count}건 발견 - 일부 분석 정확도에 영향이 있을 수 있습니다."
    return "High", "치명적인 데이터 품질 이슈가 발견되지 않았습니다."
