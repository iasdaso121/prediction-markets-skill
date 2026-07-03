# Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/); versioning follows [semver](https://semver.org/).

## [0.1.1] - 2026-07-03

### Fixed
- `poly_orderbook.py` resolves the Yes/No CLOB token by matching the outcome **label**, not by
  array position — Polymarket does not guarantee `clobTokenIds` order (py-clob-client #276).
  Position-based selection could silently return the opposite outcome's orderbook.
- `kalshi_orderbook.py` disambiguates a nonexistent ticker: the orderbook endpoint returns
  HTTP 200 with an empty book for bad tickers, so an empty book is cross-checked against
  `GET /markets/{ticker}` (exit 6 if it 404s) instead of reporting a fake empty spread.
- Kalshi geo-block detection: production hosts return a wordless 403 (nginx) or a CloudFront
  country-block page; scripts now corroborate a bare 403 against the alternate documented host
  and classify it as geo (exit 5) instead of a generic network error.

### Added
- `kalshi_markets.py --max-pages` caps client-side `--query` scans (default 5) and reports
  truncation honestly in a `scan` object — an uncapped keyword scan of the full market universe
  took minutes.
- `match_markets.py` alias canonicalization: Fed=FOMC, NYC=New York=KNYC, BTC=Bitcoin,
  Cavs=Cleveland, magnitude suffixes ($60k=60000), and threshold words (above/over→gt) are
  normalized before scoring so cross-venue title/entity overlap survives naming differences.
  Still a v0 heuristic — `confidence` stays advisory, spread is never called an "edge".
- SKILL.md workflows for weather/temperature markets (search by `KXHIGH<CITY>` series, sum
  bucket probabilities) and multi-contract events (use `--event`, not a full-universe scan).
- `gotchas.md`: wordless Kalshi geo-403, orderbook-200-on-bad-ticker, clobTokenIds label order.

### Changed
- GitHub handle updated across the repo (plugin manifest, README, install docs, script
  User-Agents) after an account rename.
- SKILL.md description optimized via skill-creator run_loop on the session model
  (claude-opus-4-8, 5 iterations, 60/40 train/test). Trigger precision 100% (no false
  positives on near-miss prompts), recall ~17% on held-out — the best of 5 candidates,
  and an improvement over the prior description (0% held-out recall). Low recall is
  expected and mostly by design: the model handles simple one-line data lookups itself,
  so short prompts under-trigger; multi-step prompts trigger reliably (task evals pass
  ~95% with the skill vs ~62% without).

## [0.1.0] - 2026-07-02

### Added
- Initial prediction-markets skill covering Kalshi and Polymarket
- 7 stdlib-only scripts: market discovery, orderbooks, price history, cross-venue matching
- 4 references (Kalshi API, Polymarket API, market mechanics, gotchas) verified against live docs
- Script routing, workflows, output contract in SKILL.md
- Repo scaffold: plugin manifest, references/scripts layout, docs-raw pipeline

### Known limitations
- Skill under-triggers on short one-line prompts (trigger eval in progress; description
  optimization pending a full run on the session model). Multi-step prompts trigger reliably.
