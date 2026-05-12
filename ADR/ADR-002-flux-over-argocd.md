# ADR-002: Flux CD over ArgoCD

**Date:** 2025-Q4  
**Status:** Accepted

## Context

Needed a GitOps controller that fits on an always-on RPi4 worker (4 GB RAM, ARM64) with native SOPS secret decryption and minimal operational overhead.

## Decision

Chose **Flux CD v2**.

## Rationale

ArgoCD is excellent but ships with a UI server, Redis, Dex (OIDC), and several controllers totalling ~500 MB RAM. Flux's controllers total ~150 MB — a meaningful difference when the RPi4 is the only always-on K8s node.

The decisive factor was **native SOPS support**. Flux's Kustomization CR accepts a `decryption.provider: sops` block — no plugins, no sidecars. ArgoCD requires a custom plugin or external operator for SOPS, adding complexity.

## Consequences

- No built-in web UI — cluster state is read via `flux get` CLI or GitHub
- Multi-tenancy is possible but requires manual RBAC setup
- Flux v2 uses Kustomize as the primary rendering engine; Helm is supported via HelmRelease CRs
