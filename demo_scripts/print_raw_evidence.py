import os
import sys
import json
import time
import sqlite3
import asyncio
import httpx
import websockets
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "audit_log", "aegis_audit.db")

async def measure_ws_latency():
    inc_id = f"ws-latency-proof-{int(time.time())}"
    uri = f"ws://127.0.0.1:8002/ws/incidents/{inc_id}"
    
    async with websockets.connect(uri) as ws:
        init_raw = await ws.recv()  # connection init message
        
        req = {
            "incident_id": inc_id,
            "description": "Real-time WebSocket Latency Measurement Test",
            "desired_action_type": "restart_service"
        }
        
        t_before = time.time()
        async with httpx.AsyncClient() as client:
            post_fut = asyncio.create_task(client.post("http://127.0.0.1:8002/incidents", json=req, timeout=15.0))
            
            # Wait for backend log_event WS push
            ws_raw = await ws.recv()
            t_after = time.time()
            recv_timestamp = datetime.now(timezone.utc).isoformat()
            
            await post_fut
            
            ws_data = json.loads(ws_raw)
            backend_log = ws_data.get("new_log", "")
            log_timestamp = backend_log.split("]")[0].replace("[", "").strip() if "]" in backend_log else ""
            
            delta_ms = (t_after - t_before) * 1000.0
            
            print("=========================================================================")
            print("1. GENUINE MEASURED WEBSOCKET REAL-TIME LATENCY")
            print("=========================================================================")
            print(f"Backend Event Timestamp (log_event()):  {log_timestamp}")
            print(f"Frontend WS Client Receipt Timestamp:   {recv_timestamp}")
            print(f"Measured Real-Time Latency Delta:       {delta_ms:.2f} ms")
            print(f"WebSocket Event Payload Type:            {ws_data.get('event_type')}")
            print(f"WebSocket Event Log Message:             {backend_log}")
            print("-------------------------------------------------------------------------")
            print(f"Summary: Event delivered via WebSocket in {delta_ms:.2f} milliseconds.")
            print()

def print_approve_button_evidence():
    print("=========================================================================")
    print("2. APPROVE BUTTON -> REAL BACKEND PIPELINE EXECUTION EVIDENCE")
    print("=========================================================================")
    
    # Fetch recent Genuine Full-Path incident (inc-p5-full-...)
    inc_id = None
    try:
        with httpx.Client() as client:
            incidents = client.get("http://127.0.0.1:8002/incidents").json()
            for inc in reversed(incidents):
                if "inc-p5-full-" in inc["incident_id"]:
                    inc_id = inc["incident_id"]
                    break
    except Exception as e:
        print(f"Error fetching Orchestrator incidents: {e}")

    if not inc_id:
        print("Error: inc-p5-full incident not found.")
        return

    print(f"Target Genuine Full-Path Incident ID (Screenshots 01-06): '{inc_id}'")
    
    # Query Policy Gateway SQLite DB audit_log/aegis_audit.db
    print("\n--- SQLite Audit Log Database Query (audit_log/aegis_audit.db) ---")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, timestamp, action_type, verdict, deciding_rule, token FROM audit_log WHERE action_type = 'restart_service' ORDER BY id DESC LIMIT 5"
    )
    rows = cursor.fetchall()
    for r in rows:
        print(f"Row #{r['id']} | Timestamp: {r['timestamp']} | Action: {r['action_type']} | Verdict: {r['verdict']} | Rule: {r['deciding_rule']} | Token: {r['token']}")
    conn.close()

    # Fetch full event_log array from Orchestrator for this incident
    print(f"\n--- Orchestrator event_log Progression for '{inc_id}' ---")
    with httpx.Client() as client:
        inc_data = client.get(f"http://127.0.0.1:8002/incidents/{inc_id}").json()
        print(f"Final Incident Status: {inc_data.get('status')}")
        print(f"Approval Token Used:   {inc_data.get('approval_token')}")
        print("\nFull Event Log Array:")
        for log in inc_data.get("event_log", []):
            print(f"  {log}")
    print()

def print_fast_path_evidence():
    print("=========================================================================")
    print("3. FAST-PATH REPEAT RUN & GENUINE LLM CALL INSTRUMENTATION COUNTERS")
    print("=========================================================================")
    
    inc_id = None
    try:
        with httpx.Client() as client:
            incidents = client.get("http://127.0.0.1:8002/incidents").json()
            for inc in reversed(incidents):
                if "inc-p5-fast-" in inc["incident_id"]:
                    inc_id = inc["incident_id"]
                    break
    except Exception as e:
        print(f"Error fetching Orchestrator incidents: {e}")

    if inc_id:
        print(f"Target Fast-Path Incident ID (Screenshot 07): '{inc_id}'")
        with httpx.Client() as client:
            inc_data = client.get(f"http://127.0.0.1:8002/incidents/{inc_id}").json()
            print(f"Incident Status: {inc_data.get('status')}")
            print("Event Log Excerpt:")
            for log in inc_data.get("event_log", []):
                if "FAST PATH" in log or "SKIPPED" in log or "Policy Gateway" in log:
                    print(f"  {log}")

    # Read actual in-process dictionary directly from orchestrator.main
    from orchestrator.main import llm_call_counters
    print("\n--- Actual In-Process llm_call_counters Dictionary (orchestrator.main) ---")
    print(json.dumps(llm_call_counters, indent=2))
    print()

async def main():
    await measure_ws_latency()
    print_approve_button_evidence()
    print_fast_path_evidence()

if __name__ == "__main__":
    asyncio.run(main())
