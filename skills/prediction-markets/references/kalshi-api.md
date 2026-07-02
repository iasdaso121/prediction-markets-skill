# Kalshi Trade API v2 — read-only market data

Scope: unauthenticated public market data only (markets, events, series, orderbook, candlesticks, trades). No trading/portfolio endpoints.
Source of truth: `docs-raw/kalshi/openapi.yaml` (spec v3.23.0) + `docs-raw/kalshi/llms-full.txt`, fetched 2026-07-01. Do NOT invent endpoints not listed here.

## Base URLs

| Env | URL | Notes |
|---|---|---|
| Production (recommended) | `https://external-api.kalshi.com/trade-api/v2` | Dedicated external Trade API host |
| Production (shared) | `https://api.elections.kalshi.com/trade-api/v2` | "Also supported"; despite the subdomain it serves ALL markets, not just elections |
| Demo | `https://external-api.demo.kalshi.co/trade-api/v2` | Mock funds; separate credentials; for trading tests |
| Demo (shared) | `https://demo-api.kalshi.co/trade-api/v2` | Also supported |

All four hosts returned HTTP 200 to unauthenticated `GET /markets?limit=1` at fetch time (see `docs-raw/INDEX.md`).

## Auth

No authentication is required for the endpoints in this file — docs state "no auth required for public market data" and the orderbook guide says "No authentication is required for this endpoint." Just `GET` with no headers.
Caveat: the OpenAPI spec formally lists `KALSHI-ACCESS-KEY`/`KALSHI-ACCESS-SIGNATURE`/`KALSHI-ACCESS-TIMESTAMP` security on the two orderbook endpoints, but the prose docs + live checks confirm unauthenticated access works. Everything under `/portfolio`, plus `/historical/fills`, `/historical/orders`, `/account/limits`, and `/account/api_usage_level/*`, carries that security scheme in the spec (auth required) — out of scope here. Exception: `GET /account/endpoint_costs` has NO security scheme in the spec and its auth requirement is not documented — likely account-scoped, but verify live before asserting.

## Units — read this first

- **Prices are fixed-point DOLLAR strings**, not cents: fields end in `_dollars`, e.g. `"0.5600"` = 56¢. Up to 6 decimal places (subpenny pricing).
- **Contract counts are fixed-point strings**, fields end in `_fp`, always 2 decimals in responses, e.g. `"10.00"` = 10 contracts. Min granularity 0.01.
- Legacy integer-cent price fields (`yes_bid`, `no_ask`, `last_price`, ...) and integer count fields were **removed from all REST responses on 2026-03-12** (per changelog). Do not read or emit them.
- Query timestamp params (`start_ts`, `end_ts`, `min_ts`, `min_close_ts`, ...) are **Unix seconds**. Response time fields (`created_time`, `open_time`, `close_time`, ...) are RFC3339 date-time strings; candlestick `end_period_ts` is Unix seconds.

## Ticker taxonomy

`Series → Event → Market`. Example (weather): series `KXHIGHNY` → event `KXHIGHNY-24JAN01` → market `KXHIGHNY-24JAN01-T60`.
Docs warning: there are occasional exceptions — do NOT parse ticker strings to infer relationships; rely on the `series_ticker` / `event_ticker` fields returned by the API.
- Series = recurring template (e.g. "Daily Weather in NYC"). Has `category`, `tags`, `fee_type`, `fee_multiplier`.
- Event = one occurrence; collection of markets; has `mutually_exclusive` flag.
- Market = single binary (or scalar) contract inside an event.

## Endpoints (all GET, all read-only)

| Path | Purpose |
|---|---|
| `/markets` | Paginated market list |
| `/markets/{ticker}` | Single market |
| `/markets/{ticker}/orderbook` | Order book (bids only) |
| `/markets/orderbooks` | Batch order books (up to 100 tickers) |
| `/markets/trades` | Public trades, all markets |
| `/markets/candlesticks` | Batch candlesticks (up to 100 markets) |
| `/series/{series_ticker}/markets/{ticker}/candlesticks` | Candlesticks for ONE market (needs BOTH path params) |
| `/series/{series_ticker}/events/{ticker}/candlesticks` | Event-level candlesticks (`{ticker}` = event ticker) |
| `/events` | Paginated event list (excludes multivariate) |
| `/events/{event_ticker}` | Single event |
| `/series` | Series list (NOT paginated) |
| `/series/{series_ticker}` | Single series |
| `/exchange/status` | Exchange status (no params) |
| `/historical/cutoff` | Live-vs-historical cutoff timestamps |
| `/historical/markets`, `/historical/markets/{ticker}` | Archived settled markets |
| `/historical/markets/{ticker}/candlesticks` | Candlesticks for archived markets |
| `/historical/trades` | Trades older than the cutoff |

### GET /markets — query params

