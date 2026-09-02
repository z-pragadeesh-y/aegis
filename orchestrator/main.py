import os
import time
import threading
import httpx
import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from target_system.stub_metrics import get_current_metrics
from agents.detective import analyze_incident, DetectiveDiagnosis
from agents.remediator import propose_remediation, submit_to_policy_gateway, RemediatorAction
from sandbox.executor import execute_action_in_sandbox
from agents.verifier import verify_remediation, VerifierResult
from agents.communicator import generate_postmortem
from memory_engine.memory import recall as memory_recall, remember as memory_remember

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

GATEWAY_URL = os.getenv("POLICY_GATEWAY_URL", "http://127.0.0.1:8001")

class IncidentStatus(str, Enum):
    detecting = "detecting"
    awaiting_approval = "awaiting_approval"
    remediating = "remediating"
    verifying = "verifying"
    communicating = "communicating"
    done = "done"
    failed = "failed"

class IncidentCreateRequest(BaseModel):
    incident_id: str
    description: str
    desired_action_type: Optional[str] = None

class IncidentState(BaseModel):
    incident_id: str
    description: str
    status: IncidentStatus
    metrics: Optional[Dict[str, Any]] = None
    diagnosis: Optional[Dict[str, Any]] = None
    proposed_action: Optional[Dict[str, Any]] = None
    policy_verdict: Optional[Dict[str, Any]] = None
    approval_token: Optional[str] = None
    postmortem: Optional[str] = None
    event_log: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

incidents_db: Dict[str, IncidentState] = {}
llm_call_counters = {
    "detective_calls": 0,
    "remediator_calls": 0,
    "verifier_calls": 0,
    "communicator_calls": 0
}

class ConnectionManager:
    def __init__(self):
        self.incident_listeners: Dict[str, List[WebSocket]] = {}
        self.broadcast_listeners: List[WebSocket] = []

    async def connect_incident(self, incident_id: str, websocket: WebSocket):
        await websocket.accept()
        if incident_id not in self.incident_listeners:
            self.incident_listeners[incident_id] = []
        self.incident_listeners[incident_id].append(websocket)

    def disconnect_incident(self, incident_id: str, websocket: WebSocket):
        if incident_id in self.incident_listeners:
            if websocket in self.incident_listeners[incident_id]:
                self.incident_listeners[incident_id].remove(websocket)

    async def connect_broadcast(self, websocket: WebSocket):
        await websocket.accept()
        self.broadcast_listeners.append(websocket)

    def disconnect_broadcast(self, websocket: WebSocket):
        if websocket in self.broadcast_listeners:
            self.broadcast_listeners.remove(websocket)

    async def broadcast_incident(self, incident_id: str, payload: dict):
        if incident_id in self.incident_listeners:
            dead_sockets = []
            for ws in list(self.incident_listeners[incident_id]):
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead_sockets.append(ws)
            for ds in dead_sockets:
                self.disconnect_incident(incident_id, ds)

    async def broadcast_global(self, payload: dict):
        dead_sockets = []
        for ws in list(self.broadcast_listeners):
            try:
                await ws.send_json(payload)
            except Exception:
                dead_sockets.append(ws)
        for ds in dead_sockets:
            self.disconnect_broadcast(ds)

manager = ConnectionManager()

main_event_loop = None

def notify_websocket_listeners(state: IncidentState, entry: str):
    global main_event_loop
    state_dump = state.model_dump()
    payload = {
        "event_type": "log_entry",
        "incident_id": state.incident_id,
        "status": state.status.value if isinstance(state.status, IncidentStatus) else str(state.status),
        "new_log": entry,
        "state": state_dump
    }
    global_payload = {
        "event_type": "incident_updated",
        "incident_id": state.incident_id,
        "status": state.status.value if isinstance(state.status, IncidentStatus) else str(state.status),
        "description": state.description,
        "updated_at": state.updated_at
    }

    try:
        loop = asyncio.get_running_loop()
        main_event_loop = loop
        loop.create_task(manager.broadcast_incident(state.incident_id, payload))
        loop.create_task(manager.broadcast_global(global_payload))
    except RuntimeError:
        if main_event_loop and main_event_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast_incident(state.incident_id, payload), main_event_loop)
            asyncio.run_coroutine_threadsafe(manager.broadcast_global(global_payload), main_event_loop)

