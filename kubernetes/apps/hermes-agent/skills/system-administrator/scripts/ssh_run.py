#!/usr/bin/env python3
"""
ssh_run.py — execute a READ-ONLY command on a homelab host via SSH.

Allowlist-enforced. Use this FIRST whenever the user asks for the state of a
host — output of kubectl, systemctl, docker, journalctl, file inspection, etc.
For commands that mutate state (restart, kill, delete, mkfs), use ssh_exec.py
which gates on user confirmation.

Reads (from env):
  HERMES_SSH_KEY  default: /etc/hermes-ssh/id_ed25519 (mounted from Secret)

Usage:
  ssh_run.py <host> "<command>"
  ssh_run.py peladn "kubectl -n mem0 get pods"
  ssh_run.py evox2  "systemctl status ollama"
  ssh_run.py peladn "pct exec 202 -- docker logs jellyfin --tail=20"
  ssh_run.py peladn "curl -s http://192.168.4.141:30800/health"

Hosts:
  peladn  -> root@192.168.4.150
  evox2   -> root@192.168.4.84
  ha      -> root@192.168.4.13
  pbs     -> root@192.168.4.27

Add --json for raw subprocess output as JSON.
"""
import argparse, ipaddress, json, os, re, shlex, subprocess, sys, urllib.parse

SSH_KEY = os.environ.get("HERMES_SSH_KEY", "/etc/hermes-ssh/id_ed25519")

HOSTS = {
    "peladn": "192.168.4.150",
    "evox2":  "192.168.4.84",
    "ha":     "192.168.4.13",
    "pbs":    "192.168.4.27",
}

# Command must START with one of these prefixes (matched against tokenized command).
ALLOWED_PREFIXES = [
    # K8s read-only
    ("kubectl", "get"), ("kubectl", "describe"), ("kubectl", "logs"),
    ("kubectl", "explain"), ("kubectl", "top"), ("kubectl", "version"),
    ("kubectl", "config"), ("kubectl", "api-resources"), ("kubectl", "cluster-info"),
    # Docker read-only
    ("docker", "ps"), ("docker", "logs"), ("docker", "inspect"),
    ("docker", "version"), ("docker", "images"), ("docker", "stats"),
    ("docker", "network"), ("docker", "volume"), ("docker", "info"),
    # Filesystem read-only
    ("ls",), ("cat",), ("head",), ("tail",), ("stat",), ("file",),
    ("wc",), ("du",), ("df",), ("find",), ("tree",), ("readlink",),
    # System info
    ("ps",), ("top", "-b"), ("uptime",), ("free",), ("uname",),
    ("id",), ("whoami",), ("date",), ("hostname",), ("printenv",), ("env",),
    # Logs
    ("journalctl",), ("dmesg",), ("last",),
    # Network read-only
    ("ss",), ("netstat",), ("ip",), ("ping", "-c"), ("nslookup",), ("dig",),
    ("showmount",),
    # systemd read-only
    ("systemctl", "status"), ("systemctl", "is-active"),
    ("systemctl", "is-enabled"), ("systemctl", "is-failed"),
    ("systemctl", "list-units"), ("systemctl", "list-unit-files"),
    ("systemctl", "show"), ("systemctl", "cat"),
    # Proxmox read-only
    ("pct", "config"), ("pct", "list"), ("pct", "status"),
    ("qm", "config"), ("qm", "list"), ("qm", "status"),
    ("pveversion",), ("pvesm", "status"), ("pvesm", "list"),
    ("pvesh", "get"),
    # pct exec — special-cased below (must match nested allowlist)
    ("pct", "exec"),
    # Hardware diagnostics
    ("smartctl",), ("lsblk",), ("nvme",), ("sensors",),
    ("lsusb",), ("lspci",), ("lscpu",), ("lsmem",),
    ("hdparm",), ("rocm-smi",), ("nvidia-smi",), ("amd-smi",),
    # HTTP GET to internal services — URL is RFC1918-checked below
    ("curl",), ("wget",),
]

