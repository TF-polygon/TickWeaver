# TickWeaver

> A backtest engine for OHLCV-based trading strategies. Reconstructs intra-bar
> price paths as **synthesized ticks**, then runs your strategy on top of them.

[![tests](https://img.shields.io/badge/tests-92%20passed-brightgreen)]()
[![hypothesis](https://img.shields.io/badge/hypothesis-2380%2B%20cases-success)]()
[![python](https://img.shields.io/badge/python-3.11+-blue)]()
[![license](https://img.shields.io/badge/license-MIT-lightgrey)]()

---

Most simple OHLC backtests fill orders only at bar open or close. Tick-level
data is expensive or has short retention. TickWeaver bridges the gap by
**synthesizing a plausible intra-bar tick path from OHLC alone**, with strict
mathematical guarantees so it never contradicts the bar.

## Key guarantees (the C1~C7 contract)

For every synthesized tick sequence on a bar `(O, H, L, C)`:

| # | Constraint | Meaning |
|---|---|---|
| C1 | `ticks[0] == O` | starts at bar open |
| C2 | `ticks[-1] == C` | ends at bar close |
| C3 | `min(ticks) == L` | bar low is hit |
| C4 | `max(ticks) == H` | bar high is hit |
| C5 | every `tick in [L, H]` | nothing escapes the bar |
| C6 | `n_min <= n <= n_max` | configurable count |
| C7 | same `(bar, n, seed)` -> bit-exact identical | deterministic |

Validated by `tick_synthesis/validator.py`. Fuzz-tested with **2380+ hypothesis
property cases**. Same suite must pass for any new generator.

## Quick start

```bash
# 1. Install (Python 3.11+)
python -m venv .venv && source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate                              # Windows
pip install -r requirements-dev.txt
pip install -e .

# 2. Download data via CCXT public endpoint (no API key required)
python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" \
    --timeframe 1h --since 2024-01-01 --until 2024-07-01

# 3. Run a backtest. --strategy auto-resolves to strategies/<name>.py
python scripts/run_backtest.py --strategy rsi_mean_reversion
```

Open `reports/<strategy>_<UTC ts>/report.html` in a browser.

## What you get

- **Six built-in streaming indicators**: `SMA`, `EMA`, `RSI`, `ATR`, `MACD`,
  `BollingerBands`. Common contract: `update / value / is_warm / reset`.
  Count-based (gap-safe), deterministic.
- **All four major order types**: `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`.
  LIMIT fills as maker (no slippage). STOP triggers as taker. Lookahead
  protection: an order submitted in `on_bar` fills from the FIRST tick of
  the NEXT bar.
- **Two synthesis algorithms**: `uniform` (default, conservative) and
  `bridge` (log-space Brownian bridge, more natural intra-bar paths).
  Direct comparison is isolated to `compare_runs.py` only.
- **HTML report** per run: metrics, equity curve + drawdown, trades table,
  and a "Tick Synthesis (proof)" section showing seed and per-bar statistics.
- **Live `tqdm` progress** with rolling equity update; auto-disabled in
  non-tty (e.g. pytest, CI).
- **Strategy authoring**: a single `.py` file with optional
  paired `.json` parameters. The engine injects `api`, `params`, and
  `context` into module globals.

## Strategy file example

```python
# strategies/rsi_mean_reversion.py
from tickweaver.strategy.indicators import RSI

rsi = None

def on_init():
    global rsi
    rsi = RSI(period=params.get("rsi_period", 14))

def on_bar(bar):
    rsi.update(bar.close)
    if not rsi.is_warm:
        return
    if rsi.value < params.get("oversold", 30) and api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.2, bar.close))
    elif rsi.value > params.get("overbought", 70) and not api.is_flat():
        api.close_position()
```

That's it. Run with:

```bash
python scripts/run_backtest.py --strategy rsi_mean_reversion
```

`--strategy` accepts any of these — all resolve to the same file:

```bash
--strategy rsi_mean_reversion
--strategy rsi_mean_reversion.py
--strategy strategies/rsi_mean_reversion.py
--strategy /abs/path/to/rsi_mean_reversion.py
```

See [`strategies/_reference.md`](strategies/_reference.md) for the full
API dictionary (signatures, types, patterns, pitfalls).

## Architecture (current scope)

```
CCXT OHLCV download
  -> normalize (standard schema, P4)
  -> ReplayFeed (BarEvent stream)
  -> tick_synthesis (uniform | bridge, C1~C7)
  -> BacktestEngine
       -> strategy.on_tick / on_bar
       -> BacktestBroker (MARKET / LIMIT / STOP / STOP_LIMIT)
  -> analytics
       -> equity.parquet, trades.parquet, metrics.json
       -> equity_curve.png, sample_tick_paths.png
       -> report.html
```

## Documentation

- [`docs/backtest_quickstart.md`](docs/backtest_quickstart.md) — first
  backtest in 30 minutes
- [`docs/strategy_authoring.md`](docs/strategy_authoring.md) — pattern
  catalog and pitfalls
- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) — end-to-end workflow,
  result interpretation, troubleshooting
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) — architecture,
  six extension scenarios, testing, debugging, release
- [`strategies/_reference.md`](strategies/_reference.md) — strategy
  API reference

## Current status

- **M0~M4 and M6 complete.** 92 tests passing (including 2380+ hypothesis
  property cases for the C1~C7 contract).
- **M5 (live trading) archived** to `_archive_live/` per decision D11.
  Restorable later.
- Current data source is **CCXT only** (D10). External OHLCV loaders
  (CSV / Binance ZIP) are frozen as future work.

## Locked decisions (excerpt)

| ID | Decision |
|---|---|
| D2 | USDT-M Perpetual (futures) is the primary market type |
| D8 | File-based strategy authoring (MT4 EA style) + JSON pairing |
| D10 | Current data source = CCXT only |
| D11 | Backtest only; live archived to `_archive_live/` |
| D12 | Synthetic tick precision = methodology, not a goal in itself |
| D13 | Missing OHLCV bars: skip-only (no interpolation, no fail) |
| D14 | Single-threaded execution |
| D15 | No API key required at any stage; `.env` not used |
| D16 | uniform vs bridge comparison is `compare_runs.py` only |
| D17 | `run_backtest.py` requires only `--strategy`; auto-resolves the path |

## Why "synthetic tick"?

Synthesizing intra-bar ticks is a **methodology to narrow the gap between
backtest and forward test**, not an end in itself (D12). It does not claim
to recover the true microstructure — it gives strategies a plausible path
that respects the bar's H/L/O/C. Pair it with conservative slippage and
fee models and treat the results as one estimate among several.

## Contributing

PRs welcome — please read [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)
first. Adding a new tick generator, indicator, or fee/slippage model is
covered there as worked examples.

When opening a PR:
- run `pytest --hypothesis-show-statistics` and ensure all 92+ tests pass
- keep new modules import-clean (no circular imports across layers)
