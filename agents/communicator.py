import os
import time
from typing import List, Optional
from dotenv import load_dotenv
import groq

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

def generate_postmortem(event_log: List[str], api_key: Optional[str] = None) -> str:
    """
    Calls Groq (openai/gpt-oss-20b) to generate a single readable postmortem paragraph
    based on the incident's full event log.
    """
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing")

    client = groq.Groq(api_key=api_key)

    events_str = "\n".join(event_log)
    prompt = (
        f"You are Communicator Agent in Aegis AI Incident Response Swarm.\n"
        f"Based on the following incident event log:\n"
        f"--- EVENT LOG START ---\n"
        f"{events_str}\n"
        f"--- EVENT LOG END ---\n\n"
        f"Write a single concise, readable postmortem paragraph summarizing: "
        f"what happened, what was diagnosed, what action was taken, and whether it resolved the issue."
    )

    max_attempts = 2
    last_exception = None

    for attempt in range(max_attempts):
        try:
            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "You are an SRE Communicator agent. Write a clear, concise postmortem paragraph."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500
            )

            content = completion.choices[0].message.content
            if content and content.strip():
                return content.strip()
            raise ValueError("LLM returned empty completion")
        except Exception as e:
            last_exception = e
            if attempt < max_attempts - 1:
                time.sleep(1.0)

    raise RuntimeError(f"Communicator Agent failed after {max_attempts} attempts: {last_exception}")
