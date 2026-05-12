#!/usr/bin/env python3
"""
Push gemma4-mem0 to Ollama using the structured create API.

Setup:
  1. Copy personal-context.txt.example → personal-context.txt
  2. Fill in your personal context
  3. Set OLLAMA_URL if your Ollama is not at the default below
  4. Run: python3 push-modelfile.py

personal-context.txt is gitignored — keep personal details out of the repo.
"""
import json, sys, urllib.request, urllib.error
from pathlib import Path

OLLAMA_URL = "http://192.168.4.12:11434"
MODEL_NAME = "gemma4-mem0"
BASE_MODEL = "gemma4:e2b"

BASE_PROMPT = """\
You are a personal memory intelligence engine for {{USER_NAME}}.

Your sole function is to extract structured, durable facts from conversations
and output them as valid JSON. You MUST:
- Output ONLY valid JSON. No explanations, no markdown fences, no preamble.
- Extract facts worth remembering across sessions: personal details, technical
  preferences, project decisions, infrastructure configs, goals, lessons learned.
- Ignore transient content: in-progress commands, build output, one-shot steps.
- If nothing worth remembering is found, output: {}

{{PERSONAL_CONTEXT}}

Prioritize extracting:
1. Technical decisions and their rationale (chose X over Y because Z)
2. Infrastructure facts: IPs, hostnames, model names, versions, port numbers
3. Personal preferences, habits, and goals
4. Project milestones and current state
5. Problems solved and their root cause (so future sessions avoid same mistakes)
6. Corrections to previously wrong assumptions

Never extract:
- Passwords, tokens, secrets, API keys, or private keys
- Temporary debugging output or one-shot commands
- Information the user already explicitly knows about themselves\
"""


def load_personal_context() -> tuple[str, str]:
    """Return (user_name, personal_context) from local personal-context.txt."""
    ctx_file = Path(__file__).parent / "personal-context.txt"
    if not ctx_file.exists():
        print(
            "Warning: personal-context.txt not found. "
            "Copy personal-context.txt.example and fill it in.",
            file=sys.stderr,
        )
        return "the user", "(no personal context configured)"
    text = ctx_file.read_text(encoding="utf-8").strip()
    # First non-comment, non-empty line treated as user name if it starts with "name:"
    user_name = "the user"
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("name:"):
            user_name = line.split(":", 1)[1].strip()
            break
    return user_name, text


def main() -> None:
    user_name, personal_context = load_personal_context()
    system_prompt = (
        BASE_PROMPT.replace("{{USER_NAME}}", user_name)
                   .replace("{{PERSONAL_CONTEXT}}", personal_context)
    )

    payload = json.dumps({
        "model": MODEL_NAME,
        "from": BASE_MODEL,
        "system": system_prompt,
        "parameters": {
            "temperature": 0.1,
            "top_p": 0.9,
            "num_ctx": 4096,
        },
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/create",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
            print(f"OK: {resp.get('status', resp)}")
    except urllib.error.HTTPError as e:
        print(f"FAIL {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
