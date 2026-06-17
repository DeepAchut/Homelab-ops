# opencode — terminal AI coding agent

OpenCode shell pod on `ira-evo-x2-talos-worker` (Strix Halo). One always-running
interactive shell you `kubectl exec` into; runs the OpenCode TUI with four
providers configured.

See [`Phase-26-implementation.md`](../../../../Phase-26-implementation.md) at
the repo root for the deploy walkthrough and design rationale.

## Quick start

```sh
# 1. Fill secret.yaml → secret.enc.yaml + encrypt
cp secret.yaml secret.enc.yaml
# edit secret.enc.yaml with real values from:
#   - kubernetes/apps/hermes-agent/secret.enc.yaml → GEMINI_API_KEY (reuse it)
#   - kubernetes/apps/hermes-agent/secret.enc.yaml  → API_SERVER_KEY
#   - kubernetes/apps/hermes-family/secret.enc.yaml → API_SERVER_KEY
sops --encrypt --in-place secret.enc.yaml

# 2. Commit + Flux reconciles
git add . && git commit -m "Phase 26 — opencode app" && git push
flux reconcile kustomization apps --with-source

# 3. Wait for pod
kubectl -n opencode get pods -w

# 4. Exec in
POD=$(kubectl -n opencode get pod -l app=opencode-shell -o name)
kubectl -n opencode exec -it "$POD" -- bash

# 5. Inside the pod:
cd /workspace/Homelab-ops
opencode    # starts the TUI
```

## Files

| File | Purpose |
|---|---|
| `namespace.yaml` | `opencode` ns with PSA baseline |
| `rbac.yaml` | ServiceAccount, no API token |
| `pvc.yaml` | 3 PVCs: workspace (20Gi), config (2Gi), home (2Gi) |
| `configmap-opencode.yaml` | `opencode.json` — provider definitions |
| `configmap-helpers.yaml` | `mem0` CLI + `HOMELAB_CONTEXT.md` session header |
| `deployment.yaml` | Single shell pod, init container installs OpenCode |
| `secret.yaml` | Plaintext shape reference (do not commit real values) |
| `secret.enc.yaml` | Real secret, SOPS-encrypted (you create this) |
| `kustomization.yaml` | Flux entrypoint |

## Providers in `opencode.json`

| Provider | Models | Use case |
|---|---|---|
| `anthropic` | opus-4-8, sonnet-4-6, haiku-4-5 | Hard tasks, agentic work |
| `ollama-evox2` | gemma4:e4b, qwen3.6:35b-a3b | Local/no-egress, multimodal, local coding |
| `hermes-admin` | hermes-default | Homelab admin skills (ssh_exec, k8s_status, etc.) |
| `hermes-family` | hermes-default | Family-safe chat, isolated mem0 namespace |

Switch model inside the TUI: `/model anthropic/claude-sonnet-4-6`

## mem0 helper

The `mem0` CLI is on `$PATH` inside the shell:

```sh
mem0 search "qwen endpoint"
mem0 add "Phase 26 done — opencode deployed 2026-06-16"
mem0 list
mem0 --user family search "preferences"
```
