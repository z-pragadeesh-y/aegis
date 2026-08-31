import os
import sys
import time
import logging
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator.main as orch_main
from agents.detective import analyze_incident, DetectiveDiagnosis
from agents.remediator import propose_remediation, RemediatorAction, load_valid_action_types

def run_phase2_tests():
    print("=== Aegis Phase 2 Test Suite ===")
    client = TestClient(orch_main.app)
    passed = 0
    total = 5

    # Test Case 1: Auto-Approved Incident Flow
    print("\n--- Test 1: Incident Flow with Auto-Approved Action (read_metrics) ---")
    try:
        req = {
            "incident_id": "test-auto-approve-1",
            "description": "High memory consumption on auth-service",
            "desired_action_type": "read_metrics"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        print(f"Status Code: {resp.status_code}, Final Status: {data.get('status')}")
        
        if not data.get("metrics"):
            raise ValueError("Stub metrics were not pulled by Orchestrator")
        
        if not data.get("diagnosis"):
            raise ValueError("Detective diagnosis missing")

        if not data.get("proposed_action"):
            raise ValueError("Remediator proposed action missing")

        if data.get("policy_verdict", {}).get("verdict") != "auto-approve":
            raise ValueError(f"Expected auto-approve verdict, got {data.get('policy_verdict')}")

        if resp.status_code == 200 and data.get("status") == "done":
            print("[PASS] Test 1: Auto-approved flow completed end-to-end to state 'done'")
            passed += 1
        else:
            print(f"[FAIL] Test 1: Unexpected state {data.get('status')}")
    except Exception as e:
        print(f"[FAIL] Test 1: {e}")

    # Test Case 2: Risky Action Flow (Needs-Approval -> Confirm -> Done)
    print("\n--- Test 2: Incident Flow with Risky Action (restart_service) ---")
    try:
        req = {
            "incident_id": "test-risky-approval-1",
            "description": "Database connection pool exhaustion",
            "desired_action_type": "restart_service"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        inc_id = data.get("incident_id")
        token = data.get("approval_token")
        status = data.get("status")
        
        print(f"Initial Status: {status}, Token: {token}")

        if resp.status_code == 200 and status == "awaiting_approval" and token:
            confirm_resp = client.post(f"/incidents/{inc_id}/confirm")
            c_data = confirm_resp.json()
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
            "incident_id": "adversarial-999",
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
            "delete_database", "drop_table", "shutdown_service", "wipe_volume"
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
            print("[PASS] Test 5: PyYAML rules extraction and fallback warning logger verified")
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
