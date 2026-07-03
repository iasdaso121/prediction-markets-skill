#!/usr/bin/env python3
# Part of prediction-markets-skill. Read-only. Stdlib only. Endpoints from docs-raw (see references/).
"""Polymarket price history via CLOB GET /prices-history.

Resolves --slug through Gamma (market slug first, then event slug) to a
token_id, then fetches the price timeseries. Timestamps are Unix SECONDS
(gotchas.md); `interval` values are windows relative to now (1m = one MONTH)
and are mutually exclusive with --start/--end; `fidelity` is minutes.
"""

import argparse
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
USER_AGENT = "prediction-markets-skill/0.1 (+https://github.com/azazelitto21/prediction-markets-skill)"
EXIT_CODES = {"usage": 2, "network": 3, "rate-limit": 4, "geo": 5, "not-found": 6, "schema": 7}
GEO_WORDS = ("cloudflare", "region", "blocked", "restricted", "geo", "unavailable in your country")

EPILOG = """Examples:
  poly_history.py --slug will-jesus-christ-return-before-gta-vi-665 --interval 1w --fidelity 60
  poly_history.py --slug new-rhianna-album-before-gta-vi-926 --outcome no --interval 1d
  poly_history.py --token-id 90435811253665578014957380826505992530054077692143838383981805324273750424057 --interval 6h --limit 50
  poly_history.py --slug new-playboi-carti-album-before-gta-vi-421 --start 2026-06-01T00:00:00Z --end 2026-06-15T00:00:00Z --fidelity 1440

Notes:
  --interval windows are relative to now: 1m = last MONTH (not minute), 1w, 1d, 6h, 1h, all, max.
  --start/--end take ISO 8601 (assumed UTC if no offset) or Unix seconds; exclusive with --interval.
  --fidelity is the resolution in minutes (server default 1).
  --limit keeps only the most recent N points (0 = keep all); summary covers the full fetched range.
  With --start/--end the live API appends an extra point at "now" beyond --end (spec says --end
  bounds the range); this script drops points past --end so summary "last" is the price at --end.
"""


def log(msg):
    print(msg, file=sys.stderr)


def fail(category, message, hint=""):
    err = {"error": {"category": category, "message": message, "hint": hint}}
    print(json.dumps(err), file=sys.stderr)
    sys.exit(EXIT_CODES[category])


class Parser(argparse.ArgumentParser):
    def error(self, message):  # emit the shared JSON error envelope on usage errors
        self.print_usage(sys.stderr)
        fail("usage", message, "See --help for runnable examples.")


def http_get_json(base, path, params, timeout, ok404=False):
    """GET JSON with 4 attempts on 429/5xx (backoff 1s/2s/4s, honor Retry-After)."""
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    host = urllib.parse.urlparse(base).netloc
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    backoff = [1, 2, 4]
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            try:
                return json.loads(body)
            except ValueError:
                fail("schema", "non-JSON response from %s%s" % (host, path),
                     "The endpoint replied 200 with a non-JSON body; re-check the URL against references/polymarket-api.md.")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            status = e.code
            if status == 404:
                if ok404:
                    return None
                fail("not-found", "%s%s returned 404" % (host, path),
                     "Check the slug/token id; slugs resolve only on Gamma, token ids only on CLOB.")
            if status in (403, 451):
                low = body.lower()
                if any(w in low for w in GEO_WORDS):
                    fail("geo", "%s appears to geo-block this request (HTTP %d)" % (host, status),
                         "Polymarket blocks some regions; check your region/VPN and try again.")
                fail("network", "%s%s returned HTTP %d" % (host, path, status), body[:200])
            if status == 400:
                fail("usage", "%s%s rejected the request (HTTP 400): %s" % (host, path, body[:200]),
                     "Check parameter values (token id, timestamps in Unix seconds, interval enum).")
            if status == 429 or status >= 500:
                if attempt < 3:
                    delay = backoff[attempt]
                    retry_after = e.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, int(retry_after))
                    log("HTTP %d from %s, retrying in %ds (attempt %d/4)" % (status, host, delay, attempt + 2))
                    time.sleep(delay)
                    continue
                if status == 429:
                    fail("rate-limit", "%s still rate-limiting after 4 attempts" % host,
                         "CLOB /prices-history allows 1000 req/10s; slow down and retry later.")
                fail("network", "%s%s returned HTTP %d after 4 attempts" % (host, path, status), body[:200])
            fail("network", "%s%s returned unexpected HTTP %d" % (host, path, status), body[:200])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            fail("network", "request to %s failed: %s" % (host, e),
                 "Check connectivity/DNS; increase --timeout if the network is slow.")
    fail("network", "exhausted retries against %s" % host, "")


