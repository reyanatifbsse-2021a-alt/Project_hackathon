"""
AegisRuntime - Verification Engine & Token Security Unit Tests
Validates that protected tools physically cannot execute without an authentic,
un-tampered, non-reusable token issued by the Verification Engine.
"""

import pytest
from app.core.security import (
    generate_action_execution_token,
    verify_and_consume_token,
    SecurityViolationException
)
from app.tools.tool_implementations import ExportDataTool, WireTransferTool
from app.verification.chaos import set_engine_offline, is_engine_offline, reset_chaos
from app.verification.verifier import ActionVerificationEngine
from app.core.models import ProposedAction, SectorProfile, Decision, RiskCategory


def test_protected_tool_refuses_execution_without_token():
    """Confirms protected tool fails closed if invoked directly without token."""
    tool = ExportDataTool()
    params = {"destination": "https://external.com", "payload": {"data": "test"}}
    
    with pytest.raises(SecurityViolationException) as exc_info:
        tool.execute(params, token=None)
    assert "FAIL_CLOSED" in str(exc_info.value)


def test_protected_tool_detects_parameter_tampering():
    """Confirms token becomes invalid if parameters are modified after verification."""
    original_params = {"amount": 100.0, "beneficiary_id": "VEND-990-SUPPLIES"}
    token = generate_action_execution_token(
        action_id="act-1",
        step_id="step-1",
        tool_name="wire_transfer",
        parameters=original_params,
        policy_id="POL-FIN-001"
    )

    tampered_params = {"amount": 500000.0, "beneficiary_id": "VEND-990-SUPPLIES"}
    tool = WireTransferTool()

    with pytest.raises(SecurityViolationException) as exc_info:
        tool.execute(tampered_params, token=token)
    assert "PARAMETER_TAMPERING" in str(exc_info.value)


def test_anti_replay_nonce_consumption():
    """Confirms an execution token cannot be replayed twice."""
    params = {"amount": 500.0, "beneficiary_id": "VEND-990-SUPPLIES"}
    token = generate_action_execution_token(
        action_id="act-2",
        step_id="step-2",
        tool_name="wire_transfer",
        parameters=params,
        policy_id="POL-FIN-001"
    )
    tool = WireTransferTool()

    # First execution succeeds
    res = tool.execute(params, token=token)
    assert res["status"] == "SUCCESS"

    # Replay attempt must be rejected
    with pytest.raises(SecurityViolationException) as exc_info:
        tool.execute(params, token=token)
    assert "REPLAY_DETECTED" in str(exc_info.value)


def test_fail_closed_when_engine_offline():
    """Confirms that when the verification engine suffers an outage, all protected actions fail closed."""
    verifier = ActionVerificationEngine()
    set_engine_offline(True)

    action = ProposedAction(
        step_id="step-test",
        tool_name="wire_transfer",
        parameters={"amount": 50.0, "beneficiary_id": "VEND-990-SUPPLIES"},
        rationale="Legitimate small payment",
        is_protected=True
    )

    try:
        res = verifier.verify_action(
            task_id="tsk-test",
            user_request="Small payment",
            action=action,
            sector=SectorProfile.FINTECH
        )
        assert res.decision == Decision.BLOCK
        assert res.risk_category == RiskCategory.VERIFICATION_FAILURE
        assert res.token is None
        assert "CRITICAL ENGINE OUTAGE" in res.reason
    finally:
        reset_chaos()
