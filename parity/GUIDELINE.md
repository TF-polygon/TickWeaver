# Parity Verification Guideline

> Procedure for comparing TickWeaver backtest results against TradingView PineScript within the
> **MEDIUM tolerance**. Reference strategies: EMA Cross (spot, long-only) + SuperTrend (futures, intra-bar SL/TP).

---

## 1. Purpose & Acceptance Criteria

Confirm that TickWeaver produces **aggregate results materially equivalent** to a certified tool
(TradingView PineScript).

**MEDIUM tolerance (acceptance conditions):**

| Metric | Criterion |
|---|---|
| Net Profit / Net Profit % | relative error ≤ 5% |
| Total Closed Trades | exact match or ±1 |
| Percent Profitable | relative error ≤ 5% |
| Profit Factor | relative error ≤ 5% |
| Max Drawdown % | relative error ≤ 5% |

**Out of scope**: exact per-trade price and timestamp matching is not part of this verification.
The goal is **aggregate metrics within 5%**.

---

## 2. TradingView Export Procedure

### 2.1 Setup

1. TradingView → apply the target strategy on the chart
2. **Timezone**: bottom-right corner of the chart → select **UTC** (must match TickWeaver data)
3. Set symbol, timeframe, and date range to **exactly match** your TickWeaver config
   (`parity/configs/parity_ema.yaml` or `parity_supertrend.yaml`)

### 2.2 Export Performance Summary

1. Click the **"Strategy Tester"** tab at the bottom of the chart
2. Select the **"Performance Summary"** tab
3. Top-right **"…"** → **"Export"** → **"Export Summary Data"**
4. Save as `<strategy>.tv_summary.csv`
   - EMA Cross → `parity/reference/ema_cross.tv_summary.csv`
   - SuperTrend → `parity/reference/supertrend.tv_summary.csv`

### 2.3 Export List of Trades

1. **"Strategy Tester"** tab → select **"List of Trades"** tab
2. Top-right **"…"** → **"Export"** → **"Export Trades Data"**
3. Save as `<strategy>.tv_trades.csv`
   - EMA Cross → `parity/reference/ema_cross.tv_trades.csv`
   - SuperTrend → `parity/reference/supertrend.tv_trades.csv`

> **Warning**: TradingView may export in a non-UTC timezone. Always set the chart timezone to
> UTC before exporting.

---

## 3. Alignment Checklist

If the settings on either side do not match, the comparison is meaningless. **Verify all items
before running.**

| Item | TickWeaver | TradingView setting |
|---|---|---|
| Exchange / Symbol | `parity/configs/parity_ema.yaml` → `data.exchange` / `data.symbol` | same chart symbol |
| Timeframe | `data.timeframe` | same chart timeframe |
| Date range | `data.start_date` ~ `data.end_date` | Strategy Tester → Date Range |
| Timezone | UTC (CCXT data) | bottom-right corner → UTC |
| Initial Capital | `10000 USDT` (`parity/configs/parity_ema.yaml`) | Properties → Initial Capital = **10000** |
| Commission | `0.05%` per side (`parity/configs/parity_ema.yaml`) | Properties → Commission = **0.05** (%) |
| Slippage | **0** (parity config) | Properties → Slippage = **0** |
| Position Sizing | `size_from_cash_pct(0.2, price)` = 20% of available cash | `percent_of_equity = 20` ² |
| Order fill timing | submitted in `on_bar` → fills on first tick of next bar | `calc_on_every_tick = false` (default) |
| Pyramiding | none (entry only when flat) | Properties → Pyramiding = **0** |

> The EMA Cross pinned values are confirmed in `parity/configs/parity_ema.yaml`
> (initial_capital=10000, commission=0.05%, slippage=0). For SuperTrend, use the values in
> `parity/configs/parity_supertrend.yaml` and enter them into TradingView verbatim.
>
> ² TradingView `percent_of_equity` sizes from *total equity*; TickWeaver `size_from_cash_pct`
> sizes from *available cash*. The two are equal when flat, but small differences grow as
> profits or losses accumulate (see §4-c).

---

## 4. Expected Divergence Catalog

Differences explainable by the causes below are considered within the acceptance criteria.

### (a) Indicator Warmup / Seeding Difference

| | Detail |
|---|---|
| **Cause** | Pine `ta.ema()` uses a simple-average (SMA) seed for the first few bars. TickWeaver `EMA` is count-based streaming — signals are suppressed (`is_warm=False`) until `period` bars have accumulated. |
| **Effect** | Early EMA values differ → first 1–2 signal timings may shift. |
| **Expected outcome** | Trade count difference of ±1 possible. Within tolerance. |

### (b) Intra-bar SL/TP Path Difference ← **largest expected divergence**

| | Detail |
|---|---|
| **Cause** | TickWeaver fills SL/TP on a synthesized tick path satisfying the C1–C7 contract (probabilistic yet deterministic). TradingView uses a **conservative worst-case** assumption inside the bar — when both SL and TP are reachable in a bar, the unfavourable direction is assumed to be hit first. |
| **Effect** | For SuperTrend (`on_tick` SL/TP management), which of SL or TP fills first on a given bar can differ → fill price differences, and in some cases trade count differences. |
| **Expected outcome** | No difference for EMA Cross (Pattern 1, `on_bar` only). Primary divergence source for SuperTrend. |
| **Key point** | The acceptance criterion is not "zero difference" but **"the difference has an explainable cause"**. |

