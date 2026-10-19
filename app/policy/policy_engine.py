"""
AegisRuntime - Independent Workflow Policy Engine
Stores policies outside of LLM reach and executes deterministic policy rules.
AI evaluators cannot override a deterministic block.
"""

from typing import Dict, Any, Optional
from app.core.models import (
    Decision, RiskCategory, VerificationResult, SectorProfile, ProposedAction
)
from app.policy.injection_detector import inspect_action_for_threats
from app.policy.sector_rules import (
    check_phi_export,
    check_controlled_substance,
    check_contraindication,
    check_unregistered_wire_destination,
    check_high_value_wire,
    check_pci_dss_pii,
    check_public_bucket_acl,
    check_destructive_operation,
    check_iam_wildcard_grant
)
from app.core.database import get_all_policies


class PolicyEngine:
    """
    Evaluates proposed actions against deterministic rules and active sector profiles.
    Guarantees deterministic safety cannot be overridden by agent requests or prompt injection.
    """

    def __init__(self):
        pass

    def evaluate(
        self,
        action: ProposedAction,
        sector: SectorProfile = SectorProfile.HEALTHCARE
    ) -> VerificationResult:
        """
        Main evaluation pipeline for protected actions.
        Priority order:
        1. Universal Threat Vector Inspection (Prompt injection, delimiter smuggling, parameter tampering)
        2. Sector Specific Deterministic Rules
        3. Configurable DB Policies
        """
        tool_name = action.tool_name
        params = action.parameters
        raw_context = action.raw_prompt_context or ""

        # Step 1: Universal Injection & Instruction Manipulation Guard
        is_threat, threats, threat_cat = inspect_action_for_threats(tool_name, params, raw_context)
        if is_threat:
            return VerificationResult(
                decision=Decision.BLOCK,
                policy_id="POL-GEN-INJ",
                rule_name="Prompt Injection & Instruction Manipulation Defense",
                risk_category=RiskCategory.PROMPT_INJECTION if threat_cat == "PROMPT_INJECTION" else RiskCategory.DECEPTIVE_BEHAVIOUR,
                reason=f"Security Intercept: Untrusted input / instruction manipulation detected: {'; '.join(threats)}. Action pathway terminated.",
                risk_score=0.98,
                context_notes="External instruction attempted to override system guardrails or alter execution logic.",
                safe_alternative_suggested="Isolate external document in read-only quarantine and process with strict sanitization."
            )

        # Step 2: Sector-Specific Deterministic Rules
        # We query active policies from DB to verify if the rule is enabled
        db_policies = {p["rule_id"]: p for p in get_all_policies(sector.value)}

        # HEALTHCARE CHECKS
        if sector == SectorProfile.HEALTHCARE:
            if tool_name in ["export_data", "send_email", "cloud_storage"]:
                if db_policies.get("POL-HC-001", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_phi_export(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-HC-001",
                            rule_name="Prohibit PHI Export to External/Public Destinations",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.92,
                            safe_alternative_suggested=alt
                        )

            if tool_name in ["prescribe_medication", "order_drug"]:
                if db_policies.get("POL-HC-003", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_contraindication(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-HC-003",
                            rule_name="Dosage Contraindication Enforcement",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.95,
                            safe_alternative_suggested=alt
                        )

                if db_policies.get("POL-HC-002", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_controlled_substance(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-HC-002",
                            rule_name="Controlled Prescription Requires Physician Human Approval",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.70,
                            safe_alternative_suggested=alt
                        )

        # FINTECH CHECKS
        elif sector == SectorProfile.FINTECH:
            if tool_name in ["wire_transfer", "disburse_funds"]:
                if db_policies.get("POL-FIN-001", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_unregistered_wire_destination(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-FIN-001",
                            rule_name="Block Unregistered External Wire Routing",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.94,
                            safe_alternative_suggested=alt
                        )

                if db_policies.get("POL-FIN-002", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_high_value_wire(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-FIN-002",
                            rule_name="High Value Wire Transfer Requires Dual Authorization",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.75,
                            safe_alternative_suggested="Split payment into staggered milestones or submit for Treasury Board clearance."
                        )

            if tool_name in ["export_data", "file_system"]:
                if db_policies.get("POL-FIN-003", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_pci_dss_pii(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-FIN-003",
                            rule_name="Prevent PII and Cardholder Leakage in External Export",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.88,
                            safe_alternative_suggested=alt
                        )

        # DEFENSE SECOPS CHECKS
        elif sector == SectorProfile.DEFENSE_SECOPS:
            if tool_name in ["cloud_storage", "s3_bucket"]:
                if db_policies.get("POL-SEC-001", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_public_bucket_acl(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-SEC-001",
                            rule_name="Prohibit Public Bucket Exposure and ACL Tampering",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.96,
                            safe_alternative_suggested=alt
                        )

            if tool_name in ["delete_resource", "file_system"]:
                if db_policies.get("POL-SEC-002", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_destructive_operation(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-SEC-002",
                            rule_name="Destructive Backup Deletion Requires Human Multi-Sig",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.85,
                            safe_alternative_suggested="Create an archive copy in write-once-read-many (WORM) storage prior to deletion."
                        )

            if tool_name in ["iam_permission", "grant_access"]:
                if db_policies.get("POL-SEC-003", {}).get("enabled", 1):
                    dec, reason, cat, alt = check_iam_wildcard_grant(params)
                    if dec != Decision.ALLOW:
                        return VerificationResult(
                            decision=dec,
                            policy_id="POL-SEC-003",
                            rule_name="Privilege Escalation & Unauthorized IAM Grants",
                            risk_category=cat,
                            reason=reason,
                            risk_score=0.95,
                            safe_alternative_suggested=alt
                        )

        # Default ALLOW if all policies and conditions pass
        return VerificationResult(
            decision=Decision.ALLOW,
            policy_id="POL-DEFAULT-PERMIT",
            rule_name="Autonomous Action Verified & Permitted",
            risk_category=RiskCategory.UNAUTHORISED_ACTION,
            reason=f"Action '{tool_name}' verified against active policies in {sector.value} sector. No restrictions violated.",
            risk_score=0.05
        )
