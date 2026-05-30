# tickweaver -- Developer Guide

> For developers maintaining or extending the codebase. Architecture, six
> extension scenarios, tests, debugging, release procedure.
> User-facing docs: [`USER_GUIDE_en.md`](USER_GUIDE_en.md).
> Quick start: [`backtest_quickstart_en.md`](backtest_quickstart_en.md).

---

## 1. Architecture overview

### 1.1 One-line definition

```
CCXT OHLCV download
    -> normalize (P4 standard schema)
    -> ReplayFeed (BarEvent stream)
    -> tick_synthesis (uniform | bridge, C1~C7 contract)
    -> BacktestEngine
        -> strategy.on_tick / on_bar
        -> BacktestBroker (MARKET / LIMIT / STOP / STOP_LIMIT)
    -> analytics
        -> equity.parquet / trades.parquet / fills.csv / metrics.json
        -> equity_curve.png / sample_tick_paths.png
        -> report.html
    -> (optional) viz.LiveChartHook
        -> finplot replay window (V2 determinism preserved)
```

### 1.2 Top-level directory

```
tickweaver/
├── pyproject.toml          # build + deps
├── requirements*.txt       # runtime / dev / viz / live (live archived)
├── src/tickweaver/         # library code
├── scripts/                # typer CLI thin wrappers
├── strategies/             # user space (gitignored)
├── tests/                  # unit + integration
├── configs/                # yaml configs (default.yaml at root)
├── docs/                   # this guide + user guide
└── data/, reports/, logs/  # gitignored
```

### 1.3 src/tickweaver module dependency

```
core/             # Protocol/ABC, dataclass, exceptions  (no deps)
utils/            # paths, seed, timeutils, logger, config
data/             # schema, normalizers, loaders/, feeds/
tick_synthesis/   # constraints, timestamps, validator, generator, strategies/
execution/        # fees, slippage, backtest_broker
strategy/         # api, file_strategy
engine/           # backtest_engine, runner
analytics/        # equity_curve, trades, metrics, report
viz/              # chart hook, recorder, finplot window (optional)
```

Imports flow top-to-bottom only. Layer violations are PR-blocked (P5).

---

## 2. Key decisions

| ID | Decision |
|---|---|
| D1 | Data source exchange priority: Binance -> OKX -> Gate.io |
| D2 | USDT-M Perpetual primary |
| D3 | Single asset (multi-symbol non-goal) |
| D4 | Python 3.11+ |
| D5 | pip + requirements*.txt |
| D8 | File-based strategy authoring (MT4 EA style) + module constants |
| D9 | Backtest = always synthesized-tick based |
| D10 | Current data source = CCXT only |
| D11 | Current scope = backtest only (M5 archived) |
| D12 | Synthesized-tick precision = methodology, not a goal |
| D13 | Missing OHLCV bars: skip-only |
| D14 | Single-threaded execution |
| D15 | No API key required at any stage |
| D16 | uniform vs bridge comparison = compare_runs.py only |
| D17 | run_backtest CLI = `--strategy` mandatory only + auto path resolution |

---

## 3. Core interfaces

```python
class DataLoader(Protocol):
    def load(self, symbol, timeframe, since, until) -> pd.DataFrame: ...
    # returns standard OHLCV (P4)

class TickGenerator(Protocol):
    name: str
    def generate(self, bar, n_ticks, rng) -> list[Tick]: ...
    # output must satisfy C1~C7

class Broker(Protocol):
    def submit(self, order) -> str: ...
    def cancel(self, order_id) -> bool: ...
    def positions(self) -> dict[str, Position]: ...
    def on_market_event(self, tick) -> list[Fill]: ...
```

A new implementation only needs to satisfy the Protocol. `runtime_checkable`
means `isinstance(x, Protocol)` works.

---

## 4. Six extension scenarios

### 4.1 Add a new tick generator

