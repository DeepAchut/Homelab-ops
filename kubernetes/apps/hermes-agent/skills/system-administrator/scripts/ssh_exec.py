#!/usr/bin/env python3
"""
ssh_exec.py — execute a state-changing command on a homelab host.

REQUIRES EXPLICIT USER CONFIRMATION in the same conversation turn before
executing. The model must:
  1. First call with --dry-run to show the user what command would run.
  2. Only call without --dry-run AFTER the user types explicit approval
     ("yes", "go", "approved", "do it") in their immediately-following message.
  3. Pass --confirmation-quote with a short excerpt of the user's approval
     so this tool can log the audit trail.

Reads (from env):
  HERMES_SSH_KEY  default: /etc/hermes-ssh/id_ed25519

Usage (dry-run, always start here):
  ssh_exec.py peladn "systemctl restart nfs-server" --dry-run

After user approves:
  ssh_exec.py peladn "systemctl restart nfs-server" --confirmation-quote "yes do it"

Hosts:
  peladn  -> root@192.168.4.150
  evox2   -> root@192.168.4.84
  ha      -> root@192.168.4.13
  pbs     -> root@192.168.4.27

Every executed command is appended to /opt/data/logs/ssh-exec-audit.log with:
  timestamp, host, command, user-confirmation-quote, exit-code.
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

SSH_KEY = os.environ.get("HERMES_SSH_KEY", "/opt/data/.ssh/id_ed25519")
AUDIT_LOG = Path("/opt/data/logs/ssh-exec-audit.log")

HOSTS = {
    "peladn": "192.168.4.150",
    "evox2":  "192.168.4.84",
    "ha":     "192.168.4.13",
    "pbs":    "192.168.4.27",
}

# Hard blocks: things we never run, even with confirmation.
NEVER_RUN = [
    "rm -rf /",
    "mkfs",
    "dd if=/dev/zero of=/dev/",
    "dd if=/dev/random of=/dev/",
    ":(){:|:&};:",  # fork bomb
    "shutdown -h now",
    "poweroff",
    "halt",
    "init 0",
    "init 6",
    "kubectl delete namespace mem0",
    "kubectl delete namespace flux-system",
    "kubectl delete namespace kube-system",
    "kubectl delete namespace n8n",
    "pct destroy",
    "qm destroy",
]


def is_never_run(cmd: str) -> str | None:
    """Return the matched forbidden pattern, or None."""
    low = cmd.lower().strip()
    for pat in NEVER_RUN:
        if pat.lower() in low:
            return pat
    return None


def audit(host_alias: str, cmd: str, conf_quote: str, exit_code: int, dry: bool):
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": host_alias,
        "cmd": cmd,
        "confirmation": conf_quote,
        "exit_code": exit_code,
        "dry_run": dry,
    }
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("host", help=f"host alias: {', '.join(HOSTS)}")
    p.add_argument("command", help="command to execute (state-changing OK)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would run; do not execute. ALWAYS use this first.")
    p.add_argument("--confirmation-quote",
                   help="Short excerpt of the user's approval message. Required for actual execution.")
    p.add_argument("--json", action="store_true", help="output as JSON")
    a = p.parse_args()

    if a.host not in HOSTS:
        print(f"  unknown host {a.host!r}", file=sys.stderr)
        sys.exit(2)
    ip = HOSTS[a.host]

    forbidden = is_never_run(a.command)
    if forbidden:
        print(f"  HARD-BLOCKED: command matches NEVER_RUN pattern {forbidden!r}", file=sys.stderr)
        print(f"  this is unrecoverable; ssh_exec will not run it under any circumstance.", file=sys.stderr)
        sys.exit(4)

    if a.dry_run:
        print(f"DRY-RUN — would execute on root@{ip} ({a.host}):")
        print(f"  {a.command}")
        print()
        print(f"After user explicit approval, re-run WITHOUT --dry-run and WITH --confirmation-quote 'their words'")
        audit(a.host, a.command, "(dry-run)", 0, dry=True)
        return

    if not a.confirmation_quote or len(a.confirmation_quote.strip()) < 2:
        print("  REFUSED: missing --confirmation-quote.", file=sys.stderr)
        print("  ssh_exec requires you to quote the user's explicit approval message.", file=sys.stderr)
        print("  Call --dry-run first; ask the user to confirm; pass their words as --confirmation-quote.", file=sys.stderr)
        sys.exit(3)

    ssh_argv = [
        "ssh", "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=/tmp/hermes-known-hosts",
        "-o", "ConnectTimeout=15",
        "-o", "BatchMode=yes",
        f"root@{ip}", a.command,
    ]
    try:
        r = subprocess.run(ssh_argv, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"  ssh timeout after 120s", file=sys.stderr)
        audit(a.host, a.command, a.confirmation_quote, 124, dry=False)
        sys.exit(124)

    audit(a.host, a.command, a.confirmation_quote, r.returncode, dry=False)

    if a.json:
        print(json.dumps({"host": a.host, "cmd": a.command, "exit": r.returncode,
                          "stdout": r.stdout, "stderr": r.stderr}, indent=2))
    else:
        if r.stdout:
            sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
