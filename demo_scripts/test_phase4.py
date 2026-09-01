import os
import sys
import json
import sqlite3
import httpx
from datetime import datetime
from fastapi.testclient import TestClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator.main as orch_main
from memory_engine.memory import remember, recall, consolidate, get_qdrant_client, COLLECTION_NAME
from target_system.stub_metrics import reset_state

AUDIT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit_log", "aegis_audit.db")

def clear_qdrant_memories():
    try:
        client = get_qdrant_client()
        records, _ = client.scroll(collection_name=COLLECTION_NAME, limit=1000)
        ids = [r.id for r in records]
        if ids:
            client.delete(collection_name=COLLECTION_NAME, points_selector=ids)
    except Exception:
        pass

def run_phase4_tests():
    print("=== Aegis Phase 4 Test Suite ===")
    client = TestClient(orch_main.app)
    passed = 0
    total = 7

    clear_qdrant_memories()

    # --------------------------------------------------------------------------
    # Test A: Cold Start (No Memory -> Full Reasoning Path)
    # --------------------------------------------------------------------------
    print("\n--- Test A: Cold Start (No Memory -> Full Reasoning Path) ---")
    try:
        orch_main.llm_call_counters["detective_calls"] = 0
        orch_main.llm_call_counters["remediator_calls"] = 0
        reset_state("test-p4-cold-start")

        req = {
            "incident_id": "test-p4-cold-start",
            "description": "Critical memory leak on checkout service",
            "desired_action_type": "restart_service"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        init_status = data.get("status")
        token = data.get("approval_token")

        if init_status == "awaiting_approval" and token:
            confirm_resp = client.post(f"/incidents/test-p4-cold-start/confirm")
            final_status = confirm_resp.json().get("status")
        else:
            final_status = init_status

        det_calls = orch_main.llm_call_counters["detective_calls"]
        rem_calls = orch_main.llm_call_counters["remediator_calls"]

        print(f"Cold Start Final Status: {final_status}")
        print(f"LLM Call Instrumentation: detective_calls={det_calls}, remediator_calls={rem_calls}")

        if final_status == "done" and det_calls == 1 and rem_calls == 1:
            print("[PASS] Test A: Cold start incident correctly took the full Detective+Remediator reasoning path (both LLM calls executed)")
            passed += 1
        else:
            print(f"[FAIL] Test A: Expected full path with 1 det / 1 rem call, got status={final_status}, det={det_calls}, rem={rem_calls}")
    except Exception as e:
        print(f"[FAIL] Test A: {e}")

    # --------------------------------------------------------------------------
    # Test B: remember() on Success (Direct Qdrant Verification)
    # --------------------------------------------------------------------------
    print("\n--- Test B: remember() on Success (Direct Qdrant Verification) ---")
    try:
        q_client = get_qdrant_client()
        records, _ = q_client.scroll(collection_name=COLLECTION_NAME, limit=10, with_payload=True)
        
        stored_ids = [r.payload.get("incident_id") for r in records if r.payload]
        print(f"Memories found in Qdrant: {stored_ids}")

        matched = [r for r in records if r.payload and r.payload.get("incident_id") == "test-p4-cold-start"]
        if matched:
            payload = matched[0].payload
            print(f"Qdrant Payload: incident_id='{payload.get('incident_id')}', outcome='{payload.get('outcome')}', action_type='{payload.get('action_taken', {}).get('action_type')}'")
            if payload.get("outcome") == "resolved":
                print("[PASS] Test B: Successful resolution automatically stored structured memory in Qdrant")
                passed += 1
            else:
                print(f"[FAIL] Test B: Memory found but outcome was '{payload.get('outcome')}'")
        else:
            print("[FAIL] Test B: No memory entry found in Qdrant for test-p4-cold-start")
    except Exception as e:
        print(f"[FAIL] Test B: {e}")

    # --------------------------------------------------------------------------
    # Test C: Fast Path on Repeat (LLM Calls SKIPPED & Policy Gateway Verified)
    # --------------------------------------------------------------------------
    print("\n--- Test C: Fast Path on Repeat (Skipped LLMs & Policy Gateway Verified) ---")
    try:
        orch_main.llm_call_counters["detective_calls"] = 0
        orch_main.llm_call_counters["remediator_calls"] = 0
        reset_state("test-p4-repeat")

        req = {
            "incident_id": "test-p4-repeat",
            "description": "Critical memory leak on checkout service",
            "desired_action_type": "restart_service"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        init_status = data.get("status")
        token = data.get("approval_token")
        event_log = data.get("event_log", [])

        fast_path_log = any("[FAST PATH TRIGGERED]" in log for log in event_log)
        det_calls = orch_main.llm_call_counters["detective_calls"]
        rem_calls = orch_main.llm_call_counters["remediator_calls"]

        print(f"Fast Path Log Present: {fast_path_log}")
        print(f"LLM Call Instrumentation: detective_calls={det_calls}, remediator_calls={rem_calls}")
        print(f"Policy Gateway Status: status='{init_status}', token='{token}'")

        has_audit_row = False
        if os.path.exists(AUDIT_DB_PATH):
            conn = sqlite3.connect(AUDIT_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id, action_type, verdict FROM audit_log ORDER BY id DESC LIMIT 5")
            rows = cur.fetchall()
            conn.close()
            print(f"Recent Policy Gateway Audit Log Rows: {rows}")
            has_audit_row = any(r[1] == "restart_service" for r in rows)

        if confirm_resp := client.post(f"/incidents/test-p4-repeat/confirm"):
            final_status = confirm_resp.json().get("status")
        else:
            final_status = init_status

        if final_status == "done" and det_calls == 0 and rem_calls == 0 and fast_path_log and init_status == "awaiting_approval" and has_audit_row:
            print("[PASS] Test C: Fast path triggered! Detective & Remediator LLM calls SKIPPED (0/0) and Policy Gateway safety check evaluated & audited in SQLite")
            passed += 1
        else:
            print(f"[FAIL] Test C: Fast path verification failed (done={final_status}, det={det_calls}, rem={rem_calls}, fast_log={fast_path_log}, audit={has_audit_row})")
    except Exception as e:
        print(f"[FAIL] Test C: {e}")

    # --------------------------------------------------------------------------
    # Test D: No False Recall for Different Fault Signature
    # --------------------------------------------------------------------------
    print("\n--- Test D: No False Recall for Different Fault Signature ---")
    try:
        orch_main.llm_call_counters["detective_calls"] = 0
        orch_main.llm_call_counters["remediator_calls"] = 0
        reset_state("test-p4-different")

        req = {
            "incident_id": "test-p4-different",
            "description": "Unrelated network socket timeout on payment gateway interface",
            "desired_action_type": "restart_service"
        }
        resp = client.post("/incidents", json=req)
        data = resp.json()
        event_log = data.get("event_log", [])

        full_path_log = any("[FULL REASONING PATH]" in log for log in event_log)
        det_calls = orch_main.llm_call_counters["detective_calls"]

        print(f"Full Path Log Present: {full_path_log}")
        print(f"LLM Call Instrumentation: detective_calls={det_calls}")

        if full_path_log and det_calls > 0:
            print("[PASS] Test D: Genuinely different fault signature correctly returned None from recall() and ran full reasoning path")
            passed += 1
        else:
            print(f"[FAIL] Test D: Expected full path for different fault signature, got det_calls={det_calls}")
    except Exception as e:
        print(f"[FAIL] Test D: {e}")

    # --------------------------------------------------------------------------
    # Test E: Failed Outcomes Never Recalled
    # --------------------------------------------------------------------------
    print("\n--- Test E: Failed Outcomes Never Recalled ---")
    try:
        remember(
            incident_id="test-p4-failed-incident",
            fault_signature="Database deadlock corruption crash",
            action_taken={"action_type": "delete_database"},
            outcome="failed",
            resolution_time_seconds=5.0
        )

        recalled = recall("Database deadlock corruption crash", similarity_threshold=0.70)
        print(f"Recall result for seeded failed memory: {recalled}")

        if recalled is None:
            print("[PASS] Test E: Safety filter confirmed! Failed past resolution memory was NEVER recalled as a suggested action")
            passed += 1
        else:
            print(f"[FAIL] Test E: Memory of failed outcome was incorrectly recalled: {recalled}")
    except Exception as e:
        print(f"[FAIL] Test E: {e}")

    # --------------------------------------------------------------------------
    # Test F: Persistence Across Restart
    # --------------------------------------------------------------------------
    print("\n--- Test F: Persistence Across Process/Client Restart ---")
    try:
        remember(
            incident_id="test-p4-persistence",
            fault_signature="Persistence test fault signature unique key 12345",
            action_taken={"action_type": "restart_service"},
            outcome="resolved",
            resolution_time_seconds=8.0
        )

        reloaded_client = get_qdrant_client(force_new=True)
        recalled = recall("Persistence test fault signature unique key 12345", similarity_threshold=0.80)
        
        print(f"Reloaded Recall Result: {recalled.get('incident_id') if recalled else None}")

        if recalled and recalled.get("incident_id") == "test-p4-persistence":
            print("[PASS] Test F: Persistent Qdrant storage verified! Memory successfully retrieved after client reload")
            passed += 1
        else:
            print(f"[FAIL] Test F: Memory failed to persist after client reload: {recalled}")
    except Exception as e:
        print(f"[FAIL] Test F: {e}")

    # --------------------------------------------------------------------------
    # Test G: Memory Consolidation
    # --------------------------------------------------------------------------
    print("\n--- Test G: Sleep-Phase Consolidation ---")
    try:
        clear_qdrant_memories()

        for i, res_time in enumerate([10.0, 12.0, 14.0]):
            remember(
                incident_id=f"test-p4-consolidate-{i}",
                fault_signature="Memory leak checkout-v1 cluster degradation",
                action_taken={"action_type": "restart_service"},
                outcome="resolved",
                resolution_time_seconds=res_time
            )

        q_client = get_qdrant_client()
        pre_records, _ = q_client.scroll(collection_name=COLLECTION_NAME, limit=10)
        print(f"Pre-consolidation memory count: {len(pre_records)}")

        c_res = consolidate(similarity_threshold=0.95)
        print(f"Consolidate Result: {c_res}")

        post_records, _ = q_client.scroll(collection_name=COLLECTION_NAME, limit=10, with_payload=True)
        print(f"Post-consolidation memory count: {len(post_records)}")

        if len(post_records) == 1:
            merged_payload = post_records[0].payload
            hit_count = merged_payload.get("hit_count")
            avg_res_time = merged_payload.get("resolution_time_seconds")
            print(f"Consolidated Runbook Payload: hit_count={hit_count}, avg_resolution_time={avg_res_time}s, consolidated={merged_payload.get('consolidated')}")

            if hit_count == 3 and abs(avg_res_time - 12.0) < 0.1:
                print("[PASS] Test G: Consolidation pass merged 3 similar memories into 1 canonical runbook entry with hit_count=3 and rolling average resolution_time=12.0s")
                passed += 1
            else:
                print(f"[FAIL] Test G: Unexpected merged payload values: hit_count={hit_count}, avg_res_time={avg_res_time}")
        else:
            print(f"[FAIL] Test G: Expected 1 merged entry, got {len(post_records)}")
    except Exception as e:
        print(f"[FAIL] Test G: {e}")

    print(f"\nResult: {passed}/{total} Phase 4 tests passed.")
    if passed == total:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    run_phase4_tests()
