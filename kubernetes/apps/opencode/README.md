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

# 4. Enter the shell (using scripts)
# Windows (PowerShell)
.\opencode-shell.ps1

# Linux / Mac / Git Bash
./opencode-shell.sh

## Better Approaches

### 1. kubectl plugin (Pro)
To make this a first-class `kubectl` command, rename or symlink the script to `kubectl-opencode` and place it in your system `PATH`. You can then run it from anywhere using:
```sh
kubectl opencode
```

### 2. Shell Functions
Add this to your shell profile to run `opencode-shell` from any directory:

**PowerShell ($PROFILE):**
```powershell
function opencode-shell {
    $POD = kubectl get pod -n opencode -l app=opencode-shell -o name | Select-Object -First 1
    kubectl exec -it -n opencode $POD -- bash -c "cd /workspace/Homelab-ops && opencode"
}
```

**Bash/Zsh (~/.bashrc):**
```bash
opencode-shell() {
    POD=$(kubectl get pod -n opencode -l app=opencode-shell -o name | head -n 1)
    kubectl exec -it -n opencode "$POD" -- bash -c "cd /workspace/Homelab-ops && opencode"
}
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
