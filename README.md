# IMP Quality Response & Root Cause Analysis System (MVP)

IMP(이온주입) 공정 Rs 산포 이상 발생 시, RTP 투입 전 영향 범위를 식별하고
데이터 기반으로 Hold/조치 여부를 판단할 수 있도록 지원하는 의사결정 지원 시스템.

GNU IC-PBL 삼성전자 DS부문 Foundry사업부 Business Challenge 교육 목적 프로젝트.

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run ui/app.py
```

사이드바에서 CSV/Excel 측정 데이터를 업로드하거나(+ 선택적으로 Event Log 업로드),
아래 3개 교육용 Sample Dataset 중 하나를 선택해 바로 체험할 수 있다
(모두 EDUCATIONAL MOCK DATA — NOT REAL FAB DATA).

| Sample | 설명 |
|---|---|
| Sample 1 — Equipment-focused anomaly | 특정 장비(EQ-02)에 이상 Lot 집중 + 그 장비의 Alarm 이력 |
| Sample 2 — Measurement-focused anomaly | 장비 3대에서 동시에 이상 발생(장비 집중 없음) + 계측 이력, Recipe 변경 없음 |
| Sample 3 — Process/Recipe-focused anomaly | 서로 다른 두 장비에서 이상 발생하지만 동일 Recipe 공유 + Recipe 변경 이력 |

세 Sample은 `data/mock/generate_sample_datasets.py`로 생성되며, 데이터 어디에도
"이 Lot의 원인은 장비다" 같은 정답 라벨을 넣지 않는다 — 각 Sample은 이상 Lot의
장비/Recipe 분포 패턴과 Event Log 이력만 다르게 구성되어 있고, 어떤 원인 후보가
1순위인지는 `src/analysis/root_cause.py`가 그 패턴을 관찰해서 매번 계산한다.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 배포 (Streamlit Community Cloud)

이 앱은 상시 실행 서버 + WebSocket이 필요한 Streamlit 앱이라 Vercel(서버리스) 배포에는
맞지 않는다. 대신 Streamlit 전용 무료 호스팅인 Streamlit Community Cloud를 사용한다.

1. https://share.streamlit.io 접속 후 GitHub 계정으로 로그인
2. "New app" → 이 저장소(`kth-0121/gnu-samsung-imp-analysis`) 선택, 브랜치 `main`
3. Main file path에 `ui/app.py` 입력
4. Deploy — `requirements.txt`가 자동으로 설치된다 (테스트 전용 `pytest`는
   `requirements-dev.txt`에 분리되어 있어 배포 환경에는 설치되지 않는다)

## 현재 구현 범위

- 데이터 업로드 + 컬럼 자동 타입/역할 인식 (컬럼명 하드코딩 없음, `config/column_roles.yaml`로 조정)
- Data Validation (결측/중복/이상값/Timestamp/Lot·장비·Recipe 누락)
- Rs Trend 시각화 (Lot/장비/Recipe 기준)
- Anomaly Detection (장비별 baseline 대비 Z-score + IQR, 단일 이상치 vs 지속적 Shift 구분,
  self-masking 방지를 위해 이상 판정된 값은 이후 baseline에서 제외)
- Impact Scope Analysis (동일 장비/Recipe/시간 인접성 기준 4단계 분류 + 근거)
- **Root Cause Candidate Analysis / Evidence / Priority Ranking** (`src/analysis/root_cause.py`)
  - Event Log(장비 Alarm/PM, 계측 Event/Calibration, Recipe/Process 변경 이력)와 Impact Scope
    결과에서 Evidence 신호(장비/Recipe 집중도, 시간 인접 이력 등)를 계산하고, `config/weights.yaml`의
    가중치로 Equipment / Measurement / Process·Recipe / Material·Lot / Other 5개 카테고리 점수를 산출한다
  - 점수가 가장 높아도 "원인 확정"이 아니라 "우선 검증 대상"으로만 표시한다 (Recommendation)
- Hold Recommendation, Immediate/Follow-up/Preventive Action Recommendation
  (Follow-up/Preventive는 Root Cause Priority 상위 후보를 참조해 구체화됨)
- Final Report Generator (Markdown, Root Cause Priority 포함)
- 3개 교육용 Sample Dataset (Equipment/Measurement/Process-Recipe) — 동일 파이프라인이 서로
  다른 상황에서 서로 다른 Priority를 산출하는지 `tests/test_root_cause.py`로 검증

## 다음 단계 (미구현)

- Material/Lot 카테고리의 실질적 Evidence화 — 현재는 관련 데이터 컬럼이 없어 항상 낮은
  baseline 점수만 부여 (Wafer/소재 입고 이력 등이 확보되면 확장 필요)
- LLM 연동 자연어 요약/보고서 문장 생성 (섹션 20, Could 단계) — 구조화 결과
  (`AnalysisResult.to_dict()`)는 이미 준비되어 있음
- Priority Ranking 가중치 조정 UI (현재는 `config/weights.yaml` 직접 수정)

## 설계 원칙

- `src/analysis`, `src/recommendation`, `src/reporting`는 UI에 의존하지 않는 순수 로직이며
  `ui/app.py`는 이 결과를 표시만 한다.
- 모든 임계치/가중치는 `config/*.yaml`에 있으며 하드코딩하지 않는다 (Root Cause 가중치는
  `config/weights.yaml` — 임의 설정값임을 코드/UI 양쪽에 명시).
- 모든 Hold/조치/원인 후보 권고는 "Recommendation"이며 최종 판단을 대신하지 않는다.
- Root Cause 결과는 Observation → Evidence(수치) → Hypothesis(카테고리 점수) → Verification(권고
  검증 절차) 구조를 유지하며, 어떤 모듈도 "root_cause = 'Equipment'" 식으로 원인을 직접
  대입하지 않는다 — 항상 데이터에서 계산한다.
- `src/schemas/models.py`가 정의하는 구조화 결과(`AnalysisResult.to_dict()`)가 LLM/외부
  연동의 유일한 입력 계약이다 — LLM이 원인을 새로 만들어내지 않도록 한다.
- `AnalysisResult.data_source`에 `mock:<sample_id>` / `upload`가 기록되어, 구조화 결과만
  따로 내보내도 mock 데이터 기반인지 알 수 있다.
