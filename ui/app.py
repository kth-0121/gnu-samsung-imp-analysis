"""
IMP Quality Response & Root Cause Analysis System - Streamlit MVP UI

정보 표시 순서는 "무엇이 문제인가"보다 "지금 무엇을 해야 하는가"를 우선한다 (섹션 19).
    1. 현재 상태
    2. 영향 가능 Lot (Hold Recommendation)
    3. 이상 Trend
    4. 추천 검증 순서
    5~7. 즉시조치 / 후속조치 / 재발방지
    8. 상세 데이터
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.ingestion.loader import load_data, DataLoadError
from src.ingestion.schema_inference import classify_column_types, infer_roles
from src.validation.data_validation import run_validation
from src.analysis.trend_analysis import build_lot_summary, trend_by_equipment, trend_by_recipe
from src.analysis.anomaly_detection import detect_anomalies
from src.analysis.impact_scope import classify_impact
from src.recommendation.hold_recommendation import build_hold_recommendations
from src.recommendation.action_recommendation import build_action_recommendations
from src.reporting.report_builder import build_analysis_result, render_report_markdown
from src.schemas.models import ColumnRoleMap
from src.config import load_thresholds

MOCK_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "mock" / "mock_imp_rs_data.csv"

st.set_page_config(page_title="IMP Rs 이상 대응 지원 시스템", layout="wide")

CATEGORY_COLOR = {
    "Confirmed Abnormal": "#e03131",
    "High Risk": "#f08c00",
    "Additional Check": "#1971c2",
    "Normal": "#868e96",
}


def _role_override_ui(df: pd.DataFrame, inferred: ColumnRoleMap) -> ColumnRoleMap:
    st.caption(
        "컬럼명을 자동으로 해석한 결과입니다. 실제 데이터 컬럼명이 다르면 아래에서 직접 지정할 수 있습니다."
    )
    cols = list(df.columns)
    options = ["(선택 안 함)"] + cols
    role_labels = {
        "lot_id": "Lot ID *", "equipment_id": "Equipment ID *", "measurement_value": "측정값(Rs) *",
        "recipe_id": "Recipe ID", "timestamp": "Timestamp", "wafer_id": "Wafer ID", "site_id": "Site ID",
    }
    result = ColumnRoleMap()
    c1, c2, c3, c4 = st.columns(4)
    ui_cols = [c1, c2, c3, c4]
    for i, (role, label) in enumerate(role_labels.items()):
        current = getattr(inferred, role)
        default_idx = options.index(current) if current in options else 0
        confidence = inferred.confidence.get(role, "Unmatched")
        with ui_cols[i % 4]:
            chosen = st.selectbox(f"{label}  ({confidence})", options, index=default_idx, key=f"role_{role}")
        setattr(result, role, None if chosen == "(선택 안 함)" else chosen)
        result.confidence[role] = confidence
    return result


def _validation_banner(report):
    color = {"High": "success", "Medium": "warning", "Low": "error"}[report.overall_confidence]
    msg = f"데이터 품질 신뢰도: **{report.overall_confidence}** - {report.confidence_reason}"
    getattr(st, color)(msg)
    with st.expander(f"Validation 상세 ({len(report.issues)}건 이슈)"):
        if not report.issues:
            st.write("발견된 이슈가 없습니다.")
        else:
            st.dataframe(pd.DataFrame([{
                "심각도": i.severity, "유형": i.issue_type, "컬럼": i.column,
                "건수": i.count, "설명": i.detail,
            } for i in report.issues]), width='stretch', hide_index=True)


def main():
    st.title("IMP Rs 산포 이상 대응 · 근본원인 분석 지원 시스템")
    st.caption("본 도구는 의사결정 '지원' 시스템입니다. 최종 Hold/투입/원인 확정 판단은 담당 엔지니어가 수행합니다.")

    with st.sidebar:
        st.header("데이터 입력")
        uploaded = st.file_uploader("CSV 또는 Excel 파일 업로드", type=["csv", "xlsx", "xls"])
        use_mock = st.button("샘플(Mock) 데이터로 체험하기", width='stretch')
        st.divider()
        st.caption("Mock 데이터는 EDUCATIONAL MOCK DATA이며 실제 Fab 데이터가 아닙니다.")

    if use_mock:
        st.session_state["_use_mock"] = True
    if uploaded is not None:
        st.session_state["_use_mock"] = False
        st.session_state["_uploaded"] = uploaded

    if not st.session_state.get("_use_mock") and "_uploaded" not in st.session_state:
        st.info("왼쪽에서 데이터를 업로드하거나 샘플 데이터를 불러오세요.")
        return

    try:
        if st.session_state.get("_use_mock"):
            st.warning("EDUCATIONAL MOCK DATA — NOT REAL FAB DATA (실제 Fab 데이터가 아닌 교육용 예시입니다)")
            df = load_data(str(MOCK_DATA_PATH))
        else:
            df = load_data(st.session_state["_uploaded"])
    except DataLoadError as e:
        st.error(str(e))
        return

    # ---- 데이터 구조 확인 ----
    st.header("데이터 구조 확인")
    col_types = classify_column_types(df)
    inferred_roles = infer_roles(df, col_types)
    with st.expander("컬럼 목록 / 타입 / 역할 매핑", expanded=False):
        st.dataframe(pd.DataFrame([
            {"컬럼명": c, "추정 타입": col_types[c], "결측": int(df[c].isna().sum()),
             "고유값 수": int(df[c].nunique())}
            for c in df.columns
        ]), width='stretch', hide_index=True)
    role_map = _role_override_ui(df, inferred_roles)

    missing = role_map.missing_required_roles()
    if missing:
        st.error(f"필수 컬럼 역할이 지정되지 않았습니다: {missing}. 위에서 직접 지정해 주세요.")
        return

    # ---- Data Validation ----
    st.header("Data Validation")
    validation = run_validation(df, role_map)
    _validation_banner(validation)

    thresholds = load_thresholds()
    try:
        lot_summary = build_lot_summary(df, role_map)
    except Exception as e:
        st.error(f"Lot 단위 집계 중 오류가 발생했습니다: {e}")
        return

    if len(lot_summary) < 4:
        st.warning("Lot 수가 너무 적어(4개 미만) 통계적 이상탐지를 수행하기 어렵습니다. 참고용으로만 활용하세요.")

    anomaly_results = {
        "rs_std": detect_anomalies(lot_summary, "rs_std", thresholds),
        "rs_mean": detect_anomalies(lot_summary, "rs_mean", thresholds),
    }
    classifications = classify_impact(lot_summary, anomaly_results, thresholds)
    hold_recs = build_hold_recommendations(classifications)
    actions = build_action_recommendations(hold_recs, classifications, validation)
    analysis_result = build_analysis_result(
        lot_summary, classifications, anomaly_results, hold_recs, actions, validation
    )

    # ---- 1. 현재 상태 ----
    st.header("1. 현재 상태")
    shift_std = anomaly_results["rs_std"].shift_lots
    shift_mean = anomaly_results["rs_mean"].shift_lots
    m1, m2, m3 = st.columns(3)
    m1.metric("분석 대상 Lot 수", len(lot_summary))
    m2.metric("Rs 산포(rs_std) 이상 Lot", len(shift_std))
    m3.metric("Rs 평균(rs_mean) 이상 Lot", len(shift_mean))
    if shift_std or shift_mean:
        st.error(
            f"이상 발생(추정) 시점: {analysis_result.anomaly_start} — "
            f"Rs 산포 지속 이상 Lot: {shift_std or '없음'} / Rs 평균 지속 이상 Lot: {shift_mean or '없음'}"
        )
    else:
        st.success("현재 기준으로 지속적인(Shift) Rs 이상은 발견되지 않았습니다. (단일 이상치는 아래 Trend에서 확인)")

    # ---- 2. 영향 가능 Lot (Hold Recommendation) ----
    st.header("2. 영향 가능 Lot — Hold Recommendation")
    hold_df = pd.DataFrame([{
        "Lot ID": r.lot_id, "권고": r.recommendation, "근거": " / ".join(r.reasons),
    } for r in hold_recs])
    cat_by_lot = {c.lot_id: c.category for c in classifications}
    hold_df["분류"] = hold_df["Lot ID"].map(cat_by_lot)
    hold_df = hold_df.sort_values(
        by="분류", key=lambda s: s.map({"Confirmed Abnormal": 0, "High Risk": 1, "Additional Check": 2, "Normal": 3})
    )

    hold_only = hold_df[hold_df["분류"].isin(["Confirmed Abnormal", "High Risk"])]
    check_only = hold_df[hold_df["분류"] == "Additional Check"]
    normal_only = hold_df[hold_df["분류"] == "Normal"]

    st.subheader(f"🔴 HOLD RECOMMENDED ({len(hold_only)}건)")
    st.dataframe(hold_only[["Lot ID", "분류", "근거"]], width='stretch', hide_index=True)
    st.subheader(f"🔵 ADDITIONAL CHECK ({len(check_only)}건)")
    st.dataframe(check_only[["Lot ID", "분류", "근거"]], width='stretch', hide_index=True)
    with st.expander(f"⚪ NORMAL ({len(normal_only)}건)"):
        st.dataframe(normal_only[["Lot ID", "분류", "근거"]], width='stretch', hide_index=True)

    # ---- 3. 이상 Trend ----
    st.header("3. Rs Trend")
    plot_df = lot_summary.copy()
    plot_df["분류"] = plot_df["lot_id"].map(cat_by_lot)

    # X축은 "공정 진행 시간(초)" 기준. 데이터에 별도의 초 단위 진행시간 컬럼은 없으므로
    # (LOT_ID, TIMESTAMP, RS_OHM_SQ 등만 존재) 이미 파싱되어 있는 timestamp를 이용해
    # 가장 이른 Lot 시각 대비 경과 초를 계산한다 - 달력 날짜가 아니라 경과시간이다.
    # timestamp가 전혀 없는 데이터일 때만 기존 순번(order) 방식으로 폴백한다.
    has_timestamp = plot_df["timestamp"].notna().any()
    if has_timestamp:
        plot_df = plot_df.sort_values("timestamp", na_position="last", kind="stable")
        start_time = plot_df["timestamp"].min()
        plot_df["elapsed_sec"] = (plot_df["timestamp"] - start_time).dt.total_seconds()
        x_col, x_label = "elapsed_sec", "진행시간 (초)"
    else:
        plot_df["order"] = range(len(plot_df))
        x_col, x_label = "order", "Lot 순서"

    t1, t2 = st.columns(2)
    with t1:
        fig = px.scatter(
            plot_df, x=x_col, y="rs_std", color="분류", hover_data=["lot_id", x_col],
            color_discrete_map=CATEGORY_COLOR, title="Lot별 Rs 산포(rs_std) 추이",
            labels={x_col: x_label, "rs_std": "Rs 산포 (rs_std)"},
        )
        fig.add_hline(y=plot_df["rs_std"].median(), line_dash="dot", annotation_text="전체 median")
        if has_timestamp:
            fig.update_xaxes(ticksuffix="초")
        st.plotly_chart(fig, width='stretch')
    with t2:
        fig2 = px.scatter(
            plot_df, x=x_col, y="rs_mean", color="분류", hover_data=["lot_id", x_col],
            color_discrete_map=CATEGORY_COLOR, title="Lot별 Rs 평균(rs_mean) 추이",
            labels={x_col: x_label, "rs_mean": "Rs 평균 (rs_mean)"},
        )
        if has_timestamp:
            fig2.update_xaxes(ticksuffix="초")
        st.plotly_chart(fig2, width='stretch')

    t3, t4 = st.columns(2)
    with t3:
        if plot_df["equipment_id"].notna().any():
            fig3 = px.box(plot_df, x="equipment_id", y="rs_std", points="all", color="equipment_id",
                           title="장비별 Rs 산포 분포")
            st.plotly_chart(fig3, width='stretch')
    with t4:
        if plot_df["recipe_id"].notna().any():
            fig4 = px.box(plot_df, x="recipe_id", y="rs_std", points="all", color="recipe_id",
                           title="Recipe별 Rs 산포 분포")
            st.plotly_chart(fig4, width='stretch')

    # ---- 4. 추천 검증 순서 (섹션 13 - 데이터에 무관하게 적용 가능한 절차) ----
    st.header("4. 추천 검증 순서")
    for i, step in enumerate([
        "계측 이상 여부 확인 (재계측으로 계측 오차 배제)",
        "이상 발생 시점 확인 (Trend 상 Shift 시작 시점)",
        "동일 장비 집중 여부 확인 (Impact Scope 결과)",
        "장비 Alarm / PM / Calibration 이력 확인 (설비팀 협의)",
        "공정 조건 및 Recipe 변경 이력 확인",
        "필요 시 유관부서(설비팀/수율팀) 추가 확인 요청",
    ], start=1):
        st.write(f"{i}. {step}")

    # ---- 5~7. Action Recommendation ----
    st.header("5~7. 대응 방안")
    for stage, title in [("Immediate", "🚨 5. 즉시조치 (RTP 투입 전)"),
                          ("Follow-up", "🔧 6. 후속조치 (원인 확인 후)"),
                          ("Preventive", "🛡️ 7. 재발방지")]:
        st.subheader(title)
        stage_actions = [a for a in actions if a.stage == stage]
        for a in stage_actions:
            with st.container(border=True):
                st.markdown(f"**{a.action}**")
                st.caption(f"근거: {a.rationale}")
                if a.evidence_ref:
                    st.caption(f"관련 Lot/장비: {', '.join(map(str, a.evidence_ref))}")

    # ---- 최종 보고서 ----
    st.header("최종 보고서")
    report_md = render_report_markdown(analysis_result)
    with st.expander("보고서 미리보기", expanded=False):
        st.markdown(report_md)
    st.download_button("보고서 다운로드 (Markdown)", report_md, file_name="imp_rs_report.md")

    # ---- 8. 상세 데이터 ----
    st.header("8. 상세 데이터")
    with st.expander("Lot 요약 테이블"):
        st.dataframe(lot_summary, width='stretch', hide_index=True)
    with st.expander("장비별 / Recipe별 집계"):
        st.write("장비별")
        st.dataframe(trend_by_equipment(lot_summary), width='stretch', hide_index=True)
        st.write("Recipe별")
        st.dataframe(trend_by_recipe(lot_summary), width='stretch', hide_index=True)
    with st.expander("원본 데이터"):
        st.dataframe(df, width='stretch', hide_index=True)
    with st.expander("구조화 분석 결과 (JSON) — LLM/외부 연동용"):
        st.json(analysis_result.to_dict())


if __name__ == "__main__":
    main()
