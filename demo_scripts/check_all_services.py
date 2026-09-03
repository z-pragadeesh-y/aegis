"""
Aegis Pre-Demo One-Command Health Check Script
Verifies all 5 microservices/ports are active and reachable:
1. Qdrant Vector Storage (6333)
2. Policy Gateway (8001)
3. Orchestrator API (8002)
4. Target System API (8003)
5. Mission Control Dashboard UI (5173 / 5174)

Prints a clear PASS/FAIL per service, and exits non-zero if any required service is down.
"""

import sys
import os
import urllib.request
import urllib.error

SERVICES = [
    {
        "name": "Qdrant Vector Storage",
        "port": 6333,
        "urls": ["http://127.0.0.1:6333/healthz", "http://127.0.0.1:6333/"],
        "fallback_allowed": True,
        "fallback_note": "Aegis auto-falls back to embedded disk storage if Docker Qdrant is off."
    },
    {
        "name": "Policy Gateway Daemon",
        "port": 8001,
        "urls": ["http://127.0.0.1:8001/audit_log", "http://127.0.0.1:8001/docs"],
        "fallback_allowed": False
    },
    {
        "name": "Orchestrator Server",
        "port": 8002,
        "urls": ["http://127.0.0.1:8002/incidents"],
        "fallback_allowed": False
    },
    {
        "name": "Target System API",
        "port": 8003,
        "urls": ["http://127.0.0.1:8003/metrics/default", "http://127.0.0.1:8003/docs"],
        "fallback_allowed": False
    },
    {
        "name": "Mission Control Dashboard",
        "port": 5173,
        "urls": ["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
        "fallback_allowed": False
    }
]

def check_url(url: str, timeout: float = 3.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Aegis-HealthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 204, 301, 302)
    except Exception:
        return False

def main():
    print("=" * 75)
    print("  AEGIS PRE-DEMO SERVICE HEALTH CHECK")
    print("=" * 75)

    all_passed = True
    critical_failures = 0

    for s in SERVICES:
        name = s["name"]
        port = s["port"]
        urls = s["urls"]
        fallback_allowed = s.get("fallback_allowed", False)

        success = any(check_url(u) for u in urls)
        if success:
            print(f"  [PASS] {name:30s} (Port {port}) -> Reachable & Responding")
        else:
            if fallback_allowed:
                print(f"  [WARN] {name:30s} (Port {port}) -> Unreachable ({s.get('fallback_note')})")
            else:
                print(f"  [FAIL] {name:30s} (Port {port}) -> UNREACHABLE / DOWN!")
                all_passed = False
                critical_failures += 1

    print("=" * 75)
    if all_passed:
        print("  >>> SYSTEM HEALTH: ALL CRITICAL SERVICES ARE ONLINE AND READY FOR DEMO! <<<")
        print("=" * 75)
        sys.exit(0)
    else:
        print(f"  >>> SYSTEM HEALTH ERROR: {critical_failures} CRITICAL SERVICE(S) DOWN! <<<")
        print("  Please launch missing services per STARTUP.md before running the demo.")
        print("=" * 75)
        sys.exit(1)

if __name__ == "__main__":
    main()
