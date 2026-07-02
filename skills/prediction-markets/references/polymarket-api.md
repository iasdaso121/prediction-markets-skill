# Polymarket API — read-only reference

Source of truth: `docs-raw/polymarket/` (llms-full.txt + gamma-openapi.yaml + clob-openapi.yaml + data-api-openapi.yaml, fetched 2026-07-01). If it is not here, it is not documented — do not invent endpoints.

## Three services (all public reads, no auth, no API key)

| Base URL | Role |
|---|---|
| `https://gamma-api.polymarket.com` | Gamma: market/event discovery, metadata, tags, search |
| `https://clob.polymarket.com` | CLOB: orderbooks, prices, midpoints, spreads, price timeseries |
| `https://data-api.polymarket.com` | Data-API: trades, holders, positions, activity, open interest |

Wrong-service calls are the top failure mode: there is NO `/book` on Gamma, NO `/events` on CLOB, and NO plain `GET /markets` on CLOB (CLOB market lists are `/simplified-markets`, `/sampling-markets`, `/sampling-simplified-markets` only).

## ID glossary

| ID | Shape | Used by |
|---|---|---|
| slug | url string, e.g. `fed-decision-in-october` (path segment after `/event/` in polymarket.com URLs) | Gamma `/events/slug/{slug}`, `/markets/slug/{slug}`, `?slug=` |
| Gamma id | numeric **string** in responses (`"id": "16183"`); pass as integer in request params | Gamma `/events/{id}`, `/markets/{id}`, `?id=`, data-api `eventId=` |
| condition_id | `0x` + 64 hex | CLOB `/clob-markets/{condition_id}`, data-api `market=` |
| token_id (= asset id) | huge decimal string, e.g. `713210456792...` | ALL CLOB price/book endpoints |

Gotcha: Gamma ids are integer-valued but serialized as JSON strings in `/events` and `/markets` response bodies — int-typed access on `event["id"]` / `market["id"]` breaks without a cast. Only the request side (`/events/{id}` path, `?id=`, data-api `eventId=`) is typed integer in the spec.

## Question → token_id (the critical path)

Every CLOB price endpoint is keyed by **token_id**, which only Gamma gives you.

1. Find the market on Gamma:
   - `GET https://gamma-api.polymarket.com/public-search?q=...` (full-text over events/markets/profiles), or
   - `GET .../events?slug=<slug>` / `GET .../events/slug/{slug}` (slug from the frontend URL), or
   - `GET .../markets?active=true&closed=false&limit=1` style listing.
2. An **event** contains one or more **markets**; each market is one binary Yes/No outcome. Multi-outcome questions = one event with many markets ("Who wins?" → one market per candidate).
3. Read the market's `clobTokenIds` field. It is a **JSON-array-encoded STRING**, not an array: `"[\"123...\",\"456...\"]"` — parse it. Index 0 = Yes token, index 1 = No token. `outcomes` and `outcomePrices` are the same kind of encoded strings and map 1:1 by index.
4. Call CLOB with that token id: `/book?token_id=`, `/price?token_id=&side=`, `/midpoint?token_id=`, `/prices-history?market=<token_id>`.
5. Reverse lookup: `GET clob /markets-by-token/{token_id}` → `{condition_id, primary_token_id (Yes), secondary_token_id (No)}`.

## Gamma API (discovery)

Responses of `/markets` and `/events` are bare JSON arrays (no envelope, no total count).

| Endpoint | Notes |
|---|---|
| `GET /events` | list events; filters below |
| `GET /events/{id}`, `GET /events/slug/{slug}` | single event (`include_chat`, `include_template`) |
| `GET /events/{id}/tags` | tags of an event |
| `GET /markets` | list markets; filters below |
| `GET /markets/{id}`, `GET /markets/slug/{slug}` | single market (`include_tag`) |
| `GET /markets/{id}/tags` | tags of a market |
| `GET /series`, `GET /series/{id}` | series (filters: `slug`, `categories_ids`, `categories_labels`, `closed`, `recurrence`, `exclude_events`) |
| `GET /tags`, `GET /tags/{id}`, `GET /tags/slug/{slug}` | tag discovery |
| `GET /sports` | sports metadata incl. tag IDs |
| `GET /public-search` | `q` required; `limit_per_type`, `page`, `events_status`, `events_tag`, `keep_closed_markets`, `search_tags`, `search_profiles`, `exclude_tag_id`, `sort`, `ascending` |
| `GET /status` | health |

