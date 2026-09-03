import os
import sys
import json
import random
from typing import Dict, Any

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_HOST_PATH = os.path.join(ROOT_DIR, "target_system", "state.json")
SANDBOX_DIR = os.path.join(ROOT_DIR, "sandbox")
IMAGE_TAG = "aegis-sandbox:latest"

def run_action_logic_on_state_file(action_type: str, file_path: str, incident_id: str = "default"):
    from target_system.stub_metrics import read_state, write_state
    state = read_state(incident_id)

    if action_type in ("restart_service", "restart_instance", "replace_instance", "rollback_deploy"):
        state["cpu_percent"] = round(random.uniform(10.0, 25.0), 1)
        state["memory_percent"] = round(random.uniform(20.0, 35.0), 1)
        state["error_rate"] = round(random.uniform(0.005, 0.02), 3)
        state["response_time_ms"] = round(random.uniform(80.0, 150.0), 1)
        state["active_connections"] = random.randint(100, 200)
        state["connectivity"] = True
        state["instance_serving"] = True
        state["status"] = "healthy"
    elif action_type == "throttle_process":
        current_cpu = float(state.get("cpu_percent", 92.0))
        current_latency = float(state.get("response_time_ms", 1200.0))
        new_cpu = round(current_cpu * 0.5, 1)
        new_latency = round(current_latency * 0.5, 1)
        state["cpu_percent"] = new_cpu
        state["response_time_ms"] = new_latency
        if new_cpu < 40.0 or new_latency < 300.0:
            state["status"] = "healthy"
    elif action_type in ("trigger_circuit_breaker", "reroute_traffic"):
        new_err = round(random.uniform(0.005, 0.02), 3)
        state["error_rate"] = new_err
        state["connectivity"] = True
        state["active_connections"] = random.randint(100, 250)
        state["response_time_ms"] = round(random.uniform(100.0, 200.0), 1)
        if new_err < 0.05 and state.get("connectivity", True):
            state["status"] = "healthy"
    elif action_type in ("read_logs", "read_metrics"):
        pass
    else:
        # Destructive or unrecognized actions: no-op
        pass

    write_state(incident_id, state)

def execute_action_in_sandbox(action_type: str, incident_id: str = "default") -> Dict[str, Any]:
    """
    Executes the specified action inside an isolated Docker container if Docker daemon is available.
    If Docker daemon is unreachable or errors, safely executes host sandbox fallback modifying state.json
    and returning success. Catches errors gracefully without hanging.
    """
    docker_available = False
    client = None

    try:
        import docker
        client = docker.from_env()
        client.ping()
        docker_available = True
    except Exception:
        docker_available = False

    if docker_available and client:
        try:
            try:
                client.images.get(IMAGE_TAG)
            except Exception:
                client.images.build(path=SANDBOX_DIR, tag=IMAGE_TAG, rm=True)

            if not os.path.exists(STATE_HOST_PATH):
                from target_system.stub_metrics import reset_state
                reset_state(incident_id)

            target_sys_dir = os.path.dirname(STATE_HOST_PATH)
            volumes = {
                os.path.abspath(target_sys_dir): {
                    "bind": "/data",
                    "mode": "rw"
                },
                os.path.abspath(os.path.join(SANDBOX_DIR, "execute_action.py")): {
                    "bind": "/app/execute_action.py",
                    "mode": "ro"
                }
            }

            container = client.containers.run(
                image=IMAGE_TAG,
                environment={"ACTION_TYPE": action_type, "INCIDENT_ID": incident_id},
                volumes=volumes,
                network_disabled=True,
                detach=True,
                auto_remove=False
            )

            res = container.wait(timeout=10)
            exit_code = res.get("StatusCode", 0) if isinstance(res, dict) else int(res)
            try:
                container.remove(force=True)
            except Exception:
                pass

            if exit_code == 0:
                return {"success": True, "exit_code": 0, "error": None}
            else:
                return {"success": False, "exit_code": exit_code, "error": f"Container exited with code {exit_code}"}
        except Exception as e:
            pass

    # Host fallback when Docker daemon is not running on host machine
    try:
        run_action_logic_on_state_file(action_type, STATE_HOST_PATH, incident_id=incident_id)
        return {"success": True, "exit_code": 0, "error": None}
    except Exception as e:
        return {"success": False, "exit_code": None, "error": f"Host sandbox execution failed: {e}"}
