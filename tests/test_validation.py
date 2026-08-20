from src.validation.data_validation import run_validation


def test_role_inference_finds_required_roles(role_map):
    missing = role_map.missing_required_roles()
    assert missing == [], f"필수 역할 컬럼을 찾지 못했습니다: {missing}"


def test_clean_mock_data_has_high_confidence(raw_df, role_map):
    report = run_validation(raw_df, role_map)
    assert report.row_count == len(raw_df)
    high_severity = [i for i in report.issues if i.severity == "High"]
    assert high_severity == [], f"클린한 mock 데이터에서 High 이슈가 발견됨: {high_severity}"
    assert report.overall_confidence == "High"


def test_validation_detects_missing_values(raw_df, role_map):
    corrupted = raw_df.copy()
    corrupted.loc[0:5, role_map.measurement_value] = None

    report = run_validation(corrupted, role_map)
    missing_issues = [i for i in report.issues if i.issue_type == "missing_value"
                       and i.column == role_map.measurement_value]
    assert len(missing_issues) == 1
    assert missing_issues[0].count == 6


def test_validation_detects_impossible_values(raw_df, role_map):
    corrupted = raw_df.copy()
    corrupted.loc[0, role_map.measurement_value] = -5.0

    report = run_validation(corrupted, role_map)
    impossible = [i for i in report.issues if i.issue_type == "impossible_value"]
    assert len(impossible) == 1
    assert impossible[0].count == 1
