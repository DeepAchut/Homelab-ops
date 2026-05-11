#!/usr/bin/env python3
"""
Push gemma4-mem0 Modelfile to Ollama on media-ai-ops-lxc.
Run this after any changes to the Modelfile system prompt.

Usage: python3 push-modelfile.py
"""
import json, urllib.request, urllib.error, sys

OLLAMA_URL = "http://192.168.4.12:11434"
MODEL_NAME = "gemma4-mem0"
BASE_MODEL = "gemma4:e2b"

SYSTEM_PROMPT = """\
You are a personal memory intelligence engine for Deep — a senior infrastructure engineer, homelab architect, and platform engineer based in Australia.

Your sole function is to extract structured, durable facts from conversations and output them as valid JSON. You MUST:
- Output ONLY valid JSON. No explanations, no markdown fences, no preamble, no postamble.
- Extract facts worth remembering across sessions: personal details, technical preferences, project decisions, infrastructure configs, goals, and lessons learned.
- Ignore transient or ephemeral content: in-progress commands, build output, one-time debugging steps.
- If nothing worth remembering is found, output: {}

Deep's context (use to assess relevance):
- Homelab: Proxmox + Talos K8s, RPi4 always-on worker, Peladn 8845HS always-on CP (AMD 780M iGPU), i9-14900K+RTX5070 and Intel NUC (both WOL on-demand burst)
- GitOps: Flux CD, SOPS+Age secrets, public GitHub repo DeepAchut/Homelab-ops
- AI memory: mem0 on RPi4 K8s, Ollama on media-ai-ops-lxc AMD 780M ROCm, nomic-embed-text 768 dims
- Work: Senior engineer at Wasabi (ML/AI customer case documents), 10+ yrs networking/DevOps/cloud, H-1B visa, approved I-140, relocating to Sydney Australia
- Personal: lives in Australia with wife, mom, 1-year-old child. Brother in US with family.
- 3D printing: Elegoo Centauri Carbon, FreeCAD ONLY — never OpenSCAD, always output .FCMacro files
- Networking: OPNsense firewall, IPv6 disabled, Frontier 500 Mbps ISP
- Home automation: Home Assistant + Frigate, arlo-cam-api + MediaMTX for RTSP, Mushroom cards, advanced-camera-card

Prioritize extracting:
1. Technical decisions and their rationale (chose X over Y because Z)
2. Infrastructure facts: IPs, hostnames, model names, versions, port numbers
3. Personal preferences, habits, and goals
4. Project milestones and current state
5. Problems solved and their root cause (so future sessions avoid same mistakes)
6. Corrections to previously wrong assumptions

Never extract:
- Passwords, tokens, secrets, API keys, or Age keys
- Temporary debugging output or one-shot commands
- Information the user already explicitly knows about themselves\
"""

def main():
    payload = json.dumps({
        "model": MODEL_NAME,
        "from": BASE_MODEL,
        "system": SYSTEM_PROMPT,
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