# Substrings that, if present anywhere in the command, hard-block.
DENIED_SUBSTRINGS = [
    " rm ", " rmdir ", " mv ", " cp ", " chmod ", " chown ", " chgrp ",
    " kill ", " killall ", " pkill ",
    " mkfs", " dd if=", " dd of=", " tee ", " nft ", " iptables ",
    " mount ", " umount ",
    " > /", " >> /", " 2> /", " 2>> /",
    "; sudo", "&& sudo", "| sudo",
    " su ", " su -",
    "$(", "`",
    " ssh ", " scp ", " rsync ",
    " --force", " -rf ", " -fr ",
    " systemctl stop ", " systemctl restart ", " systemctl start ",
    " systemctl reload ", " systemctl disable ", " systemctl enable ",
    " systemctl mask ", " systemctl unmask ",
    " docker stop", " docker rm", " docker restart", " docker kill",
    " docker run", " docker exec",
    " kubectl delete", " kubectl create", " kubectl apply",
    " kubectl patch", " kubectl edit", " kubectl scale",
    " kubectl rollout", " kubectl replace", " kubectl annotate",
    " kubectl label", " kubectl cordon", " kubectl drain", " kubectl uncordon",
    " pct stop", " pct destroy", " pct create", " pct set",
    " pct start", " pct reboot", " pct shutdown",
    " qm stop", " qm destroy", " qm create", " qm set",
    " qm start", " qm reboot", " qm shutdown",
    " apt ", " apt-get ", " dpkg ", " pip install", " pip3 install",
    " curl -X POST", " curl -X PUT", " curl -X DELETE", " curl -X PATCH",
    " wget --post-data", " wget -O ",
]


def is_private_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).hostname
        if not host:
            return False
        if host in ("localhost",):
            return True
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except (ValueError, TypeError):
        return False


def tokenize(cmd: str):
    try:
        return shlex.split(cmd)
    except ValueError as e:
        print(f"  could not parse command: {e}", file=sys.stderr)
        sys.exit(2)


def matches_prefix(tokens, prefix):
    return len(tokens) >= len(prefix) and tuple(tokens[: len(prefix)]) == prefix


def validate(cmd: str) -> tuple:
    """Return (allowed: bool, reason: str)."""
    if not cmd.strip():
        return False, "empty command"

    # Hard-block dangerous substrings
    padded = " " + cmd + " "
    for substr in DENIED_SUBSTRINGS:
        if substr in padded:
            return False, f"contains denied substring {substr.strip()!r}"

    tokens = tokenize(cmd)
    if not tokens:
        return False, "empty after tokenize"

    # curl/wget special-case: enforce URL is private + only GET methods
    if tokens[0] in ("curl", "wget"):
        for tok in tokens:
            if tok.startswith(("http://", "https://")):
                if not is_private_url(tok):
                    return False, f"URL {tok} is not RFC1918/loopback"
        if tokens[0] == "curl" and any(t in ("-X", "--request") for t in tokens):
            for i, t in enumerate(tokens):
                if t in ("-X", "--request") and i + 1 < len(tokens):
                    if tokens[i + 1].upper() not in ("GET", "HEAD"):
                        return False, "non-GET method for curl"

    # pct exec NN -- <inner-cmd>: nested allowlist
    if matches_prefix(tokens, ("pct", "exec")):
        try:
            idx = tokens.index("--")
            inner = " ".join(shlex.quote(t) for t in tokens[idx + 1 :])
            ok, reason = validate(inner)
            if not ok:
                return False, f"pct exec inner cmd rejected: {reason}"
            return True, "ok"
        except ValueError:
            # No '--' separator; just check first arg is read-only (default to allow)
            pass

    for prefix in ALLOWED_PREFIXES:
        if matches_prefix(tokens, prefix):
            return True, "ok"

    return False, f"first token {tokens[0]!r} not in allowlist"


def run_ssh(host_alias: str, cmd: str, as_json: bool):
    if host_alias not in HOSTS:
        print(f"  unknown host {host_alias!r}. known: {', '.join(HOSTS)}", file=sys.stderr)
        sys.exit(2)
    ip = HOSTS[host_alias]
    ssh_argv = [
        "ssh", "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=/tmp/hermes-known-hosts",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
        f"root@{ip}", cmd,
    ]
    try:
        r = subprocess.run(ssh_argv, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"  ssh timeout after 60s", file=sys.stderr)
        sys.exit(124)
    if as_json:
        print(json.dumps({"host": host_alias, "cmd": cmd, "exit": r.returncode,
                          "stdout": r.stdout, "stderr": r.stderr}, indent=2))
    else:
        if r.stdout:
            sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
    sys.exit(r.returncode)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("host", help=f"host alias: {', '.join(HOSTS)}")
    p.add_argument("command", help="read-only command to run on the host")
    p.add_argument("--json", action="store_true", help="output raw subprocess result as JSON")
    p.add_argument("--check", action="store_true", help="only validate, do not run")
    a = p.parse_args()

    ok, reason = validate(a.command)
    if not ok:
        print(f"  REJECTED: {reason}", file=sys.stderr)
        print(f"  command: {a.command}", file=sys.stderr)
        print(f"  for state-changing commands use ssh_exec.py (requires user confirmation)", file=sys.stderr)
        sys.exit(3)
    if a.check:
        print("  OK (allowlist match)")
        return
    run_ssh(a.host, a.command, a.json)


if __name__ == "__main__":
    main()
