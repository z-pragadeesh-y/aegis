import os
import time
import httpx
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from target_system.stub_metrics import get_current_metrics
from agents.detective import analyze_incident, DetectiveDiagnosis
from agents.remediator import propose_remediation, submit_to_policy_gateway, RemediatorAction
from sandbox.executor import execute_action_in_sandbox
from agents.verifier import verify_remediation, VerifierResult
from agents.communicator import generate_postmortem

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

def log_event(state: IncidentState, message: str):
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"[{timestamp}] {message}"
    state.event_log.append(entry)
    state.updated_at = timestamp

def check_fast_path_router(incident_id: str, description: str) -> Optional[Dict[str, Any]]:
    """
    Stub fast-path router. Returns None in Phase 3.
    Will be hooked to Memory Engine in Phase 4.
    """
    return None

def execute_remediation_and_verify(state: IncidentState):
    """
    Handles sandboxed execution, pre/post metrics verification, postmortem generation,
    and terminal state resolution.
    """
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
        postmortem_text = generate_postmortem(state.event_log)
        state.postmortem = postmortem_text
        log_event(state, f"Communicator postmortem generated: {postmortem_text[:60]}...")
    except Exception as e:
        log_event(state, f"Communicator Agent failed: {e}")
        state.status = IncidentStatus.failed
        return

    # 6. Set terminal state
    if verifier_res.resolved:
        state.status = IncidentStatus.done
        log_event(state, "Incident successfully resolved and verified.")
    else:
        state.status = IncidentStatus.failed
        log_event(state, f"Incident verification failed: {verifier_res.summary}")

def process_incident_flow(state: IncidentState, desired_action_type: Optional[str] = None):
    """
    Executes the incident response loop:
    pull metrics -> Detective -> Remediator -> Policy Gateway -> Sandboxed Execution -> Verifier -> Communicator.
    """
    # 1. Fast-path check
    fast_path_result = check_fast_path_router(state.incident_id, state.description)
    if fast_path_result:
        log_event(state, f"Fast-path router matched pattern: {fast_path_result}")
        state.status = IncidentStatus.done
        return

    # 2. Pull metrics from target system
    try:
        log_event(state, "Pulling telemetry metrics from target_system/stub_metrics.py")
        metrics = get_current_metrics(state.incident_id)
        state.metrics = metrics
    except Exception as e:
        log_event(state, f"Failed to pull stub metrics: {e}")
        state.status = IncidentStatus.failed
        return

    # 3. Call Detective Agent
    state.status = IncidentStatus.detecting
    log_event(state, "Invoking Detective Agent (openai/gpt-oss-20b)")
    try:
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

    # 5. Submit to Policy Gateway
    log_event(state, "Submitting proposed action to Policy Gateway")
    try:
        verdict_res = submit_to_policy_gateway(action, gateway_url=GATEWAY_URL)
        state.policy_verdict = verdict_res
        verdict = verdict_res.get("verdict")
        deciding_rule = verdict_res.get("deciding_rule")

        if verdict == "auto-approve":
            log_event(state, f"Action auto-approved by Policy Gateway rule '{deciding_rule}'")
            execute_remediation_and_verify(state)
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

@app.post("/incidents", response_model=IncidentState)
def create_incident(req: IncidentCreateRequest):
    if req.incident_id in incidents_db:
        raise HTTPException(status_code=400, detail="Incident ID already exists")

    state = IncidentState(
        incident_id=req.incident_id,
        description=req.description,
        status=IncidentStatus.detecting
    )
    log_event(state, f"Incident '{req.incident_id}' created: {req.description}")
    incidents_db[req.incident_id] = state

    process_incident_flow(state, desired_action_type=req.desired_action_type)
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
