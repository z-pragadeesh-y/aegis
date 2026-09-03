import os
import sys
import json
import time
import concurrent.futures
from filelock import FileLock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from target_system.stub_metrics import (
    STATE_FILE_PATH,
    LOCK_FILE_PATH,
    reset_state,
    read_state,
    load_all_states,
    save_all_states,
    BASELINE_DEGRADED_STATE
)
from sandbox.executor import execute_action_in_sandbox

def simulate_unlocked_read_modify_write(incident_id: str, new_cpu: float, delay_sec: float):
    """Simulates an un-locked read-modify-write cycle with an artificial delay to demonstrate lost updates."""
    all_states = load_all_states()
    time.sleep(delay_sec)  # Widen race window
    state = all_states.get(incident_id, BASELINE_DEGRADED_STATE.copy())
    state["cpu_percent"] = new_cpu
    state["status"] = "healthy"
    all_states[incident_id] = state
    save_all_states(all_states)

def run_unlocked_race_demonstration():
    print("\n--- 1. Demonstrating Un-locked Race Condition (Without FileLock) ---")
    ts = int(time.time())
    inc_a = f"race-unlocked-A-{ts}"
    inc_b = f"race-unlocked-B-{ts}"
    reset_state()
    read_state(inc_a)
    read_state(inc_b)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        # Process 1 reads at t=0, sleeps 0.4s before writing
        f1 = executor.submit(simulate_unlocked_read_modify_write, inc_a, 15.0, 0.4)
        # Process 2 reads at t=0.05s, writes healthy at t=0.15s
        time.sleep(0.05)
        f2 = executor.submit(simulate_unlocked_read_modify_write, inc_b, 20.0, 0.1)
        f1.result()
        f2.result()

    final_states = load_all_states()
    status_a = final_states.get(inc_a, {}).get("status")
    status_b = final_states.get(inc_b, {}).get("status")

    print(f"Un-locked Race Final Statuses: A={status_a}, B={status_b}")
    if status_b != "healthy":
        print("⚠️ DEMONSTRATION CONFIRMED: Without FileLock, Process 1 overwrote Process 2's write! 'race-unlocked-B' lost its update and reverted to degraded.")
    else:
        print("Un-locked attempt completed.")

def run_locked_concurrency_test() -> bool:
    print("\n--- 2. Testing Concurrent Writes WITH FileLock Protection ---")
    ts = int(time.time())
    inc_a = f"race-locked-A-{ts}"
    inc_b = f"race-locked-B-{ts}"
    reset_state()
    read_state(inc_a)
    read_state(inc_b)

    def simulate_locked_read_modify_write(incident_id: str, new_cpu: float, delay_sec: float):
        with FileLock(LOCK_FILE_PATH, timeout=10.0):
            all_states = load_all_states()
            time.sleep(delay_sec)
            state = all_states.get(incident_id, BASELINE_DEGRADED_STATE.copy())
            state["cpu_percent"] = new_cpu
            state["status"] = "healthy"
            all_states[incident_id] = state
            save_all_states(all_states)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(simulate_locked_read_modify_write, inc_a, 12.0, 0.2)
        time.sleep(0.05)
        f2 = executor.submit(simulate_locked_read_modify_write, inc_b, 18.0, 0.1)
        f1.result()
        f2.result()

    final_states = load_all_states()
    status_a = final_states.get(inc_a, {}).get("status")
    status_b = final_states.get(inc_b, {}).get("status")

    print(f"Locked Race Final Statuses: A={status_a}, B={status_b}")
    if status_a == "healthy" and status_b == "healthy":
        print("✅ SUCCESS: With FileLock, BOTH concurrent incident updates were safely preserved!")
        return True
    else:
        print("❌ FAIL: Lock test failed.")
        return False

def run_docker_sandbox_concurrency_test() -> bool:
    print("\n--- 3. Testing Real Concurrent Docker Sandbox Execution ---")
    ts = int(time.time())
    inc_a = f"inc-docker-A-{ts}"
    inc_b = f"inc-docker-B-{ts}"
    reset_state()
    read_state(inc_a)
    read_state(inc_b)

    print("Launching two Docker sandbox containers concurrently...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(execute_action_in_sandbox, "restart_service", incident_id=inc_a)
        f2 = executor.submit(execute_action_in_sandbox, "restart_service", incident_id=inc_b)
        res_a = f1.result()
        res_b = f2.result()

    print(f"Docker execution A result: success={res_a.get('success')}")
    print(f"Docker execution B result: success={res_b.get('success')}")

    with FileLock(LOCK_FILE_PATH, timeout=5.0):
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            full_data = json.load(f)

    print("\n--- Actual Raw state.json Contents Post-Concurrent Docker Execution ---")
    print(json.dumps(full_data, indent=2))

    has_docker_a = inc_a in full_data and full_data[inc_a].get("status") == "healthy"
    has_docker_b = inc_b in full_data and full_data[inc_b].get("status") == "healthy"

    if has_docker_a and has_docker_b:
        print("\n✅ PASSED: Both concurrent Docker sandbox executions safely updated state.json without data loss!")
        return True
    else:
        print("\n❌ FAILED: Data loss detected after concurrent Docker sandbox executions.")
        return False

def main():
    run_unlocked_race_demonstration()
    locked_success = run_locked_concurrency_test()
    docker_success = run_docker_sandbox_concurrency_test()
    if locked_success and docker_success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
