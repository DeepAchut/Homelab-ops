#!/usr/bin/env python3
"""
searxng_query.py — primary web-search tool for Hermes.

Calls the SearXNG instance at SEARXNG_URL (default in-cluster) and returns
top results. Use this FIRST for any web research need; do NOT attempt to
scrape google.com / duckduckgo.com / etc directly — they block bot traffic
and the Hermes pod has no Chrome for fallback.

Reads (from env):
  SEARXNG_URL   default: http://searxng.searxng.svc.cluster.local:8080

Usage:
  searxng_query.py search "talos linux 1.13 release notes"
  searxng_query.py search "kubectl cordon vs drain" -n 8
  searxng_query.py search "openwebui youtube tool" --categories general,it
  searxng_query.py fetch <url>          # plain-text scrape of a single URL
  searxng_query.py health               # is SearXNG reachable?

Output is concise terminal-friendly text (title + URL + snippet per result).
Add --json for the raw SearXNG response.
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request, urllib.error

DEFAULT_URL = os.environ.get(
    "SEARXNG_URL", "http://searxng.searxng.svc.cluster.local:8080"
).rstrip("/")
TIMEOUT = 12
UA = "Hermes-Agent/1.0 (homelab; +http://hermes-agent.svc)"


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} fetching {url}: {e.read()[:200].decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args):
    body, status, _ = _get(f"{DEFAULT_URL}/healthz")
    print(f"  SearXNG @ {DEFAULT_URL}  status={status}  body={body[:80].decode(errors='replace')!r}")


def cmd_search(args):
    params = {
        "q": args.query,
        "format": "json",
        "safesearch": str(args.safesearch),
        "language": args.lang,
    }
    if args.categories:
        params["categories"] = args.categories
    if args.engines:
        params["engines"] = args.engines
    if args.time_range:
        params["time_range"] = args.time_range
    url = f"{DEFAULT_URL}/search?{urllib.parse.urlencode(params)}"
    body, _, _ = _get(url)
    try:
        d = json.loads(body)
    except Exception as e:
        print(f"non-JSON response (first 200 chars): {body[:200].decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

    results = d.get("results", [])[: args.n]

    if args.json:
        print(json.dumps({"query": args.query, "results": results}, indent=2))
        return

    if not results:
        print(f"  no results for {args.query!r}")
        suggestions = d.get("suggestions") or []
        if suggestions:
            print(f"  suggestions: {', '.join(suggestions[:5])}")
        return

    print(f"  query: {args.query!r}  results: {len(results)} (of {len(d.get('results', []))})")
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()[:120]
        url_ = r.get("url") or ""
        snippet = re.sub(r"\s+", " ", (r.get("content") or "").strip())[:240]
        engines = ",".join(r.get("engines") or [])
        print()
        print(f"  [{i}] {title}")
        print(f"      {url_}")
        if snippet:
            print(f"      {snippet}")
        if engines:
            print(f"      engines: {engines}")


def cmd_fetch(args):
    """Plain-text scrape of a single URL via SearXNG isn't a thing —
    just fetch it directly. SearXNG's `image_proxy: true` helps for images;
    for HTML, urllib is fine."""
    body, status, headers = _get(args.url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    ctype = headers.get("Content-Type", "")
    text = body.decode(errors="replace") if "text" in ctype or "json" in ctype else f"<{len(body)} bytes of {ctype}>"
    if args.json:
        print(json.dumps({"url": args.url, "status": status, "content_type": ctype, "body": text[: args.max_chars]}, indent=2))
        return
    print(f"  {args.url}  HTTP {status}  {ctype}  ({len(body)} bytes)")
    if args.strip_html:
        # quick-and-dirty tag stripper — good enough for "what does this page say"
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    print(text[: args.max_chars])
    if len(text) > args.max_chars:
        print(f"\n  ... (+{len(text)-args.max_chars} chars trimmed — use --max-chars or --json)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("health", help="check SearXNG reachability")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("search", help="run a web search via SearXNG")
    sp.add_argument("query", help="search query string (quote it)")
    sp.add_argument("-n", type=int, default=5, help="max results to show (default 5)")
    sp.add_argument("--lang", default="en", help="language code (default en)")
    sp.add_argument("--safesearch", type=int, default=0, choices=[0, 1, 2])
    sp.add_argument("--categories", help="comma-separated, e.g. 'general,it'")
    sp.add_argument("--engines", help="comma-separated engine list, e.g. 'google,duckduckgo'")
    sp.add_argument("--time-range", choices=["day", "week", "month", "year"], help="freshness filter")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="fetch a single URL as text")
    sp.add_argument("url")
    sp.add_argument("--max-chars", type=int, default=8000)
    sp.add_argument("--strip-html", action="store_true", default=True)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_fetch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
