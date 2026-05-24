# Peladn → Evo-X2 Failover (n8n-triggered, GitOps)

Restore Peladn's guests (Talos CP **201**, media-ai **202**, home-ops **203**) onto the
always-on **Evo-X2** if Peladn dies. The PBS backups already live on Evo-X2 (the 26 TB +
CT200 were migrated there — see `../../` Phase 21 docs), so failover is just **restore
locally → start**. No WOL, no sync, no second PBS.

Full runbook: `Phase-21-Part-2 - failover-runbook-evox2.md` (in the docs repo root).

## Files

| File | Runs on | Purpose |
|---|---|---|
| `peladn-failover.sh` | Evo-X2 host | Restores 201/202/203 from `pbs-local` and starts them. Has a split-brain guard (refuses if Peladn API is still reachable; `FORCE=1` to override). |
| `evox2-readiness.sh` | Evo-X2 host | Idempotent prep: adds `pbs-local` storage, creates stub dirs, installs the failover script. |
| `n8n-peladn-watchdog.json` | n8n (RPi4) | Polls Peladn every 2 min; **alerts** after 3 misses. Does NOT auto-restore. |
| `n8n-peladn-failover.json` | n8n (RPi4) | Webhook-triggered: notify → SSH Evo-X2 → pull+run `peladn-failover.sh` → notify. |
| `.env` (gitignored) | — | `PBS_TOKEN_SECRET=…` for `evox2-readiness.sh` (only when adding `pbs-local` on a fresh host). |

## How the GitOps retrieval works

`peladn-failover.sh` is the **single source of truth** in this repo. The n8n failover
workflow pulls the latest copy from the public repo at trigger time and runs it:

```bash
curl -fsSL https://raw.githubusercontent.com/DeepAchut/Homelab-ops/main/infrastructure/failover/peladn-failover.sh \
  -o /usr/local/bin/peladn-failover.sh 2>/dev/null || true   # latest from GitOps (best-effort)
chmod +x /usr/local/bin/peladn-failover.sh
bash /usr/local/bin/peladn-failover.sh                        # local copy = offline fallback
```

So a `git push` to `main` is the deploy — n8n always runs the current version, and the
on-host copy (installed by `evox2-readiness.sh`) is the offline fallback if GitHub is
unreachable during an outage.

## n8n workflows

Import the two JSONs (n8n → Workflows → Import from File), then:

1. **`peladn-watchdog`** — map an HTTP **Header Auth** credential holding a Peladn PVE API
   token (`Authorization: PVEAPIToken=USER@REALM!TOKENID=SECRET`). Activate it. It alerts
   once after ~6 min of downtime. Detection only — you decide when to fail over.
2. **`peladn-failover`** — map the **SSH** credential for `root@192.168.4.84` (Evo-X2).
   Trigger it deliberately (the webhook URL, or n8n "Execute"). It runs the restore and
   notifies on completion.

> ⚠️ **Notification channel must NOT live on Peladn.** Gotify runs in CT203 (home-ops) on
> Peladn — it's **down during a Peladn failure**, so failover/watchdog alerts can't use it.
> These workflows default to **ntfy.sh** (public, zero-infra, Peladn-independent) — set your
> private topic in the two HTTP nodes. (Keep Gotify for normal/backup-success notices, which
> happen while Peladn is up.) Alternatives: Telegram, or email via SMTP.

## Secrets & infra details (what's public vs private)

Nothing sensitive is committed. The split:

- **Committed (public — this is the showcase):** all *logic* — the script, the n8n workflows, the readiness flow, this README. Values are referenced as variables.
- **Private (gitignored `./.env`, or SOPS `./.env.enc.yaml`):** environment-specific values — `PBS_SERVER` (host IP), `PBS_FINGERPRINT` (PBS cert SHA-256), `PBS_TOKEN_SECRET` (the only real credential). See `.env.example`.

`peladn-failover.sh` needs **no** secrets at all (the PBS token lives in PVE's
`/etc/pve/priv/storage/pbs-local.pw` on Evo-X2). `evox2-readiness.sh` reads the `.env`
values **only** when first adding `pbs-local`:

```bash
# on Evo-X2, in this dir
cp .env.example .env && $EDITOR .env      # or: sops -d .env.enc.yaml > .env
./evox2-readiness.sh
rm -f .env
```

> The fingerprint is the SHA-256 of the PBS *public* TLS cert (a pinning value, like an SSH
> host-key fingerprint) — not a credential. It's kept in `.env` purely to keep infra details
> out of the public repo, not because it grants access.

## Current state (2026-05-24)

`evox2-readiness.sh` has already been applied to Evo-X2 (storage `pbs-local` active, stub
dirs present, script installed). Remaining: import/activate the two n8n workflows, set the
ntfy topic, add the OPNsense reservation for the Talos CP MAC `BC:24:11:C1:FB:D7 → .172`,
and test a restore into throwaway IDs (Part 2 §9).
