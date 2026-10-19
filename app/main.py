"""
AegisRuntime - FastAPI Server & REST API
Exposes the runtime intervention engine, policy manager, human-in-the-loop queue,
ground-truth evidence verifier, chaos simulator, and audit log exporter.
"""

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import json

from app.core.models import (
    SectorProfile, ClaimVerificationRequest, ClaimVerificationRecord,
    TaskPlan, Decision, StepStatus
)
from app.core.database import (
    init_db, query_audit_logs, export_audit_logs_csv, get_all_policies,
    update_policy_status, add_or_update_policy, get_pending_human_reviews,
    resolve_human_review, get_db
)
from app.agent.planner import TaskPlanner
from app.agent.executor import WorkflowExecutor
from app.verification.evidence_verifier import EvidenceVerifier
from app.verification.chaos import set_engine_offline, is_engine_offline, get_chaos_status

# Initialize DB on startup
init_db()

app = FastAPI(
    title="AegisRuntime - Sector Adaptable AI Intervention Engine",
    description="Intervenes at the point of action with Proof-of-Authority tokens, branch isolation, and fail-closed safety.",
    version="1.0.0"
)

# In-memory store for active live task plans
_ACTIVE_PLANS: Dict[str, TaskPlan] = {}

planner = TaskPlanner()
executor = WorkflowExecutor()
evidence_verifier = EvidenceVerifier()


# Static files mount
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AegisRuntime API is running. Web UI loading..."}


# -------------------------------------------------------------
# TASK EXECUTION & WORKFLOW CONTINUITY ENDPOINTS
# -------------------------------------------------------------

class RunTaskRequest(BaseModel):
    prompt: str
    sector: SectorProfile = SectorProfile.HEALTHCARE
    scenario_id: Optional[str] = None


@app.post("/api/tasks/run")
def run_task(req: RunTaskRequest):
    plan = planner.plan_task(req.prompt, req.sector)
    executed_plan = executor.execute_plan(plan)
    _ACTIVE_PLANS[executed_plan.task_id] = executed_plan
    return executed_plan


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    if task_id not in _ACTIVE_PLANS:
        raise HTTPException(status_code=404, detail="Task not found")
    return _ACTIVE_PLANS[task_id]


class ResumeTaskRequest(BaseModel):
    step_id: str
    approved: bool
    comment: Optional[str] = ""


@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str, req: ResumeTaskRequest):
    if task_id not in _ACTIVE_PLANS:
        raise HTTPException(status_code=404, detail="Task not found")
    plan = _ACTIVE_PLANS[task_id]
    updated_plan = executor.resume_held_step(plan, req.step_id, req.approved, req.comment or "")
    _ACTIVE_PLANS[task_id] = updated_plan
    return updated_plan


# -------------------------------------------------------------
# AUDIT LOG ENDPOINTS
# -------------------------------------------------------------

@app.get("/api/audit")
def get_audit_trail(
    search: Optional[str] = None,
    decision: Optional[str] = None,
    risk: Optional[str] = None,
    limit: int = 100
):
    return query_audit_logs(search=search, decision=decision, risk=risk, limit=limit)


@app.get("/api/audit/export/csv")
def download_audit_csv():
    csv_data = export_audit_logs_csv()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aegis_audit_trail.csv"}
    )


@app.get("/api/audit/export/json")
def download_audit_json():
    logs = query_audit_logs(limit=1000)
    return Response(
        content=json.dumps(logs, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=aegis_audit_trail.json"}
    )


# -------------------------------------------------------------
# POLICY MANAGEMENT ENDPOINTS
# -------------------------------------------------------------

@app.get("/api/policies")
def list_policies(sector: Optional[str] = None):
    return get_all_policies(sector=sector)


class PolicyToggleRequest(BaseModel):
    rule_id: str
    enabled: bool


@app.post("/api/policies/toggle")
def toggle_policy(req: PolicyToggleRequest):
    update_policy_status(req.rule_id, req.enabled)
    return {"status": "SUCCESS", "rule_id": req.rule_id, "enabled": req.enabled}


class PolicyCreateRequest(BaseModel):
    rule_id: str
    sector: SectorProfile
    name: str
    category: str
    description: str
    target_tool: str
    condition_code: str
    action: Decision
    enabled: bool = True
    priority: int = 100


@app.post("/api/policies")
def create_or_update_policy(req: PolicyCreateRequest):
    add_or_update_policy(req.dict())
    return {"status": "SUCCESS", "policy": req.dict()}


# -------------------------------------------------------------
# HUMAN REVIEW / APPROVAL QUEUE ENDPOINTS
# -------------------------------------------------------------

@app.get("/api/reviews/pending")
def list_pending_reviews():
    return get_pending_human_reviews()


class ResolveReviewRequest(BaseModel):
    review_id: str
    decision: str  # APPROVED or REJECTED
    comment: Optional[str] = ""


@app.post("/api/reviews/resolve")
def resolve_review(req: ResolveReviewRequest):
    res = resolve_human_review(req.review_id, req.decision, req.comment)
    if not res:
        raise HTTPException(status_code=404, detail="Review item not found")

    # If associated task is active in memory, resume it automatically
    task_id = res.get("task_id")
    step_id = res.get("step_id")
    if task_id in _ACTIVE_PLANS:
        plan = _ACTIVE_PLANS[task_id]
        executor.resume_held_step(plan, step_id, approved=(req.decision == "APPROVED"), reason=req.comment or "")

    return {"status": "SUCCESS", "resolution": res}


# -------------------------------------------------------------
# EVIDENCE & CLAIM VERIFICATION ENDPOINTS
# -------------------------------------------------------------

@app.post("/api/claims/verify")
def verify_claim_endpoint(req: ClaimVerificationRequest):
    return evidence_verifier.verify_claim(req)


@app.get("/api/evidence/records")
def list_evidence_records():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT record_id, sector, entity_id, entity_type, data_json, last_verified_source, updated_at FROM evidence_records")
    rows = cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["data"] = json.loads(d["data_json"])
        results.append(d)
    conn.close()
    return results


# -------------------------------------------------------------
# CHAOS ENGINEERING & FAIL-CLOSED ENDPOINTS
# -------------------------------------------------------------

class ChaosToggleRequest(BaseModel):
    offline: bool


@app.post("/api/chaos/toggle")
def toggle_chaos(req: ChaosToggleRequest):
    set_engine_offline(req.offline)
    return {"status": "SUCCESS", "engine_offline": is_engine_offline()}


@app.get("/api/chaos/status")
def chaos_status():
    return get_chaos_status()


@app.get("/api/health")
def health_check():
    return {
        "status": "ONLINE",
        "engine_fail_closed_mode": is_engine_offline(),
        "sectors_available": [s.value for s in SectorProfile],
        "active_tasks_count": len(_ACTIVE_PLANS)
    }
