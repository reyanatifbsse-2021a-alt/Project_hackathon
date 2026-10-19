"""
AegisRuntime - Cryptographic Proof-of-Authority (PoA) Action Security
Guarantees that protected tools CANNOT be executed without an authentic,
un-tampered, non-reusable token issued exclusively by the Verification Engine.
"""

import hmac
import hashlib
import json
import time
import uuid
from typing import Dict, Any, Optional

# Secret key kept strictly within the runtime verification kernel
_SECURITY_KERNEL_KEY = "aegis_kernel_hmac_secret_" + uuid.uuid4().hex
_CONSUMED_NONCES = set()


class SecurityViolationException(Exception):
    """Raised when a protected tool is invoked without a valid verification token."""
    pass


def canonicalize_params(params: Dict[str, Any]) -> str:
    """Create a deterministic JSON string representation of parameters."""
    return json.dumps(params, sort_keys=True, separators=(',', ':'))


def compute_params_hash(params: Dict[str, Any]) -> str:
    """Compute SHA-256 hash of canonicalized parameters."""
    canon = canonicalize_params(params)
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()


def generate_action_execution_token(
    action_id: str,
    step_id: str,
    tool_name: str,
    parameters: Dict[str, Any],
    policy_id: str,
    ttl_seconds: int = 120
) -> Dict[str, Any]:
    """
    Issued EXCLUSIVELY by the independent VerificationEngine when an action is ALLOWED
    or approved by human.
    """
    now = time.time()
    nonce = uuid.uuid4().hex
    params_hash = compute_params_hash(parameters)
    
    payload = {
        "action_id": action_id,
        "step_id": step_id,
        "tool_name": tool_name,
        "params_hash": params_hash,
        "policy_id": policy_id,
        "issued_at": now,
        "expires_at": now + ttl_seconds,
        "nonce": nonce
    }
    
    payload_str = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        _SECURITY_KERNEL_KEY.encode('utf-8'),
        payload_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return {
        "payload": payload,
        "signature": signature
    }


def verify_and_consume_token(
    token: Optional[Dict[str, Any]],
    tool_name: str,
    parameters: Dict[str, Any]
) -> bool:
    """
    Validates the token at the point of action within protected tool implementations.
    Consumes the nonce to prevent replay attacks.
    """
    if not token or not isinstance(token, dict):
        raise SecurityViolationException(
            "FAIL_CLOSED: Protected tool execution attempted without an Action Execution Token."
        )
    
    payload = token.get("payload")
    signature = token.get("signature")
    
    if not payload or not signature:
        raise SecurityViolationException(
            "FAIL_CLOSED: Malformed Action Execution Token."
        )
    
    # Verify HMAC signature
    payload_str = json.dumps(payload, sort_keys=True)
    expected_sig = hmac.new(
        _SECURITY_KERNEL_KEY.encode('utf-8'),
        payload_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_sig):
        raise SecurityViolationException(
            "TAMPER_DETECTED: Action Execution Token signature mismatch! Forgery attempt blocked."
        )
    
    # Check expiry
    now = time.time()
    if now > payload.get("expires_at", 0):
        raise SecurityViolationException(
            "TOKEN_EXPIRED: Action Execution Token has expired. Re-verification required."
        )
    
    # Verify tool name matches
    if payload.get("tool_name") != tool_name:
        raise SecurityViolationException(
            f"TOOL_MISMATCH: Token authorized for '{payload.get('tool_name')}', "
            f"but attempted to invoke '{tool_name}'."
        )
    
    # Verify parameter hash matches (prevents parameter manipulation after verification)
    provided_hash = compute_params_hash(parameters)
    if payload.get("params_hash") != provided_hash:
        raise SecurityViolationException(
            "PARAMETER_TAMPERING: Tool parameters do not match verified specification."
        )
    
    # Verify non-reusable nonce (anti-replay)
    nonce = payload.get("nonce")
    if nonce in _CONSUMED_NONCES:
        raise SecurityViolationException(
            "REPLAY_DETECTED: Action Execution Token has already been consumed."
        )
    
    _CONSUMED_NONCES.add(nonce)
    return True
