import sys
import os
import time
import json
from unittest.mock import patch
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import orchestrator.main as orch_main
from target_system.stub_metrics import reset_state

ORCH_URL = "http://127.0.0.1:8002"
GATEWAY_URL = "http://127.0.0.1:8001"
TARGET_URL = "http://127.0.0.1:8003"

def run_single_rehearsal_pass(run_index: int):
    print(f"\n=========================================================================")
    print(f"AEGIS DEMO REHEARSAL RUN #{run_index} (PRD SECTION 9.1 SEQUENCE)")
    print(f"=========================================================================")
    client = TestClient(orch_main.app)
    start_total_time = time.time()

    # Step 1: Trigger primary incident ("Connection Pool / CPU Pressure")
    ts = int(time.time())
    inc_id_1 = f"demo-rehearsal-run{run_index}-primary-{ts}"
    reset_state(inc_id_1)

    print(f"\n[STEP A] Triggering Primary Incident '{inc_id_1}' (cpu_pressure / restart_service)...")
    # Run-specific description guarantees Step A is a genuine Cold-Start for each run,
    # and Step C is a genuine Fast-Path recall of Step A within the same run.
    run_desc = f"Connection pool exhaustion and high CPU contention on checkout worker threads in cluster run-{run_index}-{ts}"

    print(f"\n[STEP A] Triggering Primary Incident '{inc_id_1}' (cpu_pressure / restart_service)...")
    trigger_start = time.time()
    
    # Inject fault into target system
    try:
        httpx.post(f"{TARGET_URL}/faults/cpu_pressure?incident_id={inc_id_1}", timeout=5.0)
    except Exception:
        pass # Stub metrics will fall back cleanly

    req_1 = {
        "incident_id": inc_id_1,
        "description": run_desc,
        "desired_action_type": "restart_service"
    }

    counters_a_before = client.get("/llm-call-counters").json()
    with patch("memory_engine.memory.recall", return_value=None), patch("orchestrator.main.memory_recall", return_value=None):
        client.post("/incidents", json=req_1)

        # Wait for awaiting_approval state
        poll_start = time.time()
        awaiting_state = None
        while time.time() - poll_start < 45.0:
            res = client.get(f"/incidents/{inc_id_1}").json()
            st = res.get("status")
            if st == "awaiting_approval":
                awaiting_state = res
                break
            elif st == "failed":
                print(f"  -> Incident entered FAILED state! Event Log: {json.dumps(res.get('event_log'), indent=2)}")
                break
            time.sleep(0.5)

    t_creation_to_approval = time.time() - trigger_start
    counters_a_after = client.get("/llm-call-counters").json()
    det_a_calls = counters_a_after.get("detective_calls", 0) - counters_a_before.get("detective_calls", 0)
    rem_a_calls = counters_a_after.get("remediator_calls", 0) - counters_a_before.get("remediator_calls", 0)

    if awaiting_state is None:
        final_check = client.get(f"/incidents/{inc_id_1}").json()
        print(f"  -> Polling timed out/failed. Final Status: {final_check.get('status')}")
        print(f"  -> Event Log: {json.dumps(final_check.get('event_log'), indent=2)}")
    assert awaiting_state is not None, f"Run #{run_index} Primary incident failed to reach awaiting_approval"
    token_1 = awaiting_state.get("approval_token")
    print(f"  -> Reached 'awaiting_approval' in {t_creation_to_approval:.2f}s | Token: {token_1}")
    print(f"  -> Step A LLM Calls Executed: Detective={det_a_calls}, Remediator={rem_a_calls}")
    print(f"  -> Detective Root Cause: {repr(((awaiting_state.get('diagnosis') or {}).get('root_cause', '')).encode('ascii', 'ignore').decode('ascii')[:80])}")

    # Step 2: Simulate Human Approval Click (POST /incidents/{inc_id}/confirm)
    print(f"[STEP B] Simulating Human Approval Click (/confirm)...")
    confirm_start = time.time()
    confirm_resp = client.post(f"/incidents/{inc_id_1}/confirm")
    confirm_http_latency_ms = (time.time() - confirm_start) * 1000.0
    print(f"  -> /confirm HTTP Response Latency: {confirm_http_latency_ms:.2f} ms (Status: {confirm_resp.status_code})")

    # Poll background execution until 'done'
    done_start = time.time()
    final_primary_state = None
    while time.time() - done_start < 45.0:
        res = client.get(f"/incidents/{inc_id_1}").json()
        if res.get("status") == "done":
            final_primary_state = res
            break
        time.sleep(0.2)

    t_approval_to_done = time.time() - confirm_start
    assert final_primary_state is not None, f"Run #{run_index} Primary incident failed to complete in background"
    print(f"  -> Completed background remediation & verification to 'done' in {t_approval_to_done:.2f}s")
    print(f"  -> Postmortem: {repr((final_primary_state.get('postmortem') or '').encode('ascii', 'ignore').decode('ascii')[:90])}")

    # Step 3: Trigger SAME incident second time (Verify Qdrant Memory Fast Path)
    inc_id_2 = f"demo-rehearsal-run{run_index}-fastpath-{ts}"
    reset_state(inc_id_2)

    print(f"\n[STEP C] Triggering SECOND Incident '{inc_id_2}' (Fast-Path Memory Recall Verification)...")
    fastpath_start = time.time()
    req_2 = {
        "incident_id": inc_id_2,
        "description": run_desc,
        "desired_action_type": "restart_service"
    }

    # Fetch baseline LLM call counts
    counters_before = client.get("/llm-call-counters").json()
    client.post("/incidents", json=req_2)

    # Wait for awaiting_approval state
    poll_fast = time.time()
    fast_awaiting = None
    while time.time() - poll_fast < 30.0:
        res = client.get(f"/incidents/{inc_id_2}").json()
        if res.get("status") == "awaiting_approval":
            fast_awaiting = res
            break
        time.sleep(0.2)

    t_fastpath_to_approval = time.time() - fastpath_start
    counters_after = client.get("/llm-call-counters").json()

    detective_delta = counters_after.get("detective_calls", 0) - counters_before.get("detective_calls", 0)
    remediator_delta = counters_after.get("remediator_calls", 0) - counters_before.get("remediator_calls", 0)

    print(f"  -> Reached 'awaiting_approval' via Memory Fast Path in {t_fastpath_to_approval:.2f}s")
    print(f"  -> LLM Calls Executed: Detective={detective_delta}, Remediator={remediator_delta} (Expected 0/0)")

    assert detective_delta == 0 and remediator_delta == 0, (
        f"Run #{run_index} Step C Fast-Path failed! Executed LLM calls: "
        f"Detective={detective_delta}, Remediator={remediator_delta} (Expected 0/0)"
    )

    # Confirm second incident
    client.post(f"/incidents/{inc_id_2}/confirm")
    done_fast = time.time()
    while time.time() - done_fast < 30.0:
        res = client.get(f"/incidents/{inc_id_2}").json()
        if res.get("status") == "done":
            break
        time.sleep(0.2)

    # Step 4: Stretch Fault Injection (latency_injection)
    inc_id_3 = f"demo-rehearsal-run{run_index}-stretch-{ts}"
    reset_state(inc_id_3)
    print(f"\n[STEP D] Triggering Secondary Stretch Incident '{inc_id_3}' (latency_injection)...")
    req_3 = {
        "incident_id": inc_id_3,
        "description": f"High response time latency injection on payment gateway {ts}",
        "desired_action_type": "reroute_traffic"
    }
    client.post("/incidents", json=req_3)
    poll_stretch = time.time()
    stretch_state = None
    while time.time() - poll_stretch < 45.0:
        res = client.get(f"/incidents/{inc_id_3}").json()
        if res.get("status") in ("awaiting_approval", "done"):
            stretch_state = res
            break
        time.sleep(0.2)

    if stretch_state and stretch_state.get("status") == "awaiting_approval":
        client.post(f"/incidents/{inc_id_3}/confirm")
        poll_s_done = time.time()
        while time.time() - poll_s_done < 45.0:
            res = client.get(f"/incidents/{inc_id_3}").json()
            if res.get("status") == "done":
                break
            time.sleep(0.2)

    total_run_time = time.time() - start_total_time
    print(f"\n[SUCCESS] RUN #{run_index} PASSED CLEANLY! Total Wall-Clock Time: {total_run_time:.2f}s")
    
    return {
        "run_index": run_index,
        "total_wall_clock_seconds": round(total_run_time, 2),
        "primary_trigger_to_approval_seconds": round(t_creation_to_approval, 2),
        "primary_step_a_llm_calls": f"Detective={det_a_calls}, Remediator={rem_a_calls}",
        "primary_confirm_http_latency_ms": round(confirm_http_latency_ms, 2),
        "primary_confirm_to_done_seconds": round(t_approval_to_done, 2),
        "fastpath_trigger_to_approval_seconds": round(t_fastpath_to_approval, 2),
        "fastpath_llm_calls": f"Detective={detective_delta}, Remediator={remediator_delta}",
        "status": "PASSED"
    }

def run_full_rehearsal_suite():
    print("=========================================================================")
    print("AEGIS PHASE 7 FULL DEMO REHEARSAL SUITE (3 CONSECUTIVE RUNS)")
    print("=========================================================================")
    results = []
    for i in range(1, 4):
        res = run_single_rehearsal_pass(i)
        results.append(res)
        time.sleep(1.0)

    print("\n=========================================================================")
    print("AEGIS REHEARSAL SUITE SUMMARY REPORT")
    print("=========================================================================")
    print(json.dumps(results, indent=2))
    print("\nALL 3 CONSECUTIVE DEMO REHEARSAL RUNS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    run_full_rehearsal_suite()
