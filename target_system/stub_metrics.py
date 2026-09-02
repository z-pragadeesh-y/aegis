import os
import json
from typing import Dict, Any, Optional
from filelock import FileLock

STATE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
LOCK_FILE_PATH = STATE_FILE_PATH + ".lock"

BASELINE_DEGRADED_STATE = {
    "cpu_percent": 92.0,
    "memory_percent": 85.0,
    "error_rate": 0.18,
    "status": "degraded"
}

def load_all_states() -> Dict[str, Dict[str, Any]]:
    """Loads state.json dictionary keyed by incident_id."""
    if not os.path.exists(STATE_FILE_PATH):
        return {}
    try:
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                if "cpu_percent" in data:
                    return {"default": data}
                return data
    except Exception:
        pass
    return {}

def save_all_states(all_states: Dict[str, Dict[str, Any]]):
    """Saves all incident states dictionary to state.json."""
    with open(STATE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(all_states, f, indent=2)

def reset_state(incident_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Resets state for a specific incident_id (or resets all if None) to BASELINE_DEGRADED_STATE.
    Protected by filelock across processes.
    """
    with FileLock(LOCK_FILE_PATH, timeout=10.0):
        all_states = load_all_states()
        if incident_id:
            all_states[incident_id] = BASELINE_DEGRADED_STATE.copy()
            save_all_states(all_states)
            return all_states[incident_id].copy()
        else:
            all_states = {}
            save_all_states(all_states)
            return BASELINE_DEGRADED_STATE.copy()

def read_state(incident_id: str = "default") -> Dict[str, Any]:
    """
    Reads specific incident's state from state.json, auto-initializing fresh
    BASELINE_DEGRADED_STATE for any incident_id not yet present.
    Protected by filelock across processes.
    """
    with FileLock(LOCK_FILE_PATH, timeout=10.0):
        all_states = load_all_states()
        if incident_id not in all_states or not isinstance(all_states[incident_id], dict) or "cpu_percent" not in all_states[incident_id]:
            all_states[incident_id] = BASELINE_DEGRADED_STATE.copy()
            save_all_states(all_states)
        return all_states[incident_id].copy()

def write_state(incident_id: str, new_state: dict):
    """
    Overwrites specified incident's state inside state.json.
    Protected by filelock across processes.
    """
    with FileLock(LOCK_FILE_PATH, timeout=10.0):
        all_states = load_all_states()
        all_states[incident_id] = new_state
        save_all_states(all_states)

def get_current_metrics(incident_id: str) -> dict:
    """
    Returns telemetry payload merging per-incident state.json numeric fields with simulated log lines.
    """
    current_state = read_state(incident_id)
    id_lower = incident_id.lower()
    
    if "memory" in id_lower or "oom" in id_lower:
        logs = [
            "ERROR: OutOfMemoryError: Java heap space",
            "WARNING: Worker process memory usage exceeded threshold (95%)",
            "ERROR: Service checkout-v1 health check failed (timeout)"
        ]
        active_conn = 450
    elif "cpu" in id_lower or "spike" in id_lower:
        logs = [
            "WARNING: CPU usage high contention on pool worker thread",
            "ERROR: Response latency 5200ms exceeds 500ms SLA limit"
        ]
        active_conn = 1200
    elif "routine" in id_lower or "health" in id_lower or "check" in id_lower:
        logs = [
            "INFO: System metrics operating within normal SLA parameters",
            "INFO: Health check status operational",
            "INFO: Telemetry metrics collection normal"
        ]
        active_conn = 100
    else:
        logs = [
            "ERROR: Connection pool exhaustion detected in DB driver",
            "WARNING: Response time spike on /api/v1/checkout - 4200ms",
            "ERROR: Database query timeout after 30s"
        ]
        active_conn = 600

    metrics = current_state.copy()
    metrics.update({
        "incident_id": incident_id,
        "active_connections": active_conn,
        "recent_log_lines": logs
    })
    return metrics
