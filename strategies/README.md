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

4. Run. The bundled `supertrend` strategy is the canonical working example.
   It takes both long and short trades, so it needs a futures config
   (`configs/futures.yaml`) — the default spot config rejects the shorts:

   ```bash
   # canonical runnable example (bundled strategy)
   python scripts/run_backtest.py --strategy supertrend --config futures.yaml

   # your own strategy
   python scripts/run_backtest.py --strategy my_alpha --config btc_4h.yaml
   ```

## Convention — code vs config

| File | Role |
|---|---|
| `strategies/<name>.py` | Strategy logic + trading parameters (ST_PERIOD, ST_MULT, etc.) as module constants |
| `configs/<env>.yaml` | Backtest environment: data source, costs, tick synthesis, reporting |

There is no `<name>.json` side-file. Trading parameters belong inside the
`.py` because they are part of the strategy code.

## Reference strategies

| File | Pattern |
|---|---|
| `_starter.py` | Boilerplate. Copy this to start a new strategy |
| `supertrend.py` | Pattern 2 — SuperTrend flip entry + swing-low/high SL and 1.5R TP evaluated on every synthesized tick |

The other example strategies (`buy_and_hold`, `ema_cross`,
`rsi_mean_reversion`, `ema_market_sl_tp`, `limit_demo`) have been archived
under `test_strategy/` and no longer live in `strategies/`.

## API reference

See `_reference.md` for the full StrategyAPI / lifecycle / types / patterns
dictionary.
