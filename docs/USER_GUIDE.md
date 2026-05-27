# tickweaver — User Guide

> 사용자 종단 흐름. 설치 → 데이터 → 전략 → 백테스트 → 결과 해석 → 튜닝 → 트러블슈팅.
> 빠른 시작은 [`backtest_quickstart.md`](backtest_quickstart.md), 전략 작성 패턴은
> [`strategy_authoring.md`](strategy_authoring.md), API 사전은
> [`strategies/_reference.md`](../strategies/_reference.md).

---

## 1. 프로젝트 소개

tickweaver 는 **OHLCV 데이터를 봉 내부 무작위 Tick 으로 합성한 뒤, 그 위에서
매매 전략을 백테스트**하는 프로젝트입니다 (plan.md §0).

핵심 차별화:
- **합성 tick (D12)**: 한 봉을 OHLC 만 보고 체결하는 일반 백테스트와 달리, 봉 내부
  가격 경로를 합성해서 LIMIT/STOP 체결 시점이 더 사실적
- **결정성 (P3)**: 같은 (data, config, seed) → bit-exact 동일 결과
- **C1~C7 계약 (P2)**: 합성 tick 이 봉의 OHLC 와 모순되지 않음을 수학적으로 보장

현 단계 비대상 (plan.md §1.3):
- 실거래 (Live) — M5 코드는 `_archive_live/` 로 동결 (D11)
- 외부 OHLCV 직접 입력 — CCXT 다운로드만 지원 (D10)
- 호가창 시뮬레이션 / 옵션·파생 그릭

---

## 2. 설치

```powershell
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate         # macOS/Linux

pip install -r requirements-dev.txt
pip install -e .
```

설치 검증:
```powershell
python -c "from tickweaver.tick_synthesis import list_tick_generators; print(list_tick_generators())"
# -> ['bridge', 'uniform']
```

Python 3.11 이상 필수 (D4). pyproject.toml 의 `requires-python = ">=3.11"`.

---

## 3. 데이터 다운로드 + 점검

### 3.1 CCXT 다운로드 (D15 — API key 불필요)

```powershell
python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" --timeframe 1h --since 2024-01-01 --until 2024-07-01
```

옵션:
- `--exchange`: `binance` (기본) / `okx` / `gateio`
- `--symbol`: `"BTC/USDT:USDT"` (USDT-M Perpetual swap)
- `--timeframe`: `1m` / `5m` / `15m` / `1h` / `4h` / `1d` 등
- `--since` / `--until`: ISO 또는 `YYYY-MM-DD`
- `--market-type`: `swap` (기본) / `future` / `spot`
- `--force-refresh`: 캐시 무시하고 재다운로드

**캐시 동작**: 같은 범위를 두 번 호출하면 캐시 hit. 부분적으로 부족하면 부족분만 추가 fetch (재개 다운로드).

저장 경로 (plan.md §4):
```
data/processed/<exchange>/<symbol_safe>/<market_type>/<timeframe>.parquet
```

### 3.2 데이터 카탈로그 / 무결성 점검

`inspect_data` 로 다운로드된 데이터 확인 (D13 — fail 안 함, 보고만):

```powershell
# 카탈로그 — data/processed/ 안의 모든 parquet 표
python scripts/inspect_data.py list

# 단일 파일 상세 리포트
python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

리포트 내용:
- 스키마 OK 여부 (P4 표준 OHLCV)
- duplicates / high<low / nonpositive price / negative volume 카운트
- **missing bars** + 첫 5개 gap 위치 + 누락 봉 수

결손이 있어도 백테스트는 그대로 진행됩니다 (D13). 알고만 있으면 됩니다.

### 3.3 데이터 출처 (D10)

현 단계는 CCXT 한 가지만 지원. CSV / Binance ZIP / 외부 임의 parquet 입력은
future work (plan.md §5, §13.2). `data/loaders/csv_loader.py`,
`binance_zip_loader.py` 는 frozen.

---

## 4. 전략 작성

### 4.1 시작 — `_starter.py` 복사

```powershell
copy strategies\_starter.py  strategies\my_alpha.py
```

`my_alpha.py` 의 `on_bar(bar)` 만 수정해도 굴러갑니다. 매매 파라미터 (예:
`RSI_PERIOD = 14`) 는 파일 상단의 모듈 상수로 들어가 있습니다 — json 사이드
파일 없음.

### 4.2 5 가지 라이프사이클 훅

| 훅 | 시점 |
|---|---|
| `on_init()` | 시작 직전 1회 |
| `on_bar(bar)` | 각 봉 닫힌 직후 |
| `on_tick(tick)` | 봉 내부 합성 tick 마다 |
| `on_fill(fill)` | 체결 시 |
| `on_deinit()` | 종료 직후 1회 |

### 4.3 주입 globals

전략 파일은 import 없이 `api`, `context` 가 바로 사용 가능. 매매 파라미터는
파일 상단 모듈 상수로 둠:

```python
RSI_PERIOD = 14            # 모듈 상수 — 여기서 튜닝

