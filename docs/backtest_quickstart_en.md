# Backtest Quickstart -- first backtest in 30 minutes

> **Goal**: new users run an RSI strategy on BTC/USDT 1h data and view
> `report.html` within 30 minutes.
>
> This guide targets **first-time users**. For deeper material see
> `docs/USER_GUIDE_en.md`; for strategy patterns
> `docs/strategy_authoring_en.md`; for the API dictionary
> `strategies/_reference_en.md`.

---

## 0. Pre-flight checklist

- [ ] Python 3.11+ installed (`python --version`)
- [ ] Git installed (optional, for cloning)
- [ ] PowerShell (Windows) or zsh / bash (macOS / Linux)
- [ ] ~500 MB free disk (data + dependencies)

---

## 1. Install (5 min)

```powershell
# Move to project root
cd C:\Users\<you>\path\to\tickweaver

# Create + activate venv
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# or
source .venv/bin/activate          # macOS / Linux

# Dependencies + project
pip install -r requirements-dev.txt
pip install -e .
```

Verify:

```powershell
python -c "import tickweaver; print(tickweaver.__version__)"
# -> 0.1.0
```

---

## 2. Data download (3 min)

In most cases the backtest runner will auto-download for you. To pre-fetch
manually use the CCXT public endpoint (D15 -- **no API key needed**):

```powershell
python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" --timeframe 1h --since 2024-01-01 --until 2024-07-01
```

-> `data/processed/binance/BTC-USDT-USDT/swap/1h.parquet` (~4380 bars)

**Inspect the data (optional)**:

```powershell
python scripts/inspect_data.py list
python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

`missing bars: 0` means a clean dataset. Even with gaps the backtest
proceeds (D13 skip-only policy); just know that they exist.

---

## 3. Prepare a strategy (2 min)

Copy `_starter.py`:

```powershell
copy strategies\_starter.py  strategies\my_alpha.py
```

Trading parameters (e.g. `RSI_PERIOD = 14`) live as module constants at the
top of the `.py` -- no json side-files. Environment settings (capital /
symbol / period / cost / ...) live in `configs/<env>.yaml`.

Or use the built-in RSI mean-reversion strategy as-is:

```powershell
# strategies/rsi_mean_reversion.py already exists
type strategies\rsi_mean_reversion.py
```

---

## 4. Run a backtest (1 min)

D17 -- only `--strategy` is mandatory:

```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion
```

A tqdm progress bar updates per bar; the final output directory is printed
at the end:

```
100% ██████████| 4380/4380 [00:14, 305bar/s, equity=10412]
final_equity = 10412.78 (initial = 10000.00, return = +4.13%)
```

**`--strategy` auto-resolution** -- all four forms work:

```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion
python scripts/run_backtest.py --strategy rsi_mean_reversion.py
python scripts/run_backtest.py --strategy strategies/rsi_mean_reversion.py
python scripts/run_backtest.py --strategy /abs/path/to/x.py
```

---

## 5. View results (5 min)

```powershell
# Look inside reports/<strategy>_<UTC ts>/
dir reports
```

Generated artifacts:

| File | Contents |
|---|---|
| `report.html` | **Open in a browser** -- metrics, equity curve, trades table on one page |
| `metrics.json` | Sharpe / Sortino / MDD / CAGR / win_rate / profit_factor ... |
| `equity_curve.png` | Equity curve + drawdown plot |
| `equity.parquet` | Per-bar equity time series (pandas-friendly) |
| `trades.parquet` | Round-trip trades (entry / exit / PnL) |
| `fills.csv` | Raw fills with nanosecond timestamps |
| `tick_summary.json` | "Tick Synthesis (proof)" -- generator / seed / n_ticks |
| `config_snapshot.json` | Full config snapshot for reproducibility |

```powershell
# Open in a browser on Windows
start reports\rsi_mean_reversion_*\report.html
```

---

## 6. Tune parameters (5 min)

Edit the module constants at the top of `strategies/rsi_mean_reversion.py`:

```python
# strategies/rsi_mean_reversion.py
RSI_PERIOD = 21
OVERSOLD = 25.0
OVERBOUGHT = 75.0
SIZE_PCT = 0.3
```

Re-run:

```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion
```

Separate results with `--out-dir` for parameter comparison:

```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p21
```

---

## 7. uniform vs bridge comparison (optional, 5 min)

Compare both tick-synthesis algorithms on the same data and strategy
(D16 -- comparison is `compare_runs.py` only):

```powershell
python scripts/compare_runs.py backtest --strategy rsi_mean_reversion
```

```
metric              uniform        bridge
------------------  -------------  -------------
  final_equity            10412.78        10412.78
  sharpe                      0.92          0.92
  ...
```

Strategies using only `on_bar` produce identical results across generators
(expected). Differences only surface in strategies that use `on_tick`
trailing logic.

---

## Next steps

- [docs/strategy_authoring_en.md](strategy_authoring_en.md) -- write your
  own strategy
- [strategies/_reference_en.md](../strategies/_reference_en.md) --
  StrategyAPI dictionary
- [docs/USER_GUIDE_en.md](USER_GUIDE_en.md) -- result interpretation,
  troubleshooting, advanced workflow

---

## FAQ

**Q. download_data fails with NetworkError.**
A. CCXT cannot reach the exchange API. (1) Check internet (2) some
corporate / school networks block exchange APIs -- try a different network
(3) sandbox environments may also block this -- run on a real machine.

**Q. RSI triggers too rarely.**
A. With 21 days of data, 1~2 signals is normal. Use 6 months to 1 year of
data, or relax oversold / overbought thresholds to 35 / 65.

**Q. All values are 0 or NaN.**
A. No entry happens until the warm-up period ends (RSI period + 1 bars).
With fewer than 14 bars RSI never warms up. Use at least 100 bars.

**Q. The progress bar is too long.**
A. Disable it with `--no-progress`.

**Q. Results change every run.**
A. They should not (P3 determinism). Same seed -> bit-exact same result.
Check `tick_synthesis.seed` in `configs/default.yaml` is fixed.

**Q. report.html shows 0 trades but there are fills.**
A. Only completed round-trips (entry -> exit) count as trades. If a
position is open at the end, it is an unfinished trade.