def log_event(state: IncidentState, message: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"[{timestamp}] {message}"
    state.event_log.append(entry)
    state.updated_at = timestamp
    notify_websocket_listeners(state, entry)

def execute_remediation_and_verify(state: IncidentState, start_time: Optional[float] = None):
    """
    Handles sandboxed execution, pre/post metrics verification, postmortem generation,
    terminal state resolution, and storing successful resolutions in Memory Engine.
    """
    if start_time is None:
        start_time = time.time()

    action_dict = state.proposed_action or {}
    action_type = action_dict.get("action_type", "")

    # 1. Set status to remediating
    state.status = IncidentStatus.remediating
    log_event(state, f"Starting sandboxed execution for action '{action_type}'")

    # 2. Pre-execution metrics snapshot
    try:
        before_metrics = get_current_metrics(state.incident_id)
        log_event(state, f"Pre-execution metrics snapshot: status='{before_metrics.get('status')}', cpu={before_metrics.get('cpu_percent')}%, err={before_metrics.get('error_rate')}")
    except Exception as e:
        log_event(state, f"Failed to snapshot pre-execution metrics: {e}")
        state.status = IncidentStatus.failed
        return

    # 3. Call sandboxed executor
    exec_res = execute_action_in_sandbox(action_type, incident_id=state.incident_id)
    if not exec_res.get("success"):
        err_msg = exec_res.get("error", "Unknown sandbox error")
        log_event(state, f"Sandboxed execution failed: {err_msg}")
        state.status = IncidentStatus.failed
        return

    log_event(state, "Sandboxed execution completed successfully (exit_code=0)")

    # 4. Set status to verifying & invoke Verifier
    state.status = IncidentStatus.verifying
    log_event(state, "Snapshotting post-execution metrics and invoking Verifier Agent (openai/gpt-oss-20b)")
    try:
        after_metrics = get_current_metrics(state.incident_id)
        log_event(state, f"Post-execution metrics snapshot: status='{after_metrics.get('status')}', cpu={after_metrics.get('cpu_percent')}%, err={after_metrics.get('error_rate')}")
        
        llm_call_counters["verifier_calls"] += 1
        verifier_res: VerifierResult = verify_remediation(
            action_type=action_type,
            before_metrics=before_metrics,
            after_metrics=after_metrics
        )
        log_event(state, f"Verifier result: resolved={verifier_res.resolved}, confidence={verifier_res.confidence}, summary='{verifier_res.summary}'")
    except Exception as e:
        log_event(state, f"Verifier Agent failed: {e}")
        state.status = IncidentStatus.failed
        return

    # 5. Set status to communicating & invoke Communicator
    state.status = IncidentStatus.communicating
    log_event(state, "Invoking Communicator Agent (openai/gpt-oss-20b) to generate postmortem")
    try:
        llm_call_counters["communicator_calls"] += 1
        postmortem_text = generate_postmortem(state.event_log)
        state.postmortem = postmortem_text
        log_event(state, f"Communicator postmortem generated: {postmortem_text[:60]}...")
    except Exception as e:
        log_event(state, f"Communicator Agent failed: {e}")
        state.status = IncidentStatus.failed
        return

    # 6. Set terminal state & store memory on genuine success
    if verifier_res.resolved:
        state.status = IncidentStatus.done
        log_event(state, "Incident successfully resolved and verified.")

        elapsed_sec = max(0.1, round(time.time() - start_time, 2))
        root_cause = (state.diagnosis or {}).get("root_cause", "")
        if not root_cause:
            root_cause = state.description

        pre_cpu = before_metrics.get("cpu_percent", 0.0)
        pre_err = before_metrics.get("error_rate", 0.0)
        fault_sig = f"Description: {state.description} | Root Cause: {root_cause} | Metrics: status={before_metrics.get('status')}, cpu={pre_cpu}%, error_rate={pre_err}"

        try:
            memory_remember(
                incident_id=state.incident_id,
                fault_signature=fault_sig,
                action_taken=action_dict,
                outcome="resolved",
                resolution_time_seconds=elapsed_sec
            )
            log_event(state, f"[MEMORY ENGINE] Successfully stored resolution memory for incident '{state.incident_id}' (resolution_time: {elapsed_sec}s)")
        except Exception as me_err:
            log_event(state, f"[MEMORY ENGINE] Warning: Failed to store memory: {me_err}")

    else:
        state.status = IncidentStatus.failed
        log_event(state, f"Incident verification failed: {verifier_res.summary}")

def process_incident_flow(state: IncidentState, desired_action_type: Optional[str] = None):
    """
    Executes the incident response loop with Memory Engine Fast-Path:
    pull metrics -> recall() memory check -> (Fast path OR Detective+Remediator) -> Policy Gateway -> Sandboxed Execution -> Verifier -> Communicator.
    """
    start_time = time.time()

    # 1. Pull telemetry metrics from target system
    try:
        log_event(state, "Pulling telemetry metrics from target_system/stub_metrics.py")
        metrics = get_current_metrics(state.incident_id)
        state.metrics = metrics
    except Exception as e:
        log_event(state, f"Failed to pull stub metrics: {e}")
        state.status = IncidentStatus.failed
        return

    # 2. Check Memory Engine Fast Path
    pre_cpu = metrics.get("cpu_percent", 0.0)
    pre_err = metrics.get("error_rate", 0.0)
    fault_sig = f"Description: {state.description} | Root Cause: {state.description} | Metrics: status={metrics.get('status')}, cpu={pre_cpu}%, error_rate={pre_err}"

    recalled_memory = None
    try:
        recalled_memory = memory_recall(fault_sig, similarity_threshold=0.80)
    except Exception as me_err:
        log_event(state, f"[MEMORY ENGINE] Recall query error: {me_err}")

    if recalled_memory and recalled_memory.get("action_taken"):
        recalled_action = recalled_memory["action_taken"]
        confidence = recalled_memory.get("confidence", 0.0)
        past_inc_id = recalled_memory.get("incident_id", "unknown")

        log_event(
            state,
            f"[FAST PATH TRIGGERED] Recalled past resolution from incident '{past_inc_id}' "
            f"(confidence: {confidence:.2f}). SKIPPING Detective and Remediator LLM calls!"
        )
        state.proposed_action = recalled_action

    else:
        log_event(state, "[FULL REASONING PATH] No confident memory match found. Proceeding to Detective and Remediator LLM calls.")

        # 3. Call Detective Agent
        state.status = IncidentStatus.detecting
        log_event(state, "Invoking Detective Agent (openai/gpt-oss-20b)")
        try:
            llm_call_counters["detective_calls"] += 1
            diagnosis: DetectiveDiagnosis = analyze_incident(state.metrics)
            state.diagnosis = diagnosis.model_dump()
            log_event(state, f"Detective diagnosis: root_cause='{diagnosis.root_cause}', confidence={diagnosis.confidence}")
        except Exception as e:
            log_event(state, f"Detective Agent failed: {e}")
            state.status = IncidentStatus.failed
            return

        # 4. Call Remediator Agent
        state.status = IncidentStatus.remediating
        log_event(state, "Invoking Remediator Agent (openai/gpt-oss-120b)")
        try:
            llm_call_counters["remediator_calls"] += 1
            action: RemediatorAction = propose_remediation(
                diagnosis_dict=state.diagnosis,
                desired_action_type=desired_action_type
            )
            state.proposed_action = action.model_dump()
            log_event(state, f"Remediator proposed action: type='{action.action_type}', target='{action.target}'")
        except Exception as e:
            log_event(state, f"Remediator Agent failed: {e}")
            state.status = IncidentStatus.failed
            return

    # 5. CRITICAL SAFETY INVARIANT — Submit proposed action to Policy Gateway (Fast-Path and Full-Path both evaluate!)
    log_event(state, f"Submitting proposed action '{state.proposed_action.get('action_type')}' to Policy Gateway")
    try:
        p_action = RemediatorAction(**state.proposed_action) if isinstance(state.proposed_action, dict) else state.proposed_action
        verdict_res = submit_to_policy_gateway(p_action, gateway_url=GATEWAY_URL)
        state.policy_verdict = verdict_res
        verdict = verdict_res.get("verdict")
        deciding_rule = verdict_res.get("deciding_rule")

        if verdict == "auto-approve":
            log_event(state, f"Action auto-approved by Policy Gateway rule '{deciding_rule}'")
            execute_remediation_and_verify(state, start_time=start_time)
        elif verdict == "needs-approval":
            token = verdict_res.get("token")
            expires_at = verdict_res.get("expires_at")
            state.approval_token = token
            state.status = IncidentStatus.awaiting_approval
            log_event(state, f"Action requires human approval (rule '{deciding_rule}'). Token: {token}, expires: {expires_at}")
        else:
            log_event(state, f"Action denied by Policy Gateway rule '{deciding_rule}'")
            state.status = IncidentStatus.failed
    except Exception as e:
        log_event(state, f"Policy Gateway unreachable or error: {e}")
        state.status = IncidentStatus.failed

app = FastAPI(title="Aegis Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/incidents", response_model=IncidentState)
async def create_incident(req: IncidentCreateRequest):
    if req.incident_id in incidents_db:
        raise HTTPException(status_code=400, detail="Incident ID already exists")

    state = IncidentState(
        incident_id=req.incident_id,
        description=req.description,
        status=IncidentStatus.detecting
    )
    incidents_db[req.incident_id] = state
    log_event(state, f"Incident '{req.incident_id}' created: {req.description}")

    thread = threading.Thread(target=process_incident_flow, args=(state, req.desired_action_type))
    thread.start()
    return state

@app.get("/incidents/{incident_id}", response_model=IncidentState)
def get_incident(incident_id: str):
    if incident_id not in incidents_db:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incidents_db[incident_id]

@app.get("/incidents", response_model=List[IncidentState])
def list_incidents():
    return list(incidents_db.values())

@app.post("/incidents/{incident_id}/confirm", response_model=IncidentState)
def confirm_incident_approval(incident_id: str):
    if incident_id not in incidents_db:
        raise HTTPException(status_code=404, detail="Incident not found")

    state = incidents_db[incident_id]
    if state.status != IncidentStatus.awaiting_approval:
        raise HTTPException(status_code=400, detail=f"Incident is in '{state.status}' state, not 'awaiting_approval'")

    token = state.approval_token
    if not token:
        raise HTTPException(status_code=400, detail="No approval token found on incident")

    log_event(state, f"Sending approval confirmation to Policy Gateway for token '{token}'")
    try:
        resp = httpx.post(f"{GATEWAY_URL}/confirm/{token}", timeout=10.0)
        resp.raise_for_status()
        c_data = resp.json()
        result = c_data.get("result")

        if result == "approved":
            log_event(state, f"Policy Gateway confirmed approval for token '{token}'")
            execute_remediation_and_verify(state)
        elif result == "expired":
            log_event(state, f"Approval token '{token}' has expired")
            state.status = IncidentStatus.failed
        else:
            log_event(state, f"Approval confirmation returned '{result}'")
            state.status = IncidentStatus.failed
    except Exception as e:
        log_event(state, f"Policy Gateway unreachable or error: {e}")
        state.status = IncidentStatus.failed
    return state

@app.get("/llm-call-counters")
def get_llm_call_counters():
    return llm_call_counters

@app.websocket("/ws/incidents/{incident_id}")
async def websocket_incident_endpoint(websocket: WebSocket, incident_id: str):
    await manager.connect_incident(incident_id, websocket)
    if incident_id in incidents_db:
        st = incidents_db[incident_id]
        await websocket.send_json({
            "event_type": "init",
            "incident_id": incident_id,
            "status": st.status.value if isinstance(st.status, IncidentStatus) else str(st.status),
            "state": st.model_dump()
        })
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_incident(incident_id, websocket)
    except Exception:
        manager.disconnect_incident(incident_id, websocket)

@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()

@app.websocket("/ws/incidents")
async def websocket_broadcast_endpoint(websocket: WebSocket):
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    await manager.connect_broadcast(websocket)
    await websocket.send_json({
        "event_type": "init",
        "incidents": [s.model_dump() for s in incidents_db.values()]
    })
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_broadcast(websocket)
    except Exception:
        manager.disconnect_broadcast(websocket)
