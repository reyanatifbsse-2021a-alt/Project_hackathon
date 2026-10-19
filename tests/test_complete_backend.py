"""
AegisRuntime - Complete Backend & Real-Time Tool Integration Test Suite
Validates that:
1. All tools operate against real database persistence (no dummy mock data).
2. Wire transfers debit real account balances and record ledger transactions.
3. Clinical prescriptions commit real records to the clinical_prescriptions table.
4. Cloud storage mutations update bucket ACLs and object counts in SQLite.
5. Outbound data egress computes SHA-256 digests and persists audit records.
6. REST API endpoints expose real-time operational state and agent training curriculum.
"""

import json
import urllib.request
import pytest
from app.core.database import (
    get_financial_account,
    get_financial_ledger,
    get_clinical_prescriptions,
    get_cloud_storage_bucket,
    get_cloud_resource,
    list_outbound_transmissions,
    reset_real_backend_data
)
from app.agent.planner import TaskPlanner
from app.agent.executor import WorkflowExecutor
from app.core.models import SectorProfile, StepStatus

BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture(autouse=True)
def clean_backend_state():
    """Ensure pristine baseline state before each test run."""
    reset_real_backend_data()
    yield


def test_real_wire_transfer_ledger_settlement():
    """Verify that wire_transfer tool debits real account balance and creates ledger entry."""
    planner = TaskPlanner()
    executor = WorkflowExecutor()

    # Initial balance check
    account_before = get_financial_account("ACC-8821")
    assert account_before is not None
    initial_balance = account_before["balance"]
    assert initial_balance == 450000.00

    # Transfer $8,500 (below $10,000 threshold so it is ALLOWED autonomously)
    prompt = "Disburse $8,500 from ACC-8821 to vendor VEND-990-SUPPLIES for hardware supplies"
    plan = planner.plan_task(prompt, SectorProfile.FINTECH)
    executed = executor.execute_plan(plan)

    step2 = next(s for s in executed.steps if s.step_id == "step-2")
    assert step2.status == StepStatus.EXECUTED
    assert step2.execution_result["status"] == "SUCCESS"
    assert step2.execution_result["amount_settled"] == 8500.00
    assert step2.execution_result["balance_after"] == initial_balance - 8500.00

    # Verify real database balance has been updated
    account_after = get_financial_account("ACC-8821")
    assert account_after["balance"] == initial_balance - 8500.00

    # Verify ledger entry was created
    ledger = get_financial_ledger(5)
    assert len(ledger) > 0
    latest_txn = ledger[0]
    assert latest_txn["source_account"] == "ACC-8821"
    assert latest_txn["beneficiary_id"] == "VEND-990-SUPPLIES"
    assert latest_txn["amount"] == 8500.00
    assert latest_txn["status"] == "SETTLED"


def test_real_clinical_prescription_persistence():
    """Verify that prescribe_medication records real prescriptions in clinical_prescriptions table."""
    planner = TaskPlanner()
    executor = WorkflowExecutor()

    # Prescribe safe blood pressure medication to PT-1002 (Lisinopril 10mg)
    prompt = "Order 10mg Lisinopril for patient PT-1002 and monitor vitals"
    plan = planner.plan_task(prompt, SectorProfile.HEALTHCARE)
    executed = executor.execute_plan(plan)

    step2 = next(s for s in executed.steps if s.step_id == "step-2")
    assert step2.status == StepStatus.EXECUTED
    rx_num = step2.execution_result["rx_number"]
    assert rx_num.startswith("RX-")

    # Verify prescription exists in database
    db_rxs = get_clinical_prescriptions("PT-1002", 5)
    assert len(db_rxs) > 0
    matched_rx = next((r for r in db_rxs if r["rx_id"] == rx_num), None)
    assert matched_rx is not None
    assert matched_rx["medication"] == "Lisinopril"
    assert matched_rx["dose_mg"] == 10.0


