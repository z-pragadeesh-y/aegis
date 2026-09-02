import os
import json
import random
import sys
from filelock import FileLock

STATE_FILE = "/data/state.json"
LOCK_FILE = "/data/state.json.lock"

BASELINE_DEGRADED_STATE = {
    "cpu_percent": 92.0,
    "memory_percent": 85.0,
    "error_rate": 0.18,
    "status": "degraded"
}

def main():
    action_type = os.getenv("ACTION_TYPE", "").strip()
    incident_id = os.getenv("INCIDENT_ID", "default").strip()

    with FileLock(LOCK_FILE, timeout=10.0):
        if not os.path.exists(STATE_FILE):
            print(f"State file {STATE_FILE} not found")
            sys.exit(0)

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                all_states = json.load(f)
                if not isinstance(all_states, dict):
                    all_states = {}
        except Exception as e:
            print(f"Error reading state file: {e}")
            all_states = {}

        if "cpu_percent" in all_states:
            all_states = {"default": all_states}

        state = all_states.get(incident_id, BASELINE_DEGRADED_STATE.copy())

        if action_type in ("restart_service", "restart_instance", "replace_instance", "rollback_deploy"):
            state["cpu_percent"] = round(random.uniform(10.0, 25.0), 1)
            state["error_rate"] = round(random.uniform(0.005, 0.02), 3)
            state["status"] = "healthy"
        elif action_type == "throttle_process":
            current_cpu = float(state.get("cpu_percent", 92.0))
            new_cpu = round(current_cpu * 0.5, 1)
            state["cpu_percent"] = new_cpu
            if new_cpu < 40.0:
                state["status"] = "healthy"
        elif action_type in ("trigger_circuit_breaker", "reroute_traffic"):
            new_err = round(random.uniform(0.005, 0.02), 3)
            state["error_rate"] = new_err
            if new_err < 0.05:
                state["status"] = "healthy"
        elif action_type in ("read_logs", "read_metrics"):
            pass
        else:
            # Destructive or unrecognized actions: no-op
            pass

        all_states[incident_id] = state

        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(all_states, f, indent=2)
        except Exception as e:
            print(f"Error writing state file: {e}")

    sys.exit(0)

if __name__ == "__main__":
    main()
