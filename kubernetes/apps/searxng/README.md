# searxng

Self-hosted metasearch engine — aggregates Google, Bing, DuckDuckGo and others without exposing the user. Powers Open WebUI's web-search feature. Free, no API key, no quota.

Vendor: https://searxng.org · Image: `docker.io/searxng/searxng:latest`

## What's in this folder

| File | Purpose |
|---|---|
| `namespace.yaml` | `searxng` namespace with PSA baseline |
| `configmap.yaml` | `settings.yml` for SearXNG — JSON format enabled (required by Open WebUI), limiter disabled (Open WebUI's per-pod rate would trip it) |
| `secret.example.yaml` | Template for SOPS-encrypted `SEARXNG_SECRET` |
| `deployment.yaml` | 1 pod on `tier=ai-worker` (Evo-X2), no PVC needed (stateless) |
| `service.yaml` | NodePort `30802` for external/NPM access |
| `kustomization.yaml` | Index |

## First-time deploy

### 1. Generate the secret + encrypt

```bash
cd kubernetes/apps/searxng
cp secret.example.yaml secrets.yaml
sed -i "s/REPLACE_ME_32_HEX_CHARS/$(openssl rand -hex 32)/" secrets.yaml
cp secrets.yaml secret.enc.yaml
sops --encrypt --in-place secret.enc.yaml
echo "secrets.yaml" >> .gitignore
```

### 2. Commit + Flux reconcile

```bash
git add namespace.yaml configmap.yaml deployment.yaml service.yaml \
        secret.enc.yaml secret.example.yaml kustomization.yaml README.md
git commit -m "searxng: initial deploy for Open WebUI web search"
git push
kubectl -n flux-system annotate kustomization/apps reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite
kubectl -n searxng get pods -w   # wait for Running 1/1
```

### 3. NPM proxy rule (optional — only needed if you want to use the SearXNG web UI directly from a browser)

| Field | Value |
|---|---|
| Domain | `searxng.dkghar.duckdns.org` |
| Forward Hostname/IP | any Talos worker IP, e.g. Evo-X2 worker `192.168.4.71` |
| Forward Port | `30802` |
| WebSocket support | OFF (not needed) |
| Block common exploits | ON |
| Let's Encrypt SSL | ON |

If you only want SearXNG for Open WebUI (no direct browser access), skip this step — Open WebUI hits it via cluster DNS.

### 4. Wire into Open WebUI

Open WebUI → Admin Panel → Settings → **Web Search**:

| Field | Value |
|---|---|
| Enable Web Search | ON |
| Search Engine | `searxng` |
| Searxng Query URL | `http://searxng.searxng.svc.cluster.local:8080/search?q=<query>` |
| Search Result Count | `5` (default; bump to 8-10 if you want more context) |
| Concurrent Requests | `5` |

Save. Then in any chat, toggle the **"Web Search"** option (globe icon under the input) and ask something like "what's new in Talos Linux this week" — Open WebUI will hit SearXNG, scrape top results, inject them into the prompt.

## Operate

| Want | How |
|---|---|
| Tail logs | `kubectl -n searxng logs -f deploy/searxng` |
| Reload settings (after editing configmap.yaml) | `kubectl -n searxng rollout restart deploy/searxng` |
| Verify JSON format is enabled (needed by Open WebUI) | `curl 'http://searxng.searxng.svc.cluster.local:8080/search?q=test&format=json' \| jq '.results \| length'` |
| Manual test from a worker | open `http://<worker-ip>:30802/` in a browser |

## Why this config

- **`limiter: false`** — SearXNG's built-in per-IP rate limit trips when Open WebUI does 5 concurrent fetches; disabling is the standard fix for trusted internal-only use.
- **`formats: [html, json]`** — Open WebUI requires the `json` format to be enabled; default ships with only `html`.
- **No Redis sidecar** — SearXNG runs fine without it for single-pod homelab use. Adding Redis is a 2-pod tax for marginal speedup; revisit only if you start using SearXNG heavily in your browser too.
- **NodePort instead of LoadBalancer** — matches the same pattern as mem0 (30800), karakeep (30801). NPM routes external traffic via the NodePort.

## Phase 2 ideas (deferred)

- Add Redis sidecar if SearXNG becomes a daily browser-driver.
- Tune `enabled_engines` in `settings.yml` to your preference (e.g. drop SEO-spam-heavy sources).
- Add result rewriting plugins (e.g. youtube → invidious) for privacy.

## See also

- [Open WebUI Web Search docs](https://docs.openwebui.com/category/web-search/)
- [`apps/open-webui/`](../open-webui/) — consumer of this service
