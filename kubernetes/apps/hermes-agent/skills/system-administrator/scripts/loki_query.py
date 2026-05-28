#!/usr/bin/env python3
"""
loki_query.py — query Loki (LogQL) for log lines.

Usage:
  loki_query.py '{namespace="mem0"}' --range 1h --limit 50
  loki_query.py '{job="opnsense"} |~ "(block|reject)"' --range 6h
  loki_query.py --suggest                # useful starters
  loki_query.py --labels                 # what labels exist
  loki_query.py --label-values namespace # known values for a label

Output is one line per match: timestamp + labels + message snippet.
"""
import argparse, json, sys, time, urllib.parse, urllib.request

LOKI = "http://192.168.4.66:3100"

SUGGEST = [
    ("all mem0-server logs (last 30m)",
     '{namespace="mem0", app="mem0-server"}'),
    ("OPNsense filter drops/rejects (last 6h)",
     '{job="opnsense"} |~ "(?i)(block|reject|filterlog)"'),
    ("K8s panic/fatal/CrashLoop spikes (last 1h)",
     '{namespace=~".+"} |~ "(?i)(panic|fatal|crashloopbackoff|oomkilled)"'),
    ("n8n workflow execution errors",
     '{namespace="n8n"} |~ "(?i)error|fail|exception"'),
    ("Grafana provisioning + alert pipeline",
     '{container="grafana"} |~ "(?i)provisioning|alert"'),
    ("Hermes (us) recent activity",
     '{namespace="hermes-agent"}'),
]

def parse_dur(s):
    """Convert '1h', '30m', '2d' to seconds."""
    unit = s[-1]
    n = int(s[:-1])
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query", nargs="?", help="LogQL expression")
    p.add_argument("--range", default="30m", help="lookback like 30m, 6h, 1d (default 30m)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--suggest", action="store_true")
    p.add_argument("--labels", action="store_true", help="list known label names")
    p.add_argument("--label-values", help="list values for a given label name")
    a = p.parse_args()

    if a.suggest:
        for label, expr in SUGGEST:
            print(f"  {label}:\n    {expr}\n")
        return
    if a.labels:
        url = f"{LOKI}/loki/api/v1/labels"
        with urllib.request.urlopen(url, timeout=10) as r:
            print("\n".join(json.loads(r.read())["data"]))
        return
    if a.label_values:
        url = f"{LOKI}/loki/api/v1/label/{a.label_values}/values"
        with urllib.request.urlopen(url, timeout=10) as r:
            print("\n".join(json.loads(r.read())["data"]))
        return

    if not a.query:
        p.print_help()
        return

    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - parse_dur(a.range) * int(1e9)
    params = {"query": a.query, "start": start_ns, "end": end_ns, "limit": a.limit, "direction": "BACKWARD"}
    url = f"{LOKI}/loki/api/v1/query_range?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())

    if data.get("status") != "success":
        print(f"query failed: {data}", file=sys.stderr)
        sys.exit(1)

    streams = data["data"]["result"]
    total = sum(len(s["values"]) for s in streams)
    print(f"-- {len(streams)} streams, {total} lines (last {a.range}) --")
    flat = []
    for s in streams:
        ns = s["stream"].get("namespace", "")
        pod = s["stream"].get("pod", s["stream"].get("container", s["stream"].get("job", "")))
        for ts_ns, line in s["values"]:
            flat.append((int(ts_ns), ns, pod, line))
    flat.sort(reverse=True)
    for ts_ns, ns, pod, line in flat[:a.limit]:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_ns / 1e9))
        msg = line.strip().replace("\t", " ")[:300]
        print(f"  {t}  {ns}/{pod[:30]:<30}  {msg}")

if __name__ == "__main__":
    main()