def on_bar(bar):
    api.market_buy(api.size_from_cash_pct(0.1, bar.close))
```

자세한 패턴은 [`strategy_authoring.md`](strategy_authoring.md), API 사전은
[`strategies/_reference.md`](../strategies/_reference.md).

---

## 5. 백테스트 실행

### 5.1 가장 짧은 호출 (D17)

```powershell
python scripts/run_backtest.py --strategy my_alpha
```

`--strategy` 자동 해석 — 다음 4 가지 모두 동일하게 동작:

```powershell
python scripts/run_backtest.py --strategy my_alpha
python scripts/run_backtest.py --strategy my_alpha.py
python scripts/run_backtest.py --strategy strategies/my_alpha.py
python scripts/run_backtest.py --strategy /abs/path/to/my_alpha.py
```

### 5.2 모든 옵션

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `--strategy <name>` | (필수) | 전략 (자동 해석 — `name` / `name.py` / `strategies/name.py` / 절대경로) |
| `--config <file>` | `configs/default.yaml` | 백테스트 환경 yaml. **확장자 포함 파일명**(예: `futures.yaml`) 입력 시 `configs/` 자동 prefix. 확장자 없는 `futures` 는 못 찾음 |
| `--out-dir <path>` | `reports/<strategy>_<UTC ts>/` | 결과 디렉토리 |
| `--dump-ticks N` | `0` | N 개 봉의 tick path 를 dump |
| `--no-progress` | 꺼짐 | tqdm 진행 표시줄 끄기 |
| `--viz` | 꺼짐 | finplot 차트 창 (post-hoc replay) |

### 5.3 진행 표시

기본으로 tqdm progress bar 가 봉 단위로 갱신:
```
60% ██████    | 300/500 [00:00, 1045.40bar/s, equity=9976]
```

100 봉마다 equity 라이브 갱신. progress 모드에서는 strategy 의 `api.log` 출력이 silent (progress 깨짐 방지).

---

## 6. 결과 해석

`reports/<strategy>_<UTC ts>/` 안의 산출물:

### 6.1 `report.html` — 한 페이지 요약

브라우저로 열어 보세요:
- **Metrics**: Final Equity, Total Return, Sharpe, Sortino, Max Drawdown, Calmar,
  Trades 수, Win rate, Profit factor
- **Equity curve + Drawdown** 두 단 PNG
- **Tick Synthesis (proof)**: generator / seed / n_bars / n_ticks_total / 샘플 봉 인덱스
- **Trades** 표 — 상위 50개 라운드트립

### 6.2 metrics.json

머신 가독 형식. 자동화 / 외부 분석에 사용:

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

### 6.3 equity.parquet / trades.parquet

pandas 로 열어 임의 분석:

```python
import pandas as pd
eq = pd.read_parquet("reports/my_alpha_xxx/equity.parquet")
trades = pd.read_parquet("reports/my_alpha_xxx/trades.parquet")

# 일별 수익률 분포
daily = eq.resample("1D").last().pct_change().dropna()
print(daily.describe())

# trade 평균 보유 시간
trades["holding_hours"] = (
    pd.to_datetime(trades["exit_ts"]) - pd.to_datetime(trades["entry_ts"])
).dt.total_seconds() / 3600
print(trades["holding_hours"].mean())
```

### 6.4 tick_summary.json — 합성 tick 검증

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

`generator` 와 `seed` 가 동일하면 같은 데이터 위에서 bit-exact 재현됩니다.

### 6.5 config_snapshot.json

실행 시 사용된 모든 config (yaml 본문 + 전략 경로 + 데이터 경로). 결과 재현용.

---

## 7. 파라미터 튜닝

### 7.1 단일 변수 sweep

`strategies/<your>.py` 상단의 모듈 상수 (예: `RSI_PERIOD`) 를 편집하고
`--out-dir` 로 결과 분리:

```powershell
# rsi_mean_reversion.py 의 RSI_PERIOD = 7
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p7

# RSI_PERIOD = 14 로 바꾼 뒤
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p14

