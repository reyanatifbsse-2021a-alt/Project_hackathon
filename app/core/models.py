"""
AegisRuntime - Core Domain Models & Schemas
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import time
import uuid


class RiskCategory(str, Enum):
    HALLUCINATION = "HALLUCINATION"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    DECEPTIVE_BEHAVIOUR = "DECEPTIVE_BEHAVIOUR"
    EXPLOITATION = "EXPLOITATION"
    UNAUTHORISED_ACTION = "UNAUTHORISED_ACTION"
    MISSING_CONFLICTING_EVIDENCE = "MISSING_CONFLICTING_EVIDENCE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ClaimStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"
    UNABLE_TO_ASSESS = "UNABLE_TO_ASSESS"


class StepStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    PAUSED_DEPENDENCY = "PAUSED_DEPENDENCY"
    SAFE_CONTINUED = "SAFE_CONTINUED"
    FAILED = "FAILED"


class SectorProfile(str, Enum):
    HEALTHCARE = "HEALTHCARE"
    FINTECH = "FINTECH"
    DEFENSE_SECOPS = "DEFENSE_SECOPS"
    CUSTOM = "CUSTOM"


class VerificationResult(BaseModel):
    decision: Decision
    policy_id: str
    rule_name: str
    risk_category: RiskCategory
    reason: str
    token: Optional[Dict[str, Any]] = None
    risk_score: float = 0.0  # 0.0 - 1.0 contextual severity
    context_notes: Optional[str] = None
    safe_alternative_suggested: Optional[str] = None


class ProposedAction(BaseModel):
    action_id: str = Field(default_factory=lambda: f"act-{uuid.uuid4().hex[:8]}")
    step_id: str
    tool_name: str
    parameters: Dict[str, Any]
    rationale: str
    is_protected: bool = True
    raw_prompt_context: Optional[str] = None


class TaskStep(BaseModel):
    step_id: str
    title: str
    description: str
    dependencies: List[str] = []
    proposed_action: Optional[ProposedAction] = None
    status: StepStatus = StepStatus.PROPOSED
    verification_result: Optional[VerificationResult] = None
    execution_result: Optional[Dict[str, Any]] = None
    alternative_executed: bool = False
    notes: Optional[str] = None
    human_summary: Optional[str] = None
    plain_params: Optional[Dict[str, str]] = None


class TaskPlan(BaseModel):
    task_id: str = Field(default_factory=lambda: f"tsk-{uuid.uuid4().hex[:8]}")
    user_id: str = "usr-superadmin"
    user_request: str
    sector: SectorProfile = SectorProfile.HEALTHCARE
    steps: List[TaskStep]
    status: str = "IN_PROGRESS"
    created_at: float = Field(default_factory=time.time)
    completed_steps_count: int = 0
    blocked_steps_count: int = 0
    paused_steps_count: int = 0
    summary: Optional[str] = None


class ClaimVerificationRequest(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"clm-{uuid.uuid4().hex[:8]}")
    claim_text: str
    entity_id: str
    field_name: str
    claimed_value: Any
    sector: SectorProfile = SectorProfile.HEALTHCARE


class ClaimVerificationRecord(BaseModel):
    claim_id: str
    claim_text: str
    entity_id: str
    field_name: str
    claimed_value: Any
    actual_value: Optional[Any] = None
    status: ClaimStatus
    discrepancy_details: str
    source_reference: str
    timestamp: float = Field(default_factory=time.time)


class HumanReviewItem(BaseModel):
    review_id: str = Field(default_factory=lambda: f"rev-{uuid.uuid4().hex[:8]}")
    task_id: str
    step_id: str
    user_id: str = "usr-superadmin"
    action_id: str
    tool_name: str
    parameters: Dict[str, Any]
    policy_id: str
    reason: str
    risk_category: RiskCategory
    created_at: float = Field(default_factory=time.time)
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    reviewer_decision: Optional[str] = None
    reviewer_comment: Optional[str] = None


class AuditLogRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"aud-{uuid.uuid4().hex[:8]}")
    timestamp: float = Field(default_factory=time.time)
    task_id: str
    step_id: str
    user_request: str
    tool_name: str
    parameters: Dict[str, Any]
    decision: Decision
    policy_id: str
    rule_name: str
    risk_category: RiskCategory
    reason: str
    execution_status: str
    fallback_applied: Optional[str] = None
    token_nonce: Optional[str] = None


class PolicyRule(BaseModel):
    rule_id: str
    sector: SectorProfile
    name: str
    category: RiskCategory
    description: str
    target_tool: str
    condition_code: str  # Deterministic Python condition or identifier
    action: Decision
    enabled: bool = True
    priority: int = 100
