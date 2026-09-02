import os
import sys
import json
import time
import httpx
import threading
from unittest.mock import patch
from fastapi.testclient import TestClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator.main as orch_main
from target_system.stub_metrics import reset_state, read_state, write_state, load_all_states
from agents.remediator import load_valid_action_types

def run_phase3_tests():
    print("=== Aegis Phase 3 Test Suite ===")
    client = TestClient(orch_main.app)
    passed = 0
    total = 8

    # Test 1: Auto-approved flow (read_metrics) through full pipeline to done with postmortem
    print("\n--- Test 1: Auto-Approved Incident Pipeline (read_metrics) ---")
    try:
        reset_state()
        write_state("test-routine-health-1", {"cpu_percent": 22.0, "memory_percent": 45.0, "error_rate": 0.01, "status": "healthy"})
        req = {
            "incident_id": "test-routine-health-1",
            "description": "Routine metric health check",
            "desired_action_type": "read_metrics"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        status = data.get("status")
        postmortem = data.get("postmortem") or ""

        print(f"Final Status: {status}")
        print(f"Postmortem Snippet: {repr(postmortem[:80])}")

        if resp.status_code == 200 and status == "done" and postmortem and len(postmortem.strip()) > 10:
            print("[PASS] Test 1: Auto-approved flow automatically executed full pipeline to 'done' with non-empty postmortem")
            passed += 1
        else:
            print(f"[FAIL] Test 1: Expected status 'done' with postmortem, got status='{status}'")
    except Exception as e:
        print(f"[FAIL] Test 1: {e}")

    # Test 2: Risky action flow (restart_service) + state.json mutation check
    print("\n--- Test 2: Risky Action Pipeline & Real state.json Mutation (restart_service) ---")
    try:
        initial_state = reset_state("test-p3-risky-1")
        print(f"Initial state.json baseline for test-p3-risky-1: {initial_state}")
        
        req = {
            "incident_id": "test-p3-risky-1",
            "description": "Critical memory leak on checkout service",
            "desired_action_type": "restart_service"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        inc_id = data.get("incident_id")
        token = data.get("approval_token")
        init_status = data.get("status")

        print(f"Initial Status: {init_status}, Token: {token}")

        if resp.status_code == 200 and init_status == "awaiting_approval" and token:
            confirm_resp = client.post(f"/incidents/{inc_id}/confirm")
            c_data = confirm_resp.json()
            final_status = c_data.get("status")
            postmortem = c_data.get("postmortem") or ""
            
            print(f"Post-Confirm Status: {final_status}")
            print(f"Postmortem: {repr(postmortem[:100])}")

            after_state = read_state("test-p3-risky-1")
            print(f"After state.json content for test-p3-risky-1: {after_state}")

            cpu_changed = after_state.get("cpu_percent") != initial_state.get("cpu_percent")
            err_changed = after_state.get("error_rate") != initial_state.get("error_rate")
            status_healthy = after_state.get("status") == "healthy"

            if final_status == "done" and postmortem and cpu_changed and err_changed and status_healthy:
                print("[PASS] Test 2: Risky action paused at awaiting_approval, confirmed -> automatically completed pipeline -> done with real state.json mutation (status='healthy')")
                passed += 1
            else:
                print(f"[FAIL] Test 2: Pipeline completion or state.json mutation failed (status={final_status}, healthy={status_healthy}, cpu_changed={cpu_changed})")
        else:
            print(f"[FAIL] Test 2: Failed to land in awaiting_approval, got status={init_status}")
    except Exception as e:
        print(f"[FAIL] Test 2: {e}")

    # Test 3: Policy Gateway Unreachable Graceful Degradation
    print("\n--- Test 3: Graceful Degradation on Policy Gateway Unreachable ---")
    try:
        reset_state("test-p3-gw-fail-1")
        with patch("agents.remediator.httpx.post", side_effect=httpx.ConnectError("Gateway connection refused")):
            req = {
                "incident_id": "test-p3-gw-fail-1",
                "description": "Test policy gateway unreachable error handling",
                "desired_action_type": "read_metrics"
            }
            resp = client.post("/incidents", json=req)
            data = resp.json()
            status = data.get("status")
            event_log = data.get("event_log", [])
            print(f"Final Status: {status}")
            
            has_error_log = any("Policy Gateway unreachable" in log or "failed" in log for log in event_log)
            if resp.status_code == 200 and status == "failed" and has_error_log:
                print("[PASS] Test 3: Policy Gateway connection error cleanly set status to 'failed' with clear error log")
                passed += 1
            else:
                print(f"[FAIL] Test 3: Expected status 'failed', got '{status}'")
    except Exception as e:
        print(f"[FAIL] Test 3: {e}")

    # Test 4: Sandbox Execution Failure Graceful Degradation
    print("\n--- Test 4: Graceful Degradation on Docker Sandbox Failure ---")
    try:
        reset_state("test-p3-sandbox-fail-1")
        mock_sandbox_res = {"success": False, "exit_code": None, "error": "docker unreachable"}
        with patch("orchestrator.main.execute_action_in_sandbox", return_value=mock_sandbox_res):
            req = {
                "incident_id": "test-p3-sandbox-fail-1",
                "description": "Test docker sandbox failure handling",
                "desired_action_type": "read_metrics"
            }
            resp = client.post("/incidents", json=req)
            data = resp.json()
            status = data.get("status")
            event_log = data.get("event_log", [])
            print(f"Final Status: {status}")

            has_sandbox_log = any("Sandboxed execution failed" in log or "docker unreachable" in log for log in event_log)
            if resp.status_code == 200 and status == "failed" and has_sandbox_log:
                print("[PASS] Test 4: Docker sandbox failure cleanly set status to 'failed' without attempting verification")
                passed += 1
            else:
                print(f"[FAIL] Test 4: Expected status 'failed', got '{status}'")
    except Exception as e:
        print(f"[FAIL] Test 4: {e}")

    # Test 5: Verifier local sanity check override test
    print("\n--- Test 5: Verifier Local Sanity Check Override ---")
    try:
        from agents.verifier import verify_remediation, VerifierResult
        before = {"cpu_percent": 92.0, "error_rate": 0.18, "status": "degraded"}
        after = {"cpu_percent": 95.0, "error_rate": 0.20, "status": "degraded"}
        
        mock_llm_payload = {"resolved": True, "summary": "LLM mistakenly claims issue is resolved", "confidence": 0.9}
        with patch("agents.verifier.groq.Groq") as mock_groq_cls:
            mock_client = mock_groq_cls.return_value
            mock_choice = type("Choice", (), {"message": type("Message", (), {"content": json.dumps(mock_llm_payload)})()})()
            mock_client.chat.completions.create.return_value = type("Completion", (), {"choices": [mock_choice]})()
            
            res = verify_remediation("restart_service", before, after)
            print(f"Verifier result on degraded metrics: resolved={res.resolved}, summary={repr(res.summary)}")
            if res.resolved is False and "[OVERRIDE]" in res.summary:
                print("[PASS] Test 5: Local deterministic sanity check correctly overrode invalid LLM verdict to resolved=False")
                passed += 1
            else:
                print(f"[FAIL] Test 5: Expected override to resolved=False, got resolved={res.resolved}")
    except Exception as e:
        print(f"[FAIL] Test 5: {e}")

    # Test 6: Remediator dynamic 13 action types check preserved
    print("\n--- Test 6: Remediator Dynamic Action Types Extraction Preserved ---")
    try:
        rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policy_gateway", "rules.yaml")
        extracted_actions = load_valid_action_types(rules_path)
        if len(extracted_actions) == 13:
            print(f"[PASS] Test 6: Remediator action types extraction preserved ({len(extracted_actions)} items)")
            passed += 1
        else:
            print(f"[FAIL] Test 6: Expected 13 action types, got {len(extracted_actions)}")
    except Exception as e:
        print(f"[FAIL] Test 6: {e}")

    # Test 7: Per-Incident State Isolation Test
    print("\n--- Test 7: Per-Incident State Isolation Test ---")
    try:
        reset_state()
        
        # 1. Start incident-alpha and resolve to healthy
        req_a = {"incident_id": "incident-alpha", "description": "Memory leak on alpha", "desired_action_type": "restart_service"}
        resp_a = client.post("/incidents", json=req_a)
        data_a = resp_a.json()
        client.post(f"/incidents/incident-alpha/confirm")
        
        alpha_state = read_state("incident-alpha")
        print(f"Incident A ('incident-alpha') state after resolution: {alpha_state}")

        # 2. Immediately start incident-beta
        req_b = {"incident_id": "incident-beta", "description": "High CPU on beta", "desired_action_type": "restart_service"}
        resp_b = client.post("/incidents", json=req_b)
        data_b = resp_b.json()

        beta_initial_metrics = data_b.get("metrics", {})
        print(f"Incident B ('incident-beta') initial Detective metrics: status='{beta_initial_metrics.get('status')}', cpu={beta_initial_metrics.get('cpu_percent')}%, err={beta_initial_metrics.get('error_rate')}")

        all_states_dump = load_all_states()
        print(f"Full state.json content after multiple incidents:\n{json.dumps(all_states_dump, indent=2)}")

        is_beta_degraded = beta_initial_metrics.get("status") == "degraded" and beta_initial_metrics.get("cpu_percent") == 92.0
        is_alpha_healthy = alpha_state.get("status") == "healthy"
        has_multiple_keys = "incident-alpha" in all_states_dump and "incident-beta" in all_states_dump

        if is_beta_degraded and is_alpha_healthy and has_multiple_keys:
            print("[PASS] Test 7: Per-incident state isolation confirmed (Incident B received fresh degraded baseline independent of Incident A's healthy state)")
            passed += 1
        else:
            print(f"[FAIL] Test 7: Per-incident isolation failed (beta_degraded={is_beta_degraded}, alpha_healthy={is_alpha_healthy}, multiple_keys={has_multiple_keys})")
    except Exception as e:
        print(f"[FAIL] Test 7: {e}")

    # Test 8: Concurrency Intermediate Status Polling Test
    print("\n--- Test 8: Concurrency & Intermediate Status Polling Test ---")
    try:
        unique_inc_id = f"test-p3-conc-{int(time.time())}"
        reset_state(unique_inc_id)
        base_url = "http://127.0.0.1:8002"
        
        req = {"incident_id": unique_inc_id, "description": "Concurrency status test", "desired_action_type": "restart_service"}
        resp = httpx.post(f"{base_url}/incidents", json=req, timeout=10.0)
        data = resp.json()
        inc_id = data.get("incident_id")
        token = data.get("approval_token")

        polled_statuses = []
        stop_polling = threading.Event()

        def poll_status():
            client_poll = httpx.Client(base_url=base_url)
            while not stop_polling.is_set():
                try:
                    r = client_poll.get(f"/incidents/{inc_id}", timeout=2.0)
                    if r.status_code == 200:
                        st = r.json().get("status")
                        if not polled_statuses or polled_statuses[-1] != st:
                            polled_statuses.append(st)
                except Exception:
                    pass
                time.sleep(0.05)

        poll_thread = threading.Thread(target=poll_status)
        poll_thread.start()

        # Call confirm over HTTP in main thread while polling runs in background thread
        confirm_resp = httpx.post(f"{base_url}/incidents/{inc_id}/confirm", timeout=60.0)
        stop_polling.set()
        poll_thread.join()

        final_c_status = confirm_resp.json().get("status")
        if not polled_statuses or polled_statuses[-1] != final_c_status:
            polled_statuses.append(final_c_status)

        print(f"Captured status sequence during /confirm call: {polled_statuses}")

        intermediate_statuses = [s for s in polled_statuses if s not in ("awaiting_approval", "done")]
        distinct_intermediates = set(intermediate_statuses)

        if len(distinct_intermediates) >= 2:
            print(f"[PASS] Test 8: Concurrency confirmed! Polled {len(distinct_intermediates)} distinct intermediate status values ({list(distinct_intermediates)}) during in-flight /confirm call.")
            passed += 1
        else:
            print(f"[FAIL] Test 8: Captured intermediate statuses: {polled_statuses}. Expected at least 2 distinct intermediate statuses.")
    except Exception as e:
        print(f"[FAIL] Test 8: {e}")

    print(f"\nResult: {passed}/{total} Phase 3 tests passed.")
    if passed == total:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    run_phase3_tests()
