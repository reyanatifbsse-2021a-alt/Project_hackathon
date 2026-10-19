"""
AegisRuntime - Prompt Injection & Instruction Manipulation Detector
Analyzes input text, tool arguments, and context for indirect injection,
delimiter smuggling, instruction overrides, and deceptive privilege escalation.
Operates deterministically outside of LLM influence.
"""

import re
from typing import Dict, Any, Tuple, List

# High-risk instruction override patterns
INJECTION_OVERRIDE_PATTERNS = [
    r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts|directives|guidelines)\b",
    r"(?i)\bdisregard\s+(all\s+)?(safety|security|policy|restrictions|constraints)\b",
    r"(?i)\bsystem\s+override\b",
    r"(?i)\badmin(istrator)?\s+override\b",
    r"(?i)\bbypass\s+(verification|firewall|guardrails?|inspection|approval)\b",
    r"(?i)\bdeveloper\s+mode\s+activated?\b",
    r"(?i)\bdo\s+anything\s+now\b",
    r"(?i)\bemergency\s+(override|bypass|disbursement|transfer)\b",
    r"(?i)\bdisable\s+(verification|protection|security|policy)\b",
    r"(?i)\bnow\s+act\s+as\s+an\s+unrestricted\b",
]

# Delimiter and tag smuggling patterns
DELIMITER_SMUGGLING_PATTERNS = [
    r"<!--\s*INSTRUCTION\s*:",
    r"<!--\s*SYSTEM\s*:",
    r"<\s*system\s*>",
    r"<\s*/\s*system\s*>",
    r"\[\s*INST\s*\]",
    r"\[\s*/\s*INST\s*\]",
    r"###\s*SYSTEM\s*:",
    r"<\|\s*im_start\s*\|>",
    r"<\|\s*im_end\s*\|>",
]

# Deceptive parameter injection patterns
DECEPTIVE_PARAM_PATTERNS = [
    r"(?i)ignore_security_check\s*=\s*(true|1)",
    r"(?i)skip_verification\s*=\s*(true|1)",
    r"(?i)force_execute\s*=\s*(true|1)",
    r"(?i)sudo\s+",
    r"(?i)chmod\s+777",
    r"(?i)eval\s*\(",
    r"(?i)exec\s*\(",
    r"(?i)__import__",
]


def scan_for_injection(text: str) -> Tuple[bool, List[str], float]:
    """
    Scans a given text or serialized argument for prompt injection signals.
    Returns: (is_injection_detected, matched_patterns, risk_score)
    """
    if not text or not isinstance(text, str):
        return False, [], 0.0

    detected_reasons = []

    for pattern in INJECTION_OVERRIDE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            detected_reasons.append(f"Instruction Override Detected: '{match.group(0)}'")

    for pattern in DELIMITER_SMUGGLING_PATTERNS:
        match = re.search(pattern, text)
        if match:
            detected_reasons.append(f"Delimiter Smuggling Detected: '{match.group(0)}'")

    for pattern in DECEPTIVE_PARAM_PATTERNS:
        match = re.search(pattern, text)
        if match:
            detected_reasons.append(f"Deceptive Parameter Tampering Detected: '{match.group(0)}'")

    is_injected = len(detected_reasons) > 0
    score = min(1.0, 0.4 * len(detected_reasons)) if is_injected else 0.0

    return is_injected, detected_reasons, score


def inspect_action_for_threats(
    tool_name: str,
    parameters: Dict[str, Any],
    raw_context: str = ""
) -> Tuple[bool, List[str], str]:
    """
    Inspects proposed action parameters and contextual background for injection vectors.
    """
    threats = []
    category = "PROMPT_INJECTION"

    # Scan raw context
    if raw_context:
        inj, reasons, _ = scan_for_injection(raw_context)
        if inj:
            threats.extend(reasons)

    # Recursively scan all parameter values
    def scan_val(val):
        if isinstance(val, str):
            inj, reasons, _ = scan_for_injection(val)
            if inj:
                threats.extend(reasons)
        elif isinstance(val, dict):
            for k, v in val.items():
                if isinstance(k, str):
                    inj, reasons, _ = scan_for_injection(k)
                    if inj:
                        threats.extend(reasons)
                scan_val(v)
        elif isinstance(val, list):
            for item in val:
                scan_val(item)

    scan_val(parameters)

    # Check for deceptive discrepancy between stated intent and parameter targets
    if tool_name == "wire_transfer":
        desc = str(parameters.get("memo", "")).lower()
        amount = parameters.get("amount", 0)
        # Check if memo claims a low amount or charity while actual amount is massive
        if ("routine" in desc or "donation" in desc or "petty cash" in desc) and amount > 50000:
            threats.append(f"Deceptive Behaviour: Memo claims routine/donation while transferring ${amount:,.2f}")
            category = "DECEPTIVE_BEHAVIOUR"

    return len(threats) > 0, threats, category
