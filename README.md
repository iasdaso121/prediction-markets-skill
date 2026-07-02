# prediction-markets-skill

**Scope: read-only market data only. No trading, no API keys, no wallet access — ever, in this skill.**

A zero-dependency skill for Claude Code / Codex / Cursor that gives AI agents accurate, non-hallucinated access to [Kalshi](https://kalshi.com) and [Polymarket](https://polymarket.com) public market data: market discovery, orderbooks, price history, implied probability, and cross-venue market matching.

## Why

- **Zero-dependency.** Python 3.10+ stdlib only. No `pip install`, no external services, no MCP server to host.
- **No keys.** Public data from both venues without registration.
- **Auditable.** Every script reads in 5 minutes. No telemetry. Network calls only to documented Kalshi/Polymarket API hosts.
- **Knowledge, not just scripts.** References teach the model market mechanics: fees, settlement, negRisk, microstructure.
- **Cross-venue matching.** Match equivalent markets Kalshi↔Polymarket and compute the spread.

## Status

v0 scaffold — under active development. See CHANGELOG.md.

## Install

_Install one-liners land in Phase 2 (Claude Code plugin, `npx skills add`, curl into `~/.claude/skills/`)._

## Disclaimer

Educational and research tooling only. Not financial advice. This project provides read-only access to public market data and does not execute trades.

## License

MIT
