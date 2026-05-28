#!/usr/bin/env python3
"""
proxmox_status.py — read-only Proxmox VE API queries for Peladn / Evo-X2.

Requires env vars PROXMOX_TOKEN_ID + PROXMOX_TOKEN_VALUE (mounted from the
hermes-credentials Secret). If the token isn't set, this script prints a
helpful message instead of failing silently.

Token creation: Datacenter → Permissions → API Tokens → root@pam → Add
  name: hermes-readonly
  Datacenter Permissions: path=/ , Role=PVEAuditor (read-only)

Usage:
  proxmox_status.py peladn               # node status
  proxmox_status.py evox2                # node status
  proxmox_status.py peladn --guests      # all VMs+LXCs on the node
  proxmox_status.py peladn 201           # one guest's state
  proxmox_status.py both                 # both nodes summarized
"""
import argparse, json, os, ssl, sys, urllib.parse, urllib.request

HOSTS = {
    "peladn": ("192.168.4.150", "prop"),
    "evox2":  ("192.168.4.84",  "pve"),
}

def auth_header():
    tid = os.environ.get("PROXMOX_TOKEN_ID", "").strip()
    tval = os.environ.get("PROXMOX_TOKEN_VALUE", "").strip()
    if not tid or not tval:
        print("PROXMOX_TOKEN_ID/PROXMOX_TOKEN_VALUE not set — see hermes-credentials Secret.", file=sys.stderr)
        print("  Create a token at: Datacenter → Permissions → API Tokens → root@pam → Add", file=sys.stderr)
        print("  Permission: Datacenter (path=/), Role=PVEAuditor", file=sys.stderr)
        sys.exit(2)
    return f"PVEAPIToken={tid}={tval}"

def call(host_ip, path):
    ctx = ssl._create_unverified_context()  # self-signed PVE cert
    url = f"https://{host_ip}:8006/api2/json{path}"
    req = urllib.request.Request(url, headers={"Authorization": auth_header()})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            return json.loads(r.read())["data"]
    except urllib.error.HTTPError as e:
        print(f"PVE API {e.code} for {url}: {e.read()[:200].decode()}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"PVE API error: {e}", file=sys.stderr)
        sys.exit(1)

def show_node(host_alias):
    ip, node = HOSTS[host_alias]
    status = call(ip, f"/nodes/{node}/status")
    pct_cpu = status.get("cpu", 0) * 100
    mem = status.get("memory", {})
    mem_used = mem.get("used", 0) / 1e9
    mem_total = mem.get("total", 0) / 1e9
    pct_mem = (mem.get("used", 0) / max(mem.get("total", 1), 1)) * 100
    uptime_s = status.get("uptime", 0)
    upt_d = uptime_s / 86400
    print(f"=== {host_alias} ({ip}, node={node}) ===")
    print(f"  CPU busy:  {pct_cpu:5.1f} %")
    print(f"  Memory:    {mem_used:6.1f} / {mem_total:6.1f} GB  ({pct_mem:.1f} %)")
    print(f"  Uptime:    {upt_d:5.1f} d")
    print(f"  Load avg:  {status.get('loadavg', '?')}")
    print(f"  Kernel:    {status.get('kversion', '?').split()[0]}")

def show_guests(host_alias, only_id=None):
    ip, node = HOSTS[host_alias]
    lxcs = call(ip, f"/nodes/{node}/lxc")
    vms = call(ip, f"/nodes/{node}/qemu")
    rows = sorted(
        [(g["vmid"], "LXC", g.get("name", "-"), g.get("status", "?"),
          g.get("cpu", 0), g.get("mem", 0) / 1e9, g.get("maxmem", 0) / 1e9) for g in lxcs]
        + [(g["vmid"], "VM", g.get("name", "-"), g.get("status", "?"),
            g.get("cpu", 0), g.get("mem", 0) / 1e9, g.get("maxmem", 0) / 1e9) for g in vms],
    )
    if only_id:
        rows = [r for r in rows if str(r[0]) == str(only_id)]
    print(f"=== {host_alias} guests ===")
    print(f"  {'ID':<6} {'TYPE':<5} {'NAME':<28} {'STATE':<10} {'CPU%':<6} {'MEM(GB/max)'}")
    for vmid, t, name, state, cpu, mem, mmax in rows:
        cpu_pct = cpu * 100
        print(f"  {vmid:<6} {t:<5} {name:<28} {state:<10} {cpu_pct:<6.1f} {mem:.1f}/{mmax:.1f}")

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("host", choices=["peladn", "evox2", "both"], help="which PVE node")
    p.add_argument("guest_id", nargs="?", help="optional VM/LXC ID to focus on")
    p.add_argument("--guests", action="store_true", help="list all guests on the node")
    a = p.parse_args()

    if a.host == "both":
        show_node("peladn"); print()
        show_node("evox2")
        return
    show_node(a.host)
    if a.guests or a.guest_id:
        print()
        show_guests(a.host, only_id=a.guest_id)

if __name__ == "__main__":
    main()
