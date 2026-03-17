# Snowden

Autonomous prediction market trading system for [Polymarket](https://polymarket.com). Scans 500+ live markets every 15 minutes, estimates true probabilities with Claude, sizes positions with the Kelly criterion, enforces hard risk limits, and executes trades on the Polymarket CLOB.

## How It Works

```
Scanner ──► Analyst ──► Kelly ──► Sentinel ──► Trader
                                                  │
              TimescaleDB ◄───── all stages log ──┘
                   │
                Grafana
```

Every cycle runs a five-stage pipeline:

1. **Scanner** — fetches all active markets from Polymarket's Gamma API and runs them through a 5-stage funnel (liquidity gate, efficiency scoring, strategy matching, Haiku triage) to find 10-15 tradeable opportunities
2. **Analyst** — calls Claude Opus for each candidate to estimate the true probability, independent of the market price. Applies Platt scaling to correct systematic LLM bias
3. **Kelly** — computes quarter-Kelly position sizes. Confidence-weighted edge must exceed 5% to trade
4. **Sentinel** — four hard risk checks (single position < 25%, portfolio heat < 80%, daily drawdown < 10%, correlated exposure < 40%). No exceptions. 10% drawdown triggers a full kill switch
5. **Trader** — places limit orders with a 3% slippage guard. Paper mode uses real market data but simulates fills

### Strategies

| Strategy | Signal | Edge Source |
|----------|--------|-------------|
| Theta Harvest | Mid >= 0.88 or <= 0.12 | Near-certain outcomes trade at a discount |
| Longshot Fade | Mid <= 0.08 or >= 0.92 | People overpay for lottery tickets |
| Stale Reprice | Low vol + wide spread | No one is watching; reality moved on |
| Partisan Fade | Political + mid 0.25-0.75 | Partisan money distorts prices |
| News Latency | Recent news + slow adjustment | Prices lag new information |
| Correlated Arb | Linked market mispricing | Related contracts diverge |

## Project Structure

```
snowden/
├── agents/
│   ├── analyst.py        # Claude Opus probability estimation
│   ├── chief.py          # Orchestrator — runs the 15-min cycle
│   ├── sentinel.py       # Risk checks + kill switch
│   └── trader.py         # Order execution with slippage guard
├── calibrate.py          # Platt scaling (logistic regression on log-odds)
├── config.py             # Pydantic Settings from env vars
├── env.py                # Gymnasium environment for backtesting
├── kelly.py              # Kelly criterion sizing (quarter-Kelly)
├── market.py             # Polymarket API client (Gamma + CLOB)
├── news.py               # RSS feed enrichment
├── scanner.py            # 5-stage market scanning funnel
├── sim.py                # Paper trading coordinator
├── store.py              # TimescaleDB persistence (asyncpg)
└── types.py              # Pydantic models, enums, Protocol interfaces

scripts/
├── paper_trade.py        # Run continuous paper trading
├── backtest.py           # Gymnasium parameter sweep
├── calibration_report.py # Brier score + reliability diagnostics
├── scan_once.py          # Single scan for debugging
└── resolve.py            # Backfill resolved outcomes

infra/
├── init.sql              # TimescaleDB schema (hypertables)
├── continuous_aggs.sql   # Materialized views for dashboards
├── grafana/              # Datasource + 3 pre-built dashboards
└── openclaw.json         # OpenClaw integration config

tests/                    # pytest + pytest-asyncio
```

## Setup

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- A Polymarket API key (for market data)
- An Anthropic API key (for Claude)

### Install

```bash
# Clone and install
git clone <repo-url> && cd snowden
pip install -e ".[dev]"

# Copy and edit environment config
cp .env.example .env
# Set: ANTHROPIC_API_KEY, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE

# Start infrastructure (TimescaleDB + Grafana)
docker compose up -d
```

### Run

```bash
# Paper trading (default — real data, simulated fills)
python scripts/paper_trade.py

# Single scan for debugging
python scripts/scan_once.py

# Backtest with parameter sweep
python scripts/backtest.py

# Calibration report
python scripts/calibration_report.py

# Resolve predictions against outcomes
python scripts/resolve.py
```

Grafana dashboards are at `http://localhost:3000` (overview, scanner funnel, risk).

## Configuration

All config flows through environment variables (or `.env`). Key parameters:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODE` | `paper` | `paper` or `live` |
| `BANKROLL` | `2000` | Starting capital (USDC) |
| `CYCLE_INTERVAL` | `900` | Seconds between cycles |
| `KELLY_DIVISOR` | `4.0` | Quarter-Kelly (lower = more aggressive) |
| `EDGE_THRESHOLD` | `0.05` | Minimum confidence-weighted edge to trade |
| `MAX_HEAT` | `0.80` | Max portfolio exposure |
| `MAX_SINGLE_POSITION` | `0.25` | Max single position as fraction of equity |
| `MAX_DAILY_DRAWDOWN` | `0.10` | Kill switch threshold |
| `MAX_CORRELATED` | `0.40` | Max exposure per market category |
| `ANALYST_MODEL` | `claude-opus-4-6-20250415` | LLM for deep analysis |
| `TRIAGE_MODEL` | `claude-haiku-4-5-20251001` | LLM for cheap pre-screening |

## Development

```bash
# Run tests
pytest

# Type checking
mypy snowden

# Lint
ruff check snowden
```

## Architecture Notes

- **Protocol-based backends** — `MarketClient` and `DataStore` are `Protocol` interfaces. Paper and live trading share the same pipeline with different clients injected at startup
- **Calibration loop** — raw LLM probability estimates are corrected via Platt scaling fitted on resolved predictions. The system improves as it accumulates data (minimum 50 resolved predictions to activate)
- **No LLM in risk management** — the Sentinel is pure math with hard limits. Four checks, no exceptions, no overrides
- **Full audit trail** — every tick, prediction, trade, and portfolio snapshot is logged to TimescaleDB hypertables with continuous aggregates powering Grafana dashboards
