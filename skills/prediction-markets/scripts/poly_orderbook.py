#!/usr/bin/env python3
# Part of prediction-markets-skill. Read-only. Stdlib only. Endpoints from docs-raw (see references/).
"""Polymarket CLOB orderbook snapshot for one outcome token.

Resolves --slug via one Gamma call (clobTokenIds is a JSON-array-encoded STRING),
then fetches /book, /midpoint and /price (both sides) from the CLOB and emits one
JSON document on stdout: raw book (native string prices/sizes) plus a computed
summary (best_bid, best_ask, spread, midpoint, implied_probability, depth in USDC).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
USER_AGENT = "prediction-markets-skill/0.1 (+https://github.com/azazelitto21/prediction-markets-skill)"
EXIT_CODES = {"usage": 2, "network": 3, "rate-limit": 4, "geo": 5, "not-found": 6, "schema": 7}
GEO_WORDS = ("cloudflare", "region", "blocked", "restricted", "geo", "unavailable in your country")

EPILOG = """examples:
  # Orderbook for a market by its Gamma slug (YES token by default):
  poly_orderbook.py --slug will-mexico-win-the-2026-fifa-world-cup-529

  # NO side of a market, top 5 levels per side:
  poly_orderbook.py --slug will-belgium-win-the-2026-fifa-world-cup-358 --outcome no --limit 5

  # Directly by CLOB token id (huge decimal string from Gamma clobTokenIds):
  poly_orderbook.py --token-id 22587775301869146748237913050505932485648958481571808324285560650057390882036
