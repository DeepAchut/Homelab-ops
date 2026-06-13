#!/usr/bin/env python3
"""
repo_read.py — read a file from the public Homelab-ops GitHub repo.

Fetches over https from raw.githubusercontent.com. No clone in pod, no auth.
Only the configured repo + branch are reachable.

Reads (from env):
  HERMES_REPO_OWNER   default: DeepAchut
  HERMES_REPO_NAME    default: Homelab-ops
  HERMES_REPO_BRANCH  default: main

Usage:
  repo_read.py kubernetes/apps/hermes-agent/deployment.yaml
  repo_read.py README.md --lines 1-50
  repo_read.py kubernetes/apps/karakeep/deployment.yaml --json

Output is the file content. Use --lines START-END to limit.
"""
import argparse, json, os, sys, urllib.request, urllib.error

OWNER = os.environ.get("HERMES_REPO_OWNER", "DeepAchut")
REPO = os.environ.get("HERMES_REPO_NAME", "Homelab-ops")
BRANCH = os.environ.get("HERMES_REPO_BRANCH", "main")
RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"


def fetch(path: str) -> tuple[int, str]:
    url = f"{RAW_BASE}/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-agent-repo-read/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP {e.code} fetching {url}: {e.reason}"
    except Exception as e:
        return -1, f"error: {e}"


def parse_lines(spec: str) -> tuple[int, int]:
    if "-" not in spec:
        n = int(spec)
        return n, n
    a, b = spec.split("-", 1)
    return int(a), int(b)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", help="repo-relative file path")
    p.add_argument("--lines", help="START-END inclusive (1-indexed)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    status, body = fetch(a.path)
    if status != 200:
        print(body, file=sys.stderr)
        sys.exit(1)

    if a.lines:
        start, end = parse_lines(a.lines)
        all_lines = body.splitlines()
        body = "\n".join(all_lines[start - 1 : end])

    if a.json:
        print(json.dumps({"path": a.path, "branch": BRANCH, "status": status,
                          "lines": len(body.splitlines()), "content": body}, indent=2))
    else:
        print(body)


if __name__ == "__main__":
    main()
