#!/usr/bin/env python3
"""
grafana_query.py — query the Grafana HTTP API (read-only) via a service-account token.

Use this script when you need information that lives in Grafana ITSELF — currently-firing
provisioned alerts, available dashboards, datasources, alert history. For raw metrics use
vm_query.py (it talks to the VictoriaMetrics datasource directly). For raw logs use loki_query.py.

Reads (from env):
  GRAFANA_URL    e.g. http://192.168.4.66:3000  (default)
  GRAFANA_TOKEN  service-account token from Grafana UI → Administration → Service accounts

Usage:
  grafana_query.py health                          # /api/health
  grafana_query.py dashboards [search]             # list dashboards (optional search query)
  grafana_query.py alerts [--firing]               # active alert instances (--firing = state=Alerting only)
  grafana_query.py alert-rules [folder]            # provisioned alert rules
  grafana_query.py datasources                     # datasources configured in Grafana
  grafana_query.py folders                         # alert/dashboard folders
  grafana_query.py annotations [--hours N]         # recent annotations (alert history etc.)

Output is concise. Add --json for raw output.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error

DEFAULT_URL = os.environ.get("GRAFANA_URL", "http://192.168.4.66:3000").rstrip("/")
TOKEN       = os.environ.get("GRAFANA_TOKEN", "").strip()

def _check_token(require=True):
    if require and not TOKEN:
        print("GRAFANA_TOKEN not set in env.", file=sys.stderr)
        print("  → Grafana UI → Administration → Users and access → Service accounts → Add", file=sys.stderr)
        print("  → Name: hermes-reader   Role: Viewer   → Add token → copy → put in hermes-credentials Secret", file=sys.stderr)
        sys.exit(2)

def call(path, params=None, no_auth=False, method="GET", body=None):
    qs = "?" + urllib.parse.urlencode(params) if params else ""
    headers = {}
    if not no_auth:
        _check_token()
        headers["Authorization"] = f"Bearer {TOKEN}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    req = urllib.request.Request(f"{DEFAULT_URL}{path}{qs}", headers=headers, method=method, data=body)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            txt = r.read()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        body_err = e.read()[:200].decode(errors="replace")
        print(f"Grafana HTTP {e.code} for {path}: {body_err}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Grafana error for {path}: {e}", file=sys.stderr)
        sys.exit(1)

# ─── subcommands ──────────────────────────────────────────────────────────────

def cmd_health(args):
    d = call("/api/health", no_auth=True)
    print(f"  {DEFAULT_URL}")
    print(f"  database: {d.get('database', '-')}")
    print(f"  version:  {d.get('version', '-')}")
    print(f"  commit:   {d.get('commit', '-')[:12]}")

def cmd_dashboards(args):
    params = {"type": "dash-db", "limit": 200}
    if args.search:
        params["query"] = args.search
    d = call("/api/search", params)
    if args.json: print(json.dumps(d, indent=2)); return
    print(f"  {len(d)} dashboards{f' matching {args.search!r}' if args.search else ''}:")
    print(f"  {'UID':<14} {'TITLE':<45} {'FOLDER':<20} URL")
    for it in d:
        print(f"  {it.get('uid','-')[:13]:<14} {it.get('title','-')[:44]:<45} "
              f"{it.get('folderTitle','-')[:19]:<20} {it.get('url','-')}")

def cmd_alerts(args):
    # active alert instances per Grafana 8+ unified alerting
    d = call("/api/alertmanager/grafana/api/v2/alerts")
    if args.json: print(json.dumps(d, indent=2)); return
    items = d if isinstance(d, list) else d.get("alerts", [])
    if args.firing:
        items = [a for a in items if a.get("status", {}).get("state") == "active"]
    print(f"  {len(items)} alert instance(s){' (firing only)' if args.firing else ''}:")
    print(f"  {'ALERTNAME':<35} {'STATE':<10} {'STARTED':<20} LABELS")
    for a in items:
        labels = a.get("labels", {})
        name = labels.get("alertname", "-")
        state = a.get("status", {}).get("state", "-")
        started = (a.get("startsAt") or "-")[:19]
        extra = " ".join(f"{k}={v}" for k, v in labels.items() if k not in ("alertname", "__alertId__", "__alert_rule_uid__"))
        print(f"  {name[:34]:<35} {state:<10} {started:<20} {extra[:80]}")

def cmd_alert_rules(args):
    d = call("/api/v1/provisioning/alert-rules")
    if args.json: print(json.dumps(d, indent=2)); return
    items = d if isinstance(d, list) else []
    if args.folder:
        items = [r for r in items if r.get("folderUID") == args.folder or r.get("ruleGroup", "").lower() == args.folder.lower()]
    print(f"  {len(items)} alert rule(s):")
    print(f"  {'UID':<24} {'TITLE':<40} {'GROUP':<20} {'FOR':<8} STATE")
    for r in items:
        print(f"  {r.get('uid','-')[:23]:<24} {r.get('title','-')[:39]:<40} "
              f"{r.get('ruleGroup','-')[:19]:<20} {r.get('for','-'):<8} "
              f"{r.get('execErrState','-')}/{r.get('noDataState','-')}")

def cmd_datasources(args):
    d = call("/api/datasources")
    if args.json: print(json.dumps(d, indent=2)); return
    print(f"  {len(d)} datasources:")
    print(f"  {'NAME':<25} {'TYPE':<15} {'UID':<25} URL")
    for ds in d:
        print(f"  {ds.get('name','-')[:24]:<25} {ds.get('type','-')[:14]:<15} "
              f"{ds.get('uid','-')[:24]:<25} {ds.get('url','-')[:60]}")

def cmd_folders(args):
    d = call("/api/folders")
    if args.json: print(json.dumps(d, indent=2)); return
    print(f"  {len(d)} folders:")
    print(f"  {'UID':<14} {'TITLE':<40} URL")
    for f in d:
        print(f"  {f.get('uid','-')[:13]:<14} {f.get('title','-')[:39]:<40} {f.get('url','-')}")

def cmd_annotations(args):
    fro = int(time.time() * 1000) - args.hours * 3600 * 1000
    to  = int(time.time() * 1000)
    d = call("/api/annotations", {"from": fro, "to": to, "limit": 100})
    if args.json: print(json.dumps(d, indent=2)); return
    items = d if isinstance(d, list) else []
    print(f"  {len(items)} annotations in last {args.hours}h:")
    print(f"  {'TIME':<20} {'PANEL/DASH':<35} {'TEXT':<50} TAGS")
    for a in items[:40]:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a.get("time", 0)/1000))
        where = f"{a.get('dashboardUID','-')[:10]}/{a.get('panelId','-')}"
        text = (a.get("text") or "")[:48]
        tags = ",".join(a.get("tags") or [])[:30]
        print(f"  {t:<20} {where:<35} {text:<50} {tags}")

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")

    sp = sub.add_parser("dashboards");  sp.add_argument("search", nargs="?"); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("alerts");      sp.add_argument("--firing", action="store_true"); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("alert-rules"); sp.add_argument("folder", nargs="?"); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("datasources"); sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("folders");     sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("annotations"); sp.add_argument("--hours", type=int, default=24); sp.add_argument("--json", action="store_true")

    a = p.parse_args()
    {
        "health":      cmd_health,
        "dashboards":  cmd_dashboards,
        "alerts":      cmd_alerts,
        "alert-rules": cmd_alert_rules,
        "datasources": cmd_datasources,
        "folders":     cmd_folders,
        "annotations": cmd_annotations,
    }[a.cmd](a)

if __name__ == "__main__":
    main()
