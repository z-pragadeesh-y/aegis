import os
import json
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
import groq

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

class VerifierResult(BaseModel):
    resolved: bool
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("summary")
    def validate_summary(cls, v):
        if not v or not v.strip():
            raise ValueError("summary must be a non-empty string")
        return v.strip()

VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "resolved": {
            "type": "boolean",
            "description": "Whether the remediation action resolved the incident"
        },
        "summary": {
            "type": "string",
            "description": "Brief human-readable explanation of the verification outcome"
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score between 0.0 and 1.0"
        }
    },
    "required": ["resolved", "summary", "confidence"],
    "additionalProperties": False
}

def verify_remediation(action_type: str, before_metrics: Dict[str, Any], after_metrics: Dict[str, Any], api_key: Optional[str] = None) -> VerifierResult:
    """
    Calls Groq (openai/gpt-oss-20b) to verify if the remediation action resolved the incident
    by comparing before and after metrics. Applies a local deterministic sanity check safety net.
    """
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing")

    client = groq.Groq(api_key=api_key)

    prompt = (
        f"You are Verifier Agent in Aegis AI Incident Response Swarm.\n"
        f"Executed Action: '{action_type}'\n"
        f"Before Metrics:\n{json.dumps(before_metrics, indent=2)}\n\n"
        f"After Metrics:\n{json.dumps(after_metrics, indent=2)}\n\n"
        f"Determine if the incident is resolved. Output JSON matching the schema."
    )

    models_to_try = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"]
    last_exception = None
    parsed_res = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                kwargs = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "You are an SRE Verifier agent. Output JSON with fields: resolved (boolean), summary (string), confidence (number 0.0 to 1.0)."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 2500 if "qwen" in model_name else 1000
                }
                if "qwen" in model_name:
                    kwargs["response_format"] = {"type": "json_object"}
                else:
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "verifier_result",
                            "strict": True,
                            "schema": VERIFIER_SCHEMA
                        }
                    }

                completion = client.chat.completions.create(**kwargs)
                content = completion.choices[0].message.content
                if "<think>" in content and "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                elif "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                parsed = json.loads(content)
                parsed_res = VerifierResult(**parsed)
                break

            except Exception as e:
                last_exception = e
                if "429" in str(e) or "rate_limit" in str(e).lower() or "400" in str(e) or "json" in str(e).lower():
                    break
                time.sleep(0.5)
        if parsed_res:
            break

    if not parsed_res:
        raise RuntimeError(f"Verifier Agent failed across all fallback models: {last_exception}")

    # Local deterministic sanity check independent of LLM
    llm_resolved = parsed_res.resolved
    after_status = str(after_metrics.get("status", "")).lower()
    before_status = str(before_metrics.get("status", "")).lower()
    
    before_cpu = float(before_metrics.get("cpu_percent", 0.0))
    after_cpu = float(after_metrics.get("cpu_percent", 0.0))
    before_err = float(before_metrics.get("error_rate", 0.0))
    after_err = float(after_metrics.get("error_rate", 0.0))

    if llm_resolved and after_status == "degraded" and (after_cpu >= before_cpu or after_err >= before_err):
        override_summary = f"{parsed_res.summary} [OVERRIDE] Local sanity check set resolved=False because after status is still 'degraded' (CPU: {after_cpu}%, error_rate: {after_err})"
        return VerifierResult(
            resolved=False,
            summary=override_summary,
            confidence=min(parsed_res.confidence, 0.5)
        )

    return parsed_res
