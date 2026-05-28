#!/usr/bin/env python3
"""
k8s_status.py — list pods (and their state) in the homelab K8s cluster.

Uses the in-cluster ServiceAccount token (mounted at /var/run/secrets/kubernetes.io/...)
to call the K8s API directly via stdlib urllib. No `kubectl` binary needed.

Usage:
  k8s_status.py                                 # all pods, all namespaces, short summary
  k8s_status.py mem0                            # pods in namespace mem0
  k8s_status.py mem0 --pod postgres             # only pods whose name contains 'postgres'
  k8s_status.py --node ira-rpi4-talos-worker    # pods on a specific node
  k8s_status.py --all                           # verbose JSON
"""
import argparse, json, os, ssl, sys, urllib.request

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
API_HOST = "https://kubernetes.default.svc"

def call(path):
    try:
        with open(f"{SA_DIR}/token") as f:
            token = f.read().strip()
        ctx = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")
        req = urllib.request.Request(
            f"{API_HOST}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"K8s API error for {path}: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("namespace", nargs="?", help="namespace name; omit for all")
    p.add_argument("--pod", help="filter by name substring")
    p.add_argument("--node", help="filter by node name")
    p.add_argument("--all", action="store_true", help="verbose JSON output")
    a = p.parse_args()

    path = f"/api/v1/namespaces/{a.namespace}/pods" if a.namespace else "/api/v1/pods"
    data = call(path)
    items = data.get("items", [])
    if a.pod:
        items = [i for i in items if a.pod.lower() in i["metadata"]["name"].lower()]
    if a.node:
        items = [i for i in items if i.get("spec", {}).get("nodeName") == a.node]

    if a.all:
        print(json.dumps(items, indent=2))
        return

    print(f"{'NAMESPACE':<20} {'POD':<48} {'STATUS':<10} {'RESTARTS':<8} {'NODE':<30} AGE")
    for i in items:
        m = i["metadata"]
        s = i.get("status", {})
        sp = i.get("spec", {})
        ns = m["namespace"]
        name = m["name"]
        phase = s.get("phase", "?")
        cs = s.get("containerStatuses", []) or []
        restarts = max([c.get("restartCount", 0) for c in cs], default=0)
        ready = sum(1 for c in cs if c.get("ready"))
        node = sp.get("nodeName", "-")
        age = m.get("creationTimestamp", "")[:10]
        ready_str = f"{ready}/{len(cs)}" if cs else "-"
        print(f"{ns:<20} {name:<48} {phase:<10} {restarts:<8} {node:<30} {age}  [{ready_str}]")

if __name__ == "__main__":
    main()
