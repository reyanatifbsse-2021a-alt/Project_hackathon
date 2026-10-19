import urllib.request
import json
import pytest

base = "http://127.0.0.1:8000"


def test_sse_streaming_and_dual_control_clearance():
    # Test SSE streaming of Scenario 2 (Dual-control wire transfer)
    payload = json.dumps({
        "prompt": "Initiate urgent treasury wire transfer of $250,000 to supplier account ACC-8821 for offshore logistics, generate transaction invoice, and notify vendor",
        "sector": "FINTECH"
    }).encode("utf-8")

    req = urllib.request.Request(f"{base}/api/tasks/run_stream", data=payload, headers={"Content-Type": "application/json"})
    events = []
    with urllib.request.urlopen(req) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: "):
                ev_data = json.loads(line_str[6:])
                events.append(ev_data)

    event_types = [e.get("event") for e in events]

    assert "PLAN_INITIALIZED" in event_types
    assert "POINT_OF_ACTION_INTERCEPT" in event_types
    assert "STEP_HELD" in event_types
    assert "PLAN_FINAL" in event_types

    # Get task_id from PLAN_INITIALIZED
    init_event = next(e for e in events if e.get("event") == "PLAN_INITIALIZED")
    task_id = init_event["plan"]["task_id"]

    # Resume the held step
    held_event = next(e for e in events if e.get("event") == "STEP_HELD")
    step_id = held_event["step"]["step_id"]

    resume_payload = json.dumps({
        "step_id": step_id,
        "approved": True,
        "comment": "Treasury Board Dual-Control Authorized."
    }).encode("utf-8")

    resume_req = urllib.request.Request(f"{base}/api/tasks/{task_id}/resume", data=resume_payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(resume_req) as resume_resp:
        resumed_plan = json.loads(resume_resp.read().decode("utf-8"))

    resumed_step = next(s for s in resumed_plan["steps"] if s["step_id"] == step_id)
    assert resumed_step["status"] == "EXECUTED"
    assert resumed_step["verification_result"]["decision"] == "ALLOW"
    assert "signature" in resumed_step["verification_result"]["token"]
    assert resumed_step["verification_result"]["token"]["payload"]["policy_id"] == "POL-HUMAN-OVERRIDE"


def test_scenarios_endpoint_structure():
    req = urllib.request.Request(f"{base}/api/scenarios")
    with urllib.request.urlopen(req) as resp:
        scenarios = json.loads(resp.read().decode("utf-8"))

    assert len(scenarios) == 6
    for sc in scenarios:
        assert "id" in sc
        assert "title" in sc
        assert "sector" in sc
        assert "prompt" in sc
        assert "expected_outcome" in sc
