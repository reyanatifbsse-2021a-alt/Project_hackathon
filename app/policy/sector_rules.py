"""
AegisRuntime - Sector Specific Deterministic Policy Rules
Contains the concrete deterministic validation logic for Healthcare, Fintech, and Defense SecOps.
Evaluated independently from the LLM.
"""

from typing import Dict, Any, Tuple, Optional
import re
from app.core.models import Decision, RiskCategory

APPROVED_INTERNAL_DOMAINS = [
    "hospital-core.internal",
    "internal-ehr-vault",
    "treasury-vault.bank.internal",
    "govcloud-isolated.internal"
]

APPROVED_FINTECH_BENEFICIARIES = [
    "VEND-990-SUPPLIES",
    "PAYROLL-GLOBAL-01",
    "TAX-AUTHORITY-FEDERAL",
    "INTERNAL-SETTLEMENT-RESERVE"
]

CONTROLLED_MEDICATIONS = [
    "oxycodone", "fentanyl", "morphine", "ketamine", "hydromorphone",
    "adderall", "methadone", "diazepam", "lorazepam"
]


def check_phi_export(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    HIPAA Rule: Prevents transmission of Protected Health Information (PHI) to unapproved destinations.
    """
    destination = str(params.get("destination", params.get("target_url", params.get("recipient", "")))).lower()
    payload = params.get("payload", params.get("data", {}))
    payload_str = str(payload).lower()

    # Check if target is in approved internal enclave
    is_internal = any(domain in destination for domain in APPROVED_INTERNAL_DOMAINS)
    
    # Check for PHI keywords
    phi_indicators = ["diagnosis", "egfr", "patient_id", "medical_record", "ssn", "mrn", "dob", "serum", "prescription"]
    contains_phi = any(ind in payload_str for ind in phi_indicators) or any(ind in str(params).lower() for ind in phi_indicators)

    if contains_phi and not is_internal:
        return (
            Decision.BLOCK,
            f"HIPAA Violation: Unapproved export of Protected Health Information (PHI) to external destination '{destination}'. Destination is not an authorized health enclave.",
            RiskCategory.UNAUTHORISED_ACTION,
            "Sanitize export payload by stripping individual patient IDs and generating aggregated statistical metrics."
        )

    return (Decision.ALLOW, "Destination and payload conform to internal perimeter policies.", RiskCategory.UNAUTHORISED_ACTION, None)


def check_controlled_substance(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    Clinical Safety: Controlled medications require physician human approval.
    """
    medication = str(params.get("medication", params.get("drug_name", ""))).lower()
    dose_mg = float(params.get("dose_mg", params.get("dosage_mg", 0)))
    
    is_controlled = any(c_drug in medication for c_drug in CONTROLLED_MEDICATIONS)

    if is_controlled:
        return (
            Decision.HUMAN_REVIEW,
            f"Clinical Safety Requirement: Automated order of controlled substance '{medication.title()}' ({dose_mg}mg) requires mandatory human physician authorization.",
            RiskCategory.DECEPTIVE_BEHAVIOUR,
            None
        )

    return (Decision.ALLOW, "Medication is not in the controlled substance schedule.", RiskCategory.DECEPTIVE_BEHAVIOUR, None)


def check_contraindication(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    Clinical Safety: Deterministic check against known lethal contraindications.
    """
    medication = str(params.get("medication", params.get("drug_name", ""))).lower()
    patient_id = params.get("patient_id", "")
    egfr = params.get("egfr", 100)
    allergy = str(params.get("patient_allergies", "")).lower()

    # Metformin + Severe Renal Impairment
    if "metformin" in medication and egfr < 30:
        return (
            Decision.BLOCK,
            f"Lethal Clinical Hazard: Metformin contraindicated in Patient {patient_id} due to severe renal impairment (eGFR {egfr} < 30 mL/min). Risk of fatal lactic acidosis.",
            RiskCategory.HALLUCINATION,
            "Switch to renal-safe agent (e.g. DPP-4 inhibitor dose-adjusted or basal insulin)."
        )

    # Penicillin allergy + Amoxicillin
    if ("amoxicillin" in medication or "ampicillin" in medication) and "penicillin" in allergy:
        return (
            Decision.BLOCK,
            f"Severe Allergy Alert: {medication.title()} prescribed to patient with recorded severe Penicillin anaphylaxis.",
            RiskCategory.HALLUCINATION,
            "Use non-beta-lactam alternative: Azithromycin 500mg or Doxycycline."
        )

    return (Decision.ALLOW, "No lethal contraindication detected.", RiskCategory.HALLUCINATION, None)


def check_unregistered_wire_destination(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    FINRA / AML: Blocks wire transfers to unknown or non-whitelisted destinations.
    """
    beneficiary = str(params.get("beneficiary_id", params.get("recipient_account", "")))
    amount = float(params.get("amount", 0))

    if beneficiary not in APPROVED_FINTECH_BENEFICIARIES:
        return (
            Decision.BLOCK,
            f"FINRA / Anti-Money Laundering Rule: Destination account '{beneficiary}' is NOT on the verified beneficiary whitelist. Outbound transfer blocked.",
            RiskCategory.EXPLOITATION,
            "Submit vendor registration request with proof of corporate KYC before scheduling transfer."
        )

    return (Decision.ALLOW, f"Beneficiary '{beneficiary}' is verified.", RiskCategory.EXPLOITATION, None)


def check_high_value_wire(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    Treasury Controls: Transfers > $10,000 USD require dual authorization.
    """
    amount = float(params.get("amount", 0))
    threshold = 10000.00

    if amount > threshold:
        return (
            Decision.HUMAN_REVIEW,
            f"Treasury Policy POL-FIN-002: Transfer amount (${amount:,.2f}) exceeds single-agent ceiling (${threshold:,.2f}). Held for dual-signoff human clearinghouse approval.",
            RiskCategory.UNAUTHORISED_ACTION,
            None
        )

    return (Decision.ALLOW, f"Amount (${amount:,.2f}) is within autonomous execution limit.", RiskCategory.UNAUTHORISED_ACTION, None)


def check_pci_dss_pii(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    PCI-DSS: Prohibits raw export of full card numbers or sensitive customer records.
    """
    payload_str = str(params.get("payload", params.get("data", "")))
    
    # Check for 16-digit credit card pattern (PAN)
    card_pattern = r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
    if re.search(card_pattern, payload_str):
        return (
            Decision.BLOCK,
            "PCI-DSS Violation: Action payload contains unmasked 16-digit Primary Account Numbers (PAN).",
            RiskCategory.UNAUTHORISED_ACTION,
            "Apply tokenization or mask card numbers to last 4 digits (e.g. '****-****-****-1234')."
        )

    return (Decision.ALLOW, "No raw cardholder data detected in payload.", RiskCategory.UNAUTHORISED_ACTION, None)


def check_public_bucket_acl(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    SecOps: Blocks setting cloud bucket ACL to public-read or exposing assets.
    """
    acl = str(params.get("acl", params.get("permissions", ""))).lower()
    public_access = params.get("public_access", False)

    if "public" in acl or public_access is True:
        return (
            Decision.BLOCK,
            "Zero Trust Policy POL-SEC-001: Attempted to expose storage bucket to public read access. Direct violation of Cloud Security Perimeter standards.",
            RiskCategory.EXPLOITATION,
            "Configure Private ACL with IAM Role-Based Access Control and KMS Customer Managed Keys."
        )

    return (Decision.ALLOW, "Bucket access is private and compliant.", RiskCategory.EXPLOITATION, None)


def check_destructive_operation(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    SecOps: Destructive deletion of database or backup assets requires human confirmation.
    """
    resource_type = str(params.get("resource_type", "")).lower()
    resource_id = str(params.get("resource_id", ""))

    destructive_targets = ["backup", "snapshot", "database", "audit_log", "vault", "production", "prod", "server", "cluster"]
    if any(target in resource_type for target in destructive_targets) or any(target in resource_id.lower() for target in destructive_targets):
        return (
            Decision.HUMAN_REVIEW,
            f"Critical Infrastructure Guard: Deletion of '{resource_type}' (ID: {resource_id}) is irreversible. Held for SecOps Lead dual-factor review.",
            RiskCategory.EXPLOITATION,
            None
        )

    return (Decision.ALLOW, "Resource deletion is within standard safe operational scope.", RiskCategory.EXPLOITATION, None)


def check_iam_wildcard_grant(params: Dict[str, Any]) -> Tuple[Decision, str, RiskCategory, Optional[str]]:
    """
    SecOps: Blocks granting AdministratorAccess or wildcard permissions.
    """
    policy_doc = str(params.get("policy_document", params.get("permissions", "")))
    if '"*"' in policy_doc or "'*'" in policy_doc or "AdministratorAccess" in policy_doc:
        return (
            Decision.BLOCK,
            "IAM Boundary Violation POL-SEC-003: Proposed action grants wildcard ('*') or AdministratorAccess privileges. Privilege escalation blocked.",
            RiskCategory.EXPLOITATION,
            "Grant least-privilege scoped permissions with explicit resource ARNs."
        )

    return (Decision.ALLOW, "IAM grants adhere to least privilege policy.", RiskCategory.EXPLOITATION, None)
