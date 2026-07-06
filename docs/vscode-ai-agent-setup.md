# Self-hosted AI coding agent in VS Code (Claude-Code style, local models)

**Goal:** an agentic assistant *inside VS Code* — reads/edits files, runs terminal
commands, iterates — like Claude Code, but driven by a **self-hosted model** on the
homelab (no cloud, no per-token cost).

**TL;DR recommendation**

| Piece | Choice | Why |
|---|---|---|
| Extension | **Cline** (VS Code Marketplace) | Closest to Claude Code: plan/act agent, file edits, terminal, diffs, MCP. Native Ollama + OpenAI-compatible support. |
| Model | **`qwen3.6:35b-a3b`** on the Evo-X2 Ollama | Your designated local coding model (36B MoE, 3.8B active). Verified below: does OpenAI-style chat **and tool-calling** — the hard requirement for an agent. |
| Endpoint | `http://192.168.4.84:11434` (LAN, no auth) | Always-on Strix Halo host, 44 tok/s, 71 GiB VRAM. Reachable from the laptop on the `192.168.4.0/24` LAN. |

Lighter alternatives that also work with the same endpoint: **Continue.dev** (adds
inline autocomplete) and **Roo Code** (Cline fork, more knobs). Pick Cline first.

> **Cline is free.** It's open-source; pointed at your own Ollama it costs nothing —
> no account, no credits. The "sign in / buy credits" prompt you may see is only for
> Cline's *optional* hosted-model provider. Just select the **Ollama** provider and
> ignore it. All the extensions in this doc are free and open-source.

**Free + open-source options that work with your LAN Ollama** (all use the same
`http://192.168.4.84:11434` endpoint):

| Tool | Notes |
|---|---|
| **Cline** | Recommended — closest to Claude Code. Choose the Ollama provider. |
| **Roo Code** | Cline fork, more settings/knobs. Same setup. |
| **Continue.dev** | Lighter; also adds inline autocomplete. Drop-in config in the appendix. |
| **Kilo Code** | Another Cline-family fork. |

---

## Why not the other things you mentioned

- **OpenCode** — it's a TUI/CLI that runs as a pod on Evo-X2 (you reach it by
  `kubectl exec`). Its VS Code extension expects a local `opencode serve`; wiring it
  to the remote pod is awkward. It's great as a *shell* agent, not as an in-editor
  one. Keep it for terminal work; use Cline for the IDE.
- **Gemini CLI / Google Antigravity** — both are hard-wired to Google's Gemini
  models (API key / Vertex). They are **not** built to point at a local Ollama, so
  they can't use your self-hosted models. Not a fit for the "use my own model" goal.
- **Cursor / Windsurf** — poor fit for a **local/LAN** Ollama, and Cursor is the one
  that's actually *paid* (Pro subscription):
  1. **Requests route through their cloud.** Cursor's "custom OpenAI Base URL"
     override is validated/processed **server-side**, so the endpoint must be
     reachable from *Cursor's* servers — not just your laptop. Your Ollama at
     `192.168.4.84:11434` is LAN-only, so Cursor can't reach it unless you **expose
     Ollama to the public internet via a tunnel** (ngrok/Cloudflare), which defeats
     the private/no-egress goal and adds latency + a security hole.
  2. **Agent mode is model-locked.** Cursor's Composer/Agent (the real file-editing
     agent) is tied to Cursor's own models; custom/local models historically drive
     only plain chat, not the agentic editing you want.
  Net: use a **free, open-source, local-first** extension (Cline/Roo/Continue) that
  talks to the LAN endpoint directly. No tunnel, no subscription.
- **Hermes (family or admin)** — the Hermes gateways are OpenAI-compatible, **but**:
  1. They're `*.svc.cluster.local` — **in-cluster only**, so VS Code on the laptop
     can't reach them without exposing a NodePort/ingress.
  2. `hermes-family` is **gemma4:e4b-backed** (a ~4B model) — too small to drive
     agentic coding reliably (weak multi-step tool use, small effective context).
  3. Hermes is a *personal-assistant* agent (skills, mem0, SSH) — routing coding
     through it adds a hop and its system prompt without improving code quality.
  Going straight to `qwen3.6` on the Evo-X2 Ollama is both **reachable** and
  **stronger for code**. (If you still want Hermes-in-VS-Code for its skills/mem0,
  see the appendix — it needs a NodePort and you accept the gemma4 limits.)
- **gemma4:e4b directly** — fine for quick chat, but as an *agent* it will stumble on
  multi-file edits and tool loops. Use it only as a fast fallback.

> **Honest expectation:** a local 36B-MoE at ~44 tok/s is very usable but **not** as
> fast or as strong as Claude/Gemini on hard, multi-file agentic tasks. Great for
> scoped edits, boilerplate, refactors, explanations, tests. For a gnarly whole-repo
> change, still reach for Claude Code. This setup is "capable and free/private," not
> "Claude-equal."

---

## Step 0 (server, one-time) — give the model real context

Ollama truncates every prompt to ~4K tokens by default, which **breaks** agentic
tools (they send big multi-file prompts). Fix on the Evo-X2 host:

The repo change is already made in
[`infrastructure/ollama-host/ollama-override.conf`](../infrastructure/ollama-host/ollama-override.conf)
(added `OLLAMA_CONTEXT_LENGTH=32768`). Apply it on the host:

