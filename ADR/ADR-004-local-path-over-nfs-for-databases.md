# ADR-004: Local-Path Storage for Postgres and Qdrant (not NFS)

**Date:** 2026-04  
**Status:** Accepted

## Context

The homelab uses Peladn as an NFS server for most persistent workloads (n8n data, Miniflux DB). When adding mem0's Postgres and Qdrant StatefulSets, the question was whether to use NFS-backed PVCs (consistent with everything else) or local-path PVCs on the RPi4.

## Decision

**Local-path PVCs** for Postgres and Qdrant primary data. NFS for backups only.

## Rationale

Postgres and Qdrant are stateful database engines with their own WAL, locking, and atomicity guarantees. NFS can silently violate these guarantees:

- **NFS locking (fcntl/lockd)** is unreliable across network hops — Postgres uses `flock` and advisory locks internally
- **Network flap** during a Postgres WAL write can cause partial writes or WAL corruption
- **NFS `atime`/`mtime` semantics** differ from local filesystems in ways that confuse some database internals

The industry standard for homelabs and production alike: primary database storage on local block storage, backups on NFS/object store.

**Backup strategy implemented:** CronJobs run `pg_dump` and Qdrant snapshot, pushing output to the NFS server at `/mnt/pvedas/mem0-backups/`. NFS is safe for blob storage.

## Consequences

- Postgres and Qdrant data is tied to the RPi4 node — if the RPi4 disk fails, restore from NFS backup
- Disaster recovery path: provision new RPi4 worker, restore from latest NFS backup
- This is the **only** deviation from the "NFS for everything" pattern used by n8n and Miniflux
