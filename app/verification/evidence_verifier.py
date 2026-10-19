"""
AegisRuntime - Evidence and Claim Verification Engine
Compares factual claims made by the agent against approved authoritative records.
Evaluates data schemas and returns:
- VERIFIED
- UNVERIFIED
- CONFLICTING
- UNABLE TO ASSESS
Flags and holds claims to prevent hallucinations from propagating.
"""

import time
from app.core.models import (
    ClaimStatus, ClaimVerificationRequest, ClaimVerificationRecord
)
from app.core.database import get_evidence_record


class EvidenceVerifier:
    """
    Independent claim validation against authoritative ground-truth records.
    Prevents hallucinated or corrupted facts from being presented as confirmed truth.
    """

    def verify_claim(self, request: ClaimVerificationRequest) -> ClaimVerificationRecord:
        record = get_evidence_record(request.entity_id)

        # Case 1: Entity does not exist in vetted records
        if not record:
            return ClaimVerificationRecord(
                claim_id=request.claim_id,
                claim_text=request.claim_text,
                entity_id=request.entity_id,
                field_name=request.field_name,
                claimed_value=request.claimed_value,
                actual_value=None,
                status=ClaimStatus.UNABLE_TO_ASSESS,
                discrepancy_details=f"Entity ID '{request.entity_id}' not found in approved registry. Unable to assess claim validity.",
                source_reference="None (Missing from approved sources)",
                timestamp=time.time()
            )

        data = record.get("data", {})
        source_ref = record.get("last_verified_source", "Approved Enclave Registry")

        # Case 2: Field missing in authoritative schema
        if request.field_name not in data:
            return ClaimVerificationRecord(
                claim_id=request.claim_id,
                claim_text=request.claim_text,
                entity_id=request.entity_id,
                field_name=request.field_name,
                claimed_value=request.claimed_value,
                actual_value=None,
                status=ClaimStatus.UNVERIFIED,
                discrepancy_details=f"Field '{request.field_name}' is not present in authoritative schema for '{request.entity_id}'. Claim remains unverified.",
                source_reference=source_ref,
                timestamp=time.time()
            )

        actual_val = data[request.field_name]
        claimed_val = request.claimed_value

        # Normalize and compare
        match = False
        if isinstance(actual_val, (int, float)) and isinstance(claimed_val, (int, float)):
            match = abs(float(actual_val) - float(claimed_val)) < 0.001
        elif isinstance(actual_val, str) and isinstance(claimed_val, str):
            match = actual_val.strip().lower() == claimed_val.strip().lower()
        elif isinstance(actual_val, list):
            if isinstance(claimed_val, list):
                match = sorted([str(x).lower() for x in actual_val]) == sorted([str(x).lower() for x in claimed_val])
            elif isinstance(claimed_val, str):
                match = any(claimed_val.strip().lower() == str(x).strip().lower() for x in actual_val)
        else:
            match = actual_val == claimed_val

        if match:
            return ClaimVerificationRecord(
                claim_id=request.claim_id,
                claim_text=request.claim_text,
                entity_id=request.entity_id,
                field_name=request.field_name,
                claimed_value=claimed_val,
                actual_value=actual_val,
                status=ClaimStatus.VERIFIED,
                discrepancy_details=f"Exact match verified against authoritative records in {source_ref}.",
                source_reference=source_ref,
                timestamp=time.time()
            )
        else:
            return ClaimVerificationRecord(
                claim_id=request.claim_id,
                claim_text=request.claim_text,
                entity_id=request.entity_id,
                field_name=request.field_name,
                claimed_value=claimed_val,
                actual_value=actual_val,
                status=ClaimStatus.CONFLICTING,
                discrepancy_details=(
                    f"CRITICAL CONFLICT DETECTED: Agent claimed '{request.field_name}' = {claimed_val}, "
                    f"but verified authoritative source documents '{actual_val}'."
                ),
                source_reference=source_ref,
                timestamp=time.time()
            )
