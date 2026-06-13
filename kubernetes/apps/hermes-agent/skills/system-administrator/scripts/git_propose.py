#!/usr/bin/env python3
"""
git_propose.py — write a unified-diff proposal for the user to review + apply.

Hermes cannot commit to the repo directly. Instead, propose a change as a diff
against the current GitHub HEAD, save it to /opt/data/proposals/, and tell the
user where the diff lives. The user reviews it on their machine and applies it
manually (git apply <diff> or paste the new content).

Usage:
  git_propose.py <repo-path> --new-content-file /tmp/new.yaml
  git_propose.py <repo-path> --new-content-stdin <<< "the new content"
  git_propose.py <repo-path> --new-content "single-line replacement"

Output is the path to the saved diff + a short summary.
"""
import argparse, difflib, json, os, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OWNER = os.environ.get("HERMES_REPO_OWNER", "DeepAchut")
REPO = os.environ.get("HERMES_REPO_NAME", "Homelab-ops")
BRANCH = os.environ.get("HERMES_REPO_BRANCH", "main")
PROPOSAL_DIR = Path("/opt/data/proposals")


def fetch_current(path: str) -> str:
    url = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{path.lstrip('/')}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""  # file doesn't exist yet — treat as empty for diff purposes


def make_diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    ))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", help="repo-relative path of the file being proposed")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--new-content-file", help="path on disk holding the new content")
    src.add_argument("--new-content", help="inline new content (one short string)")
    src.add_argument("--new-content-stdin", action="store_true", help="read new content from stdin")
    p.add_argument("--reason", default="(no reason given)", help="why this change is being proposed")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    if a.new_content_file:
        new = Path(a.new_content_file).read_text()
    elif a.new_content_stdin:
        new = sys.stdin.read()
    else:
        new = a.new_content

    old = fetch_current(a.path)
    diff = make_diff(old, new, a.path)
    if not diff.strip():
        print("  no changes — new content is identical to current HEAD", file=sys.stderr)
        sys.exit(0)

    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = a.path.replace("/", "-").replace(".", "_")
    diff_path = PROPOSAL_DIR / f"{stamp}-{slug}.patch"
    meta_path = PROPOSAL_DIR / f"{stamp}-{slug}.meta.json"
    diff_path.write_text(diff)
    meta_path.write_text(json.dumps({
        "ts": stamp,
        "path": a.path,
        "reason": a.reason,
        "old_size": len(old),
        "new_size": len(new),
        "diff_lines": diff.count("\n"),
    }, indent=2))

    summary = {
        "diff_path": str(diff_path),
        "meta_path": str(meta_path),
        "diff_lines": diff.count("\n"),
        "reason": a.reason,
    }
    if a.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"  proposal saved to {diff_path}")
        print(f"  diff lines: {summary['diff_lines']}")
        print(f"  reason: {a.reason}")
        print()
        print(f"  the user can pull + apply via:")
        print(f"    scp root@<hermes-host>:{diff_path} /tmp/")
        print(f"    cd Homelab-ops && git apply /tmp/{diff_path.name}")
        print()
        print(f"  preview (first 30 lines):")
        for line in diff.splitlines()[:30]:
            print(f"    {line}")


if __name__ == "__main__":
    main()
