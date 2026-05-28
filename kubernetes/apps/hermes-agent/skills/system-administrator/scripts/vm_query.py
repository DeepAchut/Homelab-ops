#!/usr/bin/env python3
"""
vm_query.py — query VictoriaMetrics (PromQL/MetricsQL).

Usage:
  vm_query.py 'up'                                          # instant query
  vm_query.py 'rate(node_cpu_seconds_total[5m])' --limit 5  # top-5 of an instant
  vm_query.py 'up' --range 1h                               # range query last hour
  vm_query.py --suggest                                     # print useful query starters

Output is concise (one row per series). Add --json for the raw VM response.
"""
import argparse, json, sys, urllib.parse, urllib.request

VM = "http://192.168.4.66:8428"

SUGGEST = [
    ("scrape targets up", "up"),
    ("scrape targets DOWN (real outages)", 'up{job=~"node-.*"} < 1'),
    ("OPNsense WAN throughput Mbps", 'rate(net_bytes_recv{interface="igb1"}[5m]) * 8 / 1e6'),
    ("Evo-X2 host CPU busy %", '100 - avg by (host) (rate(node_cpu_seconds_total{mode="idle",host="evo-x2"}[5m])) * 100'),
    ("RPi4 memory used %", '(1 - node_memory_MemAvailable_bytes{host="rpi4"} / node_memory_MemTotal_bytes{host="rpi4"}) * 100'),
    ("K8s pod restarts in last 1h",
     'sum by (namespace, pod) (changes(kube_pod_container_status_restarts_total[1h])) > 0'),
    ("OPNsense internet speed download (Mbps)", 'internet_speed_download'),
    ("active series in VM (cardinality health)", 'sum(vm_cache_entries{type="storage/tsid"})'),
]

def q(query, range_=None):
    if range_:
        path = "/api/v1/query_range"
        start = f"-{range_}"
        params = {"query": query, "start": start, "end": "now", "step": "60s"}
    else:
        path = "/api/v1/query"
        params = {"query": query}
    url = f"{VM}{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"VM query error: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("query", nargs="?", help="PromQL/MetricsQL expression")
    p.add_argument("--range", help="range duration like 1h, 6h, 24h — switches to range_query")
    p.add_argument("--limit", type=int, default=15, help="max series to print")
    p.add_argument("--json", action="store_true", help="raw VM JSON response")
    p.add_argument("--suggest", action="store_true", help="print useful query starters")
    a = p.parse_args()

    if a.suggest:
        for label, expr in SUGGEST:
            print(f"  {label}:\n    {expr}\n")
        return

    if not a.query:
        p.print_help()
        return

    data = q(a.query, a.range)
    if a.json:
        print(json.dumps(data, indent=2))
        return

    if data.get("status") != "success":
        print(f"query failed: {data}", file=sys.stderr)
        sys.exit(1)

    results = data["data"]["result"]
    rtype = data["data"]["resultType"]
    print(f"-- {rtype} -- {len(results)} series --")
    for r in results[:a.limit]:
        labels = ", ".join(f"{k}={v}" for k, v in r["metric"].items() if k != "__name__")
        if rtype == "vector":
            ts, val = r["value"]
            print(f"  {labels or '(no labels)':<60}  {val}")
        elif rtype == "matrix":
            n = len(r["values"])
            first_ts, first_v = r["values"][0]
            last_ts, last_v = r["values"][-1]
            print(f"  {labels or '(no labels)':<60}  n={n}  first={first_v}  last={last_v}")
    if len(results) > a.limit:
        print(f"  ... (+{len(results) - a.limit} more series; raise --limit or filter the query)")

if __name__ == "__main__":
    main()
