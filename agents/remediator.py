import os
import json
import ast
import logging
import time
import httpx
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
import groq

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)

GATEWAY_URL = "http://127.0.0.1:8001"

def extract_action_types_from_condition(condition_str: str) -> List[str]:
    """
    Parses condition string using AST mode='eval' to programmatically
    extract literal action string constants from AST list/tuple comparators.
    """
    actions = []
    try:
        tree = ast.parse(condition_str, mode='eval')
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comp in node.comparators:
                    if isinstance(comp, (ast.List, ast.Tuple)):
                        for elt in comp.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                actions.append(elt.value)
    except Exception:
        pass
    return actions

def load_valid_action_types(rules_file_path: Optional[str] = None) -> List[str]:
    """
    Parses policy_gateway/rules.yaml using yaml.safe_load() and AST condition analysis
    to extract valid action_type enum values programmatically.
    Logs a clear warning if the file is missing or invalid YAML, falling back to default actions.
    """
    if rules_file_path is None:
        rules_file_path = os.path.join(ROOT_DIR, "policy_gateway", "rules.yaml")

    fallback_actions = [
        "read_logs", "read_metrics", "restart_service", "throttle_process",
        "trigger_circuit_breaker", "reroute_traffic", "restart_instance",
        "replace_instance", "rollback_deploy", "delete_database", "drop_table",
        "shutdown_service", "wipe_volume"
    ]

    if not os.path.exists(rules_file_path):
        logger.warning("[WARNING] Rules YAML file missing at '%s'. Falling back to default action list.", rules_file_path)
        return fallback_actions

    try:
        with open(rules_file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict) or "rules" not in data:
            logger.warning("[WARNING] Invalid rules structure in '%s'. Falling back to default action list.", rules_file_path)
            return fallback_actions

        action_set = set()
        for rule in data.get("rules", []):
            if isinstance(rule, dict) and "condition" in rule:
                cond_str = rule["condition"]
                extracted = extract_action_types_from_condition(cond_str)
                for act in extracted:
                    action_set.add(act)

        if not action_set:
            logger.warning("[WARNING] No action types extracted from '%s'. Falling back to default action list.", rules_file_path)
            return fallback_actions

        return sorted(list(action_set))

    except Exception as e:
        logger.warning("[WARNING] Genuine parse/file error loading '%s': %s. Falling back to default action list.", rules_file_path, e)
        return fallback_actions

class RemediatorAction(BaseModel):
    action_type: str
    target: str
    reasoning: str

    @field_validator("action_type")
    def validate_action_type(cls, v):
        valid = load_valid_action_types()
        if v not in valid:
            raise ValueError(f"action_type '{v}' is not in policy_gateway rules: {valid}")
        return v

    @field_validator("target", "reasoning")
    def validate_non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Field must be a non-empty string")
        return v.strip()

def propose_remediation(diagnosis_dict: Dict[str, Any], desired_action_type: Optional[str] = None, api_key: Optional[str] = None) -> RemediatorAction:
    """
    Given Detective's diagnosis, calls Groq (openai/gpt-oss-120b) to propose a remediation action.
    Uses Groq Structured Outputs with dynamic action_type enum from rules.yaml.
    Includes 1 retry with exponential backoff.
    """
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing")

    client = groq.Groq(api_key=api_key)
    valid_actions = load_valid_action_types()

    remediator_schema = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": valid_actions,
                "description": "Action type to take"
            },
            "target": {
                "type": "string",
                "description": "Target service or resource to remediate"
            },
            "reasoning": {
                "type": "string",
                "description": "Human-readable reasoning for proposing this action"
            }
        },
        "required": ["action_type", "target", "reasoning"],
        "additionalProperties": False
    }

    hint_str = ""
    if desired_action_type and desired_action_type in valid_actions:
        hint_str = f"Prefer proposing action_type '{desired_action_type}' for this incident.\n"

    prompt = (
        f"You are Remediator Agent in Aegis AI Incident Response Swarm.\n"
        f"Based on Detective Agent's diagnosis:\n{json.dumps(diagnosis_dict, indent=2)}\n\n"
        f"{hint_str}"
        f"Select the single best remediation action from the allowed list: {valid_actions}.\n"
        f"Provide action_type, target, and reasoning."
    )

    models_to_try = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
    last_exception = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a specialist SRE Remediator agent. Output JSON matching the schema."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "remediator_action",
                            "strict": True,
                            "schema": remediator_schema
                        }
                    },
                    max_tokens=1000
                )

                content = completion.choices[0].message.content
                parsed = json.loads(content)
                
                action = RemediatorAction(**parsed)
                return action

            except Exception as e:
                last_exception = e
                if "429" in str(e) or "rate_limit" in str(e).lower():
                    break # Switch to next model immediately on rate limit
                time.sleep(0.5)

    raise RuntimeError(f"Remediator Agent failed across all fallback models: {last_exception}")

def submit_to_policy_gateway(action: RemediatorAction, gateway_url: str = GATEWAY_URL) -> Dict[str, Any]:
    """
    Submits proposed action to Policy Gateway POST /evaluate endpoint.
    """
    payload = {
        "action_type": action.action_type,
        "payload": {
            "target": action.target,
            "reasoning": action.reasoning
        }
    }
    resp = httpx.post(f"{gateway_url}/evaluate", json=payload, timeout=10.0)
    resp.raise_for_status()
    return resp.json()
