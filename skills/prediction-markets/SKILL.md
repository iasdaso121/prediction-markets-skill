---
name: prediction-markets
description: Use for anything involving Kalshi or Polymarket prediction-market data: getting current odds, implied probabilities, or prices for an event; pulling orderbooks, spreads, liquidity/depth, midpoint prices, or price history; discovering markets by topic; or comparing the same event's price across the two venues. ALSO use whenever the user wants to write or run code (a script, cron job, dashboard feed, JSON endpoint) that fetches Kalshi/Polymarket data by slug, ticker, or CLOB token id — the skill's bundled scripts and API references replace guessing endpoints. And use for "what are the odds/probability of X" (elections, Fed/rates, econ, weather-temperature, crypto, sports outcomes) even with no venue named. Read-only, no keys, no trading, Python stdlib. Do NOT use for placing bets or authenticated order/trading APIs.
---

# Prediction Markets (Kalshi + Polymarket) — read-only market data

Everything here is read-only public data. No auth, no keys, no trading. All scripts:
Python 3.10+ stdlib only, run as `python3 scripts/<name>.py …` or directly (executable).

## Script routing

| You need | Run | Notes |
|---|---|---|
| Find Kalshi markets (by text, event, series, status) | `scripts/kalshi_markets.py --query "cpi" --series KXCPI` | `--ticker T` for one market. Kalshi has NO server-side text search: bare `--query` scans up to `--max-pages`×1000 markets (~5s/page) and reports truncation in the output's `scan` object — narrow with `--series`/`--event` whenever you can |
| Kalshi orderbook, spread, depth | `scripts/kalshi_orderbook.py TICKER --depth 10` | asks derived from opposite bids (see gotchas) |
| Kalshi price history (OHLC) | `scripts/kalshi_candles.py TICKER --period 60 --start 2026-07-01` | `--period` ∈ {1,60,1440} min; auto-resolves series (2 extra GETs) |
| Find Polymarket markets | `scripts/poly_markets.py --query "fed" --active` | `--slug S` for one market; full-text via Gamma /public-search |
| Polymarket orderbook, spread, midpoint | `scripts/poly_orderbook.py --slug market-slug` | or `--token-id N`; `--outcome no` for the NO token |
| Polymarket price history | `scripts/poly_history.py --slug market-slug --interval 1w` | or `--start/--end`; points are `{t, iso, p}` |
| Same event on both venues + spread | `scripts/match_markets.py --query "fed december"` | v0 heuristic matcher — verify pairs manually |

Every script: `--help` has 3+ runnable examples; `--timeout` (default 15s); retries 429/5xx
with 1s/2s/4s backoff; paginates to exhaustion or `--limit`.

## Output contract (all scripts)

stdout = single JSON: `{"venue", "endpoint", "params", "fetched_at", "count", "data"}`.
Errors: one JSON line on stderr `{"error": {"category", "message", "hint"}}` + exit code:
`2` usage · `3` network · `4` rate-limited · `5` geo-blocked · `6` not found · `7` schema surprise.
Exit 0 with `count: 0` = valid empty result (e.g. no matches), not an error.

## Workflows

### "What's the probability of X?"
1. `kalshi_markets.py --query "X" --status open` and/or `poly_markets.py --query "X" --active`.
2. Each row already carries `implied_probability` (float 0–1, from bid/ask midpoint or last).
3. Quote it as a percentage; name the market title and venue. If several markets match
   (different thresholds/dates), list them — don't silently pick one.

### "How liquid is it / what's the real cost to trade?"
1. Get the market: discovery scripts above → ticker (Kalshi) or slug/token_id (Polymarket).
2. `kalshi_orderbook.py TICKER` / `poly_orderbook.py --slug S` → `summary` has best bid/ask,
   `spread`, `midpoint`, `implied_probability`, depth totals.
3. Wide spread or thin depth = the midpoint probability is soft. Say so.

### "Compare venues / is there a price gap?"
1. `match_markets.py --query "topic" --top 5`.
2. Each pair reports `confidence` (0–1, components: title/date/entities) and `prob_spread`.
   The matcher canonicalizes common aliases (Fed=FOMC, NYC=New York=KNYC, BTC=Bitcoin,
   Cavs=Cleveland, $60k=60000) before scoring, but it is still a v0 heuristic.
3. Treat `confidence < 0.7` pairs as suggestions — read both titles yourself and check the
   markets resolve on the SAME criterion and date before claiming a price gap.
4. Raw `prob_spread` ignores fees and slippage — read `references/market-mechanics.md`
   (fees section) before calling anything an edge. This skill does not trade.

### Weather / temperature markets (Kalshi)
Kalshi weather markets live under series like `KXHIGH<CITY>` (e.g. `KXHIGHNY` = NYC daily
high, `KXHIGHLAX`, `KXHIGHCHI`). There is no text search, and scanning all markets for
"temperature" is slow — go through the series instead:
1. `kalshi_markets.py --series KXHIGHNY --status open` → today's/tomorrow's temperature buckets.
2. A day's high is split into mutually-exclusive buckets (e.g. `-B98.5`, `-B100.5`, `-T105`).
   To answer "P(high > 99°)", `kalshi_markets.py --event KXHIGHNY-26JUL04` returns ALL buckets
   of that event — sum the `implied_probability` of the buckets above the threshold.
3. Don't pick one bucket and call it the answer; the buckets partition the outcome space.

### Multi-contract events (sports, ranges) — use `--event`, not `--query`
One game or event is many contracts (moneyline, spread, totals; or temperature buckets), each
its own ticker. To get them all: find the `event_ticker` from any one market, then
`kalshi_markets.py --event <EVENT_TICKER>` returns every market in that event. `--query` alone
scans the whole universe slowly and may miss them — the event listing is exact and fast.

## References — read before deviating from the scripts

- `references/kalshi-api.md` — read when writing ANY custom Kalshi call: base URLs, no-auth
  endpoints, cursor pagination, dollar-string units (`*_dollars`, `*_fp`), rate limits.
- `references/polymarket-api.md` — read when writing ANY custom Polymarket call: Gamma vs
  CLOB vs data-api split, question→tokenId resolution, pagination differences.
- `references/market-mechanics.md` — read before doing probability/fee/settlement math or
  interpreting negRisk multi-outcome events.
- `references/gotchas.md` — read FIRST when an API call fails or numbers look wrong.
  Known traps: prices are strings, cents-era fields are gone, tokenId ≠ slug, wordless
  Kalshi geo-403, `/midpoint` returns `mid` not `mid_price`.

## Known constraints

- Kalshi production hosts geo-block some non-US regions with an unlabeled 403 (exit 5 from
  the scripts). Demo hosts (`external-api.demo.kalshi.co`) usually remain reachable for
  smoke tests; data there is not production data. Polymarket public data has shown no
  geo-blocking.
- Endpoints came from live docs snapshotted in `docs-raw/` (2026-07-01). If a script starts
  returning `schema` errors (exit 7), the API changed: re-fetch docs before "fixing" code.
- Educational/research tooling. Not financial advice. No order execution exists here.