# 21 로 바꾼 뒤
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p21
```

### 7.2 메트릭 비교 스크립트

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

### 7.3 과적합 경고

같은 데이터에서 파라미터를 너무 조정하면 **overfit**. 검증:
- **Out-of-sample**: 2022-2023 으로 튜닝 → 2024 데이터로 검증
- **Walk-forward**: rolling 6개월 학습 + 다음 1개월 검증
- **결과 안정성**: 인접 파라미터 (period 14 vs 13/15) 결과가 비슷해야 robust

---

## 8. uniform vs bridge 비교 (D16)

같은 데이터/전략에 두 합성 알고리즘으로 굴려 metrics 비교:

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

또는 단일 봉의 tick path 시각화:

```powershell
python scripts/compare_runs.py preview --o 100 --h 110 --l 90 --c 105 --n 64 --out reports/preview.png
```

**주의 (D16)**: 비교는 `compare_runs.py` 전용. `run_backtest.py` 와 `report.html`
은 한 가지 generator 결과만 표시.

---

## 9. 결과 외부로 활용

### 9.1 대시보드 / 외부 분석

`equity.parquet`, `trades.parquet`, `metrics.json` 을 그대로 다른 도구에서 import.
JSON 은 `--json` 옵션을 가진 inspect_data 와 일관 형식.

### 9.2 결정성 회귀

같은 seed → 동일 결과를 회귀 테스트로 보호:

```python
def test_alpha_regression(tmp_path):
    res = run_backtest(strategy_path="strategies/my_alpha.py", out_dir=tmp_path)
    # Baseline: 처음에 한 번 측정한 값
    assert res.final_equity == pytest.approx(10412.78, rel=0, abs=1e-9)
```

코드를 수정한 뒤 이 테스트가 깨지면 결과에 영향이 있다는 신호.

---

## 10. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `download_data` 가 NetworkError | 거래소 API 차단된 네트워크. 다른 네트워크 / VPN 시도 |
| 결과가 매번 다름 | seed 가 고정 안 됨. `configs/default.yaml` 의 `tick_synthesis.seed` 확인 |
| RSI/EMA value 가 None | 워밍업 미완료. `if not ind.is_warm: return` 가드 추가 |
| `strategy not found` | 자동 해석 시도 후도 실패. `strategies/<name>.py` 위치 확인 |
| `final_equity` 가 cash 만큼 작음 | broker 회계 버그 (선물/현물 혼합). 수정됨 — 캐시 갱신 (`find . -name '*.pyc' -delete`) |
| Windows 에서 .pyc stale | `find <src> -name '*.py' -exec touch {} +` 로 mtime 갱신 |
| n_trades = 0 인데 fills 있음 | 라운드트립 (entry → exit) 미완. 마지막 포지션 열려있음 |
| 데이터 다운로드 실패 | `configs/default.yaml` 의 `data.exchange`/`symbol`/`timeframe`/`start_date`/`end_date` 확인. 네트워크 / 거래소 차단 가능성도 점검 |
| progress 출력 + log 가 섞임 | progress 모드에서는 `api.log` 자동 silent. `--no-progress` 로 보임 |

---

## 11. FAQ

**Q. 실거래 가능?**
A. 현 단계 D11 — backtest only. M5 Live 코드는 `_archive_live/` 에 보존,
복원 절차는 `_archive_live/README.md`.

**Q. 다중 자산 / 다중 전략?**
A. 현 단계 D3 — 단일 자산만. multi 는 plan.md §13.1 의 future work.

**Q. API key 가 필요한가?**
A. 아니오 (D15). CCXT 다운로드는 public OHLCV endpoint 만 사용. `.env` 파일도
만들 필요 없음.

**Q. 결손 봉이 있는 데이터로 백테스트해도 되나?**
A. 됩니다 (D13). 결손 봉은 skip 됩니다. `inspect_data inspect <path>` 로 결손
위치만 미리 알아두세요. "12 봉 = 12 시간" 같은 시간 가정은 금지.

**Q. 새 인디케이터 / fee 모델 / tick generator 추가하려면?**
A. [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) 의 확장 시나리오 6가지 참고.

**Q. 수수료 / 슬리피지 모델 변경?**
A. `configs/default.yaml` 의 `execution.commission`, `execution.slippage` 편집.
모두 % 단위 (0.05 = 0.05%). 0 으로 두면 비활성. 거래소·계정별로 수수료가
다르면 거래소별 config 파일로 관리 (예: `configs/binance.yaml` commission=0.05,
`configs/bybit.yaml` commission=0.06). `commission` 입력값이 `BpsFeeModel` 로
전달돼 체결 `fee` 가 계산되고, viz 의 포지션 표 `Fee` 컬럼에 반영된다.

**Q. Sharpe 가 너무 높게 나오는데 의심스러워요.**
A. 짧은 백테스트 (수십~수백 봉) 는 연환산 과대. CAGR 도 마찬가지. 6개월 이상
데이터로 검증. + Out-of-sample 도 함께.
