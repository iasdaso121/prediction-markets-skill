# prediction-markets-skill

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Dependencies](https://img.shields.io/badge/dependencies-stdlib--only-success.svg)
![Zero Deps](https://img.shields.io/badge/zero--deps-true-success.svg)
![Scope](https://img.shields.io/badge/scope-read--only-green.svg)
![Trigger Accuracy](https://img.shields.io/badge/trigger_accuracy-50%25-orange.svg)

**Scope: read-only market data only. No trading, no API keys, no wallet access — ever, in this skill.**

A zero-dependency skill for Claude Code / Codex / Cursor that gives AI agents accurate, non-hallucinated access to [Kalshi](https://kalshi.com) and [Polymarket](https://polymarket.com) public market data: market discovery, orderbooks, price history, implied probability, and cross-venue market matching.

## Why

- **Zero-dependency.** Python 3.10+ stdlib only. No `pip install`, no external services, no MCP server to host.
- **No keys.** Public data from both venues without registration.
- **Auditable.** Every script reads in 5 minutes. No telemetry. Network calls only to documented Kalshi/Polymarket API hosts.
- **Knowledge, not just scripts.** References teach the model market mechanics: fees, settlement, negRisk, microstructure.
- **Cross-venue matching.** Match equivalent markets Kalshi↔Polymarket and compute the spread.

## Status

v0.1.0 — Active development. See CHANGELOG.md.

## Install

### 1. Claude Code (plugin, preferred)
```bash
claude plugin marketplace add iasdaso121/prediction-markets-skill
claude plugin install prediction-markets
```
*(Or use `/plugin marketplace add iasdaso121/prediction-markets-skill` interactively)*

### 2. Any SKILL.md-compatible agent
```bash
git clone --depth 1 https://github.com/iasdaso121/prediction-markets-skill /tmp/pms
mkdir -p ~/.claude/skills
cp -r /tmp/pms/skills/prediction-markets ~/.claude/skills/
rm -rf /tmp/pms
```

### 3. skills CLI
```bash
npx skills add iasdaso121/prediction-markets-skill
```

## Mini-example

```bash
python3 scripts/poly_markets.py --active --limit 1
```

```json
{
  "venue": "Polymarket",
  "endpoint": "https://gamma-api.polymarket.com/events",
  "params": "active=true&limit=1",
  "fetched_at": "2026-07-02T12:00:00Z",
  "count": 1,
  "data": [
    {
      "title": "Will interest rates be cut in September?",
      "slug": "fed-rate-cut-september",
      "active": true
    }
  ]
}
```

## Disclaimer

Educational and research tooling only. Not financial advice. This project provides read-only access to public market data and does not execute trades.

## License

MIT
