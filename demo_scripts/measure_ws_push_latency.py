import asyncio
import json
import time
import httpx
import websockets
from datetime import datetime, timezone

async def measure_ws_push_latency():
    inc_id = f"inc-push-test-{int(time.time())}"
    # 1. CONNECT FIRST to the global broadcast websocket endpoint
    uri = "ws://127.0.0.1:8002/ws/incidents"
    
    async with websockets.connect(uri) as ws:
        # Consume the initial connection frame ("init")
        init_frame = await ws.recv()
        
        # 2. TRIGGER SECOND (dispatch POST /incidents in background async task)
        req = {
            "incident_id": inc_id,
            "description": "Live WebSocket Push Latency Test",
            "desired_action_type": "restart_service"
        }
        
        async with httpx.AsyncClient() as client:
            t_post_dispatch = time.time()
            post_task = asyncio.create_task(client.post("http://127.0.0.1:8002/incidents", json=req, timeout=15.0))
            
            # 3. MEASURE LATENCY THIRD (wait for the live-pushed "incident_updated" WebSocket event)
            ws_frame_raw = await ws.recv()
            t_ws_recv = time.time()
            ws_recv_iso = datetime.now(timezone.utc).isoformat()
            
            # Record timing deltas
            latency_delta_ms = (t_ws_recv - t_post_dispatch) * 1000.0
            
            msg = json.loads(ws_frame_raw)
            backend_updated_at = msg.get("updated_at", "")
            
            print("=========================================================================")
            print("GENUINE MEASURED WEBSOCKET LIVE PUSH LATENCY (CONNECT-FIRST)")
            print("=========================================================================")
            print(f"POST Dispatch Timestamp (t_dispatch):     {datetime.fromtimestamp(t_post_dispatch, timezone.utc).isoformat()}")
            print(f"Backend Event Update Timestamp (log):    {backend_updated_at}")
            print(f"Frontend WS Client Receipt Timestamp:    {ws_recv_iso}")
            print(f"Measured Live Push Latency Delta:        {latency_delta_ms:.2f} ms")
            print(f"WebSocket Received Event Type:           {msg.get('event_type')}")
            print(f"WebSocket Received Event Payload:        {json.dumps(msg, indent=2)}")
            print("=========================================================================")
            
            post_task.cancel()

if __name__ == "__main__":
    asyncio.run(measure_ws_push_latency())
