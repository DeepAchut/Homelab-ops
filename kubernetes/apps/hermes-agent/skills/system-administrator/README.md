# system-administrator skill (content private)

The actual skill instructions and topology map for this skill live in [`skill-content.enc.yaml`](skill-content.enc.yaml) — a SOPS-encrypted Kubernetes Secret. Hermes mounts it at runtime as `/seed-skill/SKILL.md`.

## Why encrypted

The skill content includes the homelab's internal topology (IPs, hostnames, VM IDs, K8s namespaces, observability endpoints). Useful to the agent, sensitive in a public repo.

## What's in this folder

| Path | Purpose | Visibility |
|---|---|---|
| `README.md` (this file) | Public stub | public |
| `skill-content.enc.yaml` | Encrypted SKILL.md (Secret) | encrypted-at-rest |
| `scripts/` | Helper Python scripts the skill references | public¹ |

¹ The scripts use env vars for endpoints; defaults match the homelab's LAN IPs. If you fork this for your own lab, set `BESZEL_URL`, `GRAFANA_URL`, `SEARXNG_URL`, etc. in the Hermes deployment.

## Edit cycle

```bash
sops kubernetes/apps/hermes-agent/skills/system-administrator/skill-content.enc.yaml
# opens decrypted in $EDITOR, modify the SKILL.md content under stringData, save
# .sops.yaml auto-re-encrypts on save
git add skill-content.enc.yaml
git commit -m "hermes: update system-administrator skill"
git push
kubectl -n hermes-agent rollout restart deploy/hermes-agent
```

## SOPS pattern

The `kubernetes/.sops.yaml` file at the repo root has a dedicated `creation_rules` entry that auto-encrypts any `.enc.yaml` under this folder with the homelab's Age key (kept in Vaultwarden). The encrypted_regex pin (`^(data|stringData)$`) means the Kubernetes Secret structure stays readable in git history — only the actual content under `stringData` is ciphered.
