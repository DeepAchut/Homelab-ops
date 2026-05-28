#!/usr/bin/env python3
"""
service_health.py — HTTP health check against any of the homelab's known services.

Usage:
  service_health.py                  # all services, brief summary
  service_health.py ollama           # just one
  service_health.py --list           # show all known service short names
"""
import argparse, json, ssl, sys, time, urllib.request

# Short-name → URL + (optional) JSON path-expression for a body summary
SERVICES = {
    # Phase 22a — Ollama on Evo-X2 host
    "ollama":        ("http://192.168.4.84:11434/api/version",                "version"),
    "ollama-models": ("http://192.168.4.84:11434/api/ps",                     "models[*].name"),
    # mem0 — Peladn-Ollama-backed memory API
    "mem0":          ("http://192.168.4.141:30800/health",                    "status"),
    # Observability — CT405 on Evo-X2
    "victoriametrics": ("http://192.168.4.66:8428/health",                    None),
    "vm":            ("http://192.168.4.66:8428/health",                      None),
    "loki":          ("http://192.168.4.66:3100/ready",                       None),
    "grafana":       ("http://192.168.4.66:3000/api/health",                  "database"),
    # PBS
    "pbs":           ("https://192.168.4.27:8007",                            None),   # cert is self-signed; just want connectability
    # Gotify (push)
    "gotify":        ("https://notifications.dkghar.duckdns.org/health",      "health"),
    # NPM admin (on home-ops LXC)
    "npm":           ("http://192.168.4.13:81",                               None),
    # OPNsense telegraf prometheus output (one of many; this confirms metrics are flowing)
    "telegraf":      ("http://192.168.4.1:9273/metrics",                      None),
    # Hermes self (us)
    "hermes":        ("http://localhost:8642/health",                         None),
}

def fetch(url, timeout=5):
    ctx = ssl._create_unverified_context()  # PBS uses self-signed; OK for monitoring
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=timeout) as r:
            body = r.read(4096).decode("utf-8", errors="replace")
            dt_ms = int((time.time() - t0) * 1000)
            return r.status, dt_ms, body
    except urllib.error.HTTPError as e:
        return e.code, int((time.time() - t0) * 1000), str(e)
    except Exception as e:
        return -1, int((time.time() - t0) * 1000), str(e)[:200]

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("service", nargs="?", help="service short name (omit for all)")
    p.add_argument("--list", action="store_true", help="list known services and exit")
    a = p.parse_args()

    if a.list:
        for k, (url, _) in SERVICES.items():
            print(f"  {k:<18}  {url}")
        return

    targets = [a.service] if a.service else list(SERVICES.keys())
    print(f"{'SERVICE':<18} {'URL':<60} {'CODE':<6} {'MS':<6} BODY/REASON")
    for name in targets:
        if name not in SERVICES:
            print(f"{name:<18} (unknown — try --list)")
            continue
        url, _ = SERVICES[name]
        code, ms, body = fetch(url)
        snippet = body.replace("\n", " ")[:120]
        # Visual: ✓ for 2xx, ✗ for everything else
        mark = "✓" if 200 <= code < 300 else "✗"
        print(f"{name:<18} {url:<60} {code:<6} {ms:<6} {mark} {snippet}")

if __name__ == "__main__":
    main()
