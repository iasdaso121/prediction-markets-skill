# Market Mechanics — Kalshi + Polymarket

Math reference for prices, fees, settlement, orderbooks, cross-venue comparison.
Everything here comes from `docs-raw/kalshi/` and `docs-raw/polymarket/` dumps.
Items the docs do not state are marked **not documented** — do not invent them.

## 1. Price = implied probability

Both venues trade binary contracts that settle at $1.00 (winner) / $0.00 (loser).
Therefore: **price ÷ $1.00 payout = implied probability of that outcome**.

| Venue | Native price unit | Range | Probability conversion |
|---|---|---|---|
| Kalshi (order prices, legacy fields) | integer **cents** | 1–99 | `p = cents / 100` (42¢ → 0.42 → 42%) |
| Kalshi (`*_dollars` fields) | fixed-point dollar **string**, ≤6 decimals (schema max; see below) | "0.0000"–"1.0000" | `p = float(value)` ("0.4200" → 42%) |
| Polymarket | decimal dollars (string or number) | $0.00–$1.00 | `p = value` (0.45 → 45%) |

Kalshi specifics (documented):
- Order prices `yes_price` / `no_price` are integers with min 1, max 99 (cents). API error text: "price must be 1-99 cents".
- Newer surfaces use `*_dollars` fixed-point dollar strings (e.g. `"0.1200"`). Precision — the docs give two numbers: the `FixedPointDollars` wire schema allows up to **6** decimal places ("the maximum supported precision"), while the fixed-point migration guide says current values use up to 4 (with intermediates reaching 6 when combined with fractional contracts). **Do not hard-code a 4-decimal parser/validator limit** on `*_dollars` strings.
- `notional_value_dollars` on Market = "the total value of a single contract at settlement in dollars" — use it as the payout denominator instead of assuming $1.
- Tick size depends on `price_level_structure`: `linear_cent` ($0.01 everywhere), `tapered_deci_cent` ($0.001 below $0.10 and above $0.90, $0.01 in the middle), `deci_cent` ($0.001 everywhere). `price_ranges` gives exact intervals.
- Contract counts: `*_fp` fixed-point strings, min granularity 0.01 contracts (e.g. `"13.00"`).
- Unit trap: `GET /portfolio/balance` returns cents; some legacy fields are integer cents; new fields are `_dollars` strings. Check the suffix before doing math.

Polymarket specifics (documented):
- "Every share on Polymarket is priced between $0.00 and $1.00. The price directly represents the market's belief in the probability of that outcome." ($0.25 = 25%, $0.50 = 50%, $0.75 = 75%.)
- Prices are quoted per **token_id** (one token per outcome), as decimal strings (`"0.45"` from `/midpoint`) or numbers (`0.45` from `/price`).
- UI display rule: displayed price is the bid-ask **midpoint**; if the spread is wider than $0.10, the last traded price is displayed instead. The API `/midpoint` always returns the average of best bid and best ask.

Worked conversions:
- Kalshi market with `yes_bid_dollars: "0.4200"` → best-bid implied P(YES) = 0.42 = 42%.
- Kalshi order at `yes_price: 7` → 7¢ → P(YES) = 0.07 = 7%.
- Polymarket `/midpoint` → `{"mid_price": "0.45"}` → P(YES) = 0.45 = 45%.

## 2. Settlement at $1 / $0

Kalshi (documented):
- Yes outcome → Yes holders receive $1 per contract; No outcome → No holders receive $1 per contract. Only net positions are settled (after netting).
- Settlement fees are zero for simple yes/no determinations; may apply for sub-cent scalar settlement. Payout is rounded to whole cents.
- Markets can be `binary` or `scalar` (`market_type` enum); scalar settlement price can have 2 decimal places in cents (e.g. `30.60`).

Polymarket (documented):
- Winning tokens redeem for $1.00 each; losing tokens become worthless ($0.00). Every Yes/No pair is backed by exactly $1 of pUSD locked in the CTF contract.
- Resolution via UMA Optimistic Oracle: proposal (bond typically $750 pUSD) → 2-hour challenge period → possible disputes → DVM vote. Rare "Unknown/50-50" verdict: market resolves 50/50, each token redeems $0.50.
- P&L example (from docs): buy Yes at $0.40 → event occurs: $1.00 back, +$0.60/token (150%); doesn't occur: -$0.40/token (-100%). Position value = token balance × current price.

