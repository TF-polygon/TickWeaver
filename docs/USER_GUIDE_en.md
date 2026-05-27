# tickweaver - User Guide

> End-to-end user workflow. Install -> data -> strategy -> backtest -> result
> interpretation -> tuning -> troubleshooting.
> Quick start: [`backtest_quickstart_en.md`](backtest_quickstart_en.md).
> Strategy patterns: [`strategy_authoring_en.md`](strategy_authoring_en.md).
> API dictionary: [`strategies/_reference_en.md`](../strategies/_reference_en.md).

---

## 1. Project overview

tickweaver **synthesizes intra-bar tick paths from OHLCV bars, then runs
strategies on top of them**. Key differentiators:

- **Synthesized ticks (D12)**: standard OHLC backtests fill orders only at
  bar open / close. tickweaver reconstructs a plausible intra-bar path so
  LIMIT / STOP / SL / TP fills land at more realistic prices.
- **Determinism (P3)**: same (data, config, seed) -> bit-exact same result.
- **C1~C7 contract (P2)**: synthesized ticks are mathematically guaranteed
  to never contradict the bar's `(O, H, L, C)`.

Out of scope at this stage:

- Live trading -- M5 code frozen under `_archive_live/` (D11)
- External OHLCV (CSV / Binance ZIP) -- CCXT only (D10)
- Orderbook simulation / option Greeks

---

## 2. Install

```powershell
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate         # macOS / Linux

pip install -r requirements-dev.txt
pip install -e .
```

Verify:

```powershell
python -c "from tickweaver.tick_synthesis import list_tick_generators; print(list_tick_generators())"
# -> ['bridge', 'uniform']
```

Python 3.11+ required (D4).

---

## 3. Data download + inspection

### 3.1 CCXT download (D15 - no API key needed)

For most cases the backtest runner downloads data automatically. Manual
download is only needed for pre-fetching or CI:

```powershell
python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" --timeframe 1h --since 2024-01-01 --until 2024-07-01
```

Options:

- `--exchange`: `binance` (default) / `okx` / `gateio`
- `--symbol`: `"BTC/USDT:USDT"` (USDT-M perpetual swap)
- `--timeframe`: `1m` / `5m` / `15m` / `1h` / `4h` / `1d` ...
- `--since` / `--until`: ISO or `YYYY-MM-DD`
- `--market-type`: `swap` (default) / `future` / `spot`
- `--force-refresh`: ignore cache and re-download

**Cache behavior**: the same range called twice -> cache hit. Partial
coverage -> fetches only the missing range (resume).

Storage path:

```
data/processed/<exchange>/<symbol_safe>/<market_type>/<timeframe>.parquet
```

### 3.2 Data catalog / integrity check

Use `inspect_data` (D13 -- never fails, only reports):

```powershell
# Catalog -- list all parquet files under data/processed/
python scripts/inspect_data.py list

# Single-file detail report
python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

Report contents:

- Schema OK (P4 standard OHLCV)
- duplicates / high<low / nonpositive price / negative volume counts
- **missing bars** + first 5 gap locations + total missing count

Missing bars are skipped silently in the backtest (D13). Just know they
exist; do not assume "12 bars == 12 hours".

### 3.3 Data sources (D10)

CCXT only at this stage. CSV / Binance ZIP / arbitrary parquet ingestion is
future work; the corresponding loader files are frozen.

---

## 4. Strategy authoring

### 4.1 Start by copying `_starter.py`

```powershell
copy strategies\_starter.py  strategies\my_alpha.py
```

Edit `on_bar(bar)` in `my_alpha.py` and you are ready. Trading parameters
(e.g. `RSI_PERIOD = 14`) live as module constants at the top of the `.py` --
no json side-files.

### 4.2 Five lifecycle hooks

| Hook | When called |
|---|---|
| `on_init()` | Once, just before the run starts |
| `on_bar(bar)` | Right after each bar closes |
| `on_tick(tick)` | For every synthesized tick |
| `on_fill(fill)` | On each fill |
| `on_deinit()` | Once, right after the run ends |

### 4.3 Injected globals

The strategy file uses `api` and `context` without imports. Trading
parameters live as module constants:

```python
RSI_PERIOD = 14            # module constant -- tune here

def on_bar(bar):
    api.market_buy(api.size_from_cash_pct(0.1, bar.close))