`GET /events` filters: `limit`, `offset` (both int ≥0), `order` (comma-separated fields; documented values: `volume_24hr`, `volume`, `liquidity`, `start_date`, `end_date`, `competitive`, `closed_time`), `ascending` (default false), `id` (repeatable), `slug` (repeatable), `tag_id` (int), `exclude_tag_id`, `tag_slug`, `related_tags` (bool), `active`, `archived`, `featured`, `closed`, `liquidity_min/max`, `volume_min/max`, `start_date_min/max`, `end_date_min/max` (date-time).

`GET /markets` filters: `limit`, `offset`, `order`, `ascending`, `id`, `slug`, `clob_token_ids`, `condition_ids`, `liquidity_num_min/max`, `volume_num_min/max`, `start_date_min/max`, `end_date_min/max`, `tag_id`, `related_tags`, `closed` (default **false** — closed markets excluded unless `closed=true`), `include_tag`. Note: `active` is not in the OpenAPI param list for `/markets`, but official examples use `?active=true&closed=false` on it; docs say "Always include `active=true` when fetching live markets."

Docs-recommended discovery strategies: by slug (specific market/event), by `tag_id` (category), or `GET /events?active=true&closed=false` + pagination for all active markets (events embed their markets — fewest calls).

Market metadata worth reading: `question`, `conditionId`, `slug`, `outcomes`, `outcomePrices`, `active`, `closed`, `archived`, `acceptingOrders`, `enableOrderBook` (tradable on CLOB only if true), `orderPriceMinTickSize`, `orderMinSize`, `bestBid`, `bestAsk`, `lastTradePrice`, `spread`, `volumeNum`, `liquidityNum`, `endDateIso`, `negRisk`.

## CLOB API (prices & books)

All below are public, no auth. Most carry an explicit `security: []` in the spec; `/clob-markets/{condition_id}` and `/markets-by-token/{token_id}` omit the security field entirely (no global security scheme exists, so still public). Token-keyed endpoints:

| Endpoint | Params | Returns |
|---|---|---|
| `GET /book` | `token_id` required | `{market (condition id), asset_id, timestamp, hash, bids:[{price,size}], asks:[{price,size}], min_order_size, tick_size, neg_risk, last_trade_price}` — prices/sizes are strings. `timestamp` is a Unix-**milliseconds** string (13 digits, observed live; spec doesn't state the unit) — NOT seconds like `prices-history`/`/time` |
| `GET /books` | `token_ids` = comma-separated | array of book summaries (also `POST /books`) |
| `GET /price` | `token_id`, `side` (`BUY`\|`SELL`) both required | `{price: number}` e.g. `0.45` |
| `GET /prices` | `token_ids`, `sides` comma lists | map token_id → {side: price} (also `POST /prices`) |
| `GET /midpoint` | `token_id` | `{mid_price: "0.45"}` (string) — average of best bid and best ask |
| `GET /midpoints` | `token_ids` comma list | map token_id → midpoint (also `POST /midpoints`) |
| `GET /spread` | `token_id` | `{spread: "0.02"}` = best ask − best bid |
| `POST /spreads` | body `[{token_id}, ...]` | map token_id → spread |
| `GET /last-trade-price` | `token_id` | `{price, side}`; defaults `"0.5"` / `""` if no trades |
| `GET /last-trades-prices` | `token_ids` | batch of the above |
| `GET /tick-size` / `GET /tick-size/{token_id}` | `token_id` | `{minimum_tick_size: 0.01}` |
| `GET /neg-risk` / `GET /neg-risk/{token_id}` | `token_id` | `{neg_risk: false}` |
| `GET /fee-rate` / `GET /fee-rate/{token_id}` | `token_id` | fee rate info |
| `GET /time` | — | server Unix timestamp (seconds), plain integer |

CAUTION on `/price` side semantics: the OpenAPI description says "best bid price for BUY side or best ask price for SELL side", while the market-data guide's curl comments say `side=BUY` → "best price for buying (lowest ask)" and `side=SELL` → "best price for selling (highest bid)". The docs contradict each other — sanity-check against `/book` before trusting the direction.

Market/metadata endpoints:

| Endpoint | Notes |
|---|---|
| `GET /simplified-markets` | `next_cursor` param; returns `{limit, count, next_cursor, data:[{condition_id, tokens, rewards, active, closed, archived, accepting_orders}]}` |
| `GET /sampling-markets` | `next_cursor`; markets with rewards enabled (paginated markets shape) |
| `GET /sampling-simplified-markets` | `next_cursor`; simplified shape. WARNING: no `limit` param; at fetch time the first page measured ~582 KB and ~12 s. Prefer cursor paging, or token-scoped `/book`/`/price`/`/midpoint`, or Gamma for discovery |
| `GET /clob-markets/{condition_id}` | one-call CLOB params, abbreviated keys: `t` tokens `[{t: token_id, o: outcome}]`, `mos` min order size, `mts` min tick size, `mbf`/`tbf` maker/taker base fee **basis points**, `fd` fee curve `{r rate, e exponent, to taker-only}`, `oas` min order age (s), `rfqe` RFQ enabled, `gst` game start time |
| `GET /markets-by-token/{token_id}` | token → `{condition_id, primary_token_id, secondary_token_id}` |
| `GET /markets/live-activity/{condition_id}` (+ `POST /markets/live-activity`) | minimal market info for widgets |

### Timeseries: `GET /prices-history`

Exact path: `https://clob.polymarket.com/prices-history`. Params:

| Param | Type | Meaning |
|---|---|---|
| `market` | string, **required** | The token_id (asset id). Named `market` but takes a TOKEN ID, not a condition id — docs call this out explicitly |
| `startTs` / `endTs` | number | Unix timestamps in **seconds**, absolute range |
| `interval` | enum `max` `all` `1m` `1w` `1d` `6h` `1h` | window relative to now (`1m` = last month, NOT 1 minute); mutually exclusive with `startTs`/`endTs` — don't combine |
| `fidelity` | integer | resolution in **minutes**, default 1 |

Response: `{"history": [{"t": <unix seconds>, "p": <price 0–1>}, ...]}`.

Batch: `POST /batch-prices-history` body `{markets: [token_id, ... max 20], start_ts, end_ts, interval, fidelity}` (snake_case here) → `{history: {token_id: [{t,p}...]}}`.

## negRisk (multi-outcome events)

- `negRisk: true` (Gamma boolean on events and markets) marks a **negative-risk** event: multi-outcome, only one outcome can win; a No share in any market is convertible into 1 Yes share in every other market of the event (via the Neg Risk Adapter contract). CLOB confirms per-token via `GET /neg-risk?token_id=`.
- Augmented neg risk: event has both `enableNegRisk: true` and `negRiskAugmented: true`; outcomes include placeholders + "Other". Docs: only trade named outcomes; "Other"'s definition shifts as placeholders are clarified.
- Related Gamma fields: `negRiskMarketID`, `negRiskFeeBips` (event), `negRiskOther` (market).

## Units — do not mix these up

- **Prices are 0–1 decimals** ($0.00–$1.00) = implied probability (0.25 → 25%). Applies to `/price`, `/midpoint`, `/book` levels, `outcomePrices`, `prices-history` `p`, data-api trade `price`.
- Displayed price on polymarket.com = midpoint of bid/ask; if spread > $0.10 the last traded price is shown instead.
- Book `bids`/`asks` and most CLOB prices come back as **strings** (`"0.45"`, size `"100"`); `/price` returns a number. Sizes are share counts.
- On-chain USDC.e/pUSD amounts use **6-decimal base units** (1 USDC = 1_000_000); REST responses use human-unit decimals. Only convert when touching on-chain data.
- Timestamps in `prices-history`, `startTs/endTs`, `/time` are Unix **seconds**; `/book` snapshot `timestamp` is Unix **milliseconds** (string, observed live).
- `mbf`/`tbf`/`negRiskFeeBips` are **basis points**.

## Data-API (trades / holders / positions)

| Endpoint | Required | Key params (defaults, maxes) |
|---|---|---|
| `GET /trades` | — | `limit` (100, max 10000), `offset` (0, max 10000), `takerOnly` (true), `market` = comma-sep condition IDs XOR `eventId` = comma-sep int event IDs, `user` (0x-40-hex address), `side` `BUY`\|`SELL`, `filterType` `CASH`\|`TOKENS` + `filterAmount` (must be given together) |
| `GET /holders` | `market` (comma-sep condition IDs) | `limit` (20, **max 20** per token), `minBalance` (1, max 999999). Returns `[{token, holders:[{proxyWallet, amount, outcomeIndex, name, ...}]}]` |
| `GET /positions` | `user` | `market` XOR `eventId`; `sizeThreshold` (1.0), `redeemable`, `mergeable`, `limit` (100, max 500), `offset` (0, max 10000), `sortBy` (`TOKENS`; also CURRENT, INITIAL, CASHPNL, PERCENTPNL, TITLE, RESOLVING, PRICE, AVGPRICE), `sortDirection` (`DESC`), `title` |
| `GET /closed-positions` | `user` | `limit` (10, max 50), `offset` (0, max 100000), `sortBy` (`REALIZEDPNL`, also TITLE, PRICE, AVGPRICE, TIMESTAMP), `market` XOR `eventId`, `title` |
| `GET /activity` | `user` | `limit` (100, max 500), `offset` (0, max 10000), `type` in TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION, MAKER_REBATE; `start`/`end` (unix), `sortBy` (`TIMESTAMP`), `side` |
| `GET /value` | `user` | optional `market`; total position value `[{user, value}]` |
| `GET /oi` | — | `market` = comma-sep condition IDs; open interest `[{market, value}]` |
| `GET /live-volume` | `id` (event id, int) | `[{total, markets:[{market, value}]}]` — an ARRAY wrapping the volume object (index `[0]` for totals), like `/value` and `/oi` |
| `GET /traded` | `user` | count of markets traded |

Trade object: `{proxyWallet, side, asset (token id), conditionId, size, price, timestamp (int64), title, slug, eventSlug, outcome, outcomeIndex, transactionHash, ...}`. Position adds `avgPrice`, `initialValue`, `currentValue`, `cashPnl`, `percentPnl`, `curPrice`, `redeemable`, `negativeRisk`.

## Pagination — differs per service

| Service | Style | Details |
|---|---|---|
| Gamma | `limit` + `offset` | ints ≥0; page N = `offset=N*limit`; no documented max; `/public-search` uses `page` instead |
| CLOB list endpoints | `next_cursor` | pass returned `next_cursor` back; cursor value `"LTE="` = last page (per CLOB spec/docs); rewards pages documented at 100/page (500 for `/rewards/markets/current`) |
| Data-API | `limit` + `offset` | hard maxes per endpoint (table above); `/trades` offset max 10000 — cannot page past 10k rows |

## Rate limits (docs.polymarket.com/api-reference/rate-limits)

Cloudflare throttling, sliding windows; over-limit requests are delayed/queued rather than rejected; on 429 use exponential backoff.

| Scope | Limit / 10s |
|---|---|
| Global general | 15,000 |
| Health `/ok` | 100 |
| Gamma general | 4,000 |
| Gamma `/events` | 500 |
| Gamma `/markets` | 300 |
| Gamma `/markets` + `/events` listing | 900 |
| Gamma `/public-search` | 350 |
| Gamma `/comments`, `/tags` | 200 each |
| CLOB general | 9,000 |
| CLOB `/book`, `/price`, `/midpoint` | 1,500 each |
| CLOB `/books`, `/prices`, `/midpoints` | 500 each |
| CLOB `/prices-history` | 1,000 |
| CLOB market tick size | 200 |
| Data-API general | 1,000 |
| Data-API `/trades` | 200 |
| Data-API `/positions`, `/closed-positions` | 150 each |

## Pitfalls checklist

- `clobTokenIds`, `outcomes`, `outcomePrices` are JSON-encoded strings → parse before indexing.
- `/prices-history` takes `market=<token_id>`; `interval` `1m` = one MONTH; `interval` and `startTs/endTs` are mutually exclusive; `fidelity` is minutes.
- Gamma `/markets` `closed` defaults to false — historical queries need `closed=true`.
- Batch prices-history caps at 20 token ids per POST.
- `/holders` caps at 20 holders per token; there is no offset.
- Avoid `/sampling-simplified-markets` full scans (huge, slow, no limit param).
- Staging host `clob-staging.polymarket.com` exists in the spec but is unverified — use production.
