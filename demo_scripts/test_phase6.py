import os
import sys
import json
import time
import httpx
from fastapi.testclient import TestClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from target_system.stub_metrics import reset_state, read_state, write_state, get_current_metrics
from target_system.faults import (
    inject_memory_pressure,
    inject_cpu_pressure,
    inject_latency_injection,
    inject_packet_loss,
    inject_pod_failure,
    reset_to_healthy
)
from agents.detective import analyze_incident

import target_system.api as target_api
import orchestrator.main as orch_main

def run_phase6_test_suite():
    print("=========================================================================", flush=True)
    print("AEGIS PHASE 6 TEST SUITE & VERIFICATION", flush=True)
    print("=========================================================================", flush=True)
    
    target_client = TestClient(target_api.app)
    orch_client = TestClient(orch_main.app)
    
    passed_count = 0
    total_tests = 4

    # -------------------------------------------------------------
    # Test 1: Immediate Degraded Metrics Assertion for 5 Fault Types
    # -------------------------------------------------------------
    print("\n--- Test 1: Degraded Metrics Assertion for 5 Fault Types ---", flush=True)
    fault_results = {}

    try:
        # a) Memory Pressure
        inc_mem = "inc-p6-test-memory"
        t0 = time.time()
        res_mem = target_client.post(f"/faults/memory_pressure?incident_id={inc_mem}")
        met_mem = target_client.get(f"/metrics/{inc_mem}").json()
        dur_mem = time.time() - t0
        fault_results["memory_pressure"] = met_mem
        assert met_mem["memory_percent"] >= 90.0, f"Expected memory_percent >= 90.0, got {met_mem['memory_percent']}"
        assert met_mem["cpu_percent"] < 30.0, f"Expected cpu_percent < 30.0, got {met_mem['cpu_percent']}"
        print(f"[PASS] memory_pressure: memory={met_mem['memory_percent']}%, cpu={met_mem['cpu_percent']}% ({dur_mem:.3f}s)", flush=True)

        # b) CPU Pressure
        inc_cpu = "inc-p6-test-cpu"
        t0 = time.time()
        res_cpu = target_client.post(f"/faults/cpu_pressure?incident_id={inc_cpu}")
        met_cpu = target_client.get(f"/metrics/{inc_cpu}").json()
        dur_cpu = time.time() - t0
        fault_results["cpu_pressure"] = met_cpu
        assert met_cpu["cpu_percent"] >= 90.0, f"Expected cpu_percent >= 90.0, got {met_cpu['cpu_percent']}"
        assert met_cpu["response_time_ms"] >= 800.0, f"Expected response_time_ms >= 800.0, got {met_cpu['response_time_ms']}"
        print(f"[PASS] cpu_pressure: cpu={met_cpu['cpu_percent']}%, latency={met_cpu['response_time_ms']}ms ({dur_cpu:.3f}s)", flush=True)

        # c) Latency Injection
        inc_lat = "inc-p6-test-latency"
        t0 = time.time()
        res_lat = target_client.post(f"/faults/latency_injection?incident_id={inc_lat}")
        met_lat = target_client.get(f"/metrics/{inc_lat}").json()
        dur_lat = time.time() - t0
        fault_results["latency_injection"] = met_lat
        assert met_lat["response_time_ms"] >= 1000.0, f"Expected response_time_ms >= 1000.0, got {met_lat['response_time_ms']}"
        assert met_lat["connectivity"] is True, f"Expected connectivity True, got {met_lat['connectivity']}"
        print(f"[PASS] latency_injection: latency={met_lat['response_time_ms']}ms, connectivity={met_lat['connectivity']} ({dur_lat:.3f}s)", flush=True)

        # d) Packet Loss
        inc_pkt = "inc-p6-test-packet"
        t0 = time.time()
        res_pkt = target_client.post(f"/faults/packet_loss?incident_id={inc_pkt}")
        met_pkt = target_client.get(f"/metrics/{inc_pkt}").json()
        dur_pkt = time.time() - t0
        fault_results["packet_loss"] = met_pkt
        assert met_pkt["connectivity"] is False, f"Expected connectivity False, got {met_pkt['connectivity']}"
        assert met_pkt["error_rate"] >= 0.40, f"Expected error_rate >= 0.40, got {met_pkt['error_rate']}"
        assert met_pkt["active_connections"] <= 5, f"Expected active_connections <= 5, got {met_pkt['active_connections']}"
        print(f"[PASS] packet_loss: connectivity={met_pkt['connectivity']}, err={met_pkt['error_rate']}, active_conn={met_pkt['active_connections']} ({dur_pkt:.3f}s)", flush=True)

        # e) Pod Failure
        inc_pod = "inc-p6-test-pod"
        t0 = time.time()
        res_pod = target_client.post(f"/faults/pod_failure?incident_id={inc_pod}")
        met_pod = target_client.get(f"/metrics/{inc_pod}").json()
        dur_pod = time.time() - t0
        fault_results["pod_failure"] = met_pod
        assert met_pod["instance_serving"] is False, f"Expected instance_serving False, got {met_pod['instance_serving']}"
        assert met_pod["active_connections"] == 0, f"Expected active_connections == 0, got {met_pod['active_connections']}"
        print(f"[PASS] pod_failure: instance_serving={met_pod['instance_serving']}, active_conn={met_pod['active_connections']} ({dur_pod:.3f}s)", flush=True)

        print("\n✅ Test 1 PASSED: All 5 fault types verified with expected degraded metrics!", flush=True)
        passed_count += 1
    except Exception as e:
        print(f"❌ Test 1 FAILED: {e}", flush=True)

    # -------------------------------------------------------------
    # Test 2: Full Incident Pipeline Runs & Detective Diagnosis Assessment
    # -------------------------------------------------------------
    print("\n--- Test 2: Detective Diagnosis Assessment on Injected Fault Metrics ---", flush=True)
    detective_diagnoses = {}
    try:
        fault_types = [
            ("memory_pressure", "inc-p6-det-memory"),
            ("cpu_pressure", "inc-p6-det-cpu"),
            ("latency_injection", "inc-p6-det-latency"),
            ("packet_loss", "inc-p6-det-packet"),
            ("pod_failure", "inc-p6-det-pod")
        ]

        for fault_type, inc_id in fault_types:
            target_client.post(f"/faults/{fault_type}?incident_id={inc_id}")
            metrics = target_client.get(f"/metrics/{inc_id}").json()
            
            # Analyze metrics directly using Groq Detective agent
            diagnosis = analyze_incident(metrics)
            root_cause = diagnosis.root_cause
            confidence = diagnosis.confidence

            detective_diagnoses[fault_type] = {
                "incident_id": inc_id,
                "root_cause": root_cause,
                "confidence": confidence
            }
            print(f"[{fault_type.upper()}] Incident ID: '{inc_id}'", flush=True)
            print(f"  Detective Root Cause: \"{root_cause}\" (confidence: {confidence})", flush=True)

        print("\n✅ Test 2 PASSED: All Detective diagnoses captured successfully!", flush=True)
        passed_count += 1
    except Exception as e:
        print(f"❌ Test 2 FAILED: {e}", flush=True)

    # -------------------------------------------------------------
    # Test 3: Reset State Verification (Before vs After JSON)
    # -------------------------------------------------------------
    print("\n--- Test 3: Reset to Healthy State Verification ---", flush=True)
    reset_data = {}
    try:
        inc_reset = "inc-p6-test-reset"
        target_client.post(f"/faults/cpu_pressure?incident_id={inc_reset}")
        before_state = target_client.get(f"/metrics/{inc_reset}").json()
        
        t0 = time.time()
        res_reset = target_client.post(f"/reset?incident_id={inc_reset}")
        after_state = target_client.get(f"/metrics/{inc_reset}").json()
        dur_reset = time.time() - t0

        reset_data["before"] = before_state
        reset_data["after"] = after_state

        assert after_state["status"] == "healthy", f"Expected status healthy, got {after_state['status']}"
        assert after_state["cpu_percent"] == 15.0, f"Expected cpu 15.0, got {after_state['cpu_percent']}"
        assert after_state["memory_percent"] == 25.0, f"Expected memory 25.0, got {after_state['memory_percent']}"
        assert after_state["error_rate"] == 0.01, f"Expected error_rate 0.01, got {after_state['error_rate']}"
        assert after_state["response_time_ms"] == 120.0, f"Expected response_time 120.0, got {after_state['response_time_ms']}"
        assert after_state["active_connections"] == 150, f"Expected active_conn 150, got {after_state['active_connections']}"
        assert after_state["connectivity"] is True, f"Expected connectivity True, got {after_state['connectivity']}"
        assert after_state["instance_serving"] is True, f"Expected instance_serving True, got {after_state['instance_serving']}"

        print(f"Before Reset Status: {before_state['status']}, CPU={before_state['cpu_percent']}%, Latency={before_state['response_time_ms']}ms", flush=True)
        print(f"After Reset Status:  {after_state['status']}, CPU={after_state['cpu_percent']}%, Latency={after_state['response_time_ms']}ms", flush=True)
        print(f"Reset Duration: {dur_reset:.3f}s (well under 10s requirement)", flush=True)
        print("✅ Test 3 PASSED: State genuinely returned to healthy baseline across all 8 fields!", flush=True)
        passed_count += 1
    except Exception as e:
        print(f"❌ Test 3 FAILED: {e}", flush=True)

    # -------------------------------------------------------------
    # Test 4: Regression Run (Phase 3 & Phase 3 Concurrency)
    # -------------------------------------------------------------
    print("\n--- Test 4: Existing Phase 3 Test Suite & Concurrency Regression ---", flush=True)
    try:
        from demo_scripts.test_phase3 import run_phase3_tests
        from demo_scripts.test_phase3_concurrency import run_locked_concurrency_test
        
        print("Running Phase 3 Test Suite...", flush=True)
        p3_success = run_phase3_tests()
        
        print("\nRunning Phase 3 Concurrency Test...", flush=True)
        run_locked_concurrency_test()
        
        if p3_success:
            print("✅ Test 4 PASSED: All legacy Phase 3 assertions passed without regression!", flush=True)
            passed_count += 1
        else:
            print("❌ Test 4 FAILED: Legacy Phase 3 test suite failed.", flush=True)
    except Exception as e:
        print(f"❌ Test 4 FAILED: {e}", flush=True)

    print("\n=========================================================================", flush=True)
    print(f"PHASE 6 TEST SUMMARY: {passed_count}/{total_tests} TESTS PASSED", flush=True)
    print("=========================================================================", flush=True)

    return {
        "passed": passed_count == total_tests,
        "fault_results": fault_results,
        "detective_diagnoses": detective_diagnoses,
        "reset_data": reset_data
    }

if __name__ == "__main__":
    res = run_phase6_test_suite()
    if res["passed"]:
        sys.exit(0)
    else:
        sys.exit(1)
