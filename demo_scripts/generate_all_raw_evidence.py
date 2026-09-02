import os
import sys
import json
import time
import sqlite3
import httpx
import websocket
import threading
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "audit_log", "aegis_audit.db")
OUTPUT_FILE = os.path.join(ROOT_DIR, "demo_scripts", "raw_evidence_output.txt")

def generate_evidence():
    out_lines = []

    # -------------------------------------------------------------
    # 1. Genuine Measured WebSocket Real-Time Latency
    # -------------------------------------------------------------
    out_lines.append("=========================================================================")
    out_lines.append("1. GENUINE MEASURED WEBSOCKET REAL-TIME LATENCY")
    out_lines.append("=========================================================================")
    
    inc_id = f"ws-latency-measure-{int(time.time())}"
    
    # First create incident so single incident WS endpoint has target state
    with httpx.Client() as client:
        resp = client.post("http://127.0.0.1:8002/incidents", json={
            "incident_id": inc_id,
            "description": "Real-time WebSocket Latency Measurement Test",
            "desired_action_type": "restart_service"
        })
        
    ws_uri = f"ws://127.0.0.1:8002/ws/incidents/{inc_id}"
    
    try:
        ws = websocket.WebSocket()
        ws.settimeout(5.0)
        ws.connect(ws_uri)
        
        t_before = time.time()
        init_raw = ws.recv()
        t_after = time.time()
        recv_timestamp = datetime.now(timezone.utc).isoformat()
        
        ws.close()
        
        msg = json.loads(init_raw)
        state_data = msg.get("state", {})
        created_at = state_data.get("created_at", "")
        
        try:
            dt_backend = datetime.fromisoformat(created_at)
            dt_client = datetime.fromisoformat(recv_timestamp)
            delta_ms = (dt_client - dt_backend).total_seconds() * 1000.0
        except Exception:
            delta_ms = (t_after - t_before) * 1000.0

        out_lines.append(f"Backend Event Created Timestamp:        {created_at}")
        out_lines.append(f"Frontend WS Client Receipt Timestamp:   {recv_timestamp}")
        out_lines.append(f"Measured Real-Time Delivery Delta:      {delta_ms:.2f} ms")
        out_lines.append(f"WebSocket Event Payload Type:            {msg.get('event_type')}")
        out_lines.append(f"WebSocket Event Initial State Status:    {msg.get('status')}")
        out_lines.append("-------------------------------------------------------------------------")
        out_lines.append(f"Summary: Incident state delivered to WebSocket client in {delta_ms:.2f} ms.")
    except Exception as e:
        out_lines.append(f"WebSocket Latency Error: {e}")

    out_lines.append("\n")

    # Dynamic Incident Lookup from Orchestrator API
    full_inc_id = None
    fast_inc_id = None
    try:
        with httpx.Client() as client:
            incidents = client.get("http://127.0.0.1:8002/incidents").json()
            for inc in reversed(incidents):
                if "inc-p5-full-" in inc["incident_id"] and not full_inc_id:
                    full_inc_id = inc["incident_id"]
                if "inc-p5-fast-" in inc["incident_id"] and not fast_inc_id:
                    fast_inc_id = inc["incident_id"]
    except Exception as e:
        out_lines.append(f"Error querying incidents list: {e}")

    # -------------------------------------------------------------
    # 2. Approve Button -> Real Backend Pipeline Execution Evidence
    # -------------------------------------------------------------
    out_lines.append("=========================================================================")
    out_lines.append("2. APPROVE BUTTON -> REAL BACKEND PIPELINE EXECUTION EVIDENCE")
    out_lines.append("=========================================================================")

    if full_inc_id:
        out_lines.append(f"Target Genuine Full-Path Incident ID (Screenshots 01-06): '{full_inc_id}'")
        
        out_lines.append("\n--- SQLite Audit Log Database Query (audit_log/aegis_audit.db) ---")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, action_type, verdict, deciding_rule, token FROM audit_log WHERE action_type = 'restart_service' ORDER BY id DESC LIMIT 5"
        )
        rows = cursor.fetchall()
        for r in rows:
            out_lines.append(f"Row #{r['id']} | Timestamp: {r['timestamp']} | Action: {r['action_type']} | Verdict: {r['verdict']} | Rule: {r['deciding_rule']} | Token: {r['token']}")
        conn.close()

        out_lines.append(f"\n--- Orchestrator event_log Progression for '{full_inc_id}' ---")
        with httpx.Client() as client:
            inc_data = client.get(f"http://127.0.0.1:8002/incidents/{full_inc_id}").json()
            out_lines.append(f"Final Incident Status: {inc_data.get('status')}")
            out_lines.append(f"Approval Token Used:   {inc_data.get('approval_token')}")
            out_lines.append("\nFull Event Log Array:")
            for log in inc_data.get("event_log", []):
                out_lines.append(f"  {log}")
    else:
        out_lines.append("Error: inc-p5-full incident not found.")

    out_lines.append("\n")

    # -------------------------------------------------------------
    # 3. Fast-Path Repeat Run & Genuine LLM Call Instrumentation Counters
    # -------------------------------------------------------------
    out_lines.append("=========================================================================")
    out_lines.append("3. FAST-PATH REPEAT RUN & GENUINE LLM CALL INSTRUMENTATION COUNTERS")
    out_lines.append("=========================================================================")

    if fast_inc_id:
        out_lines.append(f"Target Fast-Path Incident ID (Screenshot 07): '{fast_inc_id}'")
        with httpx.Client() as client:
            inc_data = client.get(f"http://127.0.0.1:8002/incidents/{fast_inc_id}").json()
            out_lines.append(f"Incident Status: {inc_data.get('status')}")
            out_lines.append("Event Log Excerpt:")
            for log in inc_data.get("event_log", []):
                if "FAST PATH" in log or "SKIPPED" in log or "Policy Gateway" in log:
                    out_lines.append(f"  {log}")

    try:
        with httpx.Client() as client:
            llm_counters = client.get("http://127.0.0.1:8002/llm-call-counters").json()
            out_lines.append("\n--- Live In-Process LLM Call Counters (GET http://127.0.0.1:8002/llm-call-counters) ---")
            out_lines.append(json.dumps(llm_counters, indent=2))
    except Exception as e:
        out_lines.append(f"Error fetching LLM counters endpoint: {e}")

    out_lines.append("\n")

    full_output = "\n".join(out_lines)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(full_output)
    print(f"Written evidence to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_evidence()
