import os
import json
from typing import Dict, Any, Optional
from filelock import FileLock

STATE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
LOCK_FILE_PATH = STATE_FILE_PATH + ".lock"

HEALTHY_BASELINE_STATE = {
    "cpu_percent": 15.0,
    "memory_percent": 25.0,
    "error_rate": 0.01,
    "status": "healthy",
    "response_time_ms": 120.0,
    "active_connections": 150,
    "connectivity": True,
    "instance_serving": True
}

BASELINE_DEGRADED_STATE = {
    "cpu_percent": 92.0,
    "memory_percent": 85.0,
    "error_rate": 0.18,
    "status": "degraded",
    "response_time_ms": 1200.0,
    "active_connections": 600,
    "connectivity": True,
    "instance_serving": True
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

def reset_state(incident_id: Optional[str] = None, healthy: bool = False) -> Dict[str, Any]:
    """
    Resets state for a specific incident_id (or resets all if None) to BASELINE_DEGRADED_STATE
    or HEALTHY_BASELINE_STATE if healthy=True.
    Protected by filelock across processes.
    """
    target = HEALTHY_BASELINE_STATE if healthy else BASELINE_DEGRADED_STATE
    with FileLock(LOCK_FILE_PATH, timeout=10.0):
        all_states = load_all_states()
        if incident_id:
            all_states[incident_id] = target.copy()
            save_all_states(all_states)
            return all_states[incident_id].copy()
        else:
            all_states = {}
            save_all_states(all_states)
            return target.copy()

def read_state(incident_id: str = "default") -> Dict[str, Any]:
    """
    Reads specific incident's state from state.json, auto-initializing fresh
    BASELINE_DEGRADED_STATE for any incident_id not yet present.
    Ensures backward compatibility by supplying default values for new fields if missing.
    Protected by filelock across processes.
    """
    with FileLock(LOCK_FILE_PATH, timeout=10.0):
        all_states = load_all_states()
        if incident_id not in all_states or not isinstance(all_states[incident_id], dict) or "cpu_percent" not in all_states[incident_id]:
            all_states[incident_id] = BASELINE_DEGRADED_STATE.copy()
            save_all_states(all_states)
        else:
            state = all_states[incident_id]
            updated = False
            for k, v in BASELINE_DEGRADED_STATE.items():
                if k not in state:
                    state[k] = v
                    updated = True
            if updated:
                all_states[incident_id] = state
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
    Returns telemetry payload merging per-incident state.json fields with simulated log lines.
    """
    current_state = read_state(incident_id)
    id_lower = incident_id.lower()
    
    if "memory" in id_lower or "oom" in id_lower:
        logs = [
            "ERROR: OutOfMemoryError: Java heap space",
            "WARNING: Worker process memory usage exceeded threshold (95%)",
            "ERROR: Service checkout-v1 health check failed (timeout)"
        ]
    elif "cpu" in id_lower or "spike" in id_lower:
        logs = [
            "WARNING: CPU usage high contention on pool worker thread",
            "ERROR: Response latency exceeds SLA limit"
        ]
    elif "packet" in id_lower or "network" in id_lower or "loss" in id_lower:
        logs = [
            "ERROR: Packet loss detected across gateway interface eth0",
            "WARNING: TCP retransmission count exceeded threshold"
        ]
    elif "latency" in id_lower:
        logs = [
            "WARNING: High latency observed on service endpoints",
            "INFO: Downstream service response delayed"
        ]
    elif "pod" in id_lower or "instance" in id_lower:
        logs = [
            "WARNING: Instance registered in service mesh but not responding to health pings",
            "ERROR: Traffic routing failure to non-serving pod"
        ]
    elif "routine" in id_lower or "health" in id_lower or "check" in id_lower:
        logs = [
            "INFO: System metrics operating within normal SLA parameters",
            "INFO: Health check status operational",
            "INFO: Telemetry metrics collection normal"
        ]
    else:
        logs = [
            "ERROR: Connection pool exhaustion detected in DB driver",
            "WARNING: Response time spike on /api/v1/checkout",
            "ERROR: Query timeout after 30s"
        ]

    metrics = current_state.copy()
    metrics["incident_id"] = incident_id
    metrics["recent_log_lines"] = logs
    return metrics
