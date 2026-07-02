# prediction-markets-skill — project rules

## Language & audience
All public-facing content (SKILL.md, references, scripts, README, commits) in English. Target: US developers/traders.

## Hard rules
- Scripts: Python 3.10+, stdlib ONLY (urllib.request, json, argparse). No pip dependencies, ever.
- Network calls only to documented Kalshi/Polymarket API hosts. No telemetry, no third-party services.
- Core skill is read-only. Trading logic lives only in the separate trading skill (v1.5+).
- API endpoints and base URLs come ONLY from docs-raw/ (fetched live docs), never from model memory.
- Every script: JSON to stdout, errors to stderr, non-zero exit on failure, --help with examples, timeout, retry with backoff on 429/5xx, pagination, geo-block detection.

## Definition of done (per script)
Runs against live API, returns valid JSON in <5s, tested on 3+ distinct queries, listed in SKILL.md routing table.

## Evals
- Trigger eval: skill-creator run_loop.py, target precision/recall ≥0.9 on held-out test.
- Task evals: evals/tasks.json, review via eval-viewer/generate_review.py before any SKILL.md rewrite.

## Style
SKILL.md <500 lines. References ≤300 lines or add a TOC. Gotchas use WHEN/WRONG/RIGHT/GOTCHA format.

## Sources of truth
- Kalshi: docs.kalshi.com (verify live at session start if touching API code)
- Polymarket: docs.polymarket.com (Gamma / CLOB / data-api)