| Param | Type | Notes |
|---|---|---|
| `limit` | int 0–1000, default 100 | |
| `cursor` | string | From previous response |
| `event_ticker` | string | Single event ticker only |
| `series_ticker` | string | |
| `status` | enum | `unopened`,`open`,`paused`,`closed`,`settled` (spec enum; prose lists only unopened/open/closed/settled). One status at a time |
| `tickers` | string | Comma-separated market tickers |
| `min_created_ts`,`max_created_ts` | int (Unix s) | Only with status `unopened`/`open`/empty |
| `min_close_ts`,`max_close_ts` | int (Unix s) | Only with status `closed`/empty |
| `min_settled_ts`,`max_settled_ts` | int (Unix s) | Only with status `settled`/empty |
| `min_updated_ts` | int (Unix s) | Metadata changes only; incompatible with all other filters except `mve_filter=exclude` (+`series_ticker`) |
| `mve_filter` | enum `only`,`exclude` | Multivariate (combo) events |

Timestamp filter families are mutually exclusive with each other. Settled markets older than the cutoff DO NOT appear — use `/historical/markets`.

### GET /markets/{ticker}/orderbook

- `depth` (query, optional): int 0–100, default 0; 0 = all levels.

### GET /markets/orderbooks

- `tickers` (query, REQUIRED): 1–100 market tickers, each ≤200 chars. Spec style `form`/`explode: true` (repeated `tickers=A&tickers=B`).

### GET /markets/trades

- `limit` int 0–1000 default 100; `cursor`; `ticker` (single market filter); `min_ts`, `max_ts` (Unix s); `is_block_trade` bool (omit = all, true = only block, false = only non-block).

### GET /series/{series_ticker}/markets/{ticker}/candlesticks

Path params: BOTH `series_ticker` AND `ticker` (market ticker) are required.
Query (all required except last): `start_ts` (Unix s; includes candles ending ≥ start), `end_ts` (Unix s; includes candles ending ≤ end), `period_interval` — minutes, ONLY `1`, `60`, or `1440`; `include_latest_before_start` bool default false (prepends synthetic candle: OHLC null, `previous_price` = prior close).

### GET /markets/candlesticks (batch)

`market_tickers` comma-separated string (max 100); `start_ts`, `end_ts` (Unix s, required); `period_interval` int minutes, min 1 (no enum in spec for this endpoint); `include_latest_before_start`. Returns ≤10,000 candlesticks total across all markets, grouped per market.

### GET /series/{series_ticker}/events/{ticker}/candlesticks

`{ticker}` here is the EVENT ticker. Query: `start_ts`, `end_ts`, `period_interval` (1|60|1440) — all required. Returns per-market candle arrays aggregated for the event + `adjusted_end_ts` (end is clamped if the range is too large).

### GET /events — query params

`limit` int 1–200, **default 200, max 200** (smaller than /markets!); `cursor`; `status` (`unopened`,`open`,`closed`,`settled`); `series_ticker`; `tickers` (comma-separated event tickers); `with_nested_markets` bool default false (true = each event embeds `markets[]`; nested markets exclude pre-cutoff settled ones); `with_milestones` bool; `min_close_ts`, `min_updated_ts` (Unix s). Events are ALWAYS available here regardless of the historical cutoff.

### GET /events/{event_ticker}

`with_nested_markets` bool default false — false: markets come back as a separate top-level `markets` field; true: embedded in the event object.

### GET /series and /series/{series_ticker}

`/series` filters: `category` (single), `tags`, `include_product_metadata` bool, `include_volume` bool, `min_updated_ts`. **No limit/cursor in the spec — response is not paginated.**
`/series/{series_ticker}`: `include_volume` bool.

### Historical variants

- `/historical/cutoff` → `market_settled_ts`, `trades_created_ts`, `orders_updated_ts` — all three are RFC3339 date-time STRINGS despite the `_ts` suffix (spec `format: date-time`), NOT Unix seconds. Live window target: 3 months; cutoffs advance over time.
- `/historical/markets`: `limit` (0–1000), `cursor`, `tickers`, `event_ticker`, `series_ticker`, `mve_filter` (`exclude` only). Filters mutually exclusive.
- `/historical/markets/{ticker}/candlesticks`: `start_ts`, `end_ts`, `period_interval` (1|60|1440), all required. NOTE: historical candles use a different schema: OHLC fields inside `yes_bid`/`yes_ask`/`price` are named `open`/`low`/`high`/`close` (dollar strings, NO `_dollars` suffix) and counts are named `volume`/`open_interest` (fixed-point count strings, NO `_fp` suffix) — same string encodings as live candles, different field names; `end_period_ts` is still Unix seconds (int64).
- `/historical/trades`: same filters as `/markets/trades` (`ticker`, `min_ts`, `max_ts`, `limit`, `cursor`, `is_block_trade`).

## Pagination (cursor-based)

List endpoints return a `cursor` field. Empty/missing cursor = last page. `limit` default 100. Pattern:

```
# Request 1
GET /trade-api/v2/markets?series_ticker=KXHIGHNY&limit=100
→ { "markets": [ ...100 items... ], "cursor": "CgoyMDI0LTAxLTAx" }

# Request 2 — pass cursor back verbatim
GET /trade-api/v2/markets?series_ticker=KXHIGHNY&limit=100&cursor=CgoyMDI0LTAxLTAx
→ { "markets": [ ...remaining... ], "cursor": "" }   # empty → stop
```

