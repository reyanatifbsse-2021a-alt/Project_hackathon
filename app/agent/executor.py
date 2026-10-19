"""
AegisRuntime - Workflow Continuity Runtime Executor
Executes DAG task plans while enforcing runtime intervention at the point of action.
Isolates blocked branches, pauses dependent steps, and autonomously continues
unrelated safe work.
"""

from typing import Dict, Any, List, Set, Optional
from app.core.models import (
    TaskPlan, StepStatus, Decision, VerificationResult, RiskCategory, ProposedAction
)
from app.verification.verifier import ActionVerificationEngine
from app.tools.sandbox import ToolRegistry


class WorkflowExecutor:
    """
    Dependency-aware DAG executor with runtime safety intervention and branch isolation.
    """

    def __init__(self):
        self.verifier = ActionVerificationEngine()
        self.tool_registry = ToolRegistry()

    def _enrich_action_parameters(self, action: Optional[ProposedAction], deps: List[str], step_outputs: Dict[str, Any]):
        """Dynamically pipes live data observed in upstream steps into downstream actions."""
        if not action or not deps:
            return
        for d in deps:
            out = step_outputs.get(d, {})
            data = out.get("data", {})
            if isinstance(data, dict):
                # Clinical live data propagation
                if "egfr" in data and "egfr" in action.parameters:
                    action.parameters["egfr"] = data["egfr"]
                if "allergies" in data and "patient_allergies" in action.parameters:
                    allergies = data.get("allergies", [])
                    action.parameters["patient_allergies"] = ", ".join(allergies) if isinstance(allergies, list) else str(allergies)
                # Financial live balance propagation
                if "balance" in data:
                    action.parameters["source_balance"] = data["balance"]
                if "kyc_status" in data:
                    action.parameters["kyc_status"] = data["kyc_status"]
                # SecOps resource status propagation
                if "status" in data:
                    action.parameters["resource_status"] = data["status"]

    def execute_plan(self, plan: TaskPlan) -> TaskPlan:
        """
        Executes a task plan step-by-step according to dependency constraints.
        Safe independent branches continue even if one branch is blocked.
        """
        executed_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.EXECUTED}
        blocked_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.BLOCKED}
        paused_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.PAUSED_DEPENDENCY}
        held_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.HELD_FOR_REVIEW}
        step_outputs: Dict[str, Any] = {}

        # Iterate until all steps have reached a terminal or paused state
        changed = True
        while changed:
            changed = False
            for step in plan.steps:
                if step.status not in [StepStatus.PROPOSED]:
                    continue

                # Check upstream dependencies
                deps = step.dependencies
                upstream_blocked_or_paused = any(
                    (d in blocked_ids or d in paused_ids or d in held_ids) for d in deps
                )

                if upstream_blocked_or_paused:
                    # Upstream was blocked or held -> PAUSE this dependent step!
                    step.status = StepStatus.PAUSED_DEPENDENCY
                    blocked_upstream = [d for d in deps if (d in blocked_ids or d in paused_ids or d in held_ids)]
                    step.notes = f"Branch Quarantined: Dependent upstream step(s) {blocked_upstream} did not complete safely. Step paused to maintain state integrity."
                    paused_ids.add(step.step_id)
                    changed = True
                    continue

                all_deps_completed = all(d in executed_ids for d in deps)
                if not all_deps_completed:
                    # Waiting for an upstream step that is still proposed
                    continue

                # Step is ready for execution!
                changed = True
                action = step.proposed_action
                self._enrich_action_parameters(action, deps, step_outputs)

                if not action or not action.is_protected:
                    # Safe read-only / unprotected action
                    exec_res = self.tool_registry.execute_tool(
                        action.tool_name if action else "read_data",
                        action.parameters if action else {}
                    )
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                    executed_ids.add(step.step_id)
                    step_outputs[step.step_id] = exec_res
                    continue

                # Point-of-action runtime intervention
                verification = self.verifier.verify_action(
                    task_id=plan.task_id,
                    user_request=plan.user_request,
                    action=action,
                    sector=plan.sector,
                    user_id=getattr(plan, "user_id", "usr-superadmin")
                )
                step.verification_result = verification

                if verification.decision == Decision.ALLOW:
                    # Token was issued; pass to protected tool sandbox
                    exec_res = self.tool_registry.execute_tool(
                        action.tool_name,
                        action.parameters,
                        token=verification.token
                    )
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                    executed_ids.add(step.step_id)
                    step_outputs[step.step_id] = exec_res

                elif verification.decision == Decision.HUMAN_REVIEW:
                    # Sensitive action held in clearinghouse queue
                    step.status = StepStatus.HELD_FOR_REVIEW
                    step.notes = f"Action placed in Human Approval Queue under rule {verification.policy_id}."
                    held_ids.add(step.step_id)

                elif verification.decision == Decision.BLOCK:
                    # Unsafe action blocked at point of action
                    step.status = StepStatus.BLOCKED
                    blocked_ids.add(step.step_id)
                    step.notes = f"Blocked by Verification Engine ({verification.policy_id}): {verification.reason}"

                    # Autonomous Safe Workaround: check if fallback alternative can be formulated
                    if verification.safe_alternative_suggested:
                        step.notes += f" [Safe Workaround Recommended: {verification.safe_alternative_suggested}]"

        # Tally metrics and produce continuity summary
        plan.completed_steps_count = len(executed_ids)
        plan.blocked_steps_count = len(blocked_ids)
        plan.paused_steps_count = len(paused_ids)

        if len(blocked_ids) > 0 or len(held_ids) > 0:
            if len(executed_ids) > 0:
                plan.status = "PARTIALLY_COMPLETED_CONTINUED"
                plan.summary = (
                    f"Workflow Continuity Active: {len(executed_ids)} safe independent step(s) completed. "
                    f"{len(blocked_ids)} prohibited action(s) blocked at runtime, and {len(paused_ids)} "
                    f"dependent downstream step(s) safely isolated."
                )
            else:
                plan.status = "INTERCEPTED_HELD"
                plan.summary = f"Execution halted: {len(blocked_ids)} blocked action(s), {len(held_ids)} held for review."
        else:
            plan.status = "COMPLETED_SUCCESSFULLY"
            plan.summary = f"All {len(executed_ids)} plan steps verified and executed safely."

        return plan

    def resume_held_step(self, plan: TaskPlan, step_id: str, approved: bool, reason: str = "") -> TaskPlan:
        """
        Resumes a paused/held DAG branch when human approval or rejection is submitted.
        """
        for step in plan.steps:
            if step.step_id == step_id and step.status == StepStatus.HELD_FOR_REVIEW:
                if approved:
                    step.status = StepStatus.VERIFIED
                    # Re-verify with human override token
                    action = step.proposed_action
                    from app.core.security import generate_action_execution_token
                    token = generate_action_execution_token(
                        action_id=action.action_id,
                        step_id=step.step_id,
                        tool_name=action.tool_name,
                        parameters=action.parameters,
                        policy_id="POL-HUMAN-OVERRIDE"
                    )
                    step.verification_result = VerificationResult(
                        decision=Decision.ALLOW,
                        policy_id="POL-HUMAN-OVERRIDE",
                        rule_name="Dual-Control Human Clearinghouse Authorization",
                        risk_category=RiskCategory.UNAUTHORISED_ACTION,
                        reason=f"Human Clearance Granted: {reason or 'Dual-control credentials verified.'}",
                        token=token,
                        risk_score=0.0
                    )
                    exec_res = self.tool_registry.execute_tool(action.tool_name, action.parameters, token=token)
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                else:
                    step.status = StepStatus.BLOCKED
                    step.notes = f"Human Review Rejected: {reason}"
                    step.verification_result = VerificationResult(
                        decision=Decision.BLOCK,
                        policy_id="POL-HUMAN-REJECT",
                        rule_name="Dual-Control Human Clearinghouse Rejection",
                        risk_category=RiskCategory.UNAUTHORISED_ACTION,
                        reason=f"Human Clearance Rejected: {reason or 'Denied by supervisor.'}",
                        risk_score=1.0
                    )

        # Re-run executor to advance dependent steps if approved!
        for s in plan.steps:
            if s.status == StepStatus.PAUSED_DEPENDENCY:
                s.status = StepStatus.PROPOSED
        return self.execute_plan(plan)

    def execute_plan_stream(self, plan: TaskPlan):
        """
        Yields progressive execution events in real time.
        Allows the UI to watch the agent reason, propose actions, and undergo
        point-of-action verification progressively.
        """
        executed_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.EXECUTED}
        blocked_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.BLOCKED}
        paused_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.PAUSED_DEPENDENCY}
        held_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.HELD_FOR_REVIEW}
        step_outputs: Dict[str, Any] = {}

        changed = True
        while changed:
            changed = False
            for step in plan.steps:
                if step.status not in [StepStatus.PROPOSED]:
                    continue

                deps = step.dependencies
                upstream_blocked_or_paused = any(
                    (d in blocked_ids or d in paused_ids or d in held_ids) for d in deps
                )

                if upstream_blocked_or_paused:
                    step.status = StepStatus.PAUSED_DEPENDENCY
                    blocked_upstream = [d for d in deps if (d in blocked_ids or d in paused_ids or d in held_ids)]
                    step.notes = f"Branch Quarantined: Dependent upstream step(s) {blocked_upstream} did not complete safely. Step paused to maintain state integrity."
                    paused_ids.add(step.step_id)
                    changed = True
                    yield {
                        "event": "BRANCH_ISOLATED",
                        "step_id": step.step_id,
                        "title": step.title,
                        "reason": f"Dependent step paused because upstream step {blocked_upstream} did not complete safely.",
                        "step": step.dict()
                    }
                    continue

                all_deps_completed = all(d in executed_ids for d in deps)
                if not all_deps_completed:
                    continue

                changed = True
                action = step.proposed_action
                self._enrich_action_parameters(action, deps, step_outputs)

                # Emit Step Start / Agent Thought event with cognitive context
                thought_context = "Piping verified live parameters from upstream step(s). " if (deps and any(d in step_outputs for d in deps)) else ""
                yield {
                    "event": "STEP_START",
                    "step_id": step.step_id,
                    "title": step.title,
                    "thought": f"Agent Cognitive Synthesis: {thought_context}Invoking tool '{action.tool_name if action else 'none'}' to {step.description.lower()}",
                    "step": step.dict()
                }

                if not action or not action.is_protected:
                    exec_res = self.tool_registry.execute_tool(
                        action.tool_name if action else "read_data",
                        action.parameters if action else {}
                    )
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                    executed_ids.add(step.step_id)
                    step_outputs[step.step_id] = exec_res
                    yield {
                        "event": "STEP_EXECUTED",
                        "step_id": step.step_id,
                        "title": step.title,
                        "decision": "ALLOW",
                        "is_protected": False,
                        "step": step.dict()
                    }
                    continue

                # Point-of-action runtime intervention
                verification = self.verifier.verify_action(
                    task_id=plan.task_id,
                    user_request=plan.user_request,
                    action=action,
                    sector=plan.sector,
                    user_id=getattr(plan, "user_id", "usr-superadmin")
                )
                step.verification_result = verification

                yield {
                    "event": "POINT_OF_ACTION_INTERCEPT",
                    "step_id": step.step_id,
                    "title": step.title,
                    "decision": verification.decision.value,
                    "policy_id": verification.policy_id,
                    "rule_name": verification.rule_name,
                    "risk_category": verification.risk_category.value,
                    "reason": verification.reason,
                    "token_minted": verification.token is not None,
                    "step": step.dict()
                }

                if verification.decision == Decision.ALLOW:
                    exec_res = self.tool_registry.execute_tool(
                        action.tool_name,
                        action.parameters,
                        token=verification.token
                    )
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                    executed_ids.add(step.step_id)
                    step_outputs[step.step_id] = exec_res
                    yield {
                        "event": "STEP_EXECUTED",
                        "step_id": step.step_id,
                        "title": step.title,
                        "decision": "ALLOW",
                        "is_protected": True,
                        "step": step.dict()
                    }

                elif verification.decision == Decision.HUMAN_REVIEW:
                    step.status = StepStatus.HELD_FOR_REVIEW
                    step.notes = f"Action placed in Human Approval Queue under rule {verification.policy_id}."
                    held_ids.add(step.step_id)
                    yield {
                        "event": "STEP_HELD",
                        "step_id": step.step_id,
                        "title": step.title,
                        "policy_id": verification.policy_id,
                        "reason": verification.reason,
                        "step": step.dict()
                    }

                elif verification.decision == Decision.BLOCK:
                    step.status = StepStatus.BLOCKED
                    blocked_ids.add(step.step_id)
                    step.notes = f"Blocked by Verification Engine ({verification.policy_id}): {verification.reason}"
                    if verification.safe_alternative_suggested:
                        step.notes += f" [Safe Workaround Recommended: {verification.safe_alternative_suggested}]"
                    yield {
                        "event": "STEP_BLOCKED",
                        "step_id": step.step_id,
                        "title": step.title,
                        "policy_id": verification.policy_id,
                        "reason": verification.reason,
                        "safe_alternative": verification.safe_alternative_suggested,
                        "step": step.dict()
                    }

        plan.completed_steps_count = len(executed_ids)
        plan.blocked_steps_count = len(blocked_ids)
        plan.paused_steps_count = len(paused_ids)

        if len(blocked_ids) > 0 or len(held_ids) > 0:
            if len(executed_ids) > 0:
                plan.status = "PARTIALLY_COMPLETED_CONTINUED"
                plan.summary = (
                    f"Workflow Continuity Active: {len(executed_ids)} safe independent step(s) completed. "
                    f"{len(blocked_ids)} prohibited action(s) blocked at runtime, and {len(paused_ids)} "
                    f"dependent downstream step(s) safely isolated."
                )
            else:
                plan.status = "INTERCEPTED_HELD"
                plan.summary = f"Execution halted: {len(blocked_ids)} blocked action(s), {len(held_ids)} held for review."
        else:
            plan.status = "COMPLETED_SUCCESSFULLY"
            plan.summary = f"All {len(executed_ids)} plan steps verified and executed safely."

        yield {
            "event": "PLAN_FINAL",
            "plan": plan.dict()
        }