## 3. Kalshi trading fees

**The numeric fee formula is NOT in the downloaded docs.** What IS documented:

- Every series has a `fee_type` (enum: `quadratic`, `quadratic_with_maker_fees`, `flat`) and a `fee_multiplier` (double, "a floating point multiplier applied to the fee calculations").
- The spec defines the fee types by reference only: "'quadratic' is described by the General Trading Fees Table, 'quadratic_with_maker_fees' is described by the General Trading Fees Table with maker fees described in the Maker Fees section, 'flat' is described by the Specific Trading Fees Table" — all in `https://kalshi.com/docs/kalshi-fee-schedule.pdf` (not downloaded; the tables/coefficients are **not documented** locally).
- Events can override the series fee: `fee_type_override` + `fee_multiplier_override` (both null = override cleared, falls back to series).
- Scheduled changes: `GET /series/fee_changes` (param `show_historical`: true = all past+upcoming, false = upcoming only) and `GET /events/fee_changes`.
- Order objects (`GET /portfolio/orders`) carry per-order aggregate fees: `taker_fees_dollars`, `maker_fees_dollars`. Each fill (`GET /portfolio/fills`) reports its own fee as `fee_cost` (fixed-point dollars). Public trades gained `yes_price_dollars` / `no_price_dollars`.

**Do not compute a Kalshi fee from a remembered coefficient.** Either fetch the fee schedule PDF, or read realized fees from API fields.

### Fee rounding (documented exactly)

Balance precision targets: direct members $0.0001; non-direct members $0.01. Per fill:

1. **Trade fee** (from the fee model) is rounded **up** to the nearest $0.0001 (centicent).
2. `balance_change = revenue - trade_fee` (revenue signed; negative for buyers).
3. Floor `balance_change` toward negative infinity to the user's target precision.
4. `rounding_fee = balance_change - floor(balance_change)`.

`Net fee = trade fee + rounding fee - rebate` (always ≥ $0.00). A per-order **fee accumulator** tracks cumulative rounding overpayment across fills (taker and maker alike); once it exceeds $0.01, a whole-cent $0.01 rebate is issued, so total fees converge to the single-fill equivalent.

Worked example (verbatim from docs; non-direct member, $0.01 precision; buy 1 contract at $0.055):

```
revenue        = -$0.055 x 1        = -$0.0550
trade fee      = $0.0085              (ceiled to centicent; model input from fee schedule)
balance change = -$0.0550 - $0.0085 = -$0.0635  → floored to -$0.07
rounding fee   = $0.07 - $0.0635    =  $0.0065
net fee        = $0.0085 + $0.0065  =  $0.0150
```

## 4. Polymarket fees

Documented taker-fee formula ("Makers are never charged fees. Only takers pay fees."):

```
fee = C × feeRate × p × (1 - p)      # C = shares traded, p = share price
```

- Fees are set per-market by the protocol and applied at match time; orders carry no fee info. Markets with fees have `feesEnabled: true`.
- Fee in USDC is symmetric around 50%: a trade at 30¢ costs the same as at 70¢; it peaks at p = 0.50.
- Precision: fees rounded to 5 decimal places; smallest charged fee 0.00001 USDC; anything smaller rounds to zero.
- **Geopolitical and world events markets are fee-free** (taker rate 0).

Per-category taker fee rates (maker rate 0 everywhere):

| Category | Taker feeRate | Maker rebate share |
|---|---|---|
| Crypto | 0.07 | 20% |
| Sports | 0.03 | 25% |
| Finance / Politics / Mentions / Tech | 0.04 | 25% |
| Economics / Culture / Weather / Other | 0.05 | 25% |
| Geopolitics | 0 | — |

