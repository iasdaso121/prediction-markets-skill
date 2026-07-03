# Gotchas — Kalshi + Polymarket market data

Verified against `docs-raw/` (fetched 2026-07-01). Every value below is from the downloaded specs/docs — never memory — except values marked live-checked, where the live API contradicts the spec and the live behavior is documented instead.

## Kalshi prices are fixed-point dollar STRINGS, not integer cents
WHEN: Reading prices from `GET /markets`, `/markets/{ticker}/orderbook`, candlesticks.
WRONG: `price = market["yes_bid"] / 100` — assuming integer cents 1-99.
RIGHT: Current spec (v3.23.0) required fields are `_dollars` strings: `"yes_bid_dollars": "0.4200"`. Orderbook levels are `["0.4200", "13.00"]` = `[price_dollars, count_fp]`. Parse with Decimal; `_fp` contract counts are strings too (docs tip: multiply by 100, cast to int).
GOTCHA: Models remember Kalshi's old integer-cent API. Cent fields survive only in legacy/portfolio schemas (`amount_cents`, order "price in cents") and `response_price_units: usd_cent` is deprecated. `_dollars` strings carry up to 4 decimals (max 6); tick size can be $0.001 (`deci_cent` / `tapered_deci_cent` price_level_structure).

## Polymarket prices are 0-1 decimals — with mixed JSON types
WHEN: Reading CLOB `/price`, `/midpoint`, `/book`, or Gamma market fields.
WRONG: Dividing by 100, multiplying by 100 "to get percent", dispatching on the spec-declared JSON type, or reading `data["mid_price"]` because the spec says so (KeyError on every live response).
RIGHT: All prices are 0-1 decimals. Live-checked 2026-07-02: `/price` → `{"price": "0.51"}` — a STRING even though the spec declares `type: number`; `/midpoint` → `{"mid": "0.52"}` (string) — the live key is `mid`, though the spec declares required `mid_price`. Read `data.get("mid") or data.get("mid_price")` defensively, and parse every price field via `Decimal(str(x))` regardless of declared type. `/book` bids/asks: price and size are strings. Gamma `bestBid`/`bestAsk`/`lastTradePrice`: numbers; `outcomePrices`: a stringified array.
GOTCHA: The downloaded CLOB spec is stale on both price endpoints (wrong type for `/price`, wrong key for `/midpoint`) — do not trust spec-declared response types/keys on CLOB price endpoints without a live check. Kalshi `"0.4200"` and Polymarket `"0.42"` are the same scale (dollars/probability). Neither API returns percent. String-vs-number varies per endpoint on the same host.

## Both venues charge fees — never skip them in edge/arb math
WHEN: Computing expected value or cross-venue arbitrage.
WRONG: `edge = kalshi_yes - poly_yes`; "Polymarket has no trading fees"; reciting a Kalshi fee formula from memory.
RIGHT: Polymarket taker fee (fee-enabled markets): `fee = C × feeRate × p × (1 − p)` in USDC, C = shares, p = price. Taker rates by category: Crypto 0.07; Sports 0.03; Finance/Politics/Mentions/Tech 0.04; Economics/Culture/Weather/Other 0.05; Geopolitics 0. Makers are never charged. Check `feesEnabled` on the market; query params via `GET /clob-markets/{condition_id}` or `GET /fee-rate?token_id=`. Kalshi: per-series `fee_type` (`quadratic` | `quadratic_with_maker_fees` | `flat`) + `fee_multiplier` from `GET /series/{series_ticker}`; scheduled changes `GET /series/fee_changes`; event-level overrides `GET /events/fee_changes` (null overrides = cleared). Per fill: trade fee is ceiled to the nearest $0.0001; net fee = trade fee + rounding fee − rebate.
GOTCHA: "Polymarket is fee-free" is outdated training data — only Geopolitics is fee-free now. The `0.07 · p · (1−p)` formula models attribute to Kalshi is documented here as Polymarket's Crypto rate; Kalshi's actual fee tables live in an external PDF (kalshi-fee-schedule.pdf) and are NOT in the API docs — do not invent them.

