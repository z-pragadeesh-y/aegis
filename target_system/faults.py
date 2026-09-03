import os
import random
from typing import Dict, Any
from target_system.stub_metrics import (
    read_state,
    write_state,
    reset_state,
    HEALTHY_BASELINE_STATE,
    BASELINE_DEGRADED_STATE
)

def inject_memory_pressure(incident_id: str) -> Dict[str, Any]:
    """
    a) Memory pressure: memory_percent climbs to 90-98%, status='degraded',
       other fields near-healthy (cpu ~15%, latency ~120ms, error_rate ~0.01).
    """
    state = read_state(incident_id)
    state.update({
        "cpu_percent": round(random.uniform(12.0, 18.0), 1),
        "memory_percent": round(random.uniform(90.0, 98.0), 1),
        "error_rate": 0.01,
        "status": "degraded",
        "response_time_ms": 120.0,
        "active_connections": 150,
        "connectivity": True,
        "instance_serving": True
    })
    write_state(incident_id, state)
    return state.copy()

def inject_cpu_pressure(incident_id: str) -> Dict[str, Any]:
    """
    b) CPU pressure: cpu_percent climbs to 90-98%, response_time_ms elevated (800-1500ms),
       status='degraded', memory/connectivity near-healthy.
    """
    state = read_state(incident_id)
    state.update({
        "cpu_percent": round(random.uniform(90.0, 98.0), 1),
        "memory_percent": 25.0,
        "error_rate": 0.02,
        "status": "degraded",
        "response_time_ms": round(random.uniform(800.0, 1500.0), 1),
        "active_connections": 350,
        "connectivity": True,
        "instance_serving": True
    })
    write_state(incident_id, state)
    return state.copy()

def inject_latency_injection(incident_id: str) -> Dict[str, Any]:
    """
    c) Latency injection: response_time_ms elevated (1000-3000ms with jitter),
       status='degraded', connectivity=True, cpu/memory near-healthy, error_rate mildly elevated.
    """
    state = read_state(incident_id)
    state.update({
        "cpu_percent": 18.0,
        "memory_percent": 25.0,
        "error_rate": 0.03,
        "status": "degraded",
        "response_time_ms": round(random.uniform(1000.0, 3000.0), 1),
        "active_connections": 220,
        "connectivity": True,
        "instance_serving": True
    })
    write_state(incident_id, state)
    return state.copy()

def inject_packet_loss(incident_id: str) -> Dict[str, Any]:
    """
    d) Packet loss: connectivity=False, error_rate spikes high (0.4-0.8),
       active_connections drops sharply (near 0), cpu/memory near-healthy.
    """
    state = read_state(incident_id)
    state.update({
        "cpu_percent": 15.0,
        "memory_percent": 25.0,
        "error_rate": round(random.uniform(0.40, 0.80), 2),
        "status": "degraded",
        "response_time_ms": 2800.0,
        "active_connections": random.randint(0, 5),
        "connectivity": False,
        "instance_serving": True
    })
    write_state(incident_id, state)
    return state.copy()

def inject_pod_failure(incident_id: str) -> Dict[str, Any]:
    """
    e) Pod failure: instance_serving=False, status/cpu/memory otherwise nominal/healthy-ish.
    """
    state = read_state(incident_id)
    state.update({
        "cpu_percent": 15.0,
        "memory_percent": 25.0,
        "error_rate": 0.01,
        "status": "degraded",
        "response_time_ms": 120.0,
        "active_connections": 0,
        "connectivity": True,
        "instance_serving": False
    })
    write_state(incident_id, state)
    return state.copy()

def reset_to_healthy(incident_id: str) -> Dict[str, Any]:
    """
    Resets ALL state fields for incident_id back to healthy baseline.
    """
    return reset_state(incident_id, healthy=True)
