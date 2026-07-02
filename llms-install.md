# Installation guide for AI agents

You are an AI agent installing the `prediction-markets` skill (read-only Kalshi + Polymarket
market data). Pick the method matching your environment. No API keys, no pip installs, no
build step — the skill is a folder of markdown + Python-stdlib scripts.

## Claude Code (plugin, preferred)

```bash
claude plugin marketplace add iasdaso121/prediction-markets-skill
claude plugin install prediction-markets
```

Or from an interactive session: `/plugin marketplace add iasdaso121/prediction-markets-skill`
then `/plugin install prediction-markets`.

## Any SKILL.md-compatible agent (Claude Code, Codex, Cursor, etc.)

```bash
git clone --depth 1 https://github.com/iasdaso121/prediction-markets-skill /tmp/pms
mkdir -p ~/.claude/skills
cp -r /tmp/pms/skills/prediction-markets ~/.claude/skills/
rm -rf /tmp/pms
```

For non-Claude agents replace `~/.claude/skills/` with your skills directory
(e.g. `~/.agents/skills/`).

## skills CLI

```bash
npx skills add iasdaso121/prediction-markets-skill
```

## Verify the install

```bash
python3 ~/.claude/skills/prediction-markets/scripts/poly_markets.py --active --limit 2
```

Expected: a single JSON object on stdout with `venue`, `count`, `data` fields, exit code 0,
in under 5 seconds. Requirements: Python 3.10+, outbound HTTPS to `*.kalshi.com` and
`*.polymarket.com` only.

## Security notes (audit before trusting — it takes 5 minutes)

- Python standard library only; zero dependencies to install or compromise.
- Read-only: GET requests only, no auth headers, no keys, no wallets, no order placement.
- Network calls go exclusively to documented Kalshi/Polymarket API hosts (list in SECURITY.md).
- No telemetry. Every script is a single self-contained file under 400 lines.
