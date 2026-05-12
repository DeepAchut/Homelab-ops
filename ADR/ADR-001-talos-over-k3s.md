# ADR-001: Talos Linux over k3s / Ubuntu K8s

**Date:** 2025-Q4  
**Status:** Accepted

## Context

Needed a K8s distribution for a mixed-arch homelab cluster (RPi4 ARM64, Intel NUC x86, i9 x86). Options evaluated: k3s, kubeadm on Ubuntu, Talos Linux.

## Decision

Chose **Talos Linux**.

## Rationale

| Concern | k3s | Ubuntu + kubeadm | Talos |
| ------- | --- | ---------------- | ----- |
| Immutability | No — full Linux | No — full Linux | Yes — read-only rootfs |
| SSH required | Yes | Yes | No — API only |
| OS drift risk | High (apt updates) | High | None (upgrade = image swap) |
| ARM64 | Yes | Yes | Yes |
| Secrets in config | Manual | Manual | Encrypted machine config |
| Attack surface | Moderate | High | Minimal |

Talos treats nodes as cattle, not pets. No package manager, no shell, no drift. Upgrades are atomic image swaps via `talosctl upgrade`. This matches the "infrastructure as code" principle and produces nodes that are reproducible from config alone.

## Consequences

- No ad-hoc debugging via SSH — must use `talosctl dmesg`, `talosctl logs`, or K8s exec
- Node provisioning requires generating and applying Talos machine configs (documented in Phase 11)
- Node names are baked into the machine config at provisioning time — cannot rename without reprovisioning
