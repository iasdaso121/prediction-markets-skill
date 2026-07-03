#!/usr/bin/env python3
# Part of prediction-markets-skill. Read-only. Stdlib only. Endpoints from docs-raw (see references/).
"""Polymarket market discovery via the Gamma API (gamma-api.polymarket.com)."""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
USER_AGENT = "prediction-markets-skill/0.1 (+https://github.com/azazelitto21/prediction-markets-skill)"
PAGE_SIZE = 100  # Gamma /markets limit+offset paging; no documented max, 100 is the docs' example size

EXIT_BY_CATEGORY = {"usage": 2, "network": 3, "rate-limit": 4, "geo": 5, "not-found": 6, "schema": 7}


def fail(category, message, hint=""):
    print(json.dumps({"error": {"category": category, "message": message, "hint": hint}}),
          file=sys.stderr)
    sys.exit(EXIT_BY_CATEGORY.get(category, 3))


def http_get_json(path, params, timeout):
    """GET {GAMMA}{path}?{params} -> parsed JSON. Retries 429/5xx 3x with 1s/2s/4s backoff."""
    url = GAMMA + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    backoff = [1, 2, 4]
    last_429 = False
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            try:
                return json.loads(body)
            except ValueError:
                fail("schema", "Response from %s is not valid JSON" % url,
                     "Gamma normally returns JSON; inspect the endpoint against docs-raw/polymarket/gamma-openapi.yaml")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code == 404:
                fail("not-found", "404 from %s" % url,
                     "Check the identifier; Gamma slugs are market slugs, not polymarket.com event-page slugs")
            if e.code in (403, 451):
                blob = (body + str(e.headers)).lower()
                if any(w in blob for w in ("cloudflare", "region", "blocked", "restricted", "country", "geo")):
                    fail("geo", "HTTP %d from gamma-api.polymarket.com looks geo-blocked" % e.code,
                         "Polymarket blocks some regions; check your region/VPN and retry")
                fail("network", "HTTP %d from %s" % (e.code, url), body[:200])
            if e.code == 429 or 500 <= e.code < 600:
                last_429 = e.code == 429
                if attempt < 3:
                    delay = backoff[attempt]
                    ra = e.headers.get("Retry-After") if e.headers else None
                    if ra and ra.strip().isdigit():
                        delay = max(delay, int(ra.strip()))
                    print("HTTP %d from %s; retry in %ds (attempt %d/3)" % (e.code, path, delay, attempt + 1),
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                if last_429:
                    fail("rate-limit", "Still rate-limited (429) by %s after 3 retries" % url,
                         "Gamma /markets allows 300 req/10s; slow down and retry later")
                fail("network", "HTTP %d from %s after 3 retries" % (e.code, url), body[:200])
            fail("network", "HTTP %d from %s" % (e.code, url), body[:200])
        except (urllib.error.URLError, OSError) as e:
            fail("network", "Request to %s failed: %s" % (url, e),
                 "Check connectivity/DNS to gamma-api.polymarket.com and --timeout")
    fail("network", "Unreachable retry loop exit for %s" % url, "")


def decode_stringified_array(value):
    """Gamma serializes outcomes/outcomePrices/clobTokenIds as JSON-array-encoded STRINGS (gotchas.md)."""
    if value is None:
        return None
    if isinstance(value, list):  # defensive: pass through if the API ever returns a real array
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else None
    except (ValueError, TypeError):
        print("warning: could not decode stringified array field: %r" % (value,), file=sys.stderr)
        return None


def as_price_string(value):
    """Passthrough prices normalized to string; may arrive string OR number (gotchas.md)."""
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)


def trim_market(m):
    outcomes = decode_stringified_array(m.get("outcomes")) or []
    prices = decode_stringified_array(m.get("outcomePrices")) or []
    token_ids = decode_stringified_array(m.get("clobTokenIds")) or []
    # Docs order: index 0 = Yes token, index 1 = No token; outcomes/outcomePrices map 1:1 by index.
    rows = []
    for i in range(max(len(outcomes), len(prices), len(token_ids))):
        rows.append({
            "outcome": outcomes[i] if i < len(outcomes) else None,
            "price": as_price_string(prices[i]) if i < len(prices) else None,
            "clob_token_id": token_ids[i] if i < len(token_ids) else None,
        })
    yes_idx = 0
    for i, name in enumerate(outcomes):
        if isinstance(name, str) and name.lower() == "yes":
            yes_idx = i
            break
    implied = None
    if yes_idx < len(prices):
        try:
            implied = round(float(prices[yes_idx]), 4)
        except (TypeError, ValueError):
            pass
    return {
        "id": str(m["id"]) if m.get("id") is not None else None,  # Gamma ids are JSON strings; keep string
        "slug": m.get("slug"),
        "question": m.get("question"),
        "active": m.get("active"),
        "closed": m.get("closed"),
        "end_date": m.get("endDate"),
        "outcomes": rows,
        "clob_token_ids": token_ids,
        "volume": m.get("volume"),        # venue-native string, unchanged
        "liquidity": m.get("liquidity"),  # venue-native string, unchanged
        "neg_risk": m.get("negRisk"),     # in reference field list; absent from spec Market schema -> may be null
        "implied_probability": implied,   # float(YES outcomePrice), rounded to 4 decimals
    }


def resolve_tag_id(tag, timeout):
    """--tag accepts a numeric tag id or a tag slug (resolved via GET /tags/slug/{slug})."""
    if tag.isdigit():
        return int(tag)
    data = http_get_json("/tags/slug/" + urllib.parse.quote(tag, safe=""), {}, timeout)
    if not isinstance(data, dict) or data.get("id") is None:
        fail("schema", "Unexpected /tags/slug response shape for %r" % tag, "Expected an object with an 'id' field")
    return int(str(data["id"]))