```bash
# On the Evo-X2 host (192.168.4.84), as root:
#   copy the repo's ollama-override.conf to the systemd drop-in, then:
systemctl daemon-reload && systemctl restart ollama

# verify the model now advertises a 32K context:
curl -s http://localhost:11434/api/ps        # after first use, shows context size
```

qwen3.6 supports 256K; 32K is a good local balance (agent has room, prompt-eval stays
fast). It's cheap here because of `q8_0` KV cache + flash attention on 71 GiB VRAM.

---

## Step 1 — install Cline

1. VS Code → Extensions (`Ctrl+Shift+X`) → search **"Cline"** → Install
   (publisher **saoudrizwan**, name "Cline").
2. Click the Cline robot icon in the Activity Bar.

## Step 2 — point Cline at the Evo-X2 Ollama

In Cline's settings (gear icon → API Configuration):

**Option A — native Ollama provider (simplest):**
- **API Provider:** `Ollama`
- **Base URL:** `http://192.168.4.84:11434`
- **Model:** `qwen3.6:35b-a3b` (it auto-lists from the server)
- **Context window / num_ctx:** `32768` (if the field is shown)

**Option B — OpenAI Compatible (most robust, always works):**
- **API Provider:** `OpenAI Compatible`
- **Base URL:** `http://192.168.4.84:11434/v1`
- **API Key:** `ollama`  ← any non-empty string; Ollama ignores it
- **Model ID:** `qwen3.6:35b-a3b`

That's it — no keys, no cloud. If VS Code is on the same LAN it connects directly.

## Step 3 — use it

- Open your repo folder in VS Code.
- In Cline: type a task (e.g. *"add a health endpoint to service X and a test"*).
- Cline plans, proposes file diffs (you approve), and can run terminal commands.
- Start in **Plan** mode for anything non-trivial, then switch to **Act**.

---

## Tuning notes (local-model specific)

- **It "thinks."** qwen3.6 is a reasoning model — it emits a hidden thinking phase
  before answering, so first-token latency is higher. That's normal. Cline handles
  reasoning models. If a task is simple and you want speed, switch Cline's model to
  `gemma4:e4b` for that task.
- **Keep tasks scoped.** Local models do best with focused asks and fewer files in
  context. Use Cline's file-mention (`@file`) to include exactly what's relevant
  rather than the whole tree.
- **Auto-approve carefully.** Cline can auto-run commands/edits. On a smaller model,
  leave approval **on** until you trust its behavior on your repo.
- **Keep it hot.** `OLLAMA_KEEP_ALIVE=24h` is already set, so the model stays resident
  (no 2.6s reload each time). `ollama ps` on the host shows what's loaded.

## Verify the backend yourself (already tested green)

```bash
# reachable + models
curl -s http://192.168.4.84:11434/api/tags | grep -o '"name":"[^"]*"'

# chat works
curl -s http://192.168.4.84:11434/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6:35b-a3b","messages":[{"role":"user","content":"one-line python is_even"}],"stream":false,"max_tokens":300}'

# tool-calling works (the agentic requirement) — returns a tool_calls block
curl -s http://192.168.4.84:11434/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6:35b-a3b","messages":[{"role":"user","content":"read /etc/hostname with the tool"}],"stream":false,"tools":[{"type":"function","function":{"name":"read_file","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}}]}'
```

---

## Appendix — Continue.dev drop-in config (free alternative to Cline)

If you prefer Continue.dev (lighter, and it adds inline tab-autocomplete), install the
**Continue** extension, then put this in `~/.continue/config.yaml` (create the file if
missing). It wires chat + edit + apply to `qwen3.6` and uses the small embedding model
for codebase indexing — all on the Evo-X2 Ollama, no cloud:

```yaml
name: homelab-local
version: 0.0.1
schema: v1
models:
  - name: Qwen3.6 (Evo-X2)
    provider: ollama
    model: qwen3.6:35b-a3b
    apiBase: http://192.168.4.84:11434
    defaultCompletionOptions:
      contextLength: 32768
    roles:
      - chat
      - edit
      - apply
  - name: Gemma4 (fast fallback)
    provider: ollama
    model: gemma4:e4b
    apiBase: http://192.168.4.84:11434
    roles:
      - chat
  - name: Nomic-style embeddings (Evo-X2)
    provider: ollama
    model: qwen3-embedding:0.6b
    apiBase: http://192.168.4.84:11434
    roles:
      - embed
```

Then open Continue's sidebar, pick **Qwen3.6 (Evo-X2)**, and use **Agent** mode for
multi-step edits. (Same server-side `OLLAMA_CONTEXT_LENGTH=32768` fix from Step 0
applies — Continue's `contextLength` above only *requests* it; the server cap is what
actually enforces it.)

## Appendix — if you really want Hermes (skills + mem0) in VS Code

Doable but with caveats. You'd need to:
1. Expose the family Hermes gateway on a NodePort (it's `hermes-family.hermes-family
   .svc.cluster.local:8642` today — cluster-internal). Add a `NodePort` Service, e.g.
   `:8642 → 30642`, then use `http://192.168.4.141:30642/v1` as the base URL.
2. Set the API key (`HERMES_FAMILY_KEY`) as Cline's API key.
3. Accept that it's **gemma4:e4b-backed** — expect weaker agentic coding than
   qwen3.6, and Hermes' assistant system-prompt/skills layered on top.

Net: only worth it if you specifically want Hermes' mem0/skills *while* coding. For
pure coding, `qwen3.6` direct is better. Not recommended as the default.
