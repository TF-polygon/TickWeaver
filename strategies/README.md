# strategies/

User strategy files (MT4 EA style, single `.py` per strategy).

## Getting started

1. Copy `_starter.py` to your strategy file:

   ```bash
   cp strategies/_starter.py strategies/my_alpha.py
   ```

2. Edit trading parameters (module constants at the top) and `on_bar` /
   `on_tick` logic inside `my_alpha.py`.

3. Pick or create a yaml config under `configs/` (the yaml defines the
   environment: exchange / symbol / timeframe / period / costs).

4. Run:

   ```bash
   python scripts/run_backtest.py --strategy my_alpha
   python scripts/run_backtest.py --strategy my_alpha --config btc_4h.yaml
   ```

## Convention — code vs config

| File | Role |
|---|---|
| `strategies/<name>.py` | Strategy logic + trading parameters (RSI_PERIOD, SL_PCT, etc.) as module constants |
| `configs/<env>.yaml` | Backtest environment: data source, costs, tick synthesis, reporting |

There is no `<name>.json` side-file. Trading parameters belong inside the
`.py` because they are part of the strategy code.

## Reference strategies

| File | Pattern |
|---|---|
| `_starter.py` | Boilerplate. Copy this to start a new strategy |
| `buy_and_hold.py` | Smoke test (buys first bar, holds) |
| `ema_cross.py` | Pattern 1 — on_bar only (EMA cross entry + cross exit) |
| `rsi_mean_reversion.py` | Pattern 1 — on_bar only (RSI threshold) |
| `ema_market_sl_tp.py` | Pattern 2 — on_bar entry + on_tick market SL/TP exit |
| `limit_demo.py` | LIMIT / STOP order types demo |

## API reference

See `_reference.md` for the full StrategyAPI / lifecycle / types / patterns
dictionary.
