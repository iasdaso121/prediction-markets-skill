#!/usr/bin/env python3
# Part of prediction-markets-skill. Read-only. Stdlib only. Endpoints from docs-raw (see references/).
"""Kalshi market discovery: list/filter markets, or fetch one market by ticker.

Endpoints (Kalshi Trade API v2, docs-raw/kalshi/openapi.yaml spec v3.23.0):
  GET /markets            cursor-paginated listing with server-side filters
  GET /markets/{ticker}   single market

Prices are passed through as Kalshi-native fixed-point dollar STRINGS
(e.g. "0.5600" = 56 cents). implied_probability is a computed float.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
# Secondary documented production host (references/kalshi-api.md "Base URLs");
# used ONLY to disambiguate wordless 403s -- see classify_deny().
ALT_URL = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = "prediction-markets-skill/0.1 (+https://github.com/azazelitto21/prediction-markets-skill)"
# Status QUERY enum from spec (MarketStatusQuery). Spec wins over prose, which omits "paused".
STATUS_CHOICES = ("unopened", "open", "paused", "closed", "settled")
PAGE_MAX = 1000  # GET /markets `limit`: 0-1000, default 100 (MarketLimitQuery)
EXIT_CODES = {"usage": 2, "network": 3, "rate-limit": 4, "geo": 5, "not-found": 6, "schema": 7}
# Kalshi has NO text-search param; --query is filtered client-side on these fields.
TEXT_FIELDS = ("title", "subtitle", "yes_sub_title", "no_sub_title")

EPILOG = """examples:
  %(prog)s --series KXHIGHNY --status open --limit 5
  %(prog)s --ticker KXHIGHNY-26JUL02-T99
  %(prog)s --event KXHIGHNY-26JUL02 --raw
  %(prog)s --series KXHIGHNY --status open --query "99" --limit 10

notes:
  Kalshi has no server-side text search. --query is a client-side,
  case-insensitive substring filter on title/subtitle/yes_sub_title/
  no_sub_title, applied AFTER fetching pages -- broad queries without
  --series/--event/--status may scan many pages before finding matches.
  Prices in output are Kalshi-native fixed-point dollar strings.