def fetch_by_slug(slug, timeout):
    data = http_get_json("/markets/slug/" + urllib.parse.quote(slug, safe=""), {}, timeout)
    if not isinstance(data, dict):
        fail("schema", "Expected a single market object from /markets/slug/%s" % slug, "")
    return [data], "/markets/slug/{slug}", {"slug": slug}


def fetch_by_search(query, want_active, want_closed, limit, timeout):
    """GET /public-search?q= (documented Gamma full-text search) and flatten events[].markets[].
    active/closed are filtered client-side: /public-search has no market-level status params."""
    found, seen, page = [], set(), 1
    while len(found) < limit:
        params = {"q": query, "page": page, "limit_per_type": 20}
        resp = http_get_json("/public-search", params, timeout)
        if not isinstance(resp, dict):
            fail("schema", "Expected object from /public-search", "See Search schema in gamma-openapi.yaml")
        events = resp.get("events") or []
        for ev in events:
            for m in ev.get("markets") or []:
                mid = str(m.get("id"))
                if mid in seen:
                    continue
                seen.add(mid)
                if want_active and not (m.get("active") and not m.get("closed")):
                    continue
                if want_closed and not m.get("closed"):
                    continue
                found.append(m)
        print("search page %d: %d events, %d markets kept so far" % (page, len(events), len(found)),
              file=sys.stderr)
        has_more = (resp.get("pagination") or {}).get("hasMore")
        if not events or not has_more:
            break
        page += 1
    return found[:limit], "/public-search", {"q": query, "limit_per_type": 20}


def fetch_listing(want_active, want_closed, tag_id, limit, timeout):
    """GET /markets with limit+offset pagination to exhaustion or --limit (bare array, no envelope)."""
    params = {}
    if want_active:
        # 'active' is not in the OpenAPI param list for /markets, but official docs examples use
        # ?active=true&closed=false and say to always include it for live markets (reference wins here).
        params["active"] = "true"
        params["closed"] = "false"
    if want_closed:
        params["closed"] = "true"  # spec default is closed=false: closed markets are hidden otherwise
    if tag_id is not None:
        params["tag_id"] = tag_id
    found, offset = [], 0
    while len(found) < limit:
        page_size = min(PAGE_SIZE, limit - len(found))
        q = dict(params, limit=page_size, offset=offset)
        page = http_get_json("/markets", q, timeout)
        if not isinstance(page, list):
            fail("schema", "Expected a bare JSON array from /markets", "See gamma-openapi.yaml listMarkets")
        found.extend(page)
        print("listing offset %d: got %d markets (total %d)" % (offset, len(page), len(found)), file=sys.stderr)
        if len(page) < page_size:  # short/empty page = no more data (Gamma sends no cursor/total)
            break
        offset += page_size
    return found[:limit], "/markets", params


class JsonErrorParser(argparse.ArgumentParser):
    """argparse that reports bad usage as the shared JSON error line (exit 2)."""

    def error(self, message):
        print(self.format_usage().strip(), file=sys.stderr)
        fail("usage", message, "run with --help for examples")


def main():
    parser = JsonErrorParser(
        description="Discover Polymarket markets via the Gamma API (read-only, no auth).\n"
                    "--query uses Gamma's documented GET /public-search full-text endpoint and flattens\n"
                    "the markets embedded in matching events (active/closed filtered client-side there).",
        epilog="Examples:\n"
               '  %(prog)s --active --limit 5\n'
               '  %(prog)s --slug new-rhianna-album-before-gta-vi-926\n'
               '  %(prog)s --query "fed" --limit 5\n'
               '  %(prog)s --tag politics --active --limit 10\n'
               '  %(prog)s --closed --tag 100381 --limit 20 --raw\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", help="full-text search via GET /public-search (matches events/markets)")
    parser.add_argument("--slug", help="exact market slug via GET /markets/slug/{slug}")
    parser.add_argument("--tag", help="tag id (numeric) or tag slug; slug resolved via GET /tags/slug/{slug}")
    status = parser.add_mutually_exclusive_group()
    status.add_argument("--active", action="store_true", help="only live markets (active=true, closed=false)")
    status.add_argument("--closed", action="store_true", help="only closed markets (API hides them by default)")
    parser.add_argument("--limit", type=int, default=100, help="max markets to return (default 100)")
    parser.add_argument("--raw", action="store_true", help="emit raw Gamma market objects instead of trimmed rows")
    parser.add_argument("--timeout", type=int, default=15, help="per-request timeout seconds (default 15)")
    args = parser.parse_args()

    if args.slug and (args.query or args.tag or args.active or args.closed):
        fail("usage", "--slug is an exact lookup; it cannot be combined with other filters",
             "Use --slug alone, or --query/--tag with --active/--closed")
    if args.query and args.tag:
        fail("usage", "--tag cannot be combined with --query",
             "GET /public-search has no per-market tag filter; use --tag with the listing mode instead")
    if args.limit < 1:
        fail("usage", "--limit must be >= 1", "")

    if args.slug:
        markets, endpoint, eff = fetch_by_slug(args.slug, args.timeout)
    elif args.query:
        markets, endpoint, eff = fetch_by_search(args.query, args.active, args.closed, args.limit, args.timeout)
    else:
        tag_id = resolve_tag_id(args.tag, args.timeout) if args.tag else None
        markets, endpoint, eff = fetch_listing(args.active, args.closed, tag_id, args.limit, args.timeout)

    data = markets if args.raw else [trim_market(m) for m in markets]
    envelope = {
        "venue": "polymarket",
        "endpoint": GAMMA + endpoint,
        "params": dict(eff, limit=args.limit),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "count": len(data),
        "data": data,
    }
    json.dump(envelope, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
