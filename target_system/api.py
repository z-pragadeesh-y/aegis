import os
import sys
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from target_system.stub_metrics import get_current_metrics, read_state
from target_system.faults import (
    inject_memory_pressure,
    inject_cpu_pressure,
    inject_latency_injection,
    inject_packet_loss,
    inject_pod_failure,
    reset_to_healthy
)

app = FastAPI(title="Aegis Simulated Target System Fault Injection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FAULT_HANDLERS = {
    "memory_pressure": inject_memory_pressure,
    "cpu_pressure": inject_cpu_pressure,
    "latency_injection": inject_latency_injection,
    "packet_loss": inject_packet_loss,
    "pod_failure": inject_pod_failure
}

@app.post("/faults/{fault_type}")
def trigger_fault(fault_type: str, incident_id: str = Query("default")) -> Dict[str, Any]:
    if fault_type not in FAULT_HANDLERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fault_type '{fault_type}'. Valid types: {list(FAULT_HANDLERS.keys())}"
        )
    handler = FAULT_HANDLERS[fault_type]
    new_state = handler(incident_id)
    return {
        "status": "success",
        "fault_type": fault_type,
        "incident_id": incident_id,
        "metrics": new_state
    }

@app.post("/reset")
def reset_incident(incident_id: str = Query("default")) -> Dict[str, Any]:
    new_state = reset_to_healthy(incident_id)
    return {
        "status": "success",
        "incident_id": incident_id,
        "metrics": new_state
    }

@app.get("/metrics/{incident_id}")
def get_metrics(incident_id: str) -> Dict[str, Any]:
    metrics = get_current_metrics(incident_id)
    return metrics

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8003)
