"""
AegisRuntime - Chaos Engineering & Fail-Closed Simulator
Allows simulating outages, timeouts, and network disconnections in the
Verification Engine to test Scenario 5: Fail-Closed Enforcements.
"""

import threading

_CHAOS_STATE = {
    "engine_offline": False,
    "simulated_latency_ms": 0,
    "force_error": None
}

_LOCK = threading.Lock()


def set_engine_offline(offline: bool):
    """Toggles whether the Verification Engine is reachable or experiencing outage."""
    with _LOCK:
        _CHAOS_STATE["engine_offline"] = bool(offline)


def is_engine_offline() -> bool:
    """Checks if the Verification Engine has suffered an outage."""
    with _LOCK:
        return _CHAOS_STATE["engine_offline"]


def set_simulated_latency(ms: int):
    """Sets artificial delay on verification checks."""
    with _LOCK:
        _CHAOS_STATE["simulated_latency_ms"] = max(0, ms)


def get_chaos_status() -> dict:
    """Returns the current chaos engineering test configuration."""
    with _LOCK:
        return dict(_CHAOS_STATE)


def reset_chaos():
    """Resets all simulated faults."""
    with _LOCK:
        _CHAOS_STATE["engine_offline"] = False
        _CHAOS_STATE["simulated_latency_ms"] = 0
        _CHAOS_STATE["force_error"] = None
