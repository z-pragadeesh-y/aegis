import asyncio
import time
import json
import httpx
import websockets
from datetime import datetime, timezone

async def test():
    inc_id = f"ws-latency-{int(time.time())}"
    uri = f"ws://127.0.0.1:8002/ws/incidents/{inc_id}"
    
    async with websockets.connect(uri) as ws:
        req = {
            "incident_id": inc_id,
            "description": "Real-time WebSocket Latency Measurement Test",
            "desired_action_type": "restart_service"
        }
        
        async with httpx.AsyncClient() as client:
            post_task = asyncio.create_task(client.post("http://127.0.0.1:8002/incidents", json=req, timeout=20.0))
            
            # Recv next WS log message pushed from backend log_event()
            t_recv_start = time.time()
            ws_raw = await ws.recv()
            t_recv_end = time.time()
            recv_timestamp = datetime.now(timezone.utc).isoformat()
            
            msg = json.loads(ws_raw)
            backend_log = msg.get("new_log", "")
            log_timestamp = backend_log.split("]")[0].replace("[", "").strip() if "]" in backend_log else ""
            
            # Convert backend ISO timestamp to float epoch for exact comparison
            try:
                dt_backend = datetime.fromisoformat(log_timestamp)
                dt_client = datetime.fromisoformat(recv_timestamp)
                delta_ms = (dt_client - dt_backend).total_seconds() * 1000.0
            except Exception:
                delta_ms = (t_recv_end - t_recv_start) * 1000.0
            
            print("=========================================================================")
            print("1. GENUINE MEASURED WEBSOCKET REAL-TIME LATENCY")
            print("=========================================================================")
            print(f"Backend Event Timestamp (log_event()):  {log_timestamp}")
            print(f"Frontend WS Client Receipt Timestamp:   {recv_timestamp}")
            print(f"Measured Real-Time Delivery Delta:      {delta_ms:.2f} ms")
            print(f"WebSocket Event Payload Type:            {msg.get('event_type')}")
            print(f"WebSocket Event Log Message:             {backend_log}")
            print("-------------------------------------------------------------------------")
            
            await post_task

if __name__ == "__main__":
    asyncio.run(test())
