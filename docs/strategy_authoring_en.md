# Strategy Authoring Guide -- file-based strategy authoring

> **Goal**: write your own MT4-EA-style file-based strategy.
> This document is a **tutorial + pattern catalog**. For signature / type
> dictionary see [`strategies/_reference_en.md`](../strategies/_reference_en.md).

---

## 1. One file = one strategy

```
strategies/
├── _starter.py              # boilerplate (committed; copy as your starting point)
├── _reference.md            # API dictionary (Korean / _en for English)
├── README.md
├── buy_and_hold.py          # simplest demo
├── ema_cross.py             # EMA cross (Pattern 1)
├── rsi_mean_reversion.py    # RSI mean reversion (Pattern 1)
├── ema_market_sl_tp.py      # EMA entry + intra-bar market SL/TP (Pattern 2)
├── limit_demo.py            # LIMIT / STOP demo
└── my_alpha.py              # user strategy (gitignore)
```

Conventions:

- One strategy = a single `.py` file. **Trading parameters live as module
  constants at the top of the file**.
- Backtest environment (capital / symbol / period / cost) lives in
  `configs/<env>.yaml`.
- Module-level variables persist across the backtest run (EA-globals style).
- Define only the hooks you need: `on_init`, `on_bar`, `on_tick`, `on_fill`,
  `on_deinit`.
- The engine auto-injects `api` and `context` into the module globals.

---

## 2. The simplest start -- one file

```python
# strategies/my_first.py
def on_bar(bar):
    if api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.5, bar.close))
```

Run:

```powershell
python scripts/run_backtest.py --strategy my_first
```

This one-liner buys 50% of the cash at the first bar and holds it
(buy-and-hold).

---

## 3. Five lifecycle hooks

| Hook | When | Common use |
|---|---|---|
| `on_init()` | Once at run start | Create indicator objects, reset module-level globals |
| `on_bar(bar)` | Right after each bar closes | Signal generation, entry / exit decisions |
| `on_tick(tick)` | For every synthesized tick | Trailing stops, margin checks |
| `on_fill(fill)` | On each fill | Fill log, position counter |
| `on_deinit()` | Once at run end | Final state dump |

**Lookahead protection (enforced by the engine)**:

- Orders submitted inside `on_bar(bar_t)` fill from the **first tick of the
  NEXT bar**.
- "Fill at this bar's close immediately" is not possible.
- Using `bar.close` for signals is safe.

---

## 4. Injected globals -- `api` / `context`

The strategy file uses these without imports. Trading parameters live as
module constants at the top of the file:

```python
FAST = 12                                    # trading parameter = module constant

def on_bar(bar):
    api.market_buy(0.05)                     # StrategyAPI - order gateway
    print(context.symbol, context.bar_index) # StrategyContext - meta info
```

| Object | Type | Role |
|---|---|---|
| `api` | `StrategyAPI` | Orders / positions / account (`_reference.md` §3) |
| `context` | `StrategyContext` | symbol, timeframe, bar_index, now (UTC) |

Convenience enums also auto-injected: `Side`, `OrderType`, `PositionSide`.

---

## 5. Pattern catalog

### 5.1 Buy-and-Hold

```python
def on_bar(bar):
    if api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.99, bar.close))
```

Always good to run as a benchmark alongside your strategy.

---

### 5.2 EMA cross (trend-following)

```python
from tickweaver.strategy.indicators import EMA

# Trading parameters as module constants
EMA_FAST = 12
EMA_SLOW = 26
SIZE_PCT = 0.2

ema_fast = None
ema_slow = None
prev_diff = None

def on_init():
    global ema_fast, ema_slow, prev_diff
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)
    prev_diff = None

def on_bar(bar):
    global prev_diff
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if not (ema_fast.is_warm and ema_slow.is_warm):
        return
    diff = ema_fast.value - ema_slow.value
    if prev_diff is None:
        prev_diff = diff
        return
    if prev_diff <= 0 < diff and api.is_flat():
        api.market_buy(api.size_from_cash_pct(SIZE_PCT, bar.close))
    elif prev_diff >= 0 > diff and not api.is_flat():
        api.close_position()
    prev_diff = diff
```

Key: trigger only when **the sign of the diff changes** between previous
and current bar (a true cross-over).

---

### 5.3 RSI mean reversion (counter-trend)

```python
from tickweaver.strategy.indicators import RSI

# Trading parameters as module constants
RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0
SIZE_PCT = 0.2

rsi = None

def on_init():
    global rsi
    rsi = RSI(period=RSI_PERIOD)

def on_bar(bar):
    rsi.update(bar.close)
    if not rsi.is_warm:
        return
    if rsi.value < OVERSOLD and api.is_flat():
        api.market_buy(api.size_from_cash_pct(SIZE_PCT, bar.close))
    elif rsi.value > OVERBOUGHT and not api.is_flat():
        api.close_position()
```

Full code: `strategies/rsi_mean_reversion.py`.

---

### 5.4 LIMIT entry + STOP/LIMIT exit (bracket)

