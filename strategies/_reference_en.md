# tickweaver -- Strategy Reference

> **What is this document?**
> A dictionary-style reference, similar to the F1 help in MT4 EA editor.
> When writing a file-based strategy (`strategies/<your_name>.py`) you
> can look up lifecycle hooks, injected variables, API methods, and types
> all in one place here.
>
> For tutorial / walkthrough material, see `docs/strategy_authoring_en.md`.
> This file is the **dictionary**.

---

## Table of contents

0. [Before you start](#0-before-you-start)
1. [Lifecycle hooks](#1-lifecycle-hooks-on_init--on_bar--on_tick--on_fill--on_deinit)
2. [Injected globals](#2-injected-globals--api--context)
3. [StrategyAPI method dictionary](#3-strategyapi-method-dictionary)
4. [Trading parameters as module constants](#4-trading-parameters-as-module-constants)
5. [Type dictionary](#5-type-dictionary)
6. [Common patterns](#6-common-patterns)
7. [Pitfalls and gotchas](#7-pitfalls-and-gotchas)
8. [FAQ](#8-faq)
9. [Indicator visualization (`--viz`)](#9-indicator-visualization---viz)

---

## 0. Before you start

### 0.1 One file = one strategy

```
strategies/
├── _starter.py        <- boilerplate (copy this to start)
├── _reference.md      <- this document (Korean)
├── _reference_en.md   <- this document (English)
├── README.md
└── my_alpha.py        <- your strategy
```

Trading parameters live inside the `.py` as **module constants** (e.g.
`RSI_PERIOD = 14`). There is no json side-file. The backtest environment
(symbol / period / costs / ...) lives in `configs/<env>.yaml`.

### 0.2 One-line execution

```powershell
python scripts/run_backtest.py --strategy my_alpha
```

`--strategy` auto-resolves -- all four forms below behave the same:

```powershell
python scripts/run_backtest.py --strategy my_alpha               # stem only
python scripts/run_backtest.py --strategy my_alpha.py            # basename
python scripts/run_backtest.py --strategy strategies/my_alpha.py # explicit
python scripts/run_backtest.py --strategy /abs/path/my_alpha.py  # absolute
```

`--config` and `--out-dir` have defaults; the one-line invocation above
is enough (D17).

### 0.3 Module-level variables = MT4 globals

Module-level variables in your strategy file persist across the backtest
run, like EA globals in MT4.

```python
# strategies/my_alpha.py
prev_close = 0.0          # <- module global = EA global
trade_count = 0

def on_init():
    global prev_close, trade_count
    prev_close = 0.0
    trade_count = 0
```

Right before `on_init` is called, the engine injects `api` and `context`
into the module globals. From that point on, any hook can call
`api.market_buy(...)` without imports.

Trading parameters belong at the top of the file as module constants:

```python
RSI_PERIOD = 14
OVERSOLD = 30.0
SIZE_PCT = 0.2
```

---

## 1. Lifecycle hooks (`on_init` / `on_bar` / `on_tick` / `on_fill` / `on_deinit`)

Each hook is **optional**. Hooks that are not defined are treated as no-op.

### 1.1 `on_init() -> None`

| Property | Value |
|---|---|
| Called | Once, just before the backtest starts |
| Arguments | None |
| Available | `api` and `context` are already injected |
| Typical use | Reset module-level state, validate parameters, create indicator objects |

```python
from tickweaver.strategy.indicators import EMA

EMA_FAST = 12
EMA_SLOW = 26

ema_fast = None
ema_slow = None

def on_init():
    global ema_fast, ema_slow
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)
    api.log("strategy initialized", fast=EMA_FAST)
```

---

### 1.2 `on_bar(bar: OHLCBar) -> None`

| Property | Value |
|---|---|
| Called | Right after each bar closes (before the next bar starts) |
| Arguments | `bar` -- the OHLCBar that just closed |
| Typical use | Signal generation, entry / exit decisions |

**Important -- lookahead protection**: orders submitted inside `on_bar`
fill **starting from the first tick of the next bar**. "Fill at this bar's
close at this bar's close price" is impossible (the engine enforces this).
So using `bar.close` as signal input is safe.

```python
def on_bar(bar):
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if ema_fast.value is None or ema_slow.value is None:
        return
    if ema_fast.value > ema_slow.value and api.is_flat():
        qty = api.size_from_cash_pct(0.1, bar.close)
        api.market_buy(qty)
```

---

### 1.3 `on_tick(tick: Tick) -> None`

| Property | Value |
|---|---|
| Called | For every synthesized tick inside a bar |
| Arguments | `tick` -- one synthesized price point |
| Typical use | Per-tick trailing stop, stop-loss monitoring, margin check |

**Important**: ticks are a **plausible price path** synthesized from OHLC,
not real orderbook / fill behavior (D12). Strategies that make fine-grained
microstructure assumptions (specific jump sizes, microstructure noise) are
fragile in forward tests.

```python
TRAIL_PCT = 0.02

def on_tick(tick):
    pos = api.position()
    if pos.side != PositionSide.LONG:
        return
    high_water = max(pos.entry_price, getattr(on_tick, "_hw", pos.entry_price))
    high_water = max(high_water, tick.price)
    on_tick._hw = high_water
    if tick.price < high_water * (1 - TRAIL_PCT):
        api.close_position()
```

---

### 1.4 `on_fill(fill: Fill) -> None`

| Property | Value |
|---|---|
| Called | Each time an order fills |
| Arguments | `fill` -- the Fill record |
| Typical use | Fill logging, position-size accounting, risk counters |

```python
def on_fill(fill):
    api.log("filled",
            side=fill.side.name,
            price=fill.price,
            qty=fill.qty,
            fee=fill.fee)
```

---

### 1.5 `on_deinit() -> None`

| Property | Value |
|---|---|
| Called | Once, right after the backtest ends |
| Arguments | None |
| Typical use | Final-state logging, custom metric dump |

---

## 2. Injected globals -- `api` / `context`

Right before `on_init` the engine injects two objects into the module
globals. No import is needed; any hook can use them directly.

| Name | Type | Role |
|---|---|---|
| `api` | `StrategyAPI` | Single gateway for orders / positions / account (§3) |
| `context` | `StrategyContext` | Current bar index / symbol / timeframe metadata |

For convenience, the engine also injects the enum types: `Side`,
`OrderType`, `PositionSide`.

`context` is rarely accessed directly -- `bar` already carries timestamp
and symbol. Use `context.symbol`, `context.timeframe` only when extra
metadata is needed.

---

## 3. StrategyAPI method dictionary

> Every order method gets an **idempotency key (`client_order_id`)
> auto-assigned**. Calling the same order twice in the same bar / same
> signal may have the second call rejected. Stick to "one signal = one
> call".
>
> All order methods return `order_id (str)`. Only `cancel()` returns `bool`.
> All `qty` arguments are auto-rounded via `round_qty()` inside the broker.

### 3.1 Order methods

| Method | Parameters | Fill behavior | Slippage |
|---|---|---|---|
| `api.market_buy(qty)` | `qty: float` (positive) | Fills at next-tick price | Applied |
| `api.market_sell(qty)` | `qty: float` (positive) | Fills at next-tick price (long close or short open) | Applied |
| `api.limit_buy(qty, price)` | `qty`, `price` (target buy) | Fills at **`price`** at the first tick where tick price ≤ `price` | None (maker) |
| `api.limit_sell(qty, price)` | `qty`, `price` (target sell) | Fills at **`price`** at the first tick where tick price ≥ `price` | None (maker) |
| `api.stop_buy(qty, stop_price)` | `qty`, `stop_price` (trigger) | Converts to market buy when tick price ≥ `stop_price` (breakout / short stop-loss) | Applied |
| `api.stop_sell(qty, stop_price)` | `qty`, `stop_price` (trigger) | Converts to market sell when tick price ≤ `stop_price` (long stop-loss) | Applied |
| `api.stop_limit_buy(qty, stop_price, limit_price)` | `qty`, `stop_price` (trigger), `limit_price` (cap) | After trigger, behaves like `limit_buy(qty, limit_price)` | None |
| `api.stop_limit_sell(qty, stop_price, limit_price)` | `qty`, `stop_price` (trigger), `limit_price` (cap) | After trigger, behaves like `limit_sell(qty, limit_price)` | None |
| `api.cancel(order_id)` | `order_id: str` | Cancels a pending order. Returns `False` if already filled | -- |

Fees are applied to every fill via the `commission` rate in config.
Slippage applies only to rows marked "Applied" via the `slippage` rate.

```python
api.market_buy(0.05)
api.limit_buy(0.05, bar.close * 0.997)              # LIMIT BUY 0.3% below close
api.stop_sell(pos.qty, pos.entry_price * 0.99)      # -1% stop-loss STOP
```

---

### 3.2 Close methods

| Method | Returns | Behavior |
|---|---|---|
| `api.close_position()` | `order_id (str)` or `None` | Closes current position with a market order opposite to its side. `None` if flat |
| `api.close_all()` | `list[str]` | Same as `close_position()` under single-asset (D3). Reserved as alias for future multi-symbol support |

---

### 3.3 Query methods / properties

| Name | Kind | Returns | Notes |
|---|---|---|---|
| `api.position()` | method | `Position` (§5.5) | `Position(side=FLAT, qty=0, ...)` when no position |
| `api.is_flat()` | method | `bool` | Convenience for `api.position().side == PositionSide.FLAT` |
| `api.cash` | property | `float` | Current cash balance |
| `api.equity` | property | `float` | `cash + unrealized PnL` |

---

### 3.4 Helper methods

| Method | Parameters | Returns | Use |
|---|---|---|---|
| `api.round_qty(qty)` | `qty: float` | `float` | Rounds down to exchange step size. Order methods already call this; use directly when verifying your own sizing math |
| `api.size_from_cash_pct(pct, price)` | `pct: float (0~1)`, `price: float` | `float` | `cash * pct / price` after `round_qty()`. Lets sizing auto-scale with the equity curve |
| `api.log(event, **kwargs)` | `event: str`, arbitrary `**kwargs` | `None` | Console logger. Output format: `<ts> [info] [<component>] <event>  key=value ...`. Silenced in progress mode (use `--no-progress` to see). Not included in `report.html` |

```python
qty = api.size_from_cash_pct(0.1, bar.close)   # 10% of cash
api.market_buy(qty)

api.log("entry signal", price=bar.close, ema=ema_fast.value)
```

---

## 4. Trading parameters as module constants

All trading parameters live at the top of the strategy `.py` as module
constants. There is no json side-file -- the yaml config under `configs/`
defines the backtest environment, and the `.py` defines the strategy.

```python
# strategies/my_alpha.py

# ── Trading parameters (edit here to tune) ──────────────────
RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0
SIZE_PCT = 0.2

# ── Module-level state (engine reload calls on_init to reset) ──
rsi = None


def on_init():
    global rsi
    rsi = RSI(period=RSI_PERIOD)
```

Benefits over a json side-file:

- IDE autocompletion / type inference
- Single source of truth -- no risk of the json and `.py` going out of sync
- Easier to read at a glance: the tunables are right above the logic that uses them

---

## 5. Type dictionary

> All dataclass / Enum definitions live in `src/tickweaver/core/types.py`.
> The tables below list the fields users interact with most often.

### 5.1 `OHLCBar`

| Field | Type | Description |
|---|---|---|
| `timestamp` | `pd.Timestamp` (UTC) | Bar close time (monotonic increasing) |
| `open` / `high` / `low` / `close` | `float` | OHLC |
| `volume` | `float` | Bar volume |
| `symbol` | `str` | e.g. `"BTC/USDT:USDT"` |
| `timeframe` | `str` | e.g. `"1h"` |

### 5.2 `Tick`

| Field | Type | Description |
|---|---|---|
| `timestamp` | `pd.Timestamp` (UTC) | Synthesized tick time |
| `price` | `float` | Synthesized price |
| `bar_index` | `int` | Index of the bar this tick belongs to |
| `tick_index_in_bar` | `int` | Position of this tick inside the bar |

### 5.3 `Order`

| Field | Type | Description |
|---|---|---|
| `order_id` | `str` | Engine-assigned ID |
| `client_order_id` | `str` | Idempotency key (auto-assigned) |
| `side` | `Side` | BUY / SELL |
| `type` | `OrderType` | MARKET / LIMIT / STOP / STOP_LIMIT |
| `qty` | `float` | Quantity after `round_qty` |
| `price` | `float \| None` | Set only for LIMIT |
| `stop_price` | `float \| None` | Set only for STOP variants |

### 5.4 `Fill`

| Field | Type | Description |
|---|---|---|
| `order_id` | `str` | Which order this fill belongs to |
| `side` | `Side` | BUY / SELL |
| `qty` | `float` | Actual filled quantity |
| `price` | `float` | Filled price (slippage already applied) |
| `fee` | `float` | Commission |
| `timestamp` | `pd.Timestamp` (UTC) | Fill time |
| `pnl_realized` | `float` | Realized PnL from this fill (non-zero on position reductions) |

### 5.5 `Position`

| Field | Type | Description |
|---|---|---|
| `side` | `PositionSide` | LONG / SHORT / FLAT |
| `qty` | `float` | Absolute size (direction encoded by `side`) |
| `entry_price` | `float` | Average entry price |
| `mark_price` | `float` | Current mark price |
| `unrealized_pnl` | `float` | Unrealized PnL |
| `liquidation_price` | `float \| None` | Liquidation price (futures isolated margin) |

### 5.6 Enums

```python
class Side(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

class MarketType(Enum):
    SPOT = "spot"
    USDT_M_PERPETUAL = "usdt_m_perpetual"
```

To import them inside strategy code (they are already auto-injected but
you may want an explicit import for type hints):

```python
from tickweaver.core.types import Side, OrderType, PositionSide
```

---

## 6. Common patterns

### 6.1 Plain EMA crossover

```python
from tickweaver.strategy.indicators import EMA

EMA_FAST = 12
EMA_SLOW = 26
SIZE_PCT = 0.1

ema_fast = None
ema_slow = None


def on_init():
    global ema_fast, ema_slow
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)


def on_bar(bar):
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if ema_fast.value is None or ema_slow.value is None:
        return
    bullish = ema_fast.value > ema_slow.value
    if bullish and api.is_flat():
        api.market_buy(api.size_from_cash_pct(SIZE_PCT, bar.close))
    elif (not bullish) and not api.is_flat():
        api.close_position()
```

### 6.2 Entry in `on_bar`, trailing exit in `on_tick`

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

### 6.3 Auto-close after N bars held

```python
HOLD_N = 5

bars_held = 0


def on_bar(bar):
    global bars_held
    if not api.is_flat():
        bars_held += 1
        if bars_held >= HOLD_N:
            api.close_position()
            bars_held = 0
        return
    if some_entry_signal(bar):
        api.market_buy(api.size_from_cash_pct(0.1, bar.close))
        bars_held = 0
```

### 6.4 Parameter validation in `on_init`

```python
EMA_FAST = 12
EMA_SLOW = 26


def on_init():
    if EMA_FAST >= EMA_SLOW:
        raise ValueError(f"EMA_FAST({EMA_FAST}) must be < EMA_SLOW({EMA_SLOW})")
```

---

## 7. Pitfalls and gotchas

### 7.1 The engine guards lookahead, but only at the engine boundary

The engine enforces "orders submitted in `on_bar` fill from the first tick
of the next bar", so using `bar.close` as a signal input is safe. But you
can still break lookahead by:

- Reading future data from an external file / cache
- Inferring future bar indices from `context`

→ Inside the strategy, only use **data that has already arrived**.

### 7.2 Synthesized tick limits (D12)

Ticks coming into `on_tick` are a plausible price path synthesized from
OHLC. The following assumptions break in forward tests:

- Microstructure noise / specific jump-size patterns
- Exact intra-bar timing (the spacing is just uniform or bridge)
- Volume-weighted ticks (not supported at this stage)

The synthesized tick is a **methodology** to narrow the gap between
backtest and forward test, not a microstructure reconstruction.

### 7.3 Missing bars are silently skipped (D13)

If the exchange dropped some bars, TickWeaver **skips them and continues
with the next available bar**. No interpolation, no resampling, no error.

Therefore:

- Do not assume the gap between `bar.timestamp` values is always one
  `timeframe`
- Do not infer bar index from elapsed time -- count actual bars received
- "12 bars held == 12 hours held" is wrong

### 7.4 Single-threaded by design (D14)

Heavy work inside the strategy slows the whole backtest. Heavy ML
inference inside `on_bar` / `on_tick` is discouraged.

### 7.5 Idempotency key + duplicate submission

Calling `market_buy` twice in the same `on_bar` with the same signal
may have the second call rejected (auto `client_order_id` collision).
Follow "one signal = one call". For adding to a position, fire from a
different explicit trigger.

### 7.6 Avoid float equality

```python
if ema_fast.value == ema_slow.value:    # X NaN / float equality is risky
if math.isclose(ema_fast.value, ema_slow.value, rel_tol=1e-9):    # OK
```

### 7.7 Always reset module globals in `on_init`

Make sure `on_init` resets all module-level state. The same interpreter
can run multiple backtests, and leftover state will pollute the next run.

```python
prev_close = 0.0   # module load: once


def on_init():
    global prev_close
    prev_close = 0.0   # <- reset every run
```

---

## 8. FAQ

**Q. Is there an indicator library?**
A. Yes -- `src/tickweaver/strategy/indicators.py` provides ten streaming
indicators:

| Class | Signature | Warm-up |
|---|---|---|
| `SMA(period)` | `update(price) -> mid \| None` | period bars |
| `EMA(period)` | `update(price) -> ema \| None` (SMA seed + alpha weighting) | period bars |
| `RSI(period=14)` | `update(price) -> rsi \| None` (Wilder smoothing) | period + 1 bars |
| `ATR(period=14)` | `update(high, low, close)` or `update_bar(bar)` | period bars |
| `SuperTrend(period=10, multiplier=3.0)` | `update(high, low, close)` or `update_bar(bar)` → `.value / .direction` (ATR-based trend filter / flip line) | period bars |
| `MACD(fast=12, slow=26, signal=9)` | `update(price)` → `.macd / .signal / .histogram` | slow + signal bars |
| `BollingerBands(period=20, mult=2.0)` | `update(price) -> (mid, upper, lower) \| None` | period bars |
| `Stochastic(period=14, k_smooth=3, d_smooth=3)` | `update(high, low, close) -> (K, D)` (double-smoothed %K/%D oscillator) | ~ period + k_smooth + d_smooth bars |
| `Pivot(period=5)` | `update(high, low)` → `.last_pivot_high / .last_pivot_low`, `is_higher_low()` / `is_lower_high()` (Williams-fractal swing high/low) | ≥ 2*period+1 bars |
| `HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)` | `update(open, high, low, close)` → HA candle + `.overlay`, `.dot_signal()` (Heikin-Ashi RSI candles + RSI overlay) | harsi_len + 1 bars |

Common pattern: `value` (None until warm), `is_warm: bool`, `reset()`.

```python
from tickweaver.strategy.indicators import EMA, RSI

ema_fast = EMA(period=12)
rsi = RSI(period=14)


def on_bar(bar):
    ema_fast.update(bar.close)
    rsi.update(bar.close)
    if ema_fast.is_warm and rsi.is_warm:
        if rsi.value < 30 and bar.close > ema_fast.value:
            api.market_buy(api.size_from_cash_pct(0.1, bar.close))
```

For additional indicators, write your own class in user code and keep its
state in module globals.

**Q. How do I write a custom indicator?**
A. Keep state in a module-level dict or class instance and call
`update(bar.close)` inside `on_bar(bar)`. The simplest pattern.

**Q. Multi-symbol support?**
A. Not at this stage (D3 single-asset). Multi-symbol is future work.

**Q. Multi-strategy in one run?**
A. Same D3 reason -- not supported.

**Q. Do I need an API key?**
A. No (D15). The backtest path does not require API keys at any stage.
CCXT downloads use public OHLCV endpoints only. No `.env` file needed.

**Q. uniform vs bridge -- which is better?**
A. The system does not answer that question (D16). Use
`scripts/compare_runs.py` to run the same data and strategy with both
algorithms and inspect the difference yourself.

**Q. Is `bar.timestamp` spacing always `timeframe`?**
A. No (D13). Missing bars are skipped. Do not assume regular intervals.

**Q. Does the engine really prevent lookahead?**
A. At the engine level -- yes, "submit != fill, fill on next tick" is
enforced. But pulling future data from external files is your code's
responsibility.

**Q. Can entry and exit happen inside the same bar?**
A. The market_buy submitted in `on_bar` fills on the first tick of the
next bar. From that point on, `on_tick` may trigger an exit on a later
tick of the same bar.

**Q. Can logs be embedded in report.html?**
A. Not at this stage. `api.log` writes to console only.

**Q. Where do result files go?**
A. Without `--out-dir`, `reports/<strategy_stem>_<UTC_timestamp>/` is
auto-generated (D17). It contains `report.html`, `metrics.json`,
`equity.parquet`, `trades.parquet`, `fills.csv`, `tick_summary.json`.

---

## 9. Indicator visualization (`--viz`)

### 9.1 Concept

Streaming indicators used by the strategy (`EMA` / `RSI` / `BollingerBands` /
custom) are rendered as lines on the chart. With `--viz` off all viz calls
are no-ops, so the calls are safe to leave in production strategies.

```python
def on_init():
    global ema
    ema = EMA(period=20)
    api.bind_indicator("EMA 20", ema)   # one-line registration

def on_bar(bar):
    ema.update(bar.close)               # use the indicator as usual
                                        # engine reads .value at the end of
                                        # each bar and forwards a sample
```

### 9.2 Indicator contract

The viz layer requires the following interface on any indicator object:

| Item | Kind | Role |
|---|---|---|
| `PANEL` | class variable, `str` | `"price"` overlays on the candle axis; any other string opens (or reuses) a sub-panel of that id |
| `SUBVALUES` | class variable, `tuple[str, ...] \| None` | `None` = single-value (engine reads `.value`); a tuple = multi-value (each element must equal an attribute name on the indicator) |
| `.value` | attribute / property | The latest value for single-value indicators. `None` means the indicator is not warm yet and the sample is skipped. NaN / inf are also skipped |
| `getattr(self, sub)` for `sub` in `SUBVALUES` | property/attribute | Per sub-line value for multi-value indicators |

> The `update(...)` signature is **not** dictated by viz. The strategy calls
> the indicator on its own terms (`.update(bar.close)`, `.update_bar(bar)`,
> `.update(h, l, c)`, ...).

### 9.3 Default metadata on the ten built-in indicators

| Class | `PANEL` | `SUBVALUES` |
|---|---|---|
| `SMA` | `"price"` | `None` |
| `EMA` | `"price"` | `None` |
| `RSI` | `"rsi"` | `None` |
| `ATR` | `"atr"` | `None` |
| `SuperTrend` | `"price"` | `None` |
| `MACD` | `"macd"` | `("macd", "signal", "histogram")` |
| `BollingerBands` | `"price"` | `("middle", "upper", "lower")` |
| `Stochastic` | `"stoch"` | `("K", "D")` |
| `Pivot` | `"price"` | `None` |
| `HARSI` | `"harsi"` | `("ha_open", "ha_high", "ha_low", "ha_close", "overlay")` |

### 9.4 Authoring a custom indicator

**Single-value** -- bar range (`high - low`)

```python
class BarRange:
    PANEL = "price"
    SUBVALUES = None

    def __init__(self):
        self._value = None

    def update_bar(self, bar):
        self._value = float(bar.high - bar.low)

    @property
    def value(self):
        return self._value
```

**Multi-value** -- Keltner Channel

```python
class KeltnerChannel:
    PANEL = "price"
    SUBVALUES = ("middle", "upper", "lower")   # must match attribute names

    def __init__(self, period=20, k=2.0):
        self.period = period
        self.k = k
        self._mid = None
        self._upper = None
        self._lower = None

    def update_bar(self, bar):
        ...  # compute and update self._mid / self._upper / self._lower

    @property
    def middle(self): return self._mid

    @property
    def upper(self):  return self._upper

    @property
    def lower(self):  return self._lower
```

A single `api.bind_indicator("KC", kc)` registers three sub-lines named
`"KC.middle"`, `"KC.upper"`, `"KC.lower"` on the same panel.

### 9.5 Style overrides

```python
api.bind_indicator("EMA 20", ema, color="#FF9800", width=2)
api.bind_indicator("RSI",    rsi, panel="oscillators")   # override PANEL default
```

Supported keys:

- `color` -- hex color, e.g. `"#FF9800"`
- `width` -- integer line width
- `style` -- pyqtgraph line style (`"--"`, may be ignored on older finplot)

Omit them to let the deterministic auto-palette (8-color cycle that avoids
the BUY/SELL blue and orange) choose.

### 9.6 External-value fallback -- `api.plot`

For ad-hoc signals not worth wrapping in a streaming class:

```python
def on_bar(bar):
    score = some_external_score(bar)
    api.plot("score", score, panel="score_panel", color="#E91E63")
```

The first call auto-registers; subsequent calls only emit samples. Unlike
`bind_indicator`, `plot` bypasses the PANEL contract and takes `panel=`
directly.

### 9.7 Pitfall checklist

| Pitfall | Symptom | Avoid by |
|---|---|---|
| `SUBVALUES` sub-name mismatches the attribute | Empty sub-line (sample skipped) | If `SUBVALUES = ("middle",)`, define `self.middle` or `@property middle` |
| `.value` returns a tuple but `SUBVALUES = None` | Sample silently skipped (not a scalar) | Multi-value indicators must declare `SUBVALUES` |
| `.value` property raises | Sample skipped + WARNING log -- backtest does **not** crash (Phase 5.3 fix) | Keep the property defensive |
| `bind_indicator` called inside `on_bar` | Idempotent (Phase 5.2 fix) so safe, but unclear intent | Bind in `on_init` |
| `PANEL` not defined | Falls back to `"price"` overlay | Declare explicitly for indicators whose units differ from price |
| Not comparing viz off vs on results | Hidden break of V2 (determinism) | Always run the same backtest with and without `--viz` and compare `final_equity` / fills |

### 9.8 Determinism (V2) guarantee

When `chart_hook=None` (i.e. `--viz` off), every viz call is a no-op.
Neither `bind_indicator` nor `plot` accumulate internal state. Therefore the
`final_equity` and fills of a backtest must be bit-identical with and
without `--viz`. If they drift, your indicator's `.value` is likely
side-effecting only on the viz path -- audit the implementation.

---

## Appendix -- one-line minimal strategy

```python
# strategies/buy_and_hold.py -- buy on the first bar, then hold
def on_bar(bar):
    if api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.99, bar.close))
```

```powershell
python scripts/run_backtest.py --strategy buy_and_hold
```

That is the entire strategy. Copy `_starter.py` to grow more elaborate
strategies from this minimum.

---

*This reference is updated alongside the codebase. The authoritative
sources for type signatures are `src/tickweaver/core/types.py` and
`src/tickweaver/strategy/api.py`.*
