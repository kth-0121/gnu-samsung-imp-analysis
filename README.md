# IMP Quality Response & Root Cause Analysis System (MVP)

IMP(이온주입) 공정 Rs 산포 이상 발생 시, RTP 투입 전 영향 범위를 식별하고
데이터 기반으로 Hold/조치 여부를 판단할 수 있도록 지원하는 의사결정 지원 시스템.

GNU IC-PBL 삼성전자 DS부문 Foundry사업부 Business Challenge 교육 목적 프로젝트.

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run ui/app.py
```

사이드바에서 CSV/Excel 파일을 업로드하거나 "샘플(Mock) 데이터로 체험하기" 버튼으로
`data/mock/mock_imp_rs_data.csv`(EDUCATIONAL MOCK DATA)를 바로 사용해볼 수 있다.

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

## 현재 구현 범위 (Must / MVP)

- 데이터 업로드 + 컬럼 자동 타입/역할 인식 (컬럼명 하드코딩 없음, `config/column_roles.yaml`로 조정)
- Data Validation (결측/중복/이상값/Timestamp/Lot·장비·Recipe 누락)
- Rs Trend 시각화 (Lot/장비/Recipe 기준)
- Anomaly Detection (장비별 baseline 대비 Z-score + IQR, 단일 이상치 vs 지속적 Shift 구분,
  self-masking 방지를 위해 이상 판정된 값은 이후 baseline에서 제외)
- Impact Scope Analysis (동일 장비/Recipe/시간 인접성 기준 4단계 분류 + 근거)
- Hold Recommendation, Immediate/Follow-up/Preventive Action Recommendation
- Final Report Generator (Markdown)

## 다음 단계 (Should, 미구현)

- Root Cause Candidate Analysis / Evidence Matrix (섹션 6, 14) — 실제 장비 Alarm/PM/계측
  이력 데이터가 확보된 이후 구현 예정. 근거 없는 원인 단정을 피하기 위해 현재는 UI에서
  "다음 단계 예정"으로 명시하고 있다.
- Priority Ranking (섹션 16)

## 설계 원칙

- `src/analysis`, `src/recommendation`, `src/reporting`는 UI에 의존하지 않는 순수 로직이며
  `ui/app.py`는 이 결과를 표시만 한다.
- 모든 임계치/가중치는 `config/*.yaml`에 있으며 하드코딩하지 않는다.
- 모든 Hold/조치 권고는 "Recommendation"이며 최종 판단을 대신하지 않는다.
- `src/schemas/models.py`가 정의하는 구조화 결과(`AnalysisResult.to_dict()`)가 LLM/외부
  연동의 유일한 입력 계약이다 — LLM이 원인을 새로 만들어내지 않도록 한다.