Worked example (Weather, matches docs' 100-share fee table): buy 100 shares at $0.30 →
`fee = 100 × 0.05 × 0.30 × 0.70 = $1.05 USDC`. At $0.50 the max: `100 × 0.05 × 0.25 = $1.25`.

Querying fee params:
- `GET /fee-rate?token_id=...` or `GET /fee-rate/{token_id}` (clob) → `{"base_fee": 30}` — integer **basis points**.
- SDK `getClobMarketInfo(conditionID)` → `fd = { r: feeRate, e: exponent, to: takerOnly }`.

Builder fees (only when an order carries a builder code — not relevant to read-only data, but they exist): flat % of notional, `builder_fee = notional × bps / 10000`, additive on top of platform fees; limits taker ≤ 100 bps (1%), maker ≤ 50 bps (0.5%). Taker fees fund daily maker rebates; a tiered taker-rebate program also exists.

## 5. Polymarket outcome tokens (CTF)

- Each market = one binary question with exactly two outcome tokens (Yes, No). Tokens are **ERC1155** assets on Polygon under the Gnosis **Conditional Token Framework (CTF)**.
- Identifiers per market: `conditionId` (CTF condition), `questionId` (hash used for resolution), two **token IDs** (one per outcome) — the CLOB trades by `token_id`. CLOB market objects (`GET /markets`, `/sampling-markets` on clob.polymarket.com) expose a `tokens` array of `{token_id, outcome, ...}`; Gamma markets instead expose `clobTokenIds`, a JSON-encoded string array (first = Yes token, second = No token). Gamma has no `tokens` array.
- Fully collateralized: every Yes/No pair is backed by exactly $1 pUSD locked in the CTF contract.
- Operations: **Split** ($1 pUSD → 1 Yes + 1 No), **Merge** (1 Yes + 1 No → $1 pUSD), **Trade** (CLOB), **Redeem** (winning token → $1 after resolution).
- Only tradable on the CLOB if `enableOrderBook: true`.

Complementary pricing: price discovery works by matching a buy-Yes at $0.60 against a buy-No at $0.40 — "Since $0.60 + $0.40 = $1.00, the orders match" and $1.00 is minted into 1 Yes + 1 No. So **p_yes + p_no = 1 holds at execution**. Derived caveat: each token has its own book and its own bid/ask, so *quoted* midpoints of Yes and No can deviate from summing to exactly 1.00 by up to the spreads. Fetch the token you need; don't assume `p_no = 1 - p_yes_mid` is executable.

## 6. negRisk multi-outcome events

Documented model:
- An **event** groups 1+ binary markets. Multi-market events represent mutually exclusive multi-outcome questions (e.g. election winner: one Yes/No market per candidate + "Other").
- In a *standard* multi-outcome event, "each market is independent" — No tokens in one market have no relationship to other outcomes.
- **Negative risk**: only one outcome can win; 1 No token in any market can be converted (atomically, via the Neg Risk Adapter contract) into 1 Yes token in *every other* market of the event. Betting against one outcome ≡ betting for all others.
- Identification: Gamma `negRisk: true` on events and markets; CLOB `/book` response has `neg_risk`; `GET /neg-risk/{token_id}` (clob) returns neg-risk info. Neg-risk markets trade on a separate Neg Risk CTF Exchange contract.
- **Augmented neg risk** (`enableNegRisk: true` + `negRiskAugmented: true`): outcomes = named + placeholder slots + explicit "Other". Placeholders get clarified later; docs warn to only trade **named** outcomes; the Polymarket UI does not display unnamed outcomes. If the true outcome is never named, the market resolves to "Other".

Why YES prices across outcomes need not sum to 100%:
- Each outcome is its own binary orderbook; nothing in the API normalizes quotes across an event's markets (no price-sum invariant is documented).
- Quotes carry independent spreads; only actual conversion/arbitrage ties them together, net of fees.
- In augmented events, placeholder/"Other" outcomes exist that a naive listing may omit, so the visible YES prices undercount the full outcome set.
- Therefore: never validate data with `sum(yes_prices) == 1.0`, and never derive one outcome's probability as `1 - sum(others)`.

## 7. Orderbook microstructure

### Kalshi — bids only, two sides

`GET /markets/{ticker}/orderbook` (no auth) returns `orderbook_fp` with two arrays:
`yes_dollars` and `no_dollars`; each level is `[price_dollars, count_fp]` (both strings, e.g. `["0.4200", "13.00"]`). Arrays are sorted ascending by price — **best bid is the LAST element**.

There are no asks. Documented reciprocal relationship ("binary markets must sum to $1.00"):
- YES bid at X ≡ NO ask at ($1.00 − X); NO bid at Y ≡ YES ask at ($1.00 − Y).
- Spec phrasing (cents): "a yes bid at 7¢ is the same as a no ask at 93¢, with identical contract sizes."

Spread math (documented):
```
best_yes_bid = last price in yes_dollars
best_yes_ask = 1.00 - (last price in no_dollars)
yes_spread   = best_yes_ask - best_yes_bid
# docs example: bid 0.4200, best NO bid 0.5600 → ask 0.44 → spread $0.02
```
WebSocket caveat: `orderbook_delta`/`orderbook_snapshot` report no-side levels in **no-leg pricing** by default; pass `use_yes_price: true` to get one yes-leg scale on both sides (default will flip to true in a future release).

### Polymarket — bids and asks per token_id

| Endpoint (clob) | Returns |
|---|---|
| `GET /book?token_id=` | `bids` + `asks` arrays of `{price, size}` strings, plus `tick_size`, `min_order_size`, `neg_risk`, `last_trade_price` |
| `GET /midpoint?token_id=` | `{"mid_price": "0.45"}` — average of best bid and best ask |
| `GET /spread?token_id=` | `{"spread": "0.02"}` — best ask minus best bid |
| `GET /price?token_id=&side=` | **side=BUY → best bid; side=SELL → best ask** (spec wording; trap: not "the price you'd pay") |
| `GET /prices-history?market=<token_id>` | timeseries; `interval` ∈ max/all/1m/1w/1d/6h/1h; `fidelity` in minutes (default 1) |

Bid/ask semantics (documented): bids = highest prices buyers will pay; asks = lowest prices sellers will accept; spread = gap between best bid and best ask; "Tighter spreads mean more liquid markets."

Effective cost: market buys pay the ask, market sells receive the bid — "You won't necessarily trade at $0.37 [the midpoint] — you'll pay the ask ($0.40) when buying or receive the bid ($0.34) when selling." Midpoint is an estimate, not an executable price; the immediate round-trip cost of a position is the full spread.

Depth as liquidity proxy: sum `size`/`count_fp` across levels near the best price (Kalshi docs demo sums contracts within $0.05 of best bid). Polymarket docs: order book has no size limits, but "large orders may move the price significantly. Always check orderbook depth before trading in size."

## 8. Cross-venue comparison math

1. **Common probability.** Kalshi: `p_K = yes_price_cents / 100` or `float(yes_*_dollars) / float(notional_value_dollars)`. Polymarket: `p_P = float(price)` of the YES token. Both are P(YES) only if the two markets' resolution terms match — compare Kalshi `rules_primary`/`rules_secondary` against Polymarket resolution rules before treating them as the same event.
2. **Venue spread (signal).** `Δp = p_P_mid - p_K_mid` using midpoints (Kalshi mid = (best_yes_bid + best_yes_ask)/2 from the bids-only book; Polymarket mid from `/midpoint`).
3. **Executable edge (never use mids).** Buying YES where cheap and selling where dear:
   `gross_edge = bid_high_venue - ask_low_venue` per share, sized by `min(depth_at_bid, depth_at_ask)`.
4. **Fees must enter.** `net_edge = gross_edge - fee_low_venue - fee_high_venue` per share, where
   - Polymarket taker side: `feeRate × p × (1 - p)` per share (feeRate from the category table or `/fee-rate`; 0 if `feesEnabled` false / geopolitics).
   - Kalshi side: trade fee per the fee schedule (**coefficients not in local docs** — fetch the PDF or treat as an input) plus rounding rules from §3; net fee is never negative.

Worked sketch (weather market, illustrative quotes):
```
Kalshi implied YES ask   = 1.00 - 0.56 (best NO bid)      = $0.44
Polymarket YES best bid                                    = $0.47
gross edge               = 0.47 - 0.44                     = $0.03 / share
Polymarket taker fee     = 0.05 × 0.47 × (1-0.47)          = $0.012455 → $0.01246 (5-dp rounding)
net edge                 = 0.03 - 0.01246 - kalshi_fee     = $0.01754 - kalshi_fee
```
If `kalshi_fee` per share ≥ $0.01754, there is no edge. Since the Kalshi coefficient is not documented locally, an edge computed without it is **not actionable**.

## Not documented (do not fabricate)

- Kalshi: numeric fee formulas/coefficients for `quadratic`, `quadratic_with_maker_fees`, `flat` (live in kalshi-fee-schedule.pdf, not downloaded); maker-fee rates; whether every market's notional is exactly $1 (read `notional_value_dollars`).
- Polymarket: any guarantee that quoted YES+NO prices or multi-outcome YES prices sum to 1; the platform fee `exponent` (`fd.e`) semantics; holding-reward mechanics beyond "4.00% annualized, variable".
