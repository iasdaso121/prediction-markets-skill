#!/usr/bin/env python3
# Part of prediction-markets-skill. Read-only. Stdlib only. Endpoints from docs-raw (see references/).
"""Cross-venue matcher v0: find Kalshi/Polymarket market pairs that look like the same question.

Kalshi has no text search (we page GET /markets status=open and filter client-side); Polymarket
candidates come from Gamma GET /public-search. Score: title Jaccard + date proximity + entities.
"""
import argparse, json, re, sys, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"  # references/kalshi-api.md
GAMMA_BASE = "https://gamma-api.polymarket.com"               # references/polymarket-api.md
# Both documented Kalshi production hosts (kalshi-api.md). Live-checked 2026-07-02: geo-blocked
# networks get a BARE 403 from external-api but an explicit CloudFront country-block page from
# api.elections - so bare 403s are corroborated via the alternate host before classifying as geo.
KALSHI_ALT_HOST = {"external-api.kalshi.com": "api.elections.kalshi.com"}
_HOST_SWAP = {}  # dead host -> working alternate; filled in when a bare-403 fallback succeeds
GEO_WORDS = re.compile(r"cloudflare|cloudfront|region|country|geo|block|restricted|not available", re.I)
USER_AGENT = "prediction-markets-skill/0.1 (+https://github.com/iasdaso121/prediction-markets-skill)"
EXIT = {"usage": 2, "network": 3, "rate-limit": 4, "geo": 5, "not-found": 6, "schema": 7}
KALSHI_PAGE_SIZE = 1000   # /markets limit max per spec
SEARCH_MAX_PAGES = 5      # /public-search page cap (runtime budget)
DATE_DECAY_DAYS = 14.0    # date score hits 0.0 when closes are >=14 days apart

STOPWORDS = frozenset(
    "a an and are as at be been before but by did do does for from had has have how if in into is it its "
    "of on or out over than that the their there this to was were what when which who whose will with yes no".split()
)
MONTHS = frozenset(
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec".split()
)


def eprint(*args):
    print(*args, file=sys.stderr)


def fail(category, message, hint):
    print(json.dumps({"error": {"category": category, "message": message, "hint": hint}}), file=sys.stderr)
    sys.exit(EXIT[category])


class Parser(argparse.ArgumentParser):
    def error(self, message):  # emit the standard JSON error line on bad usage
        fail("usage", message, "run with --help for examples")


def http_get_json(url, timeout):
    host = urllib.parse.urlsplit(url).netloc
    if host in _HOST_SWAP:  # a prior bare-403 fallback proved the alternate host works
        url = url.replace(host, _HOST_SWAP[host], 1)
        host = _HOST_SWAP[host]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(4):  # 1 try + up to 3 retries, backoff 1s/2s/4s
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            try:
                return json.loads(body)
            except ValueError:
                fail("schema", f"non-JSON response from {host}", "API may have changed; re-fetch docs-raw/")
        except urllib.error.HTTPError as e:
            try:
                body = e.read(4096).decode("utf-8", "replace")
            except OSError:
                body = ""
            if e.code in (403, 451):
                if GEO_WORDS.search(body):
                    fail("geo", f"{host} returned HTTP {e.code} (geo-blocked)",
                         "check whether your region can access this venue, or use a permitted network")
                alt = KALSHI_ALT_HOST.get(host)
                if alt:  # bare 403: corroborate via the alternate documented production host
                    eprint(f"[http] {host} bare 403; retrying via alternate documented host {alt}")
                    data = http_get_json(url.replace(host, alt, 1), timeout)
                    _HOST_SWAP[host] = alt  # only reached if the alternate succeeded
                    return data
                fail("network", f"{host} returned HTTP {e.code}", "unexpected forbidden response; retry later")
            if e.code == 404:
                fail("not-found", f"HTTP 404 from {url}", "endpoint moved? re-verify against docs-raw/")
            if e.code == 429 or e.code >= 500:
                if attempt == 3:
                    if e.code == 429:
                        fail("rate-limit", f"{host} still rate-limiting after 4 attempts", "wait and retry")
                    fail("network", f"{host} returned HTTP {e.code} after 4 attempts", "venue outage? retry later")
                delay = 2 ** attempt  # 1, 2, 4
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.isdigit():
                    delay = min(max(delay, int(ra)), 30)
                eprint(f"[http] {host} HTTP {e.code}, retrying in {delay}s (attempt {attempt + 1}/4)")
                time.sleep(delay)
                continue
            fail("network", f"{host} returned HTTP {e.code}: {body[:120]}", "unexpected status; check params")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 3:
                fail("network", f"cannot reach {host}: {e}", "check connectivity / increase --timeout")
            delay = 2 ** attempt
            eprint(f"[http] {host} error ({e}), retrying in {delay}s (attempt {attempt + 1}/4)")
            time.sleep(delay)
    return None  # unreachable