1. Create `src/tickweaver/tick_synthesis/strategies/<name>.py`
2. Register with `@register_tick_generator("<name>")`
3. Implement `generate(bar, n_ticks, rng) -> list[Tick]` (must satisfy C1~C7)
4. Add `from . import <name>` in `tick_synthesis/strategies/__init__.py`
   (triggers registration)
5. Update `tick_synthesis/__init__.py` imports if needed
6. `tests/unit/test_<name>_generator.py` -- pass the same hypothesis suite
   used for `uniform`

Example -- volatility-aware:

```python
# src/tickweaver/tick_synthesis/strategies/vol_aware.py
import numpy as np
from tickweaver.core.types import OHLCBar, Tick
from tickweaver.tick_synthesis.generator import register_tick_generator
from tickweaver.tick_synthesis.timestamps import distribute_uniform


@register_tick_generator("vol_aware")
class VolAwareTickGenerator:
    name: str = "vol_aware"

    def generate(self, bar: OHLCBar, n_ticks: int, rng) -> list[Tick]:
        # ... user logic (must satisfy C1~C7)
        # validator is called afterward
        ...
```

Validation: copy the `uniform` hypothesis suite verbatim into
`tests/unit/test_vol_aware_generator.py`.

### 4.2 Add a new indicator

1. Add the class to `src/tickweaver/strategy/indicators.py`
2. Common contract: `update(...)` / `value` property / `is_warm: bool` / `reset()`
3. Add to `__all__`
4. Unit test in `tests/unit/test_indicators.py` (numeric + property test)
5. Update the indicator table in `strategies/_reference.md` §8

```python
class StochasticRSI:
    def __init__(self, rsi_period=14, stoch_period=14):
        self._rsi = RSI(period=rsi_period)
        self._buf = deque(maxlen=stoch_period)
        self._stoch_period = stoch_period

    def update(self, price):
        rv = self._rsi.update(price)
        if rv is None:
            return None
        self._buf.append(rv)
        if len(self._buf) < self._stoch_period:
            return None
        lo = min(self._buf)
        hi = max(self._buf)
        if hi == lo:
            return 50.0
        return 100.0 * (rv - lo) / (hi - lo)
    # ... value / is_warm / reset
```

### 4.3 Add a new fee / slippage model

1. Add class to `src/tickweaver/execution/fees.py` or `slippage.py`
2. Satisfy `FeeModel` / `SlippageModel` Protocol (`fee()` / `adjust()`)
3. Expose yaml key in `configs/default.yaml` (if needed)
4. Wire yaml -> object mapping in `runner.py`

```python
# Volume-scaled slippage
class VolumeBasedSlippage:
    def __init__(self, base_bps=2.0, alpha=0.5):
        self.base_bps = base_bps
        self.alpha = alpha
        self._last_volume = None

    def adjust(self, price, side):
        # higher alpha -> larger slippage on large trades
        ...
```

### 4.4 Enable external OHLCV loaders (lift D10)

The `csv_loader.py` and `binance_zip_loader.py` are currently frozen.
Activation steps:

1. Export from `data/loaders/__init__.py`
2. Verify `CsvLoader` behavior in `data/loaders/csv_loader.py`
3. Configure cleanup policy in `configs/data/external_template.yaml`
   (D13-compatible)
4. (Optional) add `--from-csv` option to `inspect_data` CLI
5. Update plan.md D10 to lift the freeze

Key insight: external OHLCV -> `normalize_ohlcv()` -> rest of the pipeline
is the same as CCXT.

### 4.5 Add a new analytics metric

1. Add the new key in `compute_metrics()` (`src/tickweaver/analytics/metrics.py`)
2. Update the pretty mapping in `_metrics_table()` of `analytics/report.py`
3. Check `metrics.json` schema impact on downstream consumers

```python
def compute_metrics(...):
    ...
    metrics["information_ratio"] = ...
    metrics["recovery_factor"] = ...
```

### 4.6 Restore live broker (lift D11)

The frozen code in `_archive_live/` has its own README. Key steps:

1. Move `_archive_live/{ccxt_broker.py, live_engine.py, monitoring/, run_live.py}`
   back to their original locations