## Cursor pagination: the first page is never "all markets"
WHEN: Listing markets, events, or trades on either venue.
WRONG: One `GET /markets` call, then treating the result as the complete universe.
RIGHT: Kalshi limit bounds vary per endpoint — `/markets` and `/markets/trades`: 1-1000 (default 100); `/events`: max 200 (default 200); multivariate events listing: max 200 (default 100) — check the spec for each. Pass the returned `cursor` back until it comes back empty ("An empty cursor indicates no more pages are available"). Polymarket CLOB: pass `next_cursor` back until it equals `"LTE="` (documented last-page marker; cursor is a base64-encoded offset).
GOTCHA: Both APIs return a plausible-looking full page plus a cursor field; ignoring the cursor produces no error, just silently truncated data (Kalshi default page = only 100 markets).

## Gamma paginates with limit+offset; CLOB with next_cursor — don't mix
WHEN: Paginating Polymarket endpoints.
WRONG: `gamma-api.polymarket.com/markets?next_cursor=MTAw` or `clob.polymarket.com/sampling-simplified-markets?offset=100`.
RIGHT: Gamma `/markets` and `/events` take `limit` + `offset` (integers, min 0; no documented max) and return a bare JSON array — no envelope, no cursor, no total. CLOB list endpoints take only `next_cursor`. (Gamma also has separate `/markets/keyset` and `/events/keyset` variants: pass each response's `next_cursor` as `after_cursor`; `offset` returns 422 if provided at all. Their `limit` has real caps — 100 on `/markets/keyset`, 500 on `/events/keyset`, default 20 — unlike plain `/markets`/`/events`.)
GOTCHA: Same company, different pagination per host. Gamma's bare-array response has no field to hint that more pages exist; you stop when a page comes back short/empty.

## Polymarket token_id is not a ticker, slug, or condition_id
WHEN: Calling CLOB `/book`, `/price`, `/midpoint`, `/prices-history`.
WRONG: `/book?token_id=will-x-win-2028` (slug), passing a `0x…` condition_id as token_id, or `market.clobTokenIds[0]` without parsing.
RIGHT: token_id (aka asset id) is a huge numeric string. Source it from Gamma market `clobTokenIds` — declared `type: string` (nullable) in the Gamma spec, i.e. a JSON-encoded array you must `json.loads` first; element [0] = Yes token, [1] = No token. Reverse lookup: `GET /markets-by-token/{token_id}`. condition_id is only for `GET /clob-markets/{condition_id}`. Slugs resolve only on Gamma (`/markets/slug/{slug}`, `/events/slug/{slug}`).
GOTCHA: `clobTokenIds` prints like an array but is a string — indexing without parsing yields `"["`. `outcomePrices` has the same stringified-array trap.

## clobTokenIds order is NOT guaranteed [Yes, No] — match by outcome LABEL
WHEN: Picking the Yes (or No) token for CLOB `/book`, `/price`, `/midpoint` from a Gamma market.
WRONG: `yes_token = clobTokenIds[0]` — assuming index 0 is always Yes.
RIGHT: `clobTokenIds[i]` corresponds to `outcomes[i]`; parse BOTH stringified arrays, find the index where `outcomes[i].lower() == "yes"`, then take `clobTokenIds[i]`. Only fall back to index 0=Yes / 1=No when the market has no `outcomes` labels at all. (This is what `poly_orderbook.py` does.)
GOTCHA: Most binary markets happen to store `[Yes, No]`, so position-based code works until it silently hits a market stored `[No, Yes]` and returns the opposite side's book — the root of py-clob-client issue #276. Positional indexing looks correct in testing and fails in production.

## negRisk events: visible YES prices are not the whole probability mass
WHEN: Summing YES prices across a multi-outcome event or hunting "sum ≠ $1" arbs.
WRONG: Assuming the listed markets are the complete outcome set and their YES prices must sum to ~1.00.
RIGHT: Check the `negRisk` boolean on Gamma events/markets (per-token: `GET /neg-risk?token_id=`). Augmented neg risk (`enableNegRisk: true` + `negRiskAugmented: true`) events include placeholder outcomes and an explicit "Other" that the Polymarket UI does not display; docs say to trade only named outcomes. Mechanics: 1 No share in any market converts to 1 Yes in every other market via the Neg Risk Adapter.
GOTCHA: The "YES + NO sum to $1.00" identity is documented for a single binary market (Kalshi orderbook docs). For augmented neg-risk events, undisplayed placeholder/Other outcomes hold probability mass, so named-outcome YES sums legitimately fall short of 1.00 — that gap is not free money.

## Timestamps: Unix SECONDS vs ISO strings, and three spellings
WHEN: Candlesticks, price history, or date-filtered listings.
WRONG: Passing `Date.now()` (milliseconds) or ISO strings to `*_ts` params; passing epoch seconds to Gamma date filters.
RIGHT: Kalshi `start_ts`/`end_ts` and `min_*_ts`/`max_*_ts` filters: Unix timestamps in seconds (int64); Kalshi `*_time` fields (`open_time`, `close_time`, …) are RFC3339 date-time strings. CLOB `GET /prices-history`: `startTs`/`endTs` (camelCase, Unix); `POST /batch-prices-history`: `start_ts`/`end_ts` (snake_case, "unix timestamp (seconds)", max 20 markets); history points are `{t: uint32 seconds, p: float}`. Gamma filters `start_date_min`/`end_date_max`: date-time strings. `GET clob.polymarket.com/time` returns server Unix seconds for clock sync.
GOTCHA: The same concept is spelled `start_ts`, `startTs`, and `start_date_min` depending on endpoint. Millisecond epochs don't even fit the documented `uint32` history field. Timezone offsets: the docs give epochs and RFC3339/date-time — never local-time strings.

## Rate limits exist on both venues — with different failure modes
WHEN: Bulk polling or backfills.
WRONG: Unthrottled request loops; assuming public endpoints are unlimited.
RIGHT: Kalshi: token buckets; default cost 10 tokens/request (`GET /account/endpoint_costs` lists exceptions); Basic tier = 200 read + 100 write tokens/sec (≈20 default GETs/sec), up to Prestige 6,000/8,000; 429 body `{"error": "too many requests"}` with NO `Retry-After` or `X-RateLimit-*` headers; batch endpoints are billed per item. Polymarket (Cloudflare, sliding windows; excess is throttled/queued, not rejected): general 15,000 req/10s; Gamma general 4,000/10s, `/markets` 300/10s, `/events` 500/10s, `/public-search` 350/10s; CLOB general 9,000/10s; data-api general 1,000/10s, `/trades` 200/10s.
GOTCHA: Polymarket delays instead of erroring, so an over-limit scraper just mysteriously slows down; Kalshi 429s but gives no headers to back off from — use exponential backoff (docs' own advice).

## CLOB market-listing endpoints have no limit param and huge pages
WHEN: Wanting Polymarket price snapshots or market lists from the CLOB.
WRONG: `GET /sampling-simplified-markets?limit=10` — inventing a `limit` param.
RIGHT: `/simplified-markets`, `/sampling-markets`, and `/sampling-simplified-markets` accept only `next_cursor`; first `/sampling-simplified-markets` page measured ~582 KB / ~12 s (INDEX.md live check). For specific tokens use `/book`, `/price`, `/midpoint` (single) or `/books`, `/prices`, `/midpoints` (batch), or `/clob-markets/{condition_id}` for full CLOB params.
GOTCHA: The downloaded CLOB spec has no plain `GET /markets` listing at all — market discovery belongs on Gamma. Models add `limit` because every Gamma list endpoint has one; here it is silently ignored.

## Kalshi candlesticks need BOTH series_ticker and market ticker
WHEN: Fetching OHLC for one Kalshi market.
WRONG: `GET /markets/{ticker}/candlesticks` — that live path does not exist.
RIGHT: `GET /series/{series_ticker}/markets/{ticker}/candlesticks` with required `start_ts`, `end_ts` (Unix seconds) and `period_interval` ∈ {1, 60, 1440} minutes (validated enum). No series ticker handy → batch `GET /markets/candlesticks?market_tickers=…` (≤100 tickers, ≤10,000 candles total) needs no series_ticker. Event-level: `GET /series/{series_ticker}/events/{ticker}/candlesticks`. Markets settled before the cutoff: `GET /historical/markets/{ticker}/candlesticks`.
GOTCHA: Everywhere else the market ticker alone suffices; only single-market candlesticks nest under the series. `period_interval` accepts exactly three values — no 5m/15m candles exist.

## Kalshi orderbook has no asks — derive them from opposite bids
WHEN: Computing spreads or depth from `/markets/{ticker}/orderbook`.
WRONG: Looking for an `asks` array, or taking element [0] as the best price.
RIGHT: Response is `orderbook_fp` with `yes_dollars` and `no_dollars` — bids only, `[price_dollars, count_fp]` string pairs sorted ascending; best bid = LAST element. best_yes_ask = $1.00 − best_no_bid; best_no_ask = $1.00 − best_yes_bid.
GOTCHA: Polymarket `/book` returns explicit `bids` AND `asks`; porting that parser to Kalshi silently misreads NO bids as asks. And `[0]` is the WORST bid, not the best.

## Kalshi live endpoints silently drop old settled markets
WHEN: Backfilling settled markets, trades, or candles.
WRONG: `GET /markets?status=settled` and assuming the result is complete history.
RIGHT: Records older than the cutoff timestamps (`GET /historical/cutoff`; live window target is 3 months) exist only on `GET /historical/markets`, `/historical/trades`, `/historical/markets/{ticker}/candlesticks`. Partitioning applies to markets, market_candlesticks, trades, orders; events and series stay on their original endpoints.
GOTCHA: No error, no truncation marker — live endpoints just exclude old settled markets, so backfills look complete but aren't.

## Base URLs: don't invent hosts, don't drop path prefixes
WHEN: Constructing any request.
WRONG: `trading-api.kalshi.com`, `api.kalshi.com`, `https://external-api.kalshi.com/markets` (missing prefix), or order-book calls against `gamma-api`.
RIGHT: Kalshi prod: `https://external-api.kalshi.com/trade-api/v2` (primary) or `https://api.elections.kalshi.com/trade-api/v2`; demo: `https://external-api.demo.kalshi.co/trade-api/v2`, `https://demo-api.kalshi.co/trade-api/v2`. Polymarket: `https://gamma-api.polymarket.com` (discovery/search), `https://clob.polymarket.com` (books/prices/timeseries), `https://data-api.polymarket.com` (trades/holders/positions). All seven verified live 2026-07-01 (INDEX.md).
GOTCHA: Every Polymarket endpoint exists on exactly one of the three hosts; Kalshi paths never work without the `/trade-api/v2` prefix. Hosts named in specs but NOT live-checked (clob-staging, relayer-v2, bridge, combos-rfq-api, builders) — verify before use.

## Kalshi orderbook returns HTTP 200 for NONEXISTENT tickers
WHEN: Deciding whether a Kalshi market exists from its orderbook response.
WRONG: Treating any 200 from `GET /markets/{ticker}/orderbook` as proof the market exists, or expecting a 404 for a bad ticker.
RIGHT: Live-checked 2026-07-02: `/markets/NOSUCHTICKER-99XYZ/orderbook` → `200 {"orderbook_fp":{"no_dollars":[],"yes_dollars":[]}}` — identical to a real market with an empty book. To disambiguate, hit `GET /markets/{ticker}` (404s properly) or the candlesticks endpoint (also 404s properly).
GOTCHA: Only the orderbook endpoint has this behavior; its siblings 404 like you'd expect. An "empty book" result on a ticker you constructed yourself (instead of taking it from `/markets`) is usually a typo, not zero liquidity.

## Kalshi geo-blocks with a WORDLESS 403 — sniffing for "blocked" finds nothing
WHEN: Classifying a 403 from Kalshi production hosts (geo vs auth vs other).
WRONG: Matching the body against `cloudflare|region|blocked` and calling anything else a generic network/auth error.
RIGHT: Live-checked 2026-07-02 from a blocked region: `external-api.kalshi.com` answers a bare nginx/awselb `403 Forbidden` with zero explanatory wording; `api.elections.kalshi.com` answers an Amazon CloudFront page — "…configured to block access from your country… Generated by cloudfront". To classify a bare 403, probe the alternate documented prod host and sniff for `cloudfront|country|block access|request blocked`. Demo hosts (`*.demo.kalshi.co` / `demo-api.kalshi.co`) responded normally from the same network. Polymarket showed no geo-blocking.
GOTCHA: Kalshi fronts with CloudFront, not Cloudflare — the word "cloudflare" never appears. Geo policy also changes without notice: the same network got HTTP 200 from both prod hosts on 2026-07-01 and 403 on 2026-07-02. Read-only public data is NOT immune.

<!-- phase-2 will append real eval failures below this line -->
