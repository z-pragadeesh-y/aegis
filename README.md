# Aegis: Autonomous Multi-Agent Incident Response System

> **HTH 3.0 Hackathon — AI Agents Track**

Aegis is an autonomous, safety-bounded SRE incident-response system that detects, diagnoses, remediates, verifies, and documents production system incidents in real time.

---

## Key Features

- **Multi-Agent Pipeline**: Specialized LLM agents (Detective, Remediator, Verifier, Communicator) orchestrating incident triage and resolution.
- **Safety Policy Gateway**: Deterministic AST rule evaluator and SQLite audit logger preventing destructive actions.
- **Sandboxed Execution**: Isolated Docker container execution environment for system remediation scripts.
- **Memory Engine**: Vector-based experience memory (Qdrant) enabling sub-second fast-path resolution for recurring fault signatures.
- **Simulated Target System**: Chaos-Mesh inspired fault injection module supporting 5 fault types (`memory_pressure`, `cpu_pressure`, `latency_injection`, `packet_loss`, `pod_failure`).
- **Mission Control Dashboard**: Real-time React frontend rendering live agent reasoning traces and WebSocket pipeline updates.

---

## Quick Start & Operating Guide

For detailed service startup instructions, see [STARTUP.md](STARTUP.md).

```powershell
# 1. Start Qdrant Vector Storage
docker-compose up -d

# 2. Start Policy Gateway (Port 8001)
uvicorn policy_gateway.main:app --host 127.0.0.1 --port 8001

# 3. Start Target System API (Port 8003)
uvicorn target_system.api:app --host 127.0.0.1 --port 8003

# 4. Start Orchestrator (Port 8002)
uvicorn orchestrator.main:app --host 127.0.0.1 --port 8002

# 5. Start Dashboard Dev Server
cd dashboard && npm run dev
```

---

## Documentation & Phase Summaries

- **[STARTUP.md](STARTUP.md)** — Comprehensive microservice startup and operation guide.
- **[TEST_AUDIT_SUMMARY.md](TEST_AUDIT_SUMMARY.md)** — Full test integrity audit record and verification pass counts.
- **Phase Summaries**: [Phase 0](PHASE_0_SUMMARY.md) | [Phase 1](PHASE_1_SUMMARY.md) | [Phase 2](PHASE_2_SUMMARY.md) | [Phase 3](PHASE_3_SUMMARY.md) | [Phase 4](PHASE_4_SUMMARY.md) | [Phase 5](PHASE_5_SUMMARY.md) | [Phase 6](PHASE_6_SUMMARY.md)
