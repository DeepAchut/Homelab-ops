# karakeep

Self-hosted bookmark + read-later manager with AI tagging. Native iOS + Android apps + browser extensions + web UI. Deployed in K8s on the Evo-X2 Talos worker (`tier=ai-worker`), with bulky asset storage on the Peladn DAS via NFS.

Vendor: https://karakeep.app · GitHub: https://github.com/karakeep-app/karakeep

## What's in this folder

| File | Purpose |
|---|---|
| `namespace.yaml` | `karakeep` namespace with PSA baseline |
| `postgres-statefulset.yaml` + `postgres-service.yaml` | Postgres 17 (5 GB local-path PVC on Evo-X2 NVMe — DON'T put on NFS, LevelDB-style locking corrupts) |
| `meilisearch-pvc.yaml` + `meilisearch-deployment.yaml` + `meilisearch-service.yaml` | Meilisearch 1.13 for full-text search (3 GB local-path PVC, same rationale) |
| `karakeep-assets-pv.yaml` + `karakeep-assets-pvc.yaml` | **NFS PV** pointing at `192.168.4.150:/mnt/pvedas/karakeep/assets` (200 Gi). Holds screenshots, page archives, uploaded PDFs |
| `karakeep-deployment.yaml` | Main app — pinned to `tier=ai-worker`, wired to local Ollama (`qwen3:4b-instruct` on Peladn) for AI tagging |
| `karakeep-service.yaml` | NodePort `30801` for NPM frontend |
| `secret.example.yaml` | Plaintext template — fill, encrypt as `secret.enc.yaml`, commit only the encrypted version |
| `kustomization.yaml` | Includes everything above |

## Storage layout — important

| Data | Where | Why |
|---|---|---|
| Postgres data files | Local-path on Evo-X2 NVMe (5 Gi) | Postgres-on-NFS = corruption risk under load |
| Meilisearch LMDB | Local-path on Evo-X2 NVMe (3 Gi) | Same — LMDB requires real fsync semantics |
| Karakeep assets (screenshots, PDFs, page archives) | **NFS to DAS at `/mnt/pvedas/karakeep/assets`** | Bulky, low-IO, perfect for NFS. Survives Evo-X2 reinstall. |

Asset growth estimate: ~50 KB per bookmark without screenshot, ~500 KB-2 MB with full screenshot + page archive. 200 GB PV holds 100K+ archived bookmarks. Adjust in `karakeep-assets-pv.yaml` if you blow past.

## First-time deploy

### 0. Pre-flight (already done as of 2026-06-02)

- NFS export on Peladn: `/mnt/pvedas/karakeep 192.168.4.0/24(rw,sync,no_subtree_check,no_root_squash)` (in `/etc/exports`, exportfs'd)
- Directory `/mnt/pvedas/karakeep/assets` exists, owner `nobody:nogroup`, mode 0777

### 1. Generate secret values

```bash
echo "NEXTAUTH_SECRET=$(openssl rand -hex 32)"
echo "MEILI_MASTER_KEY=$(openssl rand -hex 32)"
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '+/=')"  # url-safe
```

### 2. Fill the secret

```bash
cd kubernetes/apps/karakeep
cp secret.example.yaml secrets.yaml
# edit secrets.yaml — paste the 3 generated values into all 4 placeholder spots
# (NEXTAUTH_SECRET, MEILI_MASTER_KEY, POSTGRES_PASSWORD twice — once in postgres
# secret and once embedded in DATABASE_URL in karakeep-app-creds)
```

### 3. Encrypt + commit

```bash
cp secrets.yaml secret.enc.yaml
sops --encrypt --in-place secret.enc.yaml
git add namespace.yaml postgres-*.yaml meilisearch-*.yaml karakeep-*.yaml \
        secret.enc.yaml kustomization.yaml README.md secret.example.yaml
git rm --cached secrets.yaml 2>/dev/null || true   # ensure it's never committed
echo "secrets.yaml" >> .gitignore
git commit -m "karakeep: initial deploy"
git push
```

### 4. Wait for Flux

```bash
kubectl -n flux-system annotate kustomization/apps reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite
kubectl -n karakeep get pods -w   # wait for Running 1/1
```

### 5. NPM proxy rule (do this in your NPM UI)

| Field | Value |
|---|---|
| Domain | `karakeep.dkghar.duckdns.org` |
| Scheme | `http` |
| Forward Hostname/IP | `192.168.4.71` (Evo-X2 Talos worker — or any other node IP) |
| Forward Port | `30801` |
| WebSocket support | ON |
| Block common exploits | ON |
| Let's Encrypt SSL | ON |

### 6. Create your first user

Open https://karakeep.dkghar.duckdns.org/ → Sign up → use a real email so password reset works → set strong password.

### 7. Lock signups

Edit `karakeep-deployment.yaml` — flip `DISABLE_SIGNUPS` from `"false"` to `"true"` — commit + push. Flux applies, no more open registration.

### 8. Install clients

| Platform | Get it |
|---|---|
| iOS | https://apps.apple.com/app/karakeep — point at `https://karakeep.dkghar.duckdns.org`, sign in |
| Android | https://play.google.com/store/apps/details?id=app.karakeep — same |
| Chrome / Brave / Edge / Firefox | Karakeep browser extension on each store — same URL + login |
| Windows / Mac / Linux desktop | The web UI is fine; add to taskbar as PWA |

## AI tagging — how the wiring works

The deployment talks to Peladn's always-on Ollama at `http://192.168.4.12:11434/v1` using OpenAI-compat. On every new bookmark, Karakeep's worker fetches the page → asks `qwen3:4b-instruct` to suggest 3–5 tags + a 1-sentence summary → stores them. You see them auto-populated within ~10 seconds of saving a link.

If you want richer tags + summary, point at the Evo-X2 host Ollama (`http://192.168.4.84:11434/v1`) with `qwen3.6:35b-a3b` instead — but that's a 24/7 dependency on Evo-X2 staying up. Stick with the small Peladn model unless quality really lags.

To change models without redeploy: edit `INFERENCE_TEXT_MODEL` in `karakeep-deployment.yaml` and Flux rolls.

## Operate

| Want | How |
|---|---|
| Tail logs | `kubectl -n karakeep logs -f deploy/karakeep` |
| Restart app pod | `kubectl -n karakeep rollout restart deploy/karakeep` |
| Postgres shell | `kubectl -n karakeep exec -it postgres-0 -- psql -U karakeep` |
| Backup Postgres | already covered by the Saturday rpi4 PVC dump workflow? **NO** — this is on Evo-X2, not rpi4. Add to your DAS workflow: `vzdump 402` would NOT cover it because postgres data is in K8s local-path, not Proxmox-visible. Run a logical dump via cronjob (see TODO below). |
| Browse assets directly | SSH to Peladn → `ls -la /mnt/pvedas/karakeep/assets` |
| Move assets PVC to a bigger size | Edit `karakeep-assets-pv.yaml` storage value + matching PVC, kubectl apply. Underlying NFS share can hold as much as DAS has free. |

## TODO (Phase 2)

- **Postgres backup CronJob** — mirror the pattern from `apps/mem0/postgres/backup-cronjob.yaml`. Daily `pg_dump` to NFS at `/mnt/pvedas/karakeep-backups/postgres/`.
- **Meilisearch backup** — easier: it's a derived index, can be re-built from Postgres + page re-crawl. Skip backup unless reindex cost becomes prohibitive.
- **Wire to Miniflux** — when you star an entry in Miniflux, fire a webhook into Karakeep's `POST /api/v1/bookmarks` to auto-save. Closes the read-it-later loop.
- **Add to digest workflow** — let the digest curator search Karakeep's tags ("show me Karakeep items tagged #aws from last week") as a source for the Tech section.

## See also

- [`docs/case-study-ai-memory-layer.md`](../../../docs/case-study-ai-memory-layer.md) — same Postgres-on-local-path / heavy-data-on-NFS pattern
- [`apps/mem0/`](../mem0/) — closest existing reference for the StatefulSet + worker layout