2. Enable `requirements-live.txt`
3. Verify `monitoring/{kill_switch, alerts, healthcheck}`
4. Run `docs/live_deployment_checklist.md` -- 24h testnet without incident
5. Remove the archived marker in plan.md D11

**Important**: do not break P1 (single-strategy code) -- the same strategy
`.py` must run unchanged in both backtest and live.

---

## 5. Test strategy (P8)

### 5.1 Test pyramid

```
        Integration (slow, few)
         tests/integration/test_e2e_smoke.py
              -> synthetic OHLCV -> backtest -> report.html
              -> determinism regression (same seed -> same final equity)
        Unit + hypothesis (many)
         tests/unit/  (10+ files)
              -> test_constraints / test_timestamps / test_validator
              -> test_uniform_generator / test_bridge_generator
              -> test_orders (LIMIT/STOP/STOP_LIMIT)
              -> test_indicators / test_ccxt_loader / test_catalog / test_paths
```

### 5.2 Hypothesis property tests

Both `uniform` and `bridge` must pass the same suite (C1~C7):

```python
@given(bar=bars(), n=st.integers(4, 256), seed=st.integers(0, 2**31 - 1))
@settings(max_examples=250)
def test_C1_to_C6(bar, n, seed):
    ticks = generator.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    validate_ticks(bar, ticks, n_min=4, n_max=512)
```

When you add a new generator, copy this suite verbatim -- it must pass to
be registered.

### 5.3 Determinism regression (P3)

`tests/integration/test_e2e_smoke.py::test_determinism_same_seed` --
same seed twice -> bit-exact same `final_equity`.

If this test breaks after a code change, the result is affected (could be
intentional or a bug).

### 5.4 Mock-only exchange tests

`tests/unit/test_ccxt_loader.py` -- `_FakeCcxtExchange` monkeypatch pattern.
Verifies pagination + cache + resume + normalization without sandbox
network access.

### 5.5 Quick runs

```powershell
# All
pytest

# One file
pytest tests/unit/test_indicators.py -v

# Hypothesis stats
pytest --hypothesis-show-statistics

# Determinism regression only
pytest tests/integration/test_e2e_smoke.py::test_determinism_same_seed -v
```

---

## 6. Debugging

### 6.1 Windows mount + .pyc stale (common)

**Symptom**: code changed but behavior unchanged.

**Cause**: Edit changed `.py` but mtime not refreshed -- stale `.pyc` wins.

**Fix**:

```powershell
# refresh mtimes -> .pyc invalidated on next import
find src -name "*.py" -exec touch {} +    # Linux / Mac / sandbox
# Windows PowerShell:
Get-ChildItem -Recurse src -Filter *.py | ForEach-Object { $_.LastWriteTime = Get-Date }

# or delete .pyc directly
find src -name "__pycache__" -type d -exec rm -rf {} +

# or use PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE="1"
python -B scripts/run_backtest.py ...
```

### 6.2 Broken determinism

**Symptom**: same seed, different result.

**Checklist**:

- Multi-threaded code? -> violates D14. Single-threaded only.
- Non-deterministic numpy reductions (sum, mean)?
- External RNG (random.random()) used outside SeedManager?
- `dict` / `set` iteration order dependence? (Python 3.7+ dicts ordered,
  but sets are not)

### 6.3 Strategy debugging

`api.log("event", **kv)` for structured logs -- visible with
`--no-progress`.

Or Python `breakpoint()`:

```python
def on_bar(bar):
    if some_condition(bar):
        breakpoint()    # inspect api.position(), api.equity in pdb
```

### 6.4 Tick synthesis inspection

