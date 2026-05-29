#!/usr/bin/env python3
"""
beszel_query.py — query the Beszel server API for current host/container metrics + alerts.

Beszel runs as a PocketBase backend at `beszel.beszel.svc.cluster.local:8090` (in-cluster)
or NodePort `192.168.4.71:30090` (LAN). All record-listing endpoints require auth.

Reads (from env):
  BESZEL_URL       e.g. http://beszel.beszel.svc.cluster.local:8090
  BESZEL_USER      email of a Beszel UI user
  BESZEL_PASSWORD  password for that user (consider creating a dedicated "hermes-reader" user)

Usage:
  beszel_query.py systems                       # all monitored hosts + current health
  beszel_query.py systems evo-x2                # one specific host
  beszel_query.py alerts                        # active alerts (anything triggered)
  beszel_query.py stats <host> [--minutes N]    # recent system_stats for a host (default 30 min)
  beszel_query.py containers <host>             # latest container snapshot for a host
  beszel_query.py auth                          # test auth only (no data fetch)

Output is concise terminal-friendly text. Add --json for raw output.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error

DEFAULT_URL = os.environ.get("BESZEL_URL", "http://beszel.beszel.svc.cluster.local:8090")
USER     = os.environ.get("BESZEL_USER", "").strip()
PASSWORD = os.environ.get("BESZEL_PASSWORD", "").strip()

# --- auth ---------------------------------------------------------------------

def _check_env():
    if not USER or not PASSWORD:
        print("BESZEL_USER or BESZEL_PASSWORD not set in env.", file=sys.stderr)
        print("  → mount these via the hermes-credentials Secret (see secret.example.yaml).", file=sys.stderr)
        print("  → in Beszel: create a dedicated 'hermes-reader' user via UI → Settings → Users.", file=sys.stderr)
        sys.exit(2)

def auth_token(url):
    _check_env()
    body = json.dumps({"identity": USER, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{url}/api/collections/users/auth-with-password",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
            return d["token"]
    except urllib.error.HTTPError as e:
        print(f"Beszel auth failed: HTTP {e.code} — {e.read()[:200].decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Beszel auth error: {e}", file=sys.stderr)
        sys.exit(1)

def call(url, path, token, params=None):
    qs = "?" + urllib.parse.urlencode(params) if params else ""
    req = urllib.request.Request(
        f"{url}{path}{qs}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

# --- subcommands --------------------------------------------------------------

def cmd_auth(args, url, token):
    print(f"  ✓ authenticated as {USER}")
    print(f"  ✓ Beszel at {url}")
    print(f"  ✓ token length {len(token)} chars")

def cmd_systems(args, url, token):
    params = {"perPage": 100}
    if args.name:
        params["filter"] = f'name="{args.name}"'
    d = call(url, "/api/collections/systems/records", token, params)
    items = d.get("items", [])
    if args.json:
        print(json.dumps(items, indent=2)); return
    print(f"  hosts: {d.get('totalItems', len(items))}")
    print(f"  {'NAME':<22} {'HOST':<18} {'STATUS':<10} {'CPU%':<6} {'MEM%':<6} {'DISK%':<7} UPTIME")
    for s in items:
        info = s.get("info", {}) or {}
        print(f"  {s.get('name','-'):<22} {s.get('host','-'):<18} {s.get('status','-'):<10} "
              f"{str(info.get('c','-')):<6} {str(info.get('mp','-')):<6} {str(info.get('dp','-')):<7} "
              f"{info.get('u','-')}s")

def cmd_alerts(args, url, token):
    # `alerts` collection in Beszel: rows that are currently triggered have triggered=true
    params = {"perPage": 100, "sort": "-updated"}
    if args.active:
        params["filter"] = "triggered=true"
    d = call(url, "/api/collections/alerts/records", token, params)
    items = d.get("items", [])
    if args.json:
        print(json.dumps(items, indent=2)); return
    print(f"  alerts: {d.get('totalItems', len(items))} ({'triggered only' if args.active else 'all'})")
    print(f"  {'NAME':<25} {'SYSTEM':<18} {'VALUE':<8} {'THRESHOLD':<10} TRIGGERED")
    for a in items:
        print(f"  {a.get('name','-')[:24]:<25} {a.get('system','-')[:17]:<18} "
              f"{str(a.get('value','-')):<8} {str(a.get('threshold','-')):<10} {a.get('triggered',False)}")

def cmd_stats(args, url, token):
    # find the system record by name → get its ID → query system_stats filtered to it
    s = call(url, "/api/collections/systems/records", token, {"filter": f'name="{args.host}"', "perPage": 1})
    if not s.get("items"):
        print(f"  no system named '{args.host}' in Beszel", file=sys.stderr); sys.exit(1)
    sys_id = s["items"][0]["id"]
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - args.minutes * 60))
    params = {
        "filter": f'system="{sys_id}" && created >= "{cutoff}"',
        "sort": "-created",
        "perPage": 200,
    }
    d = call(url, "/api/collections/system_stats/records", token, params)
    items = d.get("items", [])
    if args.json:
        print(json.dumps(items, indent=2)); return
    print(f"  host={args.host} (id={sys_id})  records in last {args.minutes}m: {len(items)}")
    print(f"  {'TIME':<20} {'CPU%':<6} {'MEM%':<6} {'DISK%':<7} {'NET_S':<10} {'NET_R':<10}")
    for s in items[:20]:
        st = s.get("stats", {}) or {}
        print(f"  {s.get('created','-')[:19]:<20} {str(st.get('cpu','-')):<6} "
              f"{str(st.get('mp','-')):<6} {str(st.get('dp','-')):<7} "
              f"{str(st.get('ns','-')):<10} {str(st.get('nr','-')):<10}")
    if len(items) > 20:
        print(f"  ... (+{len(items)-20} more — use --json for all)")

def cmd_containers(args, url, token):
    s = call(url, "/api/collections/systems/records", token, {"filter": f'name="{args.host}"', "perPage": 1})
    if not s.get("items"):
        print(f"  no system named '{args.host}'", file=sys.stderr); sys.exit(1)
    sys_id = s["items"][0]["id"]
    d = call(url, "/api/collections/container_stats/records", token,
             {"filter": f'system="{sys_id}"', "sort": "-created", "perPage": 1})
    items = d.get("items", [])
    if not items:
        print(f"  no container snapshots for {args.host}"); return
    rec = items[0]
    stats = rec.get("stats", []) or []
    if args.json:
        print(json.dumps(stats, indent=2)); return
    print(f"  host={args.host} snapshot @ {rec.get('created','-')[:19]}  containers: {len(stats)}")
    print(f"  {'NAME':<30} {'CPU%':<8} {'MEM(MB)':<10} {'NET_S':<10} {'NET_R':<10}")
    for c in sorted(stats, key=lambda x: -(x.get("c", 0) or 0))[:30]:
        print(f"  {(c.get('n','?')[:29]):<30} {str(c.get('c','-')):<8} "
              f"{str(c.get('m','-')):<10} {str(c.get('ns','-')):<10} {str(c.get('nr','-')):<10}")

# --- main ---------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth")

    sp = sub.add_parser("systems"); sp.add_argument("name", nargs="?")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("alerts"); sp.add_argument("--active", action="store_true", help="only triggered")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("stats"); sp.add_argument("host")
    sp.add_argument("--minutes", type=int, default=30)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("containers"); sp.add_argument("host"); sp.add_argument("--json", action="store_true")

    a = p.parse_args()
    url = DEFAULT_URL.rstrip("/")
    token = auth_token(url)
    {
        "auth":       cmd_auth,
        "systems":    cmd_systems,
        "alerts":     cmd_alerts,
        "stats":      cmd_stats,
        "containers": cmd_containers,
    }[a.cmd](a, url, token)

if __name__ == "__main__":
    main()
