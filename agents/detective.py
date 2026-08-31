import os
import json
import time
from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
import groq

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

class DetectiveDiagnosis(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("root_cause")
    def validate_root_cause(cls, v):
        if not v or not v.strip():
            raise ValueError("root_cause must be a non-empty string")
        return v.strip()

DETECTIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {
            "type": "string",
            "description": "Hypothesized root cause of the incident based on logs and metrics"
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score between 0.0 and 1.0"
        }
    },
    "required": ["root_cause", "confidence"],
    "additionalProperties": False
}

def analyze_incident(metrics_payload: Dict[str, Any], api_key: str = None) -> DetectiveDiagnosis:
    """
    Analyzes metrics and logs using Groq (openai/gpt-oss-20b) to diagnose root cause.
    Includes 1 retry with exponential backoff on API errors, followed by local validation.
    """
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing")

    client = groq.Groq(api_key=api_key)

    prompt = (
        f"You are Detective Agent in Aegis AI Incident Response Swarm.\n"
        f"Analyze the following telemetry/metrics payload and identify the root cause.\n\n"
        f"Telemetry Payload:\n{json.dumps(metrics_payload, indent=2)}\n\n"
        f"Provide root_cause and confidence (0.0 to 1.0)."
    )

    max_attempts = 2
    last_exception = None

    for attempt in range(max_attempts):
        try:
            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "You are a specialist SRE Detective agent. Output JSON matching the schema."},
                    {"role": "user", "content": prompt}
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "detective_diagnosis",
                        "strict": True,
                        "schema": DETECTIVE_SCHEMA
                    }
                },
                max_tokens=1000
            )

            content = completion.choices[0].message.content
            parsed = json.loads(content)
            
            diagnosis = DetectiveDiagnosis(**parsed)
            return diagnosis

        except Exception as e:
            last_exception = e
            if attempt < max_attempts - 1:
                time.sleep(1.0)

    raise RuntimeError(f"Detective Agent failed after {max_attempts} attempts: {last_exception}")