def parse_when(value, flag):
    """ISO 8601 or Unix seconds -> Unix seconds (int)."""
    if re.fullmatch(r"\d+", value):
        return int(value)
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("usage", "%s: cannot parse %r as ISO 8601 or Unix seconds" % (flag, value),
             "Examples: 1750000000, 2026-06-01, 2026-06-01T00:00:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


def pick_token(market, outcome):
    """Extract Yes/No token_id from a Gamma market. clobTokenIds is a JSON-encoded STRING (gotchas.md)."""
    raw = market.get("clobTokenIds")
    if not raw:
        fail("schema", "market %r has no clobTokenIds" % market.get("slug"),
             "The market may not be CLOB-tradable; check enableOrderBook on Gamma.")
    try:
        ids = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        fail("schema", "clobTokenIds is not parseable JSON: %r" % raw[:80], "")
    if not isinstance(ids, list) or len(ids) < 2:
        fail("schema", "clobTokenIds has unexpected shape: %r" % ids,
             "Expected a 2-element list [yes_token, no_token].")
    return ids[0] if outcome == "yes" else ids[1]


def resolve_slug(slug, outcome, timeout):
    """Slug -> (token_id, metadata). Tries Gamma market slug, then event slug."""
    log("resolving slug %r via Gamma..." % slug)
    market = http_get_json(GAMMA, "/markets/slug/" + urllib.parse.quote(slug), {}, timeout, ok404=True)
    if market is None:
        event = http_get_json(GAMMA, "/events/slug/" + urllib.parse.quote(slug), {}, timeout, ok404=True)
        if event is None:
            fail("not-found", "no Gamma market or event with slug %r" % slug,
                 "Slug is the path segment after /event/ in polymarket.com URLs; try /public-search.")
        markets = event.get("markets") or []
        if len(markets) != 1:
            candidates = ", ".join(m.get("slug", "?") for m in markets[:10])
            fail("usage", "event %r has %d markets; pass a market slug or --token-id" % (slug, len(markets)),
                 "Market slugs in this event: %s" % (candidates or "none"))
        market = markets[0]
    token_id = pick_token(market, outcome)
    log("resolved to token_id %s... (%s, outcome=%s)" % (token_id[:16], market.get("question"), outcome))
    return token_id, {
        "slug": market.get("slug"),
        "question": market.get("question"),
        "condition_id": market.get("conditionId"),
        "gamma_market_id": market.get("id"),
    }


def summarize(points):
    if not points:
        return {"first": None, "last": None, "min": None, "max": None}
    prices = [pt["p"] for pt in points]
    return {
        "first": round(points[0]["p"], 4),
        "last": round(points[-1]["p"], 4),
        "min": round(min(prices), 4),
        "max": round(max(prices), 4),
    }


def main():
    parser = Parser(
        description="Fetch Polymarket price history (0-1 probabilities) for one outcome token "
                    "from the CLOB /prices-history endpoint. Read-only, no auth.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--token-id", help="CLOB token id (huge decimal string) — used as the 'market' param")
    src.add_argument("--slug", help="Gamma market or single-market event slug to resolve to a token id")
    parser.add_argument("--outcome", choices=["yes", "no"], default="yes",
                        help="which outcome token when resolving --slug (default: yes)")
    parser.add_argument("--interval", choices=["max", "all", "1m", "1w", "1d", "6h", "1h"],
                        help="window relative to now (1m = last MONTH); exclusive with --start/--end; "
                             "default 1d when no range is given")
    parser.add_argument("--start", help="range start: ISO 8601 or Unix seconds")
    parser.add_argument("--end", help="range end: ISO 8601 or Unix seconds")
    parser.add_argument("--fidelity", type=int, help="resolution in minutes (server default 1)")
    parser.add_argument("--limit", type=int, default=100,
                        help="keep only the most recent N points, 0 = all (default: 100)")
    parser.add_argument("--timeout", type=int, default=15, help="per-request timeout, seconds (default: 15)")
    args = parser.parse_args()

    if args.interval and (args.start or args.end):
        fail("usage", "--interval and --start/--end are mutually exclusive (per CLOB docs)",
             "Use either a relative window or an absolute timestamp range, not both.")
    if args.fidelity is not None and args.fidelity <= 0:
        fail("usage", "--fidelity must be a positive number of minutes", "")
    if args.limit < 0:
        fail("usage", "--limit must be >= 0", "")
    if args.token_id and args.outcome != "yes":
        log("note: --outcome is ignored with --token-id (the token already identifies the outcome)")

    resolved = None
    token_id = args.token_id
    if args.slug:
        token_id, resolved = resolve_slug(args.slug, args.outcome, args.timeout)

    params = {"market": token_id}
    if args.start:
        params["startTs"] = parse_when(args.start, "--start")
    if args.end:
        params["endTs"] = parse_when(args.end, "--end")
    if "startTs" in params and "endTs" in params and params["startTs"] >= params["endTs"]:
        fail("usage", "--start must be earlier than --end", "")
    if not args.start and not args.end:
        params["interval"] = args.interval or "1d"
    if args.fidelity is not None:
        params["fidelity"] = args.fidelity

    # Live-vs-spec (observed 2026-07-02, verified against direct curl): when startTs/endTs are
    # used, the live API appends one extra trailing point at "now", beyond endTs, although the
    # spec says endTs bounds the range. Spec wins: points past endTs are dropped below so that
    # summary "last" is the price at --end, not the current price.
    log("GET %s/prices-history %s" % (CLOB, json.dumps(params)))
    payload = http_get_json(CLOB, "/prices-history", params, args.timeout)
    history = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(history, list):
        fail("schema", "expected {'history': [...]} from /prices-history, got: %s" % str(payload)[:200],
             "The CLOB response shape changed; re-check docs-raw/polymarket/clob-openapi.yaml.")

    if not history and args.token_id:
        # CLOB returns 200 {"history": []} for nonexistent tokens. Disambiguate not-found from
        # valid-token-with-no-trades via the documented reverse lookup GET /markets-by-token/{token_id}
        # (docs-raw/polymarket/clob-openapi.yaml: 404 = market not found for token).
        log("empty history; checking token via GET %s/markets-by-token/..." % CLOB)
        lookup = http_get_json(CLOB, "/markets-by-token/" + urllib.parse.quote(args.token_id),
                               {}, args.timeout, ok404=True)
        if not lookup:
            fail("not-found", "no CLOB market for token id %s" % args.token_id,
                 "Token ids come from Gamma clobTokenIds; a valid token with no trades still "
                 "resolves via /markets-by-token.")
        log("token resolves on CLOB; returning empty history (no trades in the requested range)")

    points = []
    for pt in history:
        try:
            t = int(pt["t"])  # Unix SECONDS per spec (uint32) — not milliseconds
            p = float(pt["p"])  # 0-1 probability; float() guards string-vs-number drift (gotchas.md)
        except (KeyError, TypeError, ValueError):
            fail("schema", "unexpected history point shape: %r" % (pt,), "Expected {'t': seconds, 'p': 0-1}.")
        points.append({"t": t, "iso": datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%SZ"), "p": p})

    if "endTs" in params:  # drop the live API's trailing "now" point(s) past endTs (see comment above)
        kept = [pt for pt in points if pt["t"] <= params["endTs"]]
        if len(kept) < len(points):
            log("dropped %d point(s) after endTs appended by the live API beyond the spec'd range"
                % (len(points) - len(kept)))
            points = kept

    summary = summarize(points)  # over the FULL fetched range, before --limit truncation
    summary["points_total"] = len(points)
    if args.limit and len(points) > args.limit:
        log("truncating %d points to the most recent %d (--limit)" % (len(points), args.limit))
        points = points[-args.limit:]
    summary["points_returned"] = len(points)

    result = {
        "venue": "polymarket",
        "endpoint": "/prices-history",
        "params": params,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(points),
        "data": {
            "token_id": token_id,
            "outcome": args.outcome if args.slug else None,
            "resolved": resolved,
            "summary": summary,
            "points": points,
        },
    }
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