```python
def on_bar(bar):
    if api.is_flat() and signal_now(bar):
        # LIMIT BUY slightly below close (gets dropped if not filled)
        limit_buy_price = bar.close * 0.997
        qty = api.size_from_cash_pct(0.3, limit_buy_price)
        if qty > 0:
            api.limit_buy(qty, limit_buy_price)

def on_fill(fill):
    # On entry fill, place SL/TP simultaneously
    pos = api.position()
    if pos.side == PositionSide.LONG and fill.side == Side.BUY:
        api.stop_sell(pos.qty, stop_price=pos.entry_price * 0.99)   # -1% stop
        api.limit_sell(pos.qty, price=pos.entry_price * 1.015)      # +1.5% target
```

Full code: `strategies/limit_demo.py`.

**Note**: when one of SL / TP fills, the other is NOT automatically
cancelled. Either detect the fill in `on_fill` and `api.cancel(order_id)`
the other, or let position size hitting zero handle it broker-side.

---

### 5.5 Trailing stop (using on_tick)

```python
TRAIL_PCT = 0.02

high_water = None

def on_bar(bar):
    global high_water
    if some_entry_signal(bar) and api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.1, bar.close))
        high_water = bar.close

def on_tick(tick):
    global high_water
    pos = api.position()
    if pos.side != PositionSide.LONG or high_water is None:
        return
    high_water = max(high_water, tick.price)
    if tick.price < high_water * (1 - TRAIL_PCT):
        api.close_position()
        high_water = None
```

Using `on_tick` means the result depends on the synthesized tick path
(differences surface when running uniform vs bridge via `compare_runs.py`).

---

## 6. Common pitfalls

### 6.1 Missing warm-up check

```python
def on_bar(bar):
    rsi.update(bar.close)
    if rsi.value < 30:    # X before warm-up: None < 30 -> TypeError
        ...
```

-> Always check `if not rsi.is_warm: return` or `if rsi.value is None: return`
first.

### 6.2 Lookahead assumption

```python
def on_bar(bar):
    # X reading future-bar data from anywhere is lookahead
    future_close = read_future(bar.timestamp)
```

The engine enforces "submit != fill" but cannot guard against external
data reads. That is your responsibility.

### 6.3 Repeated entry on same signal

```python
def on_bar(bar):
    if signal:
        api.market_buy(...)    # fires every bar the signal holds
```

-> Add `and api.is_flat()` to hold only one position.

### 6.4 Missing-bar time assumption

```python
def on_bar(bar):
    bars_held += 1
    if bars_held >= 12:        # X "12 bars == 12 hours"
        api.close_position()
```

Under D13 missing bars are silently skipped. Do not infer real time from
bar count. Use the counter for "12 bars later" -- never for "12 hours
later".

### 6.5 Float equality

```python
if rsi.value == 30.0:    # X risky float equality
```

-> Use inequality (`< 30.0`) or `math.isclose(rsi.value, 30.0)`.

---

## 7. Debugging

### 7.1 api.log

`api.log("event_name", **kv)` writes structured logs to stdout (silenced
in progress mode; use `--no-progress` or `show_progress=False` to see):

```python
def on_bar(bar):
    api.log("bar_open", close=bar.close, equity=api.equity)
```

### 7.2 Trace transactions

Open `reports/<run>/trades.parquet` in pandas:

```python
import pandas as pd
df = pd.read_parquet("reports/my_alpha_xxx/trades.parquet")
print(df.head())
print(df["pnl"].describe())
```

### 7.3 Leverage determinism

Same (data, config, seed) -> bit-exact same result (P3). Save the first
result as baseline; later code changes can be measured precisely against it.

### 7.4 Small data + dump_ticks

```powershell
# Dump 5 bars worth of tick streams to PNG / parquet
python scripts/run_backtest.py --strategy my_alpha --dump-ticks 5
```

Check `reports/<run>/sample_tick_paths.png` for the synthesized tick path.

---

## 8. Unit tests

To protect a strategy as a regression test, use a fixed yaml so seed +
data are locked, and baseline the first result:

```python
# tests/strategies/test_my_alpha_regression.py
import pytest
from tickweaver.engine.runner import run_backtest

def test_my_alpha_regression(tmp_path):
    res = run_backtest(
        strategy_path="strategies/my_alpha.py",
        config_path="configs/default.yaml",
        out_dir=tmp_path / "out",
        show_progress=False,
    )
    # baseline measured once and locked
    assert res.final_equity == pytest.approx(10412.78, rel=0, abs=1e-9)
    assert len(res.fills) > 0
```

If `tick_synthesis.seed` in the yaml is fixed, the result is bit-exact
reproducible -- this is enough to guard against accidental regressions.

---

## 9. Next steps

- Indicator dictionary: [strategies/_reference_en.md §3.7~3.16](../strategies/_reference_en.md)
- Generator comparison: `python scripts/compare_runs.py backtest --strategy <your>`
- Result interpretation / troubleshooting: [docs/USER_GUIDE_en.md](USER_GUIDE_en.md)
- Adding a new indicator / fee model: [docs/DEVELOPER_GUIDE_en.md](DEVELOPER_GUIDE_en.md)
