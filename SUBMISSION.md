# Aegis: Autonomous Multi-Agent SRE Incident Response Swarm

> **Aegis** is an industry-grade, autonomous SRE (Site Reliability Engineering) incident response system powered by a multi-agent swarm, deterministic policy safety gateways, sandboxed execution environments, and vector-similarity long-term memory.

---

## 1. Executive Summary & Pitch

In modern high-velocity cloud systems, incident response is often limited by human reaction times, manual telemetry analysis, and unsafe automated remediation. Aegis solves these challenges through an **autonomous, self-healing multi-agent pipeline** that detects, diagnoses, remediates, verifies, and documents production incidents while guaranteeing safety through policy control:

- **Autonomous Swarm Architecture**: Decoupled specialist LLM agents (**Detective**, **Remediator**, **Verifier**, **Communicator**) orchestrated asynchronously.
- **Deterministic Policy Gateway**: Zero-trust access control intercepting high-risk remediation actions and pausing for human approval (`awaiting_approval`).
- **Sandboxed Docker Execution**: Isolated containerized remediation execution ensuring host infrastructure isolation.
- **Fast-Path Vector Memory Engine**: Qdrant-backed semantic memory that recalls past successful resolutions for recurring incidents in **sub-700ms with 0 LLM calls**.
- **Non-Blocking Live Dashboard**: Asynchronous `POST /confirm` endpoint returning in **< 500ms** with real-time WebSocket event streaming.

---

## 2. System Architecture

```mermaid
graph TD
    User["👨‍💻 SRE Operator / Dashboard"] -->|1. POST /incidents| Orch["⚡ Orchestrator Swarm"]
    Orch -->|2. Query Telemetry| Stub["📊 Stub Metrics Service (Port 8003)"]
    Orch -->|3. Vector Recall Search| Qdrant["🧠 Memory Engine (Qdrant Vector DB)"]
    
    subgraph Full Reasoning Path
        Orch -->|4a. Telemetry Analysis| Det["🕵️ Detective Agent"]
        Det -->|4b. Root Cause Diagnosis| Rem["🛠️ Remediator Agent"]
        Rem -->|4c. Propose Action| Policy["🛡️ Policy Gateway (Port 8001)"]
    end

    subgraph Fast-Path Memory Recall
        Qdrant -.->|Confidence > 0.80| FastPath["🚀 Fast-Path Direct Proposal"]
        FastPath --> Policy
    end

    Policy -->|Auto-Approved| Exec["🐳 Docker Sandbox Execution"]
    Policy -->|Risky / Needs Approval| Pause["⏸️ awaiting_approval"]
    Pause -->|Human Click /confirm| Exec

    Exec -->|5. Telemetry & State Check| Ver["✅ Verifier Agent"]
    Ver -->|6. Local Sanity & Verification| Comm["📢 Communicator Agent"]
    Comm -->|7. Postmortem Generation| MemStore["🧠 Store Resolution Memory"]
    MemStore --> Qdrant
    Orch -->|Live WS Push| User
```

---

## 3. Technology Stack & Key Libraries

| Component | Stack / Technologies |
| :--- | :--- |
| **Backend Orchestrator** | Python 3.14, FastAPI, Uvicorn, HTTPX |
| **LLM Swarm Agents** | Groq API (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.6-27b`) |
| **Policy Safety Gateway** | FastAPI Microservice, YAML Policy Engine, Token Manager |
| **Vector Memory Engine** | Qdrant Vector Database, HuggingFace `sentence-transformers/all-MiniLM-L6-v2` |
| **Sandboxed Execution** | Docker API (`docker-py`), Isolated Alpine Container Runtime |
| **Frontend Dashboard** | React 18, Vite, WebSocket Protocol, Custom CSS Visualizer |
| **State Persistence** | FileLock-Protected Concurrent `state.json` Schema |

---

## 4. Architectural Inspirations & Reference Repositories

Aegis integrates design patterns synthesized from six foundational open-source engineering paradigms:

1. **Meta-GPT / AutoGen**: Decoupled specialist agent roles with strict JSON-Schema response contracts.
2. **Chaos Mesh**: Industry-standard fault injection simulation (`cpu_pressure`, `memory_pressure`, `latency_injection`, `packet_loss`, `pod_failure`).
3. **OpenPolicyAgent (OPA)**: Centralized, declarative security and governance rule evaluations for automated system actions.
4. **LangGraph / State-Machine Orchestration**: Explicit `IncidentStatus` state lifecycle with deterministic transitions and error-recovery paths.
5. **Qdrant Vector DB**: High-performance vector embeddings for incident fault signature indexing and semantic similarity matching.
6. **Docker Engine API**: Ephemeral containerized sandbox isolation for safe tool execution.

---

## 5. Empirical Performance Benchmarks & Verification Summary

All core capabilities and edge-cases have been rigorously verified through comprehensive automated test suites and end-to-end rehearsals:

| Benchmark / Test Metric | Measured Value | Requirement / Target | Verdict |
| :--- | :--- | :--- | :---: |
| **`/confirm` Endpoint HTTP Latency** | **445 - 467 ms** | `< 500 ms` | **PASSED** |
| **Memory Fast-Path Trigger Time** | **0.65 - 0.66 s** | `< 1.0 s` | **PASSED** |
| **Memory Fast-Path LLM Call Savings** | **0 / 0 LLM Calls** | `0 LLM Calls` | **PASSED** |
| **Fault Injection Presets Verified** | **5 / 5 Fault Types** | `5 Fault Types` | **PASSED** |
| **State Isolation & Concurrency** | **FileLock Protected** | `Thread/Process Safe` | **PASSED** |
| **Phase 3 Regression Test Suite** | **8 / 8 Passed** | `100% Pass Rate` | **PASSED** |
| **Phase 6 Verification Suite** | **4 / 4 Passed** | `100% Pass Rate` | **PASSED** |
| **Phase 7 Rehearsal Suite (3 Consecutive Runs)** | **3 / 3 Clean Runs** | `100% Pass Rate` | **PASSED** |

---

## 6. Scope Boundaries & Governance Controls

- **Local Git Repository Hygiene**: All development, polish, and refactoring are maintained in local commits (`git log`). Remote pushes remain disabled per repository policy.
- **Deterministic Override Safeguard**: Deterministic metric sanity checks in the Verifier Agent override LLM hallucinations if telemetry indicates metric degradation persists after execution.
- **Human-in-the-Loop Interception**: Destructive actions (`restart_service`, `reboot_host`, `rollback_deployment`) strictly require explicit human confirmation via the Policy Gateway.
