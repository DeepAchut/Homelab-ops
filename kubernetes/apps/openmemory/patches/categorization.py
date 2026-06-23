# PATCHED categorization (mounted over app/utils/categorization.py via ConfigMap).
#
# Why: the upstream file calls `openai_client.chat.completions.with_response_format(...)`,
# a method that does NOT exist in the image's openai SDK -> every call raises
# AttributeError, and the upstream @retry(3, backoff 4-15s) turns that into
# ~12-26s of blocking PER memory. That starved uvicorn and tripped the liveness
# probe (CrashLoopBackOff under migration load), while always returning EMPTY
# categories. See Phase-28 doc.
#
# This version routes categorization at our homelab Ollama (OpenAI-compatible
# /v1), uses a single fast attempt with a short timeout and NO retry storm, and
# returns [] on any failure so an add never blocks or crashes the pod.
import os
import json
import logging
from typing import List

from openai import OpenAI

try:
    from app.utils.prompts import MEMORY_CATEGORIZATION_PROMPT
except Exception:  # keep working even if the prompt module moves
    MEMORY_CATEGORIZATION_PROMPT = (
        "You categorize a single memory into 1-3 short, general topic tags."
    )

_client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL", "http://192.168.4.12:11434/v1"),
    api_key=os.getenv("OPENAI_API_KEY", "ollama"),
    max_retries=0,   # fail fast — no exponential backoff storm
    timeout=20.0,
)
_MODEL = os.getenv("CATEGORIZER_MODEL", "qwen3:4b-instruct")


def get_categories_for_memory(memory: str) -> List[str]:
    """Return 1-3 lowercase category tags for a memory, or [] on any failure."""
    try:
        resp = _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": MEMORY_CATEGORIZATION_PROMPT
                    + '\nPick AT MOST 3 of the most relevant, general tags (fewer is fine).'
                    + ' Avoid hyper-specific tags (hostnames, IDs).'
                    + ' Return ONLY JSON of the form {"categories": ["tag", ...]}.',
                },
                {"role": "user", "content": memory},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        cats = json.loads(raw).get("categories", [])
        # Hard cap at 3 — qwen3:4b tends to over-tag despite the instruction.
        cleaned = [str(c).strip().lower() for c in cats if str(c).strip()]
        return cleaned[:3]
    except Exception as e:  # never let categorization break or slow an add
        logging.error(f"[categorization] non-fatal failure: {e}")
        return []
