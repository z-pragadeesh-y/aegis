import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import orchestrator.main as orch_main
from target_system.stub_metrics import reset_state

def test_async_confirm_latency():
    print("=== Phase 7 Async /confirm Latency & Background Execution Test ===")
    client = TestClient(orch_main.app)
    ts = int(time.time())
    inc_id = f"test-p7-async-{ts}"
    reset_state(inc_id)

    # 1. Trigger incident with risky action (restart_service)
    req = {
        "incident_id": inc_id,
        "description": f"Async confirm latency verification {ts}",
        "desired_action_type": "restart_service"
    }
    client.post("/incidents", json=req)

    # 2. Wait until incident reaches awaiting_approval
    start_poll = time.time()
    while time.time() - start_poll < 30:
        res = client.get(f"/incidents/{inc_id}").json()
        if res.get("status") == "awaiting_approval":
            break
        time.sleep(0.1)

    assert client.get(f"/incidents/{inc_id}").json().get("status") == "awaiting_approval"
    print(f"Incident '{inc_id}' successfully paused at 'awaiting_approval'.")

    # 3. Call POST /incidents/{inc_id}/confirm and measure precise HTTP wall-clock latency
    confirm_start = time.time()
    confirm_resp = client.post(f"/incidents/{inc_id}/confirm")
    confirm_elapsed_ms = (time.time() - confirm_start) * 1000.0

    print(f"POST /incidents/{inc_id}/confirm Response Code: {confirm_resp.status_code}")
    print(f"POST /incidents/{inc_id}/confirm Response Latency: {confirm_elapsed_ms:.2f} ms")

    # Assert HTTP response returned in under 500ms
    assert confirm_resp.status_code == 200
    assert confirm_elapsed_ms < 500.0, f"Expected confirm latency < 500ms, got {confirm_elapsed_ms:.2f}ms"
    print(f"[PASS] /confirm returned immediately in {confirm_elapsed_ms:.2f} ms (< 500ms threshold)!")

    # 4. Verify background execution continues to 'done'
    print("Polling incident status in background until terminal 'done' state...")
    poll_bg_start = time.time()
    final_status = "unknown"
    while time.time() - poll_bg_start < 45:
        res = client.get(f"/incidents/{inc_id}").json()
        st = res.get("status")
        if st == "done":
            final_status = "done"
            break
        time.sleep(0.2)

    print(f"Final Background Execution Status: '{final_status}'")
    assert final_status == "done", f"Expected background execution to reach 'done', got {final_status}"
    print("[PASS] Background remediation and verification completed successfully to 'done'!")
    return confirm_elapsed_ms

if __name__ == "__main__":
    test_async_confirm_latency()