"""


def log(msg):
    print(msg, file=sys.stderr)


def fail(category, message, hint=""):
    print(json.dumps({"error": {"category": category, "message": message, "hint": hint}}),
          file=sys.stderr)
    sys.exit(EXIT_CODES[category])


class Parser(argparse.ArgumentParser):
    def error(self, message):  # emit the shared JSON error envelope on usage errors
        self.print_usage(sys.stderr)
        fail("usage", message, "run with --help for examples")


def http_get_json(url, timeout, not_found_hint="check the identifier"):
    """GET url -> parsed JSON. Retries 429/5xx up to 3 times (1 try + 3 retries, 1s/2s/4s, honors Retry-After)."""
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(4):  # 1 try + up to 3 retries, backoff 1s/2s/4s
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except ValueError:
                fail("schema", "non-JSON response from %s: %s" % (url, body[:200]),
                     "API may have changed; re-check docs-raw/polymarket specs")
        except urllib.error.HTTPError as err:
            try:
                body = err.read().decode("utf-8", "replace")
            except OSError:
                body = ""
            status = err.code
            if status in (403, 451):
                if any(w in body.lower() for w in GEO_WORDS):
                    fail("geo", "HTTP %d from %s looks geo-blocked" % (status, host),
                         "Polymarket blocks some regions; check your region/VPN for %s" % host)
                fail("network", "HTTP %d from %s: %s" % (status, host, body[:200]),
                     "403/451 without geo-block wording; retry later or verify the URL")
            if status == 404:
                fail("not-found", "HTTP 404 from %s: %s" % (url, body[:200]), not_found_hint)
            if status == 429 or status >= 500:
                if attempt < 3:
                    retry_after = err.headers.get("Retry-After", "")
                    delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                    log("HTTP %d from %s; retrying in %ds (attempt %d/4)" % (status, host, delay, attempt + 2))
                    time.sleep(delay)
                    continue
                if status == 429:
                    fail("rate-limit", "still rate-limited by %s after 4 attempts" % host,
                         "Polymarket throttles per 10s window; wait and retry")
                fail("network", "HTTP %d from %s after 4 attempts: %s" % (status, host, body[:200]),
                     "server-side error; retry later")
            if status == 400:
                # CLOB rejects unknown/malformed token ids with 400; treat as not-found when it names the token.
                if any(w in body.lower() for w in ("token", "not found", "no orderbook", "invalid", "market")):
                    fail("not-found", "HTTP 400 from %s: %s" % (url, body[:200]), not_found_hint)
                fail("usage", "HTTP 400 from %s: %s" % (url, body[:200]), "check parameter values")
            fail("network", "HTTP %d from %s: %s" % (status, url, body[:200]), "unexpected status")
        except (urllib.error.URLError, TimeoutError) as err:
            reason = getattr(err, "reason", err)
            fail("network", "request to %s failed: %s" % (url, reason),
                 "check connectivity/DNS, or raise --timeout")
    fail("network", "exhausted retries for %s" % url, "retry later")


def parse_encoded_array(raw, field, slug):
    """Gamma clobTokenIds/outcomes are JSON-array-encoded STRINGS, not arrays (gotchas.md)."""
    if isinstance(raw, list):  # be lenient if Gamma ever returns a real array
        return raw
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        fail("schema", "market '%s': %s is not a parseable JSON-encoded array: %r" % (slug, field, raw),
             "Gamma schema surprise; see references/gotchas.md")
    if not isinstance(val, list):
        fail("schema", "market '%s': %s decoded to %s, expected list" % (slug, field, type(val).__name__), "")
    return val


def resolve_slug(slug, outcome, timeout):
    """One Gamma call: market slug -> (token_id, resolution metadata)."""
    url = GAMMA + "/markets/slug/" + urllib.parse.quote(slug, safe="")
    log("resolving slug via %s" % url)
    market = http_get_json(url, timeout, not_found_hint=(
        "no MARKET with this slug; event URLs use event slugs — list per-market slugs via "
        "GET %s/events/slug/%s, or pass --token-id" % (GAMMA, slug)))
    raw_tokens = market.get("clobTokenIds")
    if not raw_tokens:
        fail("not-found", "market '%s' has no clobTokenIds (not CLOB-tradable)" % slug,
             "check enableOrderBook on the Gamma market")
    tokens = parse_encoded_array(raw_tokens, "clobTokenIds", slug)
    labels = []
    if market.get("outcomes"):
        try:
            labels = parse_encoded_array(market["outcomes"], "outcomes", slug)
        except SystemExit:
            raise
    # Match the token by OUTCOME LABEL, not by array position: Polymarket does not
    # guarantee outcomes are ordered [Yes, No] (py-clob-client #276), so trusting
    # index 0=Yes silently returns the wrong side on markets stored [No, Yes].
    # clobTokenIds[i] corresponds to outcomes[i]. Fall back to position only when
    # labels are absent (default binary convention: index 0=Yes, 1=No).
    idx = None
    if labels:
        for i, name in enumerate(labels):
            if isinstance(name, str) and name.strip().lower() == outcome:
                idx = i
                break
        if idx is None:
            fail("not-found", "market '%s' has no '%s' outcome; outcomes are %s"
                 % (slug, outcome, labels),
                 "use --outcome matching one of the listed labels, or pass --token-id")
    else:
        idx = 0 if outcome == "yes" else 1  # no labels: fall back to documented binary order
    if idx >= len(tokens):
        fail("schema", "market '%s' has %d clobTokenIds; no index %d for outcome '%s'"
             % (slug, len(tokens), idx, outcome), "")
    meta = {
        "slug": slug,
        "question": market.get("question"),
        "gamma_market_id": market.get("id"),  # numeric string in Gamma responses
        "condition_id": market.get("conditionId"),
        "outcome": labels[idx] if idx < len(labels) else outcome.upper(),
        "neg_risk": market.get("negRisk"),
    }
    return tokens[idx], meta


def to_float(value):
    """CLOB prices arrive as string OR number depending on endpoint (gotchas.md)."""
    return float(str(value))


def book_timestamp_iso(ts):
    """/book 'timestamp' is a Unix-MILLISECONDS string (13 digits, live-checked; the spec
    does not state the unit) — NOT seconds like /prices-history or /time. See gotchas.md."""
    try:
        val = int(str(ts))
    except (TypeError, ValueError):
        return None
    if val >= 10 ** 12:  # 13+ digits => milliseconds
        return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc).isoformat()
    return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()


def side_stats(levels, side, url):
    """(best_price, depth_usdc, sorted-best-first levels). Server ordering is undocumented,
    so sort by price instead of trusting element [0]."""
    if not isinstance(levels, list):
        fail("schema", "book %s is %s, expected list (%s)" % (side, type(levels).__name__, url), "")
    try:
        parsed = [(to_float(lv["price"]), to_float(lv["size"]), lv) for lv in levels]
    except (KeyError, TypeError, ValueError) as err:
        fail("schema", "unparseable %s level in %s: %s" % (side, url, err), "")
    parsed.sort(key=lambda t: t[0], reverse=(side == "bids"))  # bids: best = highest; asks: best = lowest
    best = parsed[0][0] if parsed else None
    depth = sum(p * s for p, s, _ in parsed)
    return best, depth, [lv for _, _, lv in parsed]


def rnd(value):
    return None if value is None else round(value, 4)


def main():
    parser = Parser(
        description="Polymarket CLOB orderbook snapshot (read-only): raw /book plus "
                    "midpoint, both /price sides, spread and USDC depth for one outcome token.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--token-id", help="CLOB token id (huge decimal string, aka asset id)")
    who.add_argument("--slug", help="Gamma MARKET slug (resolved via GET /markets/slug/{slug})")
    parser.add_argument("--outcome", choices=("yes", "no"), default="yes",
                        help="which outcome token when using --slug (default: yes)")
    parser.add_argument("--limit", type=int, default=100,
                        help="max book levels per side in output (default: 100)")
    parser.add_argument("--timeout", type=int, default=15,
                        help="per-request timeout in seconds (default: 15)")
    args = parser.parse_args()
    if args.limit < 1:
        fail("usage", "--limit must be >= 1", "")
    if args.timeout < 1:
        fail("usage", "--timeout must be >= 1", "")
    if args.token_id and args.outcome != "yes":
        log("note: --outcome is ignored with --token-id (the token already encodes the outcome)")

    resolved = None
    token_id = args.token_id
    if args.slug:
        token_id, resolved = resolve_slug(args.slug, args.outcome, args.timeout)

    unknown_hint = "token id unknown to the CLOB; get it from Gamma clobTokenIds (index 0=Yes, 1=No)"
    book_url = CLOB + "/book?" + urllib.parse.urlencode({"token_id": token_id})
    book = http_get_json(book_url, args.timeout, not_found_hint=unknown_hint)
    if not isinstance(book, dict) or "bids" not in book or "asks" not in book:
        fail("not-found" if book in ({}, None, []) else "schema",
             "/book returned no orderbook for token %s...: %s" % (str(token_id)[:24], str(book)[:200]),
             unknown_hint)

    best_bid, bid_depth, bids_sorted = side_stats(book["bids"], "bids", book_url)
    best_ask, ask_depth, asks_sorted = side_stats(book["asks"], "asks", book_url)

    mid_url = CLOB + "/midpoint?" + urllib.parse.urlencode({"token_id": token_id})
    mid_resp = http_get_json(mid_url, args.timeout, not_found_hint=unknown_hint)
    # Live key is "mid"; the stale spec says "mid_price" — read both (gotchas.md).
    mid_raw = mid_resp.get("mid", mid_resp.get("mid_price")) if isinstance(mid_resp, dict) else None

    prices = {}
    for side in ("BUY", "SELL"):
        p_url = CLOB + "/price?" + urllib.parse.urlencode({"token_id": token_id, "side": side})
        p_resp = http_get_json(p_url, args.timeout, not_found_hint=unknown_hint)
        p_val = p_resp.get("price") if isinstance(p_resp, dict) else None
        prices[side] = None if p_val is None else str(p_val)  # normalize string-or-number to string

    midpoint = to_float(mid_raw) if mid_raw is not None else (
        (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None)
    spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None

    book_out = dict(book)
    book_out["bids"] = bids_sorted[:args.limit]  # native {price,size} string levels, best first
    book_out["asks"] = asks_sorted[:args.limit]

    data = {
        "token_id": token_id,
        "resolved": resolved,
        "book": book_out,
        "bids_total": len(bids_sorted),
        "asks_total": len(asks_sorted),
        "book_timestamp_iso": book_timestamp_iso(book.get("timestamp")),
        "midpoint_raw": None if mid_raw is None else str(mid_raw),
        "price": prices,
        "summary": {
            "best_bid": rnd(best_bid),
            "best_ask": rnd(best_ask),
            "spread": rnd(spread),
            "midpoint": rnd(midpoint),
            "implied_probability": rnd(midpoint),  # price 0-1 IS P(outcome) (market-mechanics.md)
            "bid_depth_usdc": rnd(bid_depth),  # sum(price*size) over the FULL book, not just --limit levels
            "ask_depth_usdc": rnd(ask_depth),
        },
    }
    envelope = {
        "venue": "polymarket",
        "endpoint": "/book,/midpoint,/price",
        "params": {"token_id": token_id, "slug": args.slug, "outcome": args.outcome,
                   "limit": args.limit, "timeout": args.timeout},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(book_out["bids"]) + len(book_out["asks"]),
        "data": data,
    }
    print(json.dumps(envelope))


if __name__ == "__main__":
    main()