def test_real_cloud_storage_and_resource_operations():
    """Verify that cloud storage and delete_resource update real database tables."""
    from app.tools.sandbox import ToolRegistry
    from app.core.security import generate_action_execution_token

    registry = ToolRegistry()

    # 1. Test real bucket ACL change
    token_acl = generate_action_execution_token(
        action_id="act-acl",
        step_id="step-acl",
        tool_name="cloud_storage",
        parameters={"bucket_name": "cloud-prod-storage", "action": "set_bucket_acl", "acl": "private"},
        policy_id="POL-SEC-001"
    )
    res_acl = registry.execute_tool(
        "cloud_storage",
        {"bucket_name": "cloud-prod-storage", "action": "set_bucket_acl", "acl": "private"},
        token=token_acl
    )
    assert res_acl["status"] == "SUCCESS"
    bucket = get_cloud_storage_bucket("cloud-prod-storage")
    assert bucket["acl"] == "private"
    assert bucket["is_public"] == 0

    # 2. Test real object upload to bucket
    token_obj = generate_action_execution_token(
        action_id="act-obj",
        step_id="step-obj",
        tool_name="cloud_storage",
        parameters={"bucket_name": "cloud-prod-storage", "action": "put_object", "object_key": "secops_log.json"},
        policy_id="POL-SEC-001"
    )
    res_obj = registry.execute_tool(
        "cloud_storage",
        {"bucket_name": "cloud-prod-storage", "action": "put_object", "object_key": "secops_log.json"},
        token=token_obj
    )
    assert res_obj["status"] == "SUCCESS"
    assert res_obj["object_key"] == "secops_log.json"

    # 3. Test real server decommission
    token_del = generate_action_execution_token(
        action_id="act-del",
        step_id="step-del",
        tool_name="delete_resource",
        parameters={"resource_id": "SRV-DEV-02", "resource_type": "DEVELOPMENT_SERVER"},
        policy_id="POL-SEC-002"
    )
    res_del = registry.execute_tool(
        "delete_resource",
        {"resource_id": "SRV-DEV-02", "resource_type": "DEVELOPMENT_SERVER"},
        token=token_del
    )
    assert res_del["status"] == "SUCCESS"
    res_db = get_cloud_resource("SRV-DEV-02")
    assert res_db["status"] == "DECOMMISSIONED"


def test_real_outbound_egress_digest_calculation():
    """Verify that export_data calculates SHA-256 digests and logs real outbound egress."""
    from app.tools.sandbox import ToolRegistry
    from app.core.security import generate_action_execution_token

    registry = ToolRegistry()
    dest = "https://hospital-core.internal/ehr/sync"
    payload = {"patient_id": "PT-1002", "status": "stable"}

    token = generate_action_execution_token(
        action_id="act-egr",
        step_id="step-egr",
        tool_name="export_data",
        parameters={"destination": dest, "payload": payload},
        policy_id="POL-HC-001"
    )

    res = registry.execute_tool(
        "export_data",
        {"destination": dest, "payload": payload},
        token=token
    )
    assert res["status"] == "SUCCESS"
    assert "payload_sha256" in res
    assert len(res["payload_sha256"]) == 64

    # Verify egress was recorded in DB
    transmissions = list_outbound_transmissions(5)
    assert len(transmissions) > 0
    assert transmissions[0]["destination_url"] == dest


def test_backend_rest_api_endpoints():
    """Test all new /api/backend/* REST API endpoints for real-time visibility."""
    # 1. State overview
    req = urllib.request.Request(f"{BASE_URL}/api/backend/state")
    with urllib.request.urlopen(req) as resp:
        state = json.loads(resp.read().decode())
        assert "financial" in state
        assert "clinical" in state
        assert "cloud" in state
        assert len(state["financial"]["accounts"]) >= 8
        assert len(state["clinical"]["patients"]) >= 3
        assert len(state["cloud"]["resources"]) >= 4

    # 2. Financial Accounts
    req = urllib.request.Request(f"{BASE_URL}/api/backend/financial/accounts")
    with urllib.request.urlopen(req) as resp:
        accounts = json.loads(resp.read().decode())
        assert any(a["account_id"] == "ACC-8821" for a in accounts)

    # 3. Clinical Patients
    req = urllib.request.Request(f"{BASE_URL}/api/backend/clinical/patients")
    with urllib.request.urlopen(req) as resp:
        patients = json.loads(resp.read().decode())
        assert any(p["patient_id"] == "PT-1001" for p in patients)

    # 4. Agent Training Curriculum
    req = urllib.request.Request(f"{BASE_URL}/api/agent/training")
    with urllib.request.urlopen(req) as resp:
        training = json.loads(resp.read().decode())
        assert "HEALTHCARE" in training
        assert "FINTECH" in training
        assert "DEFENSE_SECOPS" in training
        assert "pharmacopeia_contraindications" in training["HEALTHCARE"]
        assert "metformin" in training["HEALTHCARE"]["pharmacopeia_contraindications"]