### (c) Cash-vs-Equity Position Sizing Difference

| | Detail |
|---|---|
| **Cause** | TickWeaver sizes from available cash; TradingView sizes from equity. |
| **Effect** | Entry quantity drifts slightly as P&L accumulates. |
| **Expected outcome** | Sub-decimal level. Within the 5% aggregate threshold. |

### (d) Commission / Quantity Rounding

| | Detail |
|---|---|
| **Cause** | Differences in quantity truncation and commission decimal handling. |
| **Effect** | Negligible; proportional to commission size. |
| **Expected outcome** | Within the 5% aggregate threshold. |

### (e) Max Drawdown Measurement Basis Difference

| | Detail |
|---|---|
| **Cause** | TradingView computes MDD **intrabar** — open-trade unrealized equity swings within a bar are included. TickWeaver computes drawdown on the **bar-close** equity series (`analytics/metrics.py`). |
| **Effect** | On volatile bars TV's MDD reads larger. Even when all other metrics match, `max_drawdown_pct` is the metric most likely to approach or slightly exceed the 5% tolerance. |
| **Expected outcome** | Expected difference. Interpret `max_drawdown_pct` comparison results with this measurement-basis caveat in mind. |

---

## 5. Running the Comparison

### 5.1 Run compare

```bash
# EMA Cross
python -m parity.compare \
  --strategy ema_cross \
  --tw-report reports/parity_ema_cross/ \
  --tv-summary parity/reference/ema_cross.tv_summary.csv \
  [--tv-trades parity/reference/ema_cross.tv_trades.csv] \
  [--pct 0.05]

# SuperTrend
python -m parity.compare \
  --strategy supertrend \
  --tw-report reports/parity_supertrend/ \
  --tv-summary parity/reference/supertrend.tv_summary.csv \
  [--tv-trades parity/reference/supertrend.tv_trades.csv] \
  [--pct 0.05]
```

Options:

| Flag | Description |
|---|---|
| `--strategy` | `ema_cross` or `supertrend` |
| `--tw-report` | TickWeaver report directory (must contain `metrics.json` + `trades.parquet`) |
| `--tv-summary` | TradingView Performance Summary CSV path |
| `--tv-trades` | (optional) TradingView List of Trades CSV path |
| `--pct` | relative tolerance (default: `0.05` = 5%) |

### 5.2 Reading the output

`parity.compare` prints Markdown:

```markdown
# Parity report — ema_cross

| Metric | TickWeaver | TradingView | Δ abs | Δ % | OK |
| --- | ---: | ---: | ---: | ---: | :---: |
| net_profit | 556.1600 | 572.40 | 16.2400 | 2.84% | OK |
| net_profit_pct | 5.5616 | 5.72 | 0.1584 | 2.77% | OK |
| n_trades | 41 | 41 | 0 | 0.00% | OK |
| win_rate_pct | 43.9000 | 44.20 | 0.3000 | 0.68% | OK |
| profit_factor | 1.4100 | 1.44 | 0.0300 | 2.08% | OK |
| max_drawdown_pct | 4.7800 | 4.91 | 0.1300 | 2.65% | OK |

**PASS**
```

Column descriptions:

| Column | Content |
|---|---|
| **Metric** | normalized key name (printed in NORMALIZED_KEYS order) |
| **TickWeaver** | value derived from `metrics.json` |
| **TradingView** | value read from the Performance Summary CSV |
| **Δ abs** | absolute difference |
| **Δ %** | relative error = `|TW − TV| / |TV| × 100` |
| **OK** | `OK` = within tolerance / `X` = exceeded |

Final result: all metrics `OK` → **PASS**; any `X` → **FAIL**.

> `n_trades` uses an absolute tolerance (±1); all other metrics use relative error ≤ 5%.

---

## 6. End-to-End Reproduction Procedure

```
1. Download data
   python scripts/download_data.py \
       --exchange binance --symbol "BTC/USDT:USDT" \
       --timeframe 1h --since 2024-01-01 --until 2024-07-01

2. Run TickWeaver backtests (using parity-specific configs)

   # EMA Cross (spot)
   python scripts/run_backtest.py \
       --strategy test_strategy/ema_cross.py \
       --config parity/configs/parity_ema.yaml \
       --out-dir reports/parity_ema_cross/

   # SuperTrend (futures)
   python scripts/run_backtest.py \
       --strategy supertrend \
       --config parity/configs/parity_supertrend.yaml \
       --out-dir reports/parity_supertrend/

3. Run the same strategy in TradingView
   - Match symbol / timeframe / date range / settings (§3 checklist)
   - Export Performance Summary + List of Trades CSVs per §2

4. Place CSVs in the reference folder
   parity/reference/ema_cross.tv_summary.csv
   parity/reference/ema_cross.tv_trades.csv        (optional)
   parity/reference/supertrend.tv_summary.csv
   parity/reference/supertrend.tv_trades.csv       (optional)

5. Run compare (see §5.1 commands)

6. Record results in parity/RESULTS.md
```
