# Backtest Quickstart -- first backtest in 30 minutes

> **Goal**: a first-time user runs the bundled example strategy `supertrend`
> on BTC/USDT 1h data and gets all the way to `report.html` within 30 minutes.
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

Download Binance BTC/USDT perpetual-futures 1h bars via the CCXT public
endpoint (D15 -- **no API key needed**):

```powershell
python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" --timeframe 1h --since 2024-01-01 --until 2024-07-01
```

-> `data/processed/binance/BTC-USDT-USDT/swap/1h.parquet` (~4380 bars)

> You can actually skip this step -- `run_backtest.py` reads the data range
> from the config and auto-downloads anything missing from the cache. Use the
> command above only when you want to pre-fetch.

**Inspect the data (optional)**:

```powershell
python scripts/inspect_data.py list
python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

`missing bars: 0` means a clean dataset. Even with gaps the backtest
proceeds (D13 skip-only policy); just know that they exist.

---

## 3. Prepare a strategy (1 min)

The bundled example strategy `strategies/supertrend.py` already ships with the
repo -- no need to copy anything. When SuperTrend flips bearish->bullish it goes
Long, when it flips bullish->bearish it goes Short, and it checks a swing
low/high stop-loss + 1.5R take-profit on **every synthesized intra-bar tick**.
This is a textbook Pattern 2 strategy (entry on `on_bar` + exit on `on_tick`).

```powershell
# Take a look
type strategies\supertrend.py
```

Trading parameters live as module constants at the top of the `.py` -- no json
side-files:

```python
ST_PERIOD = 10          # SuperTrend ATR length
ST_MULT = 3.0           # SuperTrend ATR multiplier
SWING_LOOKBACK = 2      # bars each side to confirm a swing low/high (the stop)
TP_R = 1.5              # take-profit = TP_R * risk (entry-to-SL distance)
SIZE_PCT = 0.2          # 20% of available cash per entry
```

> To start your own strategy, copy `strategies/_starter.py`:
> `copy strategies\_starter.py strategies\my_alpha.py`. Environment settings
> (capital / symbol / period / cost / ...) live in `configs/<env>.yaml`.

---

## 4. Run a backtest (1 min)

SuperTrend opens short positions, so it needs a **futures config
(`configs/futures.yaml`)**. The default `configs/default.yaml` is spot and
rejects the short (`SpotShortNotAllowedError`):

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml
```

A tqdm progress bar updates per bar; the final output directory is printed
at the end:

```
100% ██████████| 4368/4368 [00:04, 950bar/s, equity=10556]
final_equity = 10556.16 (initial = 10000.00, return = +5.56%)
```

**`--config` auto-resolution** -- a filename with an extension (e.g.
`futures.yaml`) is looked up automatically under `configs/`. Include a path
separator (e.g. `configs/futures.yaml`) and it is used as-is.

**`--strategy` auto-resolution** -- all four forms work identically:

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml
python scripts/run_backtest.py --strategy supertrend.py --config futures.yaml
python scripts/run_backtest.py --strategy strategies/supertrend.py --config futures.yaml
python scripts/run_backtest.py --strategy /abs/path/to/supertrend.py --config futures.yaml
```

> **(optional) View it as a chart** -- append `--viz` and a finplot window
> opens after the backtest. `--viz --stream` replays it as a streaming
> animation where each candle grows tick by tick. Install the viz extras
> first with `pip install -r requirements-viz.txt`.
> ```powershell
> python scripts/run_backtest.py --strategy supertrend --config futures.yaml --viz
> python scripts/run_backtest.py --strategy supertrend --config futures.yaml --viz --stream
> ```

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
| `tick_summary.json` | "Tick Synthesis (proof)" -- generator / seed / n_ticks |
| `config_snapshot.json` | Full config snapshot for reproducibility |

`metrics.json` example (from the run above):

```json
{
  "final_equity": 10556.16,
  "total_return": 0.0556,
  "cagr": 0.1148,
  "sharpe": 1.42,
  "sortino": 1.63,
  "max_drawdown": -0.0478,
  "calmar": 2.40,
  "n_trades": 41,
  "win_rate": 0.439,
  "profit_factor": 1.41
}
```

```powershell
# Open in a browser on Windows
start reports\supertrend_*\report.html
```

---

## 6. Tune parameters (5 min)

Edit the module constants at the top of `strategies/supertrend.py`:

```python
# strategies/supertrend.py
ST_PERIOD = 14         # make SuperTrend slower (fewer signals, less noise)
ST_MULT = 2.5          # tighter bands (flips more often)
SWING_LOOKBACK = 3     # stop placed further away (slower confirmation)
TP_R = 2.0             # take-profit at 2R (lower win rate, higher payoff)
SIZE_PCT = 0.3         # 30% per entry
```

Re-run:

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml
```

Separate results with `--out-dir` for parameter comparison:

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml --out-dir reports/st_tp2
```

---

## 7. uniform vs bridge comparison (optional, 5 min)

Compare both tick-synthesis algorithms on the same data and strategy
(D16 -- comparison is `compare_runs.py` only):

```powershell
python scripts/compare_runs.py backtest --strategy supertrend --config futures.yaml
```

```
metric              uniform        bridge
------------------  -------------  -------------
  final_equity            10556.1591      10255.8204
  total_return                0.0556          0.0256
  sharpe                      1.4162          0.6893
  max_drawdown               -0.0478         -0.0588
  n_trades                        41              41
  ...
```

Strategies using only `on_bar` produce identical results across generators.
But `supertrend` checks its stop-loss / take-profit in `on_tick` (on
intra-bar synthesized ticks), making it a Pattern 2 strategy, so **the two
results diverge** -- the synthesized tick path determines exactly when the
exit fires. That divergence is itself the proof that the synthesized ticks
are doing real work.

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

**Q. I get a `Cannot MARKET SELL in spot mode` error.**
A. SuperTrend opens short positions, so it needs a futures config. If you
omit `--config futures.yaml` it falls back to the default spot config
(default.yaml) and the short entry is blocked. Run it with
`--config futures.yaml`.

**Q. download_data fails with NetworkError.**
A. CCXT cannot reach the Binance API. (1) Check internet (2) some
corporate / school networks block exchange APIs -- try a different network
(3) sandbox environments may also block this -- run on a real machine.

**Q. I get too few / too many trades.**
A. SuperTrend flip frequency is driven by `ST_PERIOD` and `ST_MULT`. A
shorter period or lower multiplier flips more often, giving more trades;
the opposite gives fewer. A few dozen over 6 months of data is normal (the
example above is 41).

**Q. All values are 0 or NaN.**
A. No entry happens until the warm-up period ends (SuperTrend needs
`ST_PERIOD` + 1 bars). With too little data warm-up never completes. Use at
least 100 bars.

**Q. The progress bar is too long.**
A. Disable it with `--no-progress`.

**Q. Results change every run.**
A. They should not (P3 determinism). Same seed -> bit-exact same result.
Check `tick_synthesis.seed` in `configs/futures.yaml` is fixed.

**Q. report.html shows fewer trades than fills.**
A. Only completed round-trips (entry -> exit) count as trades. Each entry
and exit is a separate fill, so fills outnumber trades; a position still
open at the end is an unfinished trade.
