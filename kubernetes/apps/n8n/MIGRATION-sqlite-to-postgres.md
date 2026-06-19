# n8n: SQLite-on-NFS → PostgreSQL migration

**Why:** n8n was running default SQLite with its DB on a DAS-backed **NFS** PVC
(`nfs-storage`). When the DAS USB drive flapped (2026-06-19, see
[`Phase-27-nextcloud-recovery.md`](../../../../Phase-27-nextcloud-recovery.md)),
the NFS share dropped mid-write and n8n threw `SQLITE_CORRUPT: database disk
image is malformed`. **SQLite over NFS is unsafe** (NFS file locking is
unreliable). This migrates n8n to PostgreSQL on **local-path** (node-local)
storage, eliminating the failure mode.

The data was already exported as a portable safety backup:
- in-pod: `/home/node/.n8n/migration-export/{workflows.json,credentials.json}`
- off-NFS on the admin box: `C:\Users\Administrator\n8n-migration-backup\`
- 39 workflows, 28 credentials (verified via a clean `.recover` test)

The full corrupt DB is also backed up in-pod at
`/home/node/.n8n/_corrupt_backup_20260619-153711/`.

## What changed in the manifests

- **NEW** `postgres/` — `n8n-postgres` StatefulSet (`postgres:17`), headless
  Service, `n8n-postgres-data` PVC on **local-path**, `n8n-postgres-creds`
  Secret. Pinned to `ira-rpi4-talos-worker` (where n8n runs).
- **`deployment.yaml`** — added `DB_TYPE=postgresdb` + `DB_POSTGRESDB_*` env.
  `N8N_ENCRYPTION_KEY` is unchanged (critical — imported credentials only
  decrypt with the same key).
- **`kustomization.yaml`** — added the four `postgres/*` resources.

## Cutover runbook

### Step 0 — set the Postgres password + encrypt the secret (you)

```sh
cd Homelab-ops/kubernetes/apps/n8n/postgres
cp secret.yaml secret.enc.yaml
# edit secret.enc.yaml — set POSTGRES_PASSWORD to a real value:
#   openssl rand -hex 24
sops --encrypt --in-place secret.enc.yaml
```

### Step 1 — commit + let Flux deploy (you)

```sh
cd Homelab-ops
git add kubernetes/apps/n8n/
git commit -m "n8n: migrate SQLite-on-NFS to PostgreSQL (local-path)"
git push
flux reconcile kustomization apps --with-source
```

Flux will: bring up `n8n-postgres` (empty DB; the image creates the `n8n`
database + user from the secret), then restart the n8n pod with
`DB_TYPE=postgresdb`. n8n connects to the empty Postgres, runs **its own schema
migrations**, and starts healthy — but with **0 workflows** (DB is empty).
That's expected; the import is next.

Watch:
```sh
kubectl -n n8n get pods -w
# wait for n8n-postgres-0 Ready AND the n8n pod Running/Ready
```

### Step 2 — import workflows + credentials (me, or you)

The export files are still on the n8n config PVC. Import **credentials first**
(workflows reference them), then workflows:

```sh
POD=$(kubectl -n n8n get pod -l app=n8n -o jsonpath='{.items[0].metadata.name}')

kubectl -n n8n exec "$POD" -c n8n -- \
  n8n import:credentials --input=/home/node/.n8n/migration-export/credentials.json

kubectl -n n8n exec "$POD" -c n8n -- \
  n8n import:workflow --input=/home/node/.n8n/migration-export/workflows.json
```

### Step 3 — restart n8n so active workflows re-register their triggers

`import:workflow` writes the workflows (including their `active` flag) but the
trigger/webhook registration happens at n8n **startup**. Bounce the pod so the
previously-active workflows re-activate:

```sh
kubectl -n n8n rollout restart deploy/n8n
kubectl -n n8n rollout status deploy/n8n
```

### Step 4 — verify

```sh
POD=$(kubectl -n n8n get pod -l app=n8n -o jsonpath='{.items[0].metadata.name}')
# Counts from Postgres (should be 39 / 28):
kubectl -n n8n exec n8n-postgres-0 -- psql -U n8n -d n8n -tAc \
  "select (select count(*) from workflow_entity) as workflows,
          (select count(*) from credentials_entity) as creds;"
# No SQLITE errors in logs anymore:
kubectl -n n8n logs "$POD" -c n8n --tail=100 | grep -iE 'sqlite|corrupt' || echo "clean — no sqlite references"
# UI: log in at https://n8n.dkghar.duckdns.org, confirm workflows + a test execution.
```

Then re-check that the workflows that were **active** before are active again
(in the UI). If any didn't re-activate, toggle them on — their triggers will
register.

## Post-migration cleanup (optional, later)

- The old `database.sqlite` on the NFS config PVC is now unused. Leave it for a
  while as a safety net; delete `_corrupt_backup_*` and `database.sqlite*` once
  you've confirmed Postgres is solid for a few days.
- `binaryData` still lives on the NFS config PVC. It's blob files (no DB
  locking), so far lower corruption risk than SQLite was — but moving the
  config/data PVCs to local-path too would fully de-risk n8n from the DAS.
  Separate task.

## Rollback

If Postgres misbehaves, revert to SQLite-on-NFS instantly: `git revert` the
migration commit + `flux reconcile`. n8n restarts without `DB_TYPE`, reopens the
original `database.sqlite` (untouched on the NFS PVC — the migration never
deleted it). You lose anything created in Postgres since cutover (workflows you
add post-migration), so prefer fixing forward unless Postgres is truly broken.