# ---------- text heuristics ----------

def tokenize(text):
    raw = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
    return {t for t in raw if t not in STOPWORDS and (len(t) > 1 or t.isdigit())}


def extract_entities(text):
    text = text or ""
    ents = set(re.findall(r"\d+(?:\.\d+)?", text))  # numbers incl. years
    lowered = re.findall(r"[a-z]+", text.lower())
    ents |= {w for w in lowered if w in MONTHS}
    # capitalized proper nouns (stopword filter drops sentence-initial "Will" etc.)
    ents |= {w.lower() for w in re.findall(r"\b[A-Z][A-Za-z]+\b", text) if w.lower() not in STOPWORDS}
    return ents


def jaccard(a, b):
    if not a and not b:
        return None  # undefined
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))  # 3.10 fromisoformat can't take "Z"
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def date_score(a, b):
    if a is None or b is None:
        return 0.5  # neutral when a date is missing
    a, b = a.astimezone(timezone.utc), b.astimezone(timezone.utc)
    if a.date() == b.date():
        return 1.0
    diff_days = abs((a - b).total_seconds()) / 86400.0
    return max(0.0, 1.0 - diff_days / DATE_DECAY_DAYS)


# ---------- venue fetchers ----------

def fetch_kalshi(query_tokens, limit, max_pages, timeout):
    """Page GET /markets?status=open and keep markets sharing >=1 query token."""
    cands, cursor, pages, scanned = [], "", 0, 0
    while pages < max_pages and len(cands) < limit:
        params = {"status": "open", "limit": KALSHI_PAGE_SIZE, "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor  # echo back verbatim, never construct
        data = http_get_json(f"{KALSHI_BASE}/markets?{urllib.parse.urlencode(params)}", timeout)
        markets = data.get("markets")
        if not isinstance(markets, list):
            fail("schema", "Kalshi /markets response missing 'markets' list", "re-verify docs-raw/kalshi/")
        pages += 1
        scanned += len(markets)
        for m in markets:
            # 'title' is deprecated in the spec but still populated; yes_sub_title is the blessed fallback
            title = m.get("title") or m.get("yes_sub_title") or m.get("ticker") or ""
            text = " ".join(filter(None, [m.get("title"), m.get("yes_sub_title")]))
            toks = tokenize(text)
            if not (query_tokens & toks):
                continue
            cands.append({
                "ticker": m.get("ticker"), "title": title, "close_time": m.get("close_time"),
                "prob": kalshi_prob(m), "tok": toks, "ents": extract_entities(text),
                "dt": parse_dt(m.get("close_time")),
            })
            if len(cands) >= limit:
                break
        cursor = data.get("cursor") or ""
        eprint(f"[kalshi] page {pages}: scanned {scanned} open markets, {len(cands)} candidates")
        if not cursor:
            break
    truncated = bool(cursor) and len(cands) < limit
    return cands, pages, truncated


def kalshi_prob(m):
    """Convenience float only; native values are fixed-point dollar STRINGS (do not mutate them)."""
    try:
        bid = float(m.get("yes_bid_dollars") or 0.0)
        ask = float(m.get("yes_ask_dollars") or 0.0)
        last = float(m.get("last_price_dollars") or 0.0)
        notional = float(m.get("notional_value_dollars") or 1.0) or 1.0  # payout denominator per docs
    except (TypeError, ValueError):
        return None
    if bid > 0.0 and ask > 0.0:
        return round(((bid + ask) / 2.0) / notional, 4)
    if last > 0.0:
        return round(last / notional, 4)
    return None


def fetch_polymarket(query, limit, timeout):
    """Gamma /public-search; events embed markets. Skip closed/archived client-side."""
    cands, seen, page, pages_fetched, has_more = [], set(), 1, 0, False
    while len(cands) < limit and page <= SEARCH_MAX_PAGES:
        params = {"q": query, "limit_per_type": min(limit, 100), "page": page}
        data = http_get_json(f"{GAMMA_BASE}/public-search?{urllib.parse.urlencode(params)}", timeout)
        if not isinstance(data, dict):
            fail("schema", "Gamma /public-search returned a non-object", "re-verify docs-raw/polymarket/")
        pages_fetched += 1
        events = data.get("events") or []
        for ev in events:
            for m in (ev.get("markets") or []):
                slug, question = m.get("slug"), m.get("question")
                if not slug or not question or slug in seen:
                    continue
                if m.get("closed") is True or m.get("archived") is True:
                    continue
                seen.add(slug)
                end = m.get("endDate") or m.get("endDateIso") or ev.get("endDate")
                text = question
                cands.append({
                    "slug": slug, "question": question, "end_date": end,
                    "prob": poly_prob(m), "tok": tokenize(text), "ents": extract_entities(text),
                    "dt": parse_dt(end),
                })
                if len(cands) >= limit:
                    break
            if len(cands) >= limit:
                break
        has_more = bool((data.get("pagination") or {}).get("hasMore"))
        eprint(f"[polymarket] search page {page}: {len(events)} events, {len(cands)} candidates")
        if not events or not has_more:
            break
        page += 1
    truncated = has_more and page > SEARCH_MAX_PAGES and len(cands) < limit  # stopped at page cap early
    return cands, pages_fetched, truncated


def poly_prob(m):
    """YES implied probability. outcomePrices is a JSON-array-encoded STRING (gotchas.md); index 0 = Yes."""
    raw = m.get("outcomePrices")
    if isinstance(raw, str) and raw:
        try:
            prices = json.loads(raw)
            if isinstance(prices, list) and prices:
                return round(float(prices[0]), 4)
        except (ValueError, TypeError):
            pass
    bb, ba = m.get("bestBid"), m.get("bestAsk")
    if isinstance(bb, (int, float)) and isinstance(ba, (int, float)) and (bb or ba):
        return round((float(bb) + float(ba)) / 2.0, 4)
    ltp = m.get("lastTradePrice")
    if isinstance(ltp, (int, float)) and ltp:
        return round(float(ltp), 4)
    return None


# ---------- pairing ----------

def score_pair(k, p):
    t = jaccard(k["tok"], p["tok"])
    t = 0.0 if t is None else t
    d = date_score(k["dt"], p["dt"])
    e = jaccard(k["ents"], p["ents"])
    e = 0.5 if e is None else e  # both entity sets empty -> neutral
    conf = 0.5 * t + 0.2 * d + 0.3 * e
    shared = sorted(k["ents"] & p["ents"])
    parts = []
    if shared:
        parts.append("shared entities: " + ", ".join(shared[:5]))
    if k["dt"] and p["dt"]:
        dd = abs((k["dt"] - p["dt"]).total_seconds()) / 86400.0
        parts.append("same-day close" if d == 1.0 else f"close dates {dd:.1f} days apart")
    else:
        parts.append("close/end date missing on one side")
    spread = None
    if k["prob"] is not None and p["prob"] is not None:
        spread = round(k["prob"] - p["prob"], 4)
    return {
        "kalshi": {"ticker": k["ticker"], "title": k["title"], "implied_probability": k["prob"],
                   "close_time": k["close_time"]},
        "polymarket": {"slug": p["slug"], "question": p["question"], "implied_probability": p["prob"],
                       "end_date": p["end_date"]},
        "confidence": round(conf, 4),
        "components": {"title": round(t, 4), "date": round(d, 4), "entities": round(e, 4)},
        "prob_spread": spread,
        "note": "; ".join(parts) or "token overlap only",
    }


def main():
    parser = Parser(
        description="Cross-venue matcher v0: pair likely-identical Kalshi and Polymarket markets for a query.",
        epilog=(
            "Runtime budget: <15s with default limits (Kalshi scan capped by --kalshi-max-pages).\n\n"
            "Examples:\n"
            '  match_markets.py --query "government shutdown"\n'
            '  match_markets.py --query "fed rate cut" --top 5 --min-confidence 0.4\n'
            '  match_markets.py --query "bitcoin price" --limit-per-venue 50 --kalshi-max-pages 3\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", required=True, help="free-text question to match across venues")
    parser.add_argument("--limit-per-venue", type=int, default=100, help="max candidate markets per venue (default 100)")
    parser.add_argument("--min-confidence", type=float, default=0.3, help="drop pairs below this confidence (default 0.3)")
    parser.add_argument("--top", type=int, default=10, help="max pairs to return (default 10)")
    parser.add_argument("--kalshi-max-pages", type=int, default=4,
                        help="max Kalshi /markets pages of 1000 to scan (default 4; runtime guard — "
                             "each page costs ~2-3s live, so 4 pages keeps default runs under ~15s)")
    parser.add_argument("--timeout", type=int, default=15, help="per-request timeout seconds (default 15)")
    args = parser.parse_args()

    if args.limit_per_venue < 1 or args.top < 1 or args.kalshi_max_pages < 1 or args.timeout < 1:
        fail("usage", "--limit-per-venue, --top, --kalshi-max-pages and --timeout must be >= 1", "see --help")
    if not 0.0 <= args.min_confidence <= 1.0:
        fail("usage", "--min-confidence must be between 0 and 1", "see --help")
    query_tokens = tokenize(args.query)
    if not query_tokens:
        fail("usage", "query contains no matchable tokens after stopword removal", "use a more specific --query")

    poly, poly_pages, p_truncated = fetch_polymarket(args.query, args.limit_per_venue, args.timeout)
    kalshi, k_pages, k_truncated = fetch_kalshi(query_tokens, args.limit_per_venue, args.kalshi_max_pages, args.timeout)
    eprint(f"[match] {len(kalshi)} kalshi x {len(poly)} polymarket candidates")

    pairs = [score_pair(k, p) for k in kalshi for p in poly]
    pairs = [pr for pr in pairs if pr["confidence"] >= args.min_confidence]
    pairs.sort(key=lambda pr: (-pr["confidence"], -pr["components"]["title"]))
    pairs = pairs[: args.top]

    caveats = ("v0 heuristic matcher (token/date/entity overlap, not semantic equivalence): verify pairs manually, "
               "including resolution rules on both venues; prob_spread ignores fees, bid/ask spread and slippage.")
    if k_truncated:
        caveats += (f" Kalshi scan stopped after {k_pages} page(s) without exhausting pagination; "
                    "matching markets may be missing - raise --kalshi-max-pages or use a more specific query.")
    if p_truncated:
        caveats += (f" Polymarket search stopped after {poly_pages} page(s) with more results available; "
                    "matching markets may be missing - use a more specific query.")
    missing = [venue for venue, c in (("Kalshi", kalshi), ("Polymarket", poly)) if not c]
    if missing:
        caveats += " No candidates found on " + " or ".join(missing) + " for this query."

    envelope = {
        "venue": "kalshi+polymarket",
        "endpoint": "kalshi:/trade-api/v2/markets + gamma:/public-search",
        "params": {"query": args.query, "limit_per_venue": args.limit_per_venue,
                   "min_confidence": args.min_confidence, "top": args.top,
                   "kalshi_pages_scanned": k_pages, "polymarket_search_pages": poly_pages},
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(pairs),
        "caveats": caveats,
        "data": pairs,
    }
    json.dump(envelope, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