```

Patterns: [`strategy_authoring_en.md`](strategy_authoring_en.md).
API dictionary: [`strategies/_reference_en.md`](../strategies/_reference_en.md).

---

## 5. Running a backtest

### 5.1 Shortest invocation (D17)

```powershell
python scripts/run_backtest.py --strategy my_alpha
```

`--strategy` auto-resolves -- all four forms work:

```powershell
python scripts/run_backtest.py --strategy my_alpha
python scripts/run_backtest.py --strategy my_alpha.py
python scripts/run_backtest.py --strategy strategies/my_alpha.py
python scripts/run_backtest.py --strategy /abs/path/to/my_alpha.py
```

### 5.2 All options

| Flag | Default | Description |
|---|---|---|
| `--strategy <name>` | (required) | Strategy (auto-resolved -- `name` / `name.py` / `strategies/name.py` / abs path) |
| `--config <file>` | `configs/default.yaml` | Backtest env yaml. **Filename with extension** (e.g. `futures.yaml`) auto-prefixes under `configs/`. A bare `futures` (no extension) is not found |
| `--out-dir <path>` | `reports/<strategy>_<UTC ts>/` | Output directory |
| `--dump-ticks N` | `0` | Dump tick paths for N sample bars |
| `--no-progress` | off | Disable tqdm progress bar |
| `--viz` | off | Open the finplot post-hoc replay window |

### 5.3 Progress display

By default a tqdm progress bar updates per bar:

```
60% ██████    | 300/500 [00:00, 1045.40bar/s, equity=9976]
```

Equity is refreshed every 100 bars. In progress mode the strategy's
`api.log` output is silenced to avoid corrupting the progress bar
(use `--no-progress` to see logs).

---

## 6. Reading the results

Artifacts under `reports/<strategy>_<UTC ts>/`:

### 6.1 `report.html` -- single-page summary

Open in a browser:

- **Metrics**: Final Equity, Total Return, Sharpe, Sortino, Max Drawdown,
  Calmar, Trades, Win rate, Profit factor
- **Equity curve + Drawdown** two-panel PNG
- **Tick Synthesis (proof)**: generator / seed / n_bars / n_ticks_total /
  sample bar indices
- **Trades** table -- top 50 round-trips

### 6.2 metrics.json

Machine-readable format for automation / external analysis:

```json
{
  "final_equity": 10412.78,
  "total_return": 0.0413,
  "sharpe": 0.92,
  "sortino": 1.05,
  "max_drawdown": -0.052,
  "n_trades": 18,
  "win_rate": 0.61,
  "profit_factor": 1.42
}
```

### 6.3 equity.parquet / trades.parquet / fills.csv

Open with pandas for arbitrary analysis:

```python
import pandas as pd
eq = pd.read_parquet("reports/my_alpha_xxx/equity.parquet")
trades = pd.read_parquet("reports/my_alpha_xxx/trades.parquet")
fills = pd.read_csv("reports/my_alpha_xxx/fills.csv")

# Daily return distribution
daily = eq.resample("1D").last().pct_change().dropna()
print(daily.describe())

# Average trade holding time
trades["holding_hours"] = (
    pd.to_datetime(trades["exit_ts"]) - pd.to_datetime(trades["entry_ts"])
).dt.total_seconds() / 3600
print(trades["holding_hours"].mean())
```

`fills.csv` preserves nanosecond-precision timestamps -- inspect intra-bar
fills directly in Excel or pandas.

### 6.4 tick_summary.json -- synthesis verification

```json
{
  "generator": "uniform",
  "seed": 42,
  "n_bars": 4380,
  "n_ticks_total": 565123,
  "avg_ticks_per_bar": 129.0,
  "sample_bar_indices": [123, 456, 789, ...]
}
```

Same `generator` and `seed` -> bit-exact reproducible result on the same
data.

### 6.5 config_snapshot.json

Complete record of the config used for the run (yaml body + strategy path +
data source). Use for reproducibility.

---

## 7. Parameter tuning

### 7.1 Single-variable sweep

Edit the module constants at the top of `strategies/<your>.py` (e.g.
`RSI_PERIOD`) and separate results with `--out-dir`:

```powershell
# RSI_PERIOD = 7 in rsi_mean_reversion.py
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p7

# After changing to RSI_PERIOD = 14
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p14

# RSI_PERIOD = 21
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p21
```

### 7.2 Metric comparison snippet

```python
import json, pandas as pd
runs = ["rsi_p7", "rsi_p14", "rsi_p21"]
rows = []
for r in runs:
    m = json.load(open(f"reports/{r}/metrics.json"))
    m["run"] = r
    rows.append(m)