Never construct cursors; only echo the value from the previous response.

## Response shapes (key fields + units)

### Market (`GET /markets` → `{markets:[], cursor}`; `GET /markets/{t}` → `{market}`)

```
ticker, event_ticker            string
market_type                     "binary" | "scalar"
status                          initialized|inactive|active|closed|determined|disputed|amended|finalized
                                (NB: response enum differs from the status QUERY filter values!)
yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars,
last_price_dollars, previous_price_dollars, notional_value_dollars,
settlement_value_dollars        dollar strings, e.g. "0.5600"
yes_bid_size_fp, yes_ask_size_fp, volume_fp, volume_24h_fp,
open_interest_fp                count strings, e.g. "10.00"
open_time, close_time, created_time, updated_time, latest_expiration_time,
expected_expiration_time, settlement_ts   RFC3339 strings
result                          "yes" | "no" | "scalar" | ""
can_close_early                 bool
floor_strike, cap_strike        number (settlement thresholds)
strike_type                     greater|greater_or_equal|less|less_or_equal|between|functional|custom|structured
rules_primary, rules_secondary  strings (plain-language terms)
price_level_structure, price_ranges   tick-size / valid price range info
liquidity_dollars               DEPRECATED, always "0.0000"
title, subtitle                 DEPRECATED (use yes_sub_title / no_sub_title)
```

### Orderbook (`GET /markets/{t}/orderbook` → `{orderbook_fp}`)

```
{ "orderbook_fp": {
    "yes_dollars": [ ["0.0100","200.00"], ..., ["0.4200","13.00"] ],
    "no_dollars":  [ ["0.0100","100.00"], ..., ["0.5600","17.00"] ] } }
```
- Each level = `[price_dollars_string, contract_count_fp_string]` — second element is quantity, NOT price.
- BIDS ONLY, both sides (a yes bid at $X ≡ a no ask at $(1−X); docs phrase it in cents: yes bid 7¢ = no ask 93¢). No asks are returned.
- Sorted ascending by price; **best bid is the LAST element**.
- Batch endpoint returns `{orderbooks: [{ticker, orderbook_fp}, ...]}`.

### Candlestick (`GET /series/{s}/markets/{t}/candlesticks` → `{ticker, candlesticks:[]}`)

```
end_period_ts        Unix seconds (inclusive end of period)
yes_bid, yes_ask     { open_dollars, low_dollars, high_dollars, close_dollars }  dollar strings
price                { open/low/high/close/mean/previous_dollars }  dollar strings, null if no trade in period
volume_fp            contracts traded in period (count string)
open_interest_fp     contracts open at end_period_ts (count string)
```
Batch response: `{markets: [{market_ticker, candlesticks:[]}]}`. Event response: `{market_tickers:[], market_candlesticks:[[...]], adjusted_end_ts}`.

### Trade (`GET /markets/trades` → `{trades:[], cursor}`)

```
trade_id, ticker         strings
count_fp                 contracts (count string)
yes_price_dollars, no_price_dollars   dollar strings
taker_outcome_side       "yes"|"no" (canonical; buy-yes & sell-no → "yes")
taker_book_side          "bid"|"ask" (bid ≡ outcome yes)
taker_side               "yes"|"no"  DEPRECATED — prefer the two above
created_time             RFC3339
is_block_trade           bool (block trades included by default)
```

## Historical vs live routing

Live endpoints silently drop old data. Before backfilling: `GET /historical/cutoff`; anything settled/filled before the relevant cutoff must come from `/historical/*` or it will simply be missing from live responses.

## Rate limits (as documented)

- Documented for **authenticated** requests: token buckets, Read + Write budgets refill per second. Default cost **10 tokens/request**; `GET /account/endpoint_costs` lists non-default costs (its own auth requirement is undocumented — the spec defines no security scheme for it).
- Tier read budgets (tokens/s): Basic 200, Advanced 300, Expert 600, Premier 1,000, Paragon 2,000, Prime 4,000, Prestige 6,000. Basic ⇒ ~20 default reads/s sustained.
- On limit: `429` with body `{"error": "too many requests"}`; **no `Retry-After` or `X-RateLimit-*` headers**; no cooldown penalty — use exponential backoff.
- Limits for UNAUTHENTICATED requests: not documented. Assume the same order of magnitude and back off on 429.
- Scheduled maintenance: Thursdays 03:00–05:00 ET (trading pause; expect disconnections).

## Verify before use

This file was distilled from `docs-raw/kalshi/` fetched 2026-07-01. Kalshi ships breaking changes on announced dates (e.g. legacy cents-field removal 2026-03-12). If behavior disagrees with this file, or >~1 month has passed, re-download `llms-full.txt` + `openapi.yaml` into `docs-raw/kalshi/` (see `docs-raw/kalshi/MANIFEST.md` for sources) and re-check: field units (`_dollars`/`_fp`), param limits, and the `/historical` cutoff behavior.
