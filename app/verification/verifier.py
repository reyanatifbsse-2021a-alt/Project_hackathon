"""
AegisRuntime - Independent Action Verification Engine
Intercepts every protected tool action at the point of action prior to execution.
Enforces deterministic policies, detects injection & privilege escalation,
and issues cryptographic Proof-of-Authority tokens exclusively upon ALLOW.
Fails closed if the engine is offline.
"""

from typing import Dict, Any, Optional
from app.core.models import (
    Decision, RiskCategory, VerificationResult, ProposedAction, SectorProfile
)
from app.core.security import generate_action_execution_token
from app.core.database import log_audit_record, add_human_review_item
from app.policy.policy_engine import PolicyEngine
from app.verification.chaos import is_engine_offline
import time


class ActionVerificationEngine:
    """
    Independent Gatekeeper Kernel.
    Every protected tool action MUST pass through this engine.
    There is no alternative route to protected tools.
    """

    def __init__(self):
        self.policy_engine = PolicyEngine()

    def verify_action(
        self,
        task_id: str,
        user_request: str,
        action: ProposedAction,
        sector: SectorProfile = SectorProfile.HEALTHCARE
    ) -> VerificationResult:
        timestamp = time.time()

        # 1. Chaos / Fail-Closed Check (Scenario 5)
        if is_engine_offline():
            res = VerificationResult(
                decision=Decision.BLOCK,
                policy_id="POL-FAIL-CLOSED-001",
                rule_name="Fail-Closed Protection on Verification Service Outage",
                risk_category=RiskCategory.VERIFICATION_FAILURE,
                reason="CRITICAL ENGINE OUTAGE: Verification service is offline or unreachable. Fail-closed zero-trust policy strictly blocks execution of protected tools to prevent unverified actions.",
                risk_score=1.0,
                context_notes="Verification engine unavailable. Protected actions are frozen."
            )
            # Log failure to audit trail
            log_audit_record({
                "id": f"aud-{int(timestamp * 1000)}",
                "timestamp": timestamp,
                "task_id": task_id,
                "step_id": action.step_id,
                "user_request": user_request,
                "tool_name": action.tool_name,
                "parameters": action.parameters,
                "decision": res.decision.value,
                "policy_id": res.policy_id,
                "rule_name": res.rule_name,
                "risk_category": res.risk_category.value,
                "reason": res.reason,
                "execution_status": "BLOCKED_FAIL_CLOSED",
                "fallback_applied": None,
                "token_nonce": None
            })
            return res

        # 2. Evaluate action through independent Policy Engine
        eval_result = self.policy_engine.evaluate(action, sector)

        # 3. Decision Handlers
        if eval_result.decision == Decision.ALLOW:
            # Issue cryptographic Proof-of-Authority (PoA) token
            token = generate_action_execution_token(
                action_id=action.action_id,
                step_id=action.step_id,
                tool_name=action.tool_name,
                parameters=action.parameters,
                policy_id=eval_result.policy_id
            )
            eval_result.token = token

            # Record in audit trail
            log_audit_record({
                "id": f"aud-{int(timestamp * 1000)}",
                "timestamp": timestamp,
                "task_id": task_id,
                "step_id": action.step_id,
                "user_request": user_request,
                "tool_name": action.tool_name,
                "parameters": action.parameters,
                "decision": eval_result.decision.value,
                "policy_id": eval_result.policy_id,
                "rule_name": eval_result.rule_name,
                "risk_category": eval_result.risk_category.value,
                "reason": eval_result.reason,
                "execution_status": "VERIFIED_PERMITTED",
                "fallback_applied": None,
                "token_nonce": token["payload"]["nonce"]
            })

        elif eval_result.decision == Decision.HUMAN_REVIEW:
            # Place in Human Approval Queue
            add_human_review_item({
                "review_id": f"rev-{action.action_id}",
                "task_id": task_id,
                "step_id": action.step_id,
                "action_id": action.action_id,
                "tool_name": action.tool_name,
                "parameters": action.parameters,
                "policy_id": eval_result.policy_id,
                "reason": eval_result.reason,
                "risk_category": eval_result.risk_category.value,
                "created_at": timestamp
            })

            # Record in audit trail
            log_audit_record({
                "id": f"aud-{int(timestamp * 1000)}",
                "timestamp": timestamp,
                "task_id": task_id,
                "step_id": action.step_id,
                "user_request": user_request,
                "tool_name": action.tool_name,
                "parameters": action.parameters,
                "decision": eval_result.decision.value,
                "policy_id": eval_result.policy_id,
                "rule_name": eval_result.rule_name,
                "risk_category": eval_result.risk_category.value,
                "reason": eval_result.reason,
                "execution_status": "HELD_IN_QUEUE",
                "fallback_applied": None,
                "token_nonce": None
            })

        elif eval_result.decision == Decision.BLOCK:
            # Action strictly blocked - NO token issued
            log_audit_record({
                "id": f"aud-{int(timestamp * 1000)}",
                "timestamp": timestamp,
                "task_id": task_id,
                "step_id": action.step_id,
                "user_request": user_request,
                "tool_name": action.tool_name,
                "parameters": action.parameters,
                "decision": eval_result.decision.value,
                "policy_id": eval_result.policy_id,
                "rule_name": eval_result.rule_name,
                "risk_category": eval_result.risk_category.value,
                "reason": eval_result.reason,
                "execution_status": "BLOCKED_PRE_EXECUTION",
                "fallback_applied": eval_result.safe_alternative_suggested,
                "token_nonce": None
            })

        return eval_result
