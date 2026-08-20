"""
분석 파이프라인의 모든 단계가 주고받는 구조화 데이터 계약(schema)을 정의한다.

중요: LLM/UI는 이 모듈이 정의하는 구조 이상의 정보를 스스로 만들어내면 안 된다.
      (섹션 20 "AI/LLM 사용 원칙" 참고)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Ingestion / Schema Inference
# ---------------------------------------------------------------------------

@dataclass
class ColumnRoleMap:
    """컬럼명 -> 개념적 역할 매핑. 값이 None이면 해당 역할을 가진 컬럼을 찾지 못한 것."""

    lot_id: Optional[str] = None
    wafer_id: Optional[str] = None
    site_id: Optional[str] = None
    equipment_id: Optional[str] = None
    recipe_id: Optional[str] = None
    timestamp: Optional[str] = None
    measurement_value: Optional[str] = None

    # 역할별 자동 매칭 신뢰도: 'High' | 'Medium' | 'Low' | 'Unmatched'
    confidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def missing_required_roles(self) -> list:
        """분석에 최소한 필요한 역할 중 비어있는 것을 반환."""
        required = ["lot_id", "equipment_id", "measurement_value"]
        return [r for r in required if getattr(self, r) is None]


# ---------------------------------------------------------------------------
# Data Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    issue_type: str          # 예: 'missing_value', 'duplicate_row', 'impossible_value' ...
    column: Optional[str]
    severity: str             # 'High' | 'Medium' | 'Low'
    count: int
    detail: str               # 사람이 읽을 수 있는 설명


@dataclass
class ValidationReport:
    row_count: int
    issues: list = field(default_factory=list)   # list[ValidationIssue]
    overall_confidence: str = "High"              # 'High' | 'Medium' | 'Low'
    confidence_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "issues": [asdict(i) for i in self.issues],
            "overall_confidence": self.overall_confidence,
            "confidence_reason": self.confidence_reason,
        }


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------

@dataclass
class AnomalyPoint:
    lot_id: str
    timestamp: Optional[str]
    metric_name: str          # 예: 'rs_std' (산포), 'rs_mean'
    value: float
    baseline_mean: float
    baseline_std: float
    z_score: Optional[float]
    iqr_flag: bool
    control_limit_flag: bool
    is_point_anomaly: bool    # 단일 이상점
    is_shift_member: bool     # 연속 이상(지속적 변화)의 일부인지


@dataclass
class AnomalyResult:
    metric_name: str
    points: list = field(default_factory=list)     # list[AnomalyPoint], 전체 lot 아님. 이상 flag된 것만
    shift_lots: list = field(default_factory=list)  # 연속 이상으로 판정된 lot_id 목록 (시간순)
    anomaly_start: Optional[str] = None
    method_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "points": [asdict(p) for p in self.points],
            "shift_lots": self.shift_lots,
            "anomaly_start": self.anomaly_start,
            "method_notes": self.method_notes,
        }


# ---------------------------------------------------------------------------
# Impact Scope / Hold Recommendation
# ---------------------------------------------------------------------------

@dataclass
class LotClassification:
    lot_id: str
    category: str             # 'Confirmed Abnormal' | 'High Risk' | 'Additional Check' | 'Normal'
    reasons: list              # list[str], 근거 문장들 (Observation -> Evidence 형태)
    equipment_id: Optional[str]
    recipe_id: Optional[str]
    timestamp: Optional[str]


@dataclass
class HoldRecommendation:
    lot_id: str
    recommendation: str        # 'HOLD RECOMMENDED' | 'ADDITIONAL CHECK' | 'NORMAL'
    reasons: list


@dataclass
class ActionItem:
    stage: str                 # 'Immediate' | 'Follow-up' | 'Preventive'
    action: str
    rationale: str
    evidence_ref: list = field(default_factory=list)   # 관련 lot_id 등


# ---------------------------------------------------------------------------
# Root Cause Candidate Analysis / Evidence / Priority Ranking
# ---------------------------------------------------------------------------

@dataclass
class EvidenceSignal:
    """원인 후보 점수를 구성하는 개별 근거 신호. 값과 설명을 함께 남겨 '왜 이 점수인지' 추적 가능하게 한다."""
    name: str
    value: float           # 0.0 ~ 1.0로 정규화된 신호 값
    weight: float           # config/weights.yaml에서 온 가중치 (임의 설정값, 문서화되어 있음)
    description: str        # 사람이 읽을 수 있는 근거 설명 (수치 포함)


@dataclass
class CandidateCause:
    category: str                # 'Equipment' | 'Measurement' | 'Process/Recipe' | 'Material/Lot' | 'Other'
    score: float                  # 0~100. Evidence 신호의 가중합 (섹션16 - 임의 가중치, config에 명시)
    confidence: str                # 'High' | 'Medium' | 'Low'
    verification_priority: int     # 1 = 가장 먼저 검증할 후보
    signals: list                  # list[EvidenceSignal]
    association_summary: str       # signals 설명을 이어붙인 요약 문장
    recommended_verification: str  # 이 후보를 검증하기 위해 무엇을 확인해야 하는지

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "score": round(self.score, 1),
            "confidence": self.confidence,
            "verification_priority": self.verification_priority,
            "signals": [asdict(s) for s in self.signals],
            "association_summary": self.association_summary,
            "recommended_verification": self.recommended_verification,
        }


# ---------------------------------------------------------------------------
# Top-level Analysis Result (섹션 20의 JSON 구조에 대응)
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    anomaly_start: Optional[str]
    affected_lots: list                  # list[LotClassification]
    equipment_association: dict          # equipment_id -> 관련 lot_id 목록/설명
    trend_changes: dict                  # metric별 AnomalyResult.to_dict()
    candidate_causes: list               # list[CandidateCause], Priority 내림차순 정렬
    evidence: list                       # list[str], candidate_causes의 signals를 평탄화한 근거 문장 모음
    recommended_actions: list            # list[ActionItem]
    validation: ValidationReport
    verification_plan: list = field(default_factory=list)  # list[str], Priority 순서의 검증 절차
    data_source: str = "unknown"         # 'mock:<sample_id>' | 'upload' — mock/실제 데이터 구분용
    notes: list = field(default_factory=list)   # 불확실성/제약 사항 명시

    def to_dict(self) -> dict:
        return {
            "anomaly_start": self.anomaly_start,
            "affected_lots": [asdict(l) for l in self.affected_lots],
            "equipment_association": self.equipment_association,
            "trend_changes": self.trend_changes,
            "candidate_causes": [c.to_dict() for c in self.candidate_causes],
            "evidence": self.evidence,
            "recommended_actions": [asdict(a) for a in self.recommended_actions],
            "validation": self.validation.to_dict(),
            "verification_plan": self.verification_plan,
            "data_source": self.data_source,
            "notes": self.notes,
        }
