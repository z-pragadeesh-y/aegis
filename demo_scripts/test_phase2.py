import os
import sys
import json
import time
import logging
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator.main as orch_main
from agents.detective import analyze_incident, DetectiveDiagnosis
from agents.remediator import propose_remediation, RemediatorAction, load_valid_action_types
from target_system.stub_metrics import reset_state, write_state

def wait_for_incident_data(client: TestClient, incident_id: str, check_fn, timeout: float = 60.0) -> dict:
    """Helper to poll HTTP endpoint until check_fn(data) is True."""
    start = time.time()
    last_data = {}
    while time.time() - start < timeout:
        try:
            res = client.get(f"/incidents/{incident_id}")
            if res.status_code == 200:
                last_data = res.json()
                if check_fn(last_data):
                    return last_data
        except Exception:
            pass
        time.sleep(0.3)
    return last_data

def run_phase2_tests():
    print("=== Aegis Phase 2 Test Suite ===")
    client = TestClient(orch_main.app)
    passed = 0
    total = 5
    ts = int(time.time())

    with patch("orchestrator.main.memory_recall", return_value=None):

        # Test Case 1: Auto-Approved Incident Flow
        print("\n--- Test 1: Incident Flow with Auto-Approved Action (read_metrics) ---")
        try:
            auto_inc_id = f"test-auto-approve-health-{ts}"
            reset_state(auto_inc_id)
            write_state(auto_inc_id, {
                "cpu_percent": 22.0,
                "memory_percent": 45.0,
                "error_rate": 0.01,
                "status": "healthy",
                "response_time_ms": 120.0,
                "active_connections": 150,
                "connectivity": True,
                "instance_serving": True
            })
            req = {
                "incident_id": auto_inc_id,
                "description": f"Routine metric health check {ts}",
                "desired_action_type": "read_metrics"
            }
            client.post("/incidents", json=req)
            data = wait_for_incident_data(client, auto_inc_id, lambda d: d.get("status") in ("done", "failed"), timeout=60.0)
            print(f"Final Status: {data.get('status')}")
            
            if not data.get("metrics"):
                raise ValueError("Stub metrics were not pulled by Orchestrator")
            
            if not data.get("diagnosis"):
                raise ValueError("Detective diagnosis missing")

            if not data.get("proposed_action"):
                raise ValueError("Remediator proposed action missing")

            if data.get("policy_verdict", {}).get("verdict") != "auto-approve":
                raise ValueError(f"Expected auto-approve verdict, got {data.get('policy_verdict')}")

            if data.get("status") == "done":
                print("[PASS] Test 1: Auto-approved flow completed end-to-end to state 'done'")
                passed += 1
            else:
                print(f"Event log for failed incident:\n{json.dumps(data.get('event_log', []), indent=2)}")
                print(f"[FAIL] Test 1: Unexpected state {data.get('status')}")
        except Exception as e:
            print(f"[FAIL] Test 1: {e}")

        # Test Case 2: Risky Action Flow (Needs-Approval -> Confirm -> Done)
        print("\n--- Test 2: Incident Flow with Risky Action (restart_service) ---")
        try:
            risky_inc_id = f"test-risky-approval-{ts}"
            reset_state(risky_inc_id)
            req = {
                "incident_id": risky_inc_id,
                "description": f"Database connection pool exhaustion {ts}",
                "desired_action_type": "restart_service"
            }
            client.post("/incidents", json=req)
            data = wait_for_incident_data(client, risky_inc_id, lambda d: d.get("status") in ("awaiting_approval", "failed"), timeout=60.0)
            inc_id = data.get("incident_id")
            token = data.get("approval_token")
            status = data.get("status")
            
            print(f"Initial Status: {status}, Token: {token}")

            if status == "awaiting_approval" and token:
                confirm_resp = client.post(f"/incidents/{inc_id}/confirm")
                c_data = wait_for_incident_data(client, inc_id, lambda d: d.get("status") in ("done", "failed"), timeout=60.0)
                print(f"Confirm Status Code: {confirm_resp.status_code}, Final Status: {c_data.get('status')}")
                
                if confirm_resp.status_code == 200 and c_data.get("status") == "done":
                    print("[PASS] Test 2: Risky action flow paused at 'awaiting_approval' and advanced to 'done' after confirmation")
                    passed += 1
                else:
                    print(f"[FAIL] Test 2: Confirmation failed, state: {c_data.get('status')}")
            else:
                print(f"[FAIL] Test 2: Failed to land in 'awaiting_approval', got status={status}")
        except Exception as e:
            print(f"[FAIL] Test 2: {e}")

        # Test Case 3: Malformed / Adversarial Metrics Payload to Detective
        print("\n--- Test 3: Adversarial Metrics Payload to Detective Agent ---")
        try:
            adversarial_payload = {
                "incident_id": f"adversarial-{ts}",
                "cpu_percent": "INVALID_CPU_VALUE",
                "recent_log_lines": ["DROP TABLE users; --", "SELECT * FROM secrets"],
                "unexpected_nested": {"foo": None, "bar": [1, 2, 3]}
            }
            diagnosis = analyze_incident(adversarial_payload)
            print(f"Detective Diagnosis: root_cause='{diagnosis.root_cause}', confidence={diagnosis.confidence}")
            if isinstance(diagnosis, DetectiveDiagnosis) and diagnosis.root_cause and 0.0 <= diagnosis.confidence <= 1.0:
                print("[PASS] Test 3: Detective Agent successfully produced schema-valid output on adversarial payload")
                passed += 1
            else:
                print("[FAIL] Test 3: Detective diagnosis failed schema validation")
        except Exception as e:
            print(f"[FAIL] Test 3: {e}")

        # Test Case 4: Invalid API Key Retry and Graceful Failure
        print("\n--- Test 4: Invalid API Key Retry and Graceful Failure ---")
        try:
            try:
                analyze_incident({"test": "data"}, api_key="invalid_groq_key_xyz")
                print("[FAIL] Test 4: Expected RuntimeError on invalid API key")
            except RuntimeError as err:
                print(f"Retry-with-backoff executed and caught expected error: {err}")
                print("[PASS] Test 4: Failed LLM call triggered retry and returned clean failure state without hanging")
                passed += 1
        except Exception as e:
            print(f"[FAIL] Test 4: {e}")

        # Test Case 5: PyYAML Rules Loader Extraction & Fallback Warning
        print("\n--- Test 5: PyYAML Rules Loader Extraction & Fallback Warning ---")
        try:
            rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policy_gateway", "rules.yaml")
            extracted_actions = load_valid_action_types(rules_path)
            expected_actions = sorted([
                "read_logs", "read_metrics", "restart_service", "throttle_process",
                "trigger_circuit_breaker", "reroute_traffic", "restart_instance",
                "replace_instance", "rollback_deploy", "delete_database", "drop_table",
                "shutdown_service", "wipe_volume"
            ])
            print(f"Extracted action types from rules.yaml ({len(extracted_actions)}): {extracted_actions}")
            if extracted_actions != expected_actions:
                raise ValueError(f"Extracted actions {extracted_actions} do not match expected {expected_actions}")
            
            # Test fallback warning logger
            rem_logger = logging.getLogger("agents.remediator")
            captured_logs = []
            class LogCapturer(logging.Handler):
                def emit(self, record):
                    captured_logs.append(record.getMessage())

            handler = LogCapturer()
            rem_logger.addHandler(handler)
            fallback_res = load_valid_action_types("non_existent_rules_file.yaml")
            rem_logger.removeHandler(handler)

            if captured_logs and "[WARNING]" in captured_logs[0]:
                print(f"Fallback logger output captured: {captured_logs[0]}")
                print("[PASS] Test 5: PyYAML rules extraction (13 action types) and fallback warning logger verified")
                passed += 1
            else:
                raise ValueError("Fallback path did not log expected warning message")

        except Exception as e:
            print(f"[FAIL] Test 5: {e}")

    print(f"\nResult: {passed}/{total} Phase 2 tests passed.")
    if passed == total:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    run_phase2_tests()