"""


def fail(category, message, hint=""):
    print(json.dumps({"error": {"category": category, "message": message, "hint": hint}}),
          file=sys.stderr)
    sys.exit(EXIT_CODES[category])


class JsonErrorParser(argparse.ArgumentParser):
    """argparse that reports bad usage as the shared JSON error line (exit 2)."""

    def error(self, message):
        print(self.format_usage().strip(), file=sys.stderr)
        fail("usage", message, "run with --help for examples")


# Observed live 2026-07-02 (noted per gotchas guidance): when region-blocked,
# api.elections.kalshi.com serves a CloudFront page saying it is "configured to
# block access from your country"; external-api.kalshi.com serves a bare nginx
# "403 Forbidden" with NO wording at all.
GEO_WORDS = ("cloudflare", "cloudfront", "region", "block", "restricted",
             "geograph", "country", "not available in your", "unavailable in your")


def looks_geo_blocked(body):
    lowered = body.lower()
    return any(w in lowered for w in GEO_WORDS)


def classify_deny(status, url, body, timeout):
    """Classify an HTTP 403/451 as geo or network, then fail(). Never returns.

    external-api.kalshi.com's region block is a WORDLESS nginx 403 (observed
    live 2026-07-02), so body sniffing alone cannot catch it: for a wordless
    deny, probe ALT_URL, whose block page does carry geo wording. Both are
    unauthenticated public GETs, so if both deny us, geo is the likely cause.
    """
    host = urllib.parse.urlsplit(url).hostname or "kalshi"
    hint = "Kalshi blocks some regions; check the region/network you are calling from."
    if looks_geo_blocked(body):
        fail("geo", "HTTP %d from %s looks geo-blocked" % (status, host), hint)
    probe = urllib.request.Request(ALT_URL + "/markets?limit=1",
                                   headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    alt_status, alt_body = None, ""
    try:
        with urllib.request.urlopen(probe, timeout=timeout) as resp:
            alt_status = resp.status
    except urllib.error.HTTPError as err:
        alt_status = err.code
        try:
            alt_body = err.read().decode("utf-8", "replace")
        except OSError:
            alt_body = ""
    except urllib.error.URLError:
        pass  # secondary unreachable; fall through to network below
    if alt_status in (403, 451):
        confirmed = " (geo wording on secondary host)" if looks_geo_blocked(alt_body) else ""
        fail("geo", "HTTP %d from %s and HTTP %d from api.elections.kalshi.com; "
                    "Kalshi appears geo-blocked from this network%s"
                    % (status, host, alt_status, confirmed), hint)
    fail("network", "HTTP %d from %s: %s" % (status, url, body[:200]),
         "Access denied but the secondary Kalshi host answered; likely not a geo-block.")


def http_get_json(path, params, timeout):
    """GET BASE_URL+path -> parsed JSON. Retries 429/5xx 3 times (backoff 1s/2s/4s)."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    delays = (1, 2, 4)
    for attempt in range(len(delays) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            try:
                return json.loads(body)
            except ValueError:
                fail("schema", "Response from %s is not valid JSON" % url,
                     "The API may have changed; re-fetch docs-raw/kalshi/ and re-check.")
        except urllib.error.HTTPError as err:
            try:
                body = err.read().decode("utf-8", "replace")
            except OSError:
                body = ""
            status = err.code
            if status == 429 or 500 <= status < 600:
                if attempt < len(delays):
                    delay = delays[attempt]
                    retry_after = err.headers.get("Retry-After")  # Kalshi docs say none is sent; honor it if present
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, int(retry_after))
                    print("HTTP %d from %s; retry %d/3 in %ds" % (status, url, attempt + 1, delay),
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                if status == 429:
                    fail("rate-limit", "Still rate-limited by %s after 3 retries" % url,
                         "Wait a minute and retry; lower request volume.")
                fail("network", "HTTP %d from %s after 3 retries: %s" % (status, url, body[:200]),
                     "Kalshi server error; retry later. Maintenance window: Thu 03:00-05:00 ET.")
            if status in (403, 451):
                classify_deny(status, url, body, timeout)
            if status == 404:
                fail("not-found", "HTTP 404: %s does not exist on Kalshi" % path,
                     "Check the ticker spelling; list candidates via --series/--event first.")
            if status == 400:
                fail("usage", "Kalshi rejected the request (HTTP 400): %s" % body[:200],
                     "Check flag values and combinations; see --help.")
            fail("network", "Unexpected HTTP %d from %s: %s" % (status, url, body[:200]))
        except urllib.error.URLError as err:
            fail("network", "Could not reach %s: %s" % (url, err.reason),
                 "Check connectivity/DNS, or raise --timeout.")
    return None  # unreachable


def implied_probability(market):
    """Float from yes midpoint when the book has quotes, else last trade price; None otherwise."""
    def as_float(key):
        raw = market.get(key)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    bid = as_float("yes_bid_dollars")
    ask = as_float("yes_ask_dollars")
    last = as_float("last_price_dollars")
    # bid 0.0000 / ask 1.0000 is Kalshi's empty-book sentinel (observed live);
    # its 0.5 midpoint is uninformative, so fall back to last trade price.
    empty_book = bid == 0.0 and ask == 1.0
    if bid is not None and ask is not None and ask > 0 and not empty_book:
        return round((bid + ask) / 2, 4)
    if last is not None and last > 0:
        return round(last, 4)
    return None


def trim(market):
    """Trimmed row. Dollar/count fields pass through as Kalshi-native strings."""
    row = {"ticker": market.get("ticker"), "event_ticker": market.get("event_ticker")}
    if market.get("title"):  # deprecated in spec but still served
        row["title"] = market["title"]
    if market.get("yes_sub_title"):
        row["yes_sub_title"] = market["yes_sub_title"]
    row.update({
        "status": market.get("status"),
        "yes_bid_dollars": market.get("yes_bid_dollars"),
        "yes_ask_dollars": market.get("yes_ask_dollars"),
        "last_price_dollars": market.get("last_price_dollars"),
        "implied_probability": implied_probability(market),
        "volume_fp": market.get("volume_fp"),
        "open_interest_fp": market.get("open_interest_fp"),
        "close_time": market.get("close_time"),
    })
    return row


def matches_query(market, needle):
    return any(needle in str(market.get(field) or "").lower() for field in TEXT_FIELDS)


def fetch_markets(args):
    """Paginate GET /markets until --limit rows collected, cursor exhausted, or
    (client-side --query only) --max-pages scanned. Returns (rows, server_params, scan)."""
    server_params = {}
    if args.event:
        server_params["event_ticker"] = args.event
    if args.series:
        server_params["series_ticker"] = args.series
    if args.status:
        server_params["status"] = args.status
    needle = args.query.lower() if args.query else None
    collected = []
    cursor = ""
    page = 0
    scanned = 0
    while True:
        page += 1
        # With a client-side query, fetch max-size pages so filtering has material to work on.
        page_limit = PAGE_MAX if needle else min(PAGE_MAX, args.limit - len(collected))
        params = dict(server_params, limit=page_limit)
        if cursor:
            params["cursor"] = cursor  # echo back verbatim, never construct
        payload = http_get_json("/markets", params, args.timeout)
        markets = payload.get("markets")
        if not isinstance(markets, list):
            fail("schema", "GET /markets response is missing the 'markets' array",
                 "The API may have changed; re-fetch docs-raw/kalshi/ and re-check.")
        scanned += len(markets)
        for market in markets:
            if needle and not matches_query(market, needle):
                continue
            collected.append(market)
            if len(collected) >= args.limit:
                break
        cursor = payload.get("cursor") or ""  # empty cursor = last page
        exhausted = len(collected) >= args.limit or not cursor or not markets
        # The full market universe is tens of thousands of rows (~1s per 1000-row page), so an
        # uncapped --query scan runs for minutes. Cap it and report the truncation honestly.
        capped = needle is not None and not exhausted and page >= args.max_pages
        if exhausted or capped:
            scan = {"pages_scanned": page, "markets_scanned": scanned,
                    "scan_complete": not capped}
            if capped:
                scan["note"] = ("stopped at --max-pages %d before the market list was exhausted; "
                                "more matches may exist. Narrow with --series/--event/--status "
                                "or raise --max-pages." % args.max_pages)
                print("WARNING: %s" % scan["note"], file=sys.stderr)
            return collected, server_params, scan
        print("page %d done: %d/%d rows; following cursor" % (page, len(collected), args.limit),
              file=sys.stderr)


def parse_args():
    parser = JsonErrorParser(
        description="Kalshi market discovery (read-only, unauthenticated). "
                    "Lists markets with filters, or fetches one market with --ticker. "
                    "Prints a single JSON envelope to stdout.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", help="exact market ticker -> GET /markets/{ticker}, returns one object")
    parser.add_argument("--event", help="filter by event ticker (single)")
    parser.add_argument("--series", help="filter by series ticker")
    parser.add_argument("--status", choices=STATUS_CHOICES, help="filter by market status (one at a time)")
    parser.add_argument("--query", help="CLIENT-SIDE case-insensitive substring filter on "
                                        "title/subtitle fields, applied after fetching (no API support). "
                                        "Scans up to --max-pages; combine with --series/--event/--status "
                                        "to search less of the market universe")
    parser.add_argument("--max-pages", type=int, default=5,
                        help="max %d-row pages to scan when --query is set (default 5); "
                             "truncation is reported in the output's 'scan' object" % PAGE_MAX)
    parser.add_argument("--limit", type=int, default=100, help="max rows to return (default 100)")
    parser.add_argument("--raw", action="store_true", help="full market objects instead of trimmed rows")
    parser.add_argument("--timeout", type=int, default=15, help="per-request timeout in seconds (default 15)")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.ticker and (args.event or args.series or args.status or args.query):
        fail("usage", "--ticker fetches one exact market; it cannot combine with "
                      "--event/--series/--status/--query", "Drop --ticker or the other filters.")
    if args.limit < 1:
        fail("usage", "--limit must be >= 1")
    if args.max_pages < 1:
        fail("usage", "--max-pages must be >= 1")
    if args.timeout < 1:
        fail("usage", "--timeout must be >= 1")

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.ticker:
        payload = http_get_json("/markets/" + urllib.parse.quote(args.ticker), {}, args.timeout)
        market = payload.get("market")
        if not isinstance(market, dict):
            fail("schema", "GET /markets/{ticker} response is missing the 'market' object",
                 "The API may have changed; re-fetch docs-raw/kalshi/ and re-check.")
        endpoint = "/markets/" + args.ticker
        params = {"ticker": args.ticker}
        data = market if args.raw else trim(market)
        count = 1
    else:
        markets, server_params, scan = fetch_markets(args)
        endpoint = "/markets"
        params = dict(server_params, limit=args.limit)
        if args.query:
            params["query"] = args.query  # client-side filter, not sent to the API
        data = markets if args.raw else [trim(m) for m in markets]
        count = len(data)

    envelope = {"venue": "kalshi", "endpoint": endpoint, "params": params,
                "fetched_at": fetched_at, "count": count, "data": data}
    if not args.ticker and args.query:
        envelope["scan"] = scan
    print(json.dumps(envelope, indent=2))


if __name__ == "__main__":
    main()
