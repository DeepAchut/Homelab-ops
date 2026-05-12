# Case Study: GitOps on Talos Linux with Flux CD and SOPS

**Problem:** Managing a multi-node homelab cluster manually — applying manifests by hand, tracking config drift, rotating secrets unsafely — doesn't scale and isn't production-credible.

**Solution:** Treat the Git repository as the single source of truth. Flux CD reconciles cluster state from Git continuously. SOPS + Age encrypts secrets so they're safe to commit to a public repo.

---

## Why Talos Linux?

Talos is a minimal, immutable Linux distribution purpose-built for running Kubernetes. Compared to Ubuntu/Debian-based K8s:

| | Traditional | Talos |
| - | ----------- | ----- |
| SSH access | Required for management | No SSH — API only (`talosctl`) |
| OS packages | Apt/dnf updates, drift | Read-only rootfs, no package manager |
| K8s upgrades | Manual kubeadm steps | Single `talosctl upgrade` command |
| Attack surface | Full Linux userspace | Minimal — only K8s-related processes |
| Config format | Multiple files, scripts | Single machine config YAML |

Talos is the right choice when you want K8s nodes that behave like appliances, not servers.

---

## Why Flux CD over ArgoCD?

| | Flux CD | ArgoCD |
| - | ------- | ------ |
| Resource usage | ~150 MB (controllers only) | ~500 MB (includes UI, Dex) |
| SOPS support | Native (no plugins) | Requires plugin |
| ARM64 | Full support | Full support |
| UI | None (CLI + Git) | Rich web UI |
| Pull model | Yes | Yes |

For a homelab where the RPi4 is the only always-on K8s worker, Flux's lower memory footprint is decisive. SOPS native support means zero extra moving parts for secrets.

---

## Repository Structure

```text
kubernetes/
├── apps/                        # Application manifests
│   ├── kustomization.yaml       # Root — lists all apps
│   ├── mem0/
│   ├── n8n/
│   └── ...
└── clusters/
    └── homelab/                 # Flux bootstrap config
        ├── apps.yaml            # Kustomization CR pointing at ./kubernetes/apps
        └── flux-system/
            ├── gotk-components.yaml   # Flux controllers
            ├── gotk-sync.yaml         # GitRepository + root Kustomization
            └── kustomization.yaml
```

**Flow:** Flux watches the Git repo → reconciles `clusters/homelab/` → which reconciles `apps/` → which applies all app kustomizations.

---

## Secrets with SOPS + Age

### How it works

1. Generate an Age keypair: `age-keygen -o age.key`
2. Store the **private key** in Vaultwarden only — never commit it
3. Add the **public key** to `.sops.yaml` in the repo
4. Flux reads the private key from a K8s Secret (`sops-age`) it creates at bootstrap
5. SOPS-encrypted files (`.enc.yaml`) are committed to Git — safe because only the Age private key can decrypt them

```yaml
# .sops.yaml
creation_rules:
  - path_regex: kubernetes/apps/.*\.enc\.yaml$
    age: age1<your-public-key>
```

### Encrypting a secret

```bash
# Create plaintext secret (never commit this)
cat > secret.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: my-app-secret
  namespace: my-app
stringData:
  password: "my-plaintext-password"
EOF

# Encrypt
sops --encrypt secret.yaml > secret.enc.yaml

# Verify decryption works
sops --decrypt secret.enc.yaml

# Commit only the encrypted version
git add secret.enc.yaml
```

### Flux decryption

Flux's Kustomization CRs include a `decryption` block:

```yaml
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age   # K8s Secret containing the Age private key
```

Flux automatically decrypts `.enc.yaml` files before applying them.

---

## Bootstrap Process (fresh cluster)

```bash
# 1. Create the SOPS age key secret in the cluster
kubectl create namespace flux-system
kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.agekey=age.key

# 2. Bootstrap Flux (reads from your Git repo)
flux bootstrap github \
  --owner=<your-github-username> \
  --repository=Homelab-ops \
  --branch=main \
  --path=kubernetes/clusters/homelab \
  --personal

# Flux is now reconciling — check:
flux get kustomizations
flux get sources git
```

---

## Day-2 Operations

### Adding a new application

```bash
mkdir -p kubernetes/apps/myapp
# Create: namespace.yaml, deployment.yaml, service.yaml, kustomization.yaml
# Add entry to kubernetes/apps/kustomization.yaml
git add kubernetes/apps/myapp/
git commit -m "feat: add myapp"
git push
# Flux deploys within 1-10 min (interval: 10m)
```

### Force reconcile

```bash
flux reconcile kustomization apps --with-source
```

### Suspend reconciliation (maintenance)

```bash
flux suspend kustomization apps
# ... make manual changes ...
flux resume kustomization apps
```

---

## Lessons Learned

- **Commit the encrypted secret, never the plaintext** — add `**/secret.yaml` and `**/secrets.yaml` to `.gitignore` so plaintext secrets can't accidentally slip in.
- **SOPS key rotation is destructive** — if you change the Age key, you must re-encrypt every `.enc.yaml` file in the repo. Keep the key backed up in at least two places.
- **Flux prune = true is powerful but sharp** — with `prune: true`, deleting a manifest from Git deletes the resource from the cluster. This is correct for GitOps but surprising at first.
- **talos-config/ must be gitignored** — Talos machine configs contain sensitive data (bootstrap tokens, certs). The `.gitignore` in this repo excludes the entire `talos-config/` directory.
