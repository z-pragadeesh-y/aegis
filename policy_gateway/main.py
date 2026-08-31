import os
import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from fastapi import FastAPI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from policy_gateway.expression_evaluator import evaluate_condition

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(ROOT_DIR, ".env")
load_dotenv(dotenv_path=env_path)

db_path_env = os.getenv("SQLITE_DB_PATH", "./audit_log/aegis_audit.db")
if not os.path.isabs(db_path_env):
    DB_PATH = os.path.normpath(os.path.join(ROOT_DIR, db_path_env))
else:
    DB_PATH = db_path_env

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

APPROVAL_TOKEN_TTL_SECONDS = 120

pending_tokens: Dict[str, Dict[str, Any]] = {}

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_payload TEXT NOT NULL,
                verdict TEXT NOT NULL,
                deciding_rule TEXT NOT NULL,
                token TEXT
            );
        """)
        conn.commit()

init_db()

def load_rules():
    rules_file = os.path.join(os.path.dirname(__file__), "rules.yaml")
    rules = []
    if not os.path.exists(rules_file):
        return rules
    current_rule = None
    with open(rules_file, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str.startswith("- id:") or line_str.startswith("id:"):
                if current_rule:
                    rules.append(current_rule)
                rule_id = line_str.split("id:", 1)[1].strip().strip('"').strip("'")
                current_rule = {"id": rule_id}
            elif line_str.startswith("condition:") and current_rule is not None:
                cond = line_str.split("condition:", 1)[1].strip()
                if (cond.startswith("'") and cond.endswith("'")) or (cond.startswith('"') and cond.endswith('"')):
                    cond = cond[1:-1]
                current_rule["condition"] = cond
            elif line_str.startswith("verdict:") and current_rule is not None:
                verdict = line_str.split("verdict:", 1)[1].strip().strip('"').strip("'")
                current_rule["verdict"] = verdict
        if current_rule:
            rules.append(current_rule)
    return rules

RULES = load_rules()

def insert_audit_log(
    action_type: str,
    payload: dict,
    verdict: str,
    deciding_rule: str,
    token: Optional[str] = None,
    timestamp: Optional[str] = None
):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (timestamp, action_type, action_payload, verdict, deciding_rule, token)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (timestamp, action_type, payload_json, verdict, deciding_rule, token)
        )
        conn.commit()

app = FastAPI(title="Aegis Policy Gateway")

class EvaluateRequest(BaseModel):
    action_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)

class EvaluateResponse(BaseModel):
    verdict: str
    deciding_rule: str
    token: Optional[str] = None
    expires_at: Optional[str] = None

class ConfirmResponse(BaseModel):
    result: str

@app.post("/evaluate", response_model=EvaluateResponse)
def evaluate_action(req: EvaluateRequest):
    context = {
        "action": {
            "type": req.action_type,
            "payload": req.payload
        },
        "payload": req.payload
    }
    
    matched_rule = None
    for rule in RULES:
        condition_str = rule.get("condition", "")
        try:
            if evaluate_condition(condition_str, context):
                matched_rule = rule
                break
        except Exception:
            continue
            
    if matched_rule:
        verdict = matched_rule["verdict"]
        deciding_rule = matched_rule["id"]
    else:
        verdict = "deny"
        deciding_rule = "default-deny-fail-closed"
        
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    if verdict == "needs-approval":
        token = str(uuid.uuid4())
        expires_at = now + timedelta(seconds=APPROVAL_TOKEN_TTL_SECONDS)
        expires_at_iso = expires_at.isoformat()
        
        pending_tokens[token] = {
            "action_type": req.action_type,
            "payload": req.payload,
            "deciding_rule": deciding_rule,
            "expires_at": expires_at
        }
        
        insert_audit_log(
            action_type=req.action_type,
            payload=req.payload,
            verdict="needs-approval",
            deciding_rule=deciding_rule,
            token=token,
            timestamp=now_iso
        )
        
        return EvaluateResponse(
            verdict=verdict,
            deciding_rule=deciding_rule,
            token=token,
            expires_at=expires_at_iso
        )
    else:
        insert_audit_log(
            action_type=req.action_type,
            payload=req.payload,
            verdict=verdict,
            deciding_rule=deciding_rule,
            token=None,
            timestamp=now_iso
        )
        
        return EvaluateResponse(
            verdict=verdict,
            deciding_rule=deciding_rule,
            token=None,
            expires_at=None
        )

@app.post("/confirm/{token}", response_model=ConfirmResponse)
def confirm_action(token: str):
    if token not in pending_tokens:
        return ConfirmResponse(result="not_found")
        
    info = pending_tokens.pop(token)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    if now > info["expires_at"]:
        result = "expired"
    else:
        result = "approved"
        
    insert_audit_log(
        action_type=info["action_type"],
        payload=info["payload"],
        verdict=result,
        deciding_rule=info["deciding_rule"],
        token=token,
        timestamp=now_iso
    )
    
    return ConfirmResponse(result=result)
