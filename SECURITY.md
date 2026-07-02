# Security

This skill is designed to be auditable in 5 minutes.

- **Zero dependencies.** Python 3.10+ standard library only. No `pip install`, no lockfiles, no supply chain.
- **Read-only.** No trading, no order placement, no wallet or key access. There is nothing in this repo that can move money.
- **No secrets.** No API keys required or accepted for any script in the core skill.
- **No telemetry.** Nothing is logged, phoned home, or collected.
- **Network allowlist.** Scripts make HTTPS calls only to these documented API hosts (verified live from official docs, 2026-07-01):
  - `api.elections.kalshi.com` — Kalshi Trade API v2 (public market data)
  - `gamma-api.polymarket.com` — Polymarket Gamma API (market/event discovery)
  - `clob.polymarket.com` — Polymarket CLOB API (orderbooks, prices)
  - `data-api.polymarket.com` — Polymarket data API (trades, holders)

## Reporting

Open a GitHub issue or contact the maintainer. Response SLA: 48 hours.