df = pd.DataFrame(rows).set_index("run")
print(df[["sharpe", "max_drawdown", "n_trades", "win_rate"]])
```

### 7.3 Overfitting warning

Tuning parameters too aggressively on the same data leads to **overfitting**.
Validation strategies:

- **Out-of-sample**: tune on 2022-2023, validate on 2024
- **Walk-forward**: rolling 6-month training + 1-month validation
- **Parameter stability**: adjacent values (period 14 vs 13/15) should give
  similar results -- if not, the result is fragile

---

## 8. uniform vs bridge comparison (D16)

Compare the two synthesis algorithms on the same data and strategy:

```powershell
python scripts/compare_runs.py backtest --strategy my_alpha
```

```
metric              uniform        bridge
final_equity            10412.78        10421.05
sharpe                      0.92            0.95
max_drawdown               -0.052          -0.049
n_trades                       18              18
```

Or visualize the tick path of a single bar:

```powershell
python scripts/compare_runs.py preview --o 100 --h 110 --l 90 --c 105 --n 64 --out reports/preview.png
```

**Note (D16)**: comparison is `compare_runs.py` only. `run_backtest.py` and
`report.html` always show a single generator's result.

---

## 9. Using results externally

### 9.1 Dashboards / external analysis

Import `equity.parquet`, `trades.parquet`, `fills.csv`, and `metrics.json`
directly into other tools.

### 9.2 Determinism regression test

Guard the same-seed -> same-result invariant with a test:

```python
def test_alpha_regression(tmp_path):
    res = run_backtest(strategy_path="strategies/my_alpha.py", out_dir=tmp_path)
    # Baseline: measured once and locked
    assert res.final_equity == pytest.approx(10412.78, rel=0, abs=1e-9)
```

If this test breaks after a code change, the result is affected.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `download_data` raises NetworkError | Exchange API blocked on this network. Try another network / VPN |
| Result changes each run | Seed not fixed. Check `tick_synthesis.seed` in `configs/default.yaml` |
| RSI / EMA value is None | Indicator not warm. Add `if not ind.is_warm: return` guard |
| `strategy not found` | Auto-resolution failed. Check `strategies/<name>.py` exists |
| `final_equity` shrinks to cash | Old broker accounting bug. Refresh caches (`find . -name '*.pyc' -delete`) |
| Stale .pyc on Windows | `find <src> -name '*.py' -exec touch {} +` to refresh mtimes |
| n_trades = 0 but fills exist | Round-trip (entry -> exit) incomplete. Position still open at end |
| Data download fails | Check `data.exchange` / `symbol` / `timeframe` / `start_date` / `end_date` in `configs/default.yaml`. Network / exchange access may also be blocked |
| progress output and logs interleave | In progress mode `api.log` is silenced automatically. Use `--no-progress` to see logs |

---

## 11. FAQ

**Q. Can I trade live?**
A. Not at this stage (D11 -- backtest only). M5 live code is preserved in
`_archive_live/`; see its README for the restore procedure.

**Q. Multi-asset or multi-strategy?**
A. Single-asset only at this stage (D3). Multi is future work.

**Q. Do I need an API key?**
A. No (D15). CCXT downloads use public OHLCV endpoints only. No `.env`
file required.

**Q. Can I backtest data with missing bars?**
A. Yes (D13). Missing bars are skipped. Use `inspect_data inspect <path>`
to know the gaps. Never assume "12 bars == 12 hours".

**Q. How do I add a new indicator / fee model / tick generator?**
A. See [`docs/DEVELOPER_GUIDE_en.md`](DEVELOPER_GUIDE_en.md) -- six worked
extension scenarios.

**Q. How do I change commission / slippage?**
A. Edit `execution.commission` and `execution.slippage` in
`configs/default.yaml`. Both use percent units (0.05 = 0.05%). Set to 0
to disable. When fees differ per exchange/account, keep one config per
exchange (e.g. `configs/binance.yaml` commission=0.05,
`configs/bybit.yaml` commission=0.06). The `commission` value feeds
`BpsFeeModel`, which computes each fill's `fee` and surfaces it in the
position table's `Fee` column in the viz.

**Q. My Sharpe looks suspiciously high.**
A. Short backtests (tens to hundreds of bars) over-annualize. Same for
CAGR. Validate with 6+ months of data, and pair with out-of-sample.