`--dump-ticks N` saves N bars' worth of synthesized ticks to PNG / parquet:

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml --dump-ticks 10
# -> reports/<run>/sample_tick_paths.png
# -> reports/<run>/sample_ticks.parquet
```

`compare_runs.py preview` visualizes a single bar's uniform vs bridge path.

### 6.5 OHLCV inspection

`inspect_data inspect <path>` checks missing bars / integrity violations /
schema (D13 -- report only).

---

## 7. Release procedure

Internal use at this stage; PyPI release TBD.

Release steps:

1. Update version in `__init__.py` (semver)
2. Run full tests (`pytest --hypothesis-show-statistics`)
3. `git tag` (e.g. `v0.2.0`)
4. (optional) `python -m build` for wheels

Semver guide:

- **MAJOR**: breaking change to user strategy code / config yaml / public API
- **MINOR**: new feature (new indicator, new generator, ...)
- **PATCH**: bug fixes

---

## 8. Code style

- **Ruff** enforced (line-length=100, py311 target). Pre-PR:
  `ruff check src/ tests/ scripts/`.
- **mypy** recommended (strict=False), apply incrementally.
- **import-linter** -- layer-violation blocker. CI auto-check.
- **Avoid Korean docstrings in `.py` files** -- Windows mount cp949 ↔ UTF-8
  race condition. Internal code comments ASCII only; user-facing docs (md)
  can be Korean.
- **type hints** -- `from __future__ import annotations` + `|` syntax used
  consistently.

### 8.1 Adding dependencies

Edit both `requirements.txt` and `pyproject.toml`. Dev-only:
`requirements-dev.txt` + `[project.optional-dependencies] dev`.

---

## 9. Risks + mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Synthesized tick microstructure limits | Extrapolation bound | D12 -- precision is not a goal. Cover with slippage model |
| OHLC missing bars | Bars dropped | D13 -- skip-only |
| Lookahead | Overfit | Engine enforces submit != fill. External data is user responsibility |
| Broken determinism | Non-reproducible | Single-threaded (D14), SeedManager, regression tests |
| Windows .pyc stale | Debugging confusion | `touch` mtime refresh, delete `__pycache__` |
| Sandbox network blocked | Cannot verify real download | Mock-only tests (`_FakeCcxtExchange`). Validate on real machine |

---

## 10. Frequent dev questions

**Q. Add a new exchange (Bybit, Coinbase)?**
A. If CCXT supports it, data download works immediately -- just change
`--exchange bybit`. Broker adapters follow the `_archive_live/ccxt_broker.py`
`_BinanceAdapter` / `_OkxAdapter` pattern.

**Q. Multi-asset backtest?**
A. The D3 single-asset assumption is baked in deep (singular Position,
single-symbol BacktestBroker). Multi is future work -- requires major
Engine + Broker rewrite.

**Q. Add a new yaml section?**
A. Add a new dataclass to `BacktestConfig` in `utils/config.py` + update
`configs/default.yaml`.

**Q. Redirect logger to a file?**
A. Add a file handler in `configure_logging()` of `utils/logger.py`.
Currently stdout only.

**Q. Add CI?**
A. `.github/workflows/ci.yml` -- pytest + ruff + mypy + import-linter.
Not implemented yet; future work.

---

## 11. Reference docs

- [strategies/_reference_en.md](../strategies/_reference_en.md) -- StrategyAPI dictionary
- [docs/strategy_authoring_en.md](strategy_authoring_en.md) -- strategy authoring tutorial
- [docs/USER_GUIDE_en.md](USER_GUIDE_en.md) -- user end-to-end workflow
- [docs/backtest_quickstart_en.md](backtest_quickstart_en.md) -- 30-min first backtest

---

## 12. Next-step candidates

- **Backtest extensions**:
  - MT4-strategy-tester-like verbose visualization (partially done -- viz module)
  - Additional tick generators (volume-weighted, regime-switching)
  - Additional exchange data loader verification

- **External OHLCV input** (when D10 lifted):
  - Activate `csv_loader` / `binance_zip_loader`
  - External input -> bypass CCXT cache path

- **Live restoration** (when D11 lifted):
  - WebSocket live feed (ccxt.pro)
  - Hedge mode
  - Additional broker adapters

- **Infrastructure**:
  - GitHub Actions CI
  - PyPI release (`python -m build`)
