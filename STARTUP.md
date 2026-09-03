# Aegis System Startup & Operating Guide

This guide provides step-by-step instructions to launch all Aegis microservices, target system stubs, and the Mission Control Dashboard in the correct sequence.

---

## Service Architecture & Port Assignments

| Component | Module Location | Port | Description |
| :--- | :--- | :--- | :--- |
| **Qdrant Vector Storage** | Docker container / Embedded disk | `6333` | Long-term vector memory engine |
| **Policy Gateway** | `policy_gateway/main.py` | `8001` | Safety AST evaluator & SQLite audit logger |
| **Orchestrator** | `orchestrator/main.py` | `8002` | Multi-agent incident pipeline & WebSocket hub |
| **Target System API** | `target_system/api.py` | `8003` | Chaos engineering fault injection & metrics API |
| **Mission Control Dashboard**| `dashboard/` | `5173` | Real-time React frontend UI |

---

## 1. Prerequisites

Ensure environment variables are configured in `.env`:
```bash
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
QDRANT_URL=http://localhost:6333
SQLITE_DB_PATH=./audit_log/aegis_audit.db
```

Ensure Python virtual environment is activated:
```powershell
.\venv\Scripts\activate
```

---

## 2. Service Startup Sequence

Launch each service in a separate terminal window in the specified order:

### Terminal 1: Qdrant Vector Database
```powershell
docker-compose up -d
```
*(Note: If Docker is unavailable, Aegis automatically falls back to embedded disk storage at `memory_engine/qdrant_storage`.)*

### Terminal 2: Policy Gateway Daemon (Port 8001)
```powershell
uvicorn policy_gateway.main:app --host 127.0.0.1 --port 8001 --reload
```

### Terminal 3: Target System API & Chaos Module (Port 8003)
```powershell
uvicorn target_system.api:app --host 127.0.0.1 --port 8003 --reload
```

### Terminal 4: Orchestrator & WebSocket Server (Port 8002)
```powershell
uvicorn orchestrator.main:app --host 127.0.0.1 --port 8002 --reload
```

### Terminal 5: Mission Control Dashboard UI (Port 5173)
```powershell
cd dashboard
npm run dev
```

---

## 3. Running Verification Test Suites

To verify individual components or run full system regression suites:

```powershell
# Policy Gateway & Safety Engine Test
python -u demo_scripts/test_policy_gateway.py

# Multi-Agent Pipeline Test (Phase 2)
python -u demo_scripts/test_phase2.py

# Sandboxed Execution & Verifier Test (Phase 3)
python -u demo_scripts/test_phase3.py

# Memory Engine & Fast-Path Test (Phase 4)
python -u demo_scripts/test_phase4.py

# Chaos Engineering & Fault Types Test (Phase 6)
python -u demo_scripts/test_phase6.py
```

---

## 4. Triggering Chaos Fault Scenarios (For Demo / Rehearsal)

To inject a fault scenario into the running system:

```powershell
# Inject Memory Pressure Fault
curl -X POST http://127.0.0.1:8003/inject-fault -H "Content-Type: application/json" -d '{"fault_type": "memory_pressure"}'

# Trigger Incident Resolution in Orchestrator
curl -X POST http://127.0.0.1:8002/incidents -H "Content-Type: application/json" -d '{"incident_id": "demo-inc-01", "description": "Critical memory pressure on payment service", "desired_action_type": "restart_service"}'

# Reset Target System to Healthy State
curl -X POST http://127.0.0.1:8003/reset
```
