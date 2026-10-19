"""
AegisRuntime - Workflow Continuity Runtime Executor
Executes DAG task plans while enforcing runtime intervention at the point of action.
Isolates blocked branches, pauses dependent steps, and autonomously continues
unrelated safe work.
"""

from typing import Dict, Any, List, Set, Optional
from app.core.models import (
    TaskPlan, TaskStep, StepStatus, Decision, SectorProfile
)
from app.verification.verifier import ActionVerificationEngine
from app.tools.sandbox import ToolRegistry
import time


class WorkflowExecutor:
    """
    Dependency-aware DAG executor with runtime safety intervention and branch isolation.
    """

    def __init__(self):
        self.verifier = ActionVerificationEngine()
        self.tool_registry = ToolRegistry()

    def execute_plan(self, plan: TaskPlan) -> TaskPlan:
        """
        Executes a task plan step-by-step according to dependency constraints.
        Safe independent branches continue even if one branch is blocked.
        """
        steps_by_id = {s.step_id: s for s in plan.steps}
        executed_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.EXECUTED}
        blocked_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.BLOCKED}
        paused_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.PAUSED_DEPENDENCY}
        held_ids: Set[str] = {s.step_id for s in plan.steps if s.status == StepStatus.HELD_FOR_REVIEW}

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

                if not action or not action.is_protected:
                    # Safe read-only / unprotected action
                    exec_res = self.tool_registry.execute_tool(
                        action.tool_name if action else "read_data",
                        action.parameters if action else {}
                    )
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                    executed_ids.add(step.step_id)
                    continue

                # Point-of-action runtime intervention
                verification = self.verifier.verify_action(
                    task_id=plan.task_id,
                    user_request=plan.user_request,
                    action=action,
                    sector=plan.sector
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
                    step.notes = f"Human Review Approved: {reason}"
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
                    exec_res = self.tool_registry.execute_tool(action.tool_name, action.parameters, token=token)
                    step.status = StepStatus.EXECUTED
                    step.execution_result = exec_res
                else:
                    step.status = StepStatus.BLOCKED
                    step.notes = f"Human Review Rejected: {reason}"

        # Re-run executor to advance dependent steps if approved!
        for s in plan.steps:
            if s.status == StepStatus.PAUSED_DEPENDENCY:
                s.status = StepStatus.PROPOSED
        return self.execute_plan(plan)
