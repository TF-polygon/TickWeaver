# Backtest Quickstart — 30분 안에 첫 백테스트

> **목표**: 처음 시작하는 사용자가 30분 안에 BTC/USDT 1h 데이터로 번들 예시
> 전략 `supertrend` 를 굴려서 `report.html` 까지 보는 것.
>
> 이 가이드는 **새로 시작하는 사용자**가 대상. 더 깊은 내용은
> `docs/USER_GUIDE.md`, 전략 작성 패턴은 `docs/strategy_authoring.md`,
> API 사전은 `strategies/_reference.md` 를 보세요.

---

## 0. 시작 전 체크리스트

- [ ] Python 3.11+ 설치 (`python --version`)
- [ ] Git 설치 (선택, 프로젝트 클론용)
- [ ] PowerShell (Windows) 또는 zsh/bash (macOS/Linux)
- [ ] 디스크 공간 ~500MB (데이터 + 의존성)

---

## 1. 설치 (5분)

```powershell
# 프로젝트 루트로 이동
cd C:\Users\<you>\path\to\tickweaver

# 가상환경 생성 + 활성화
python -m venv .venv
.venv\Scripts\activate     # Windows PowerShell
# 또는
source .venv/bin/activate    # macOS/Linux

# 의존성 + 프로젝트 설치
pip install -r requirements-dev.txt
pip install -e .
```

설치 확인:
```powershell
python -c "import tickweaver; print(tickweaver.__version__)"
# -> 0.1.0
```

---

## 2. 데이터 다운로드 (3분)

CCXT public endpoint 로 Binance 에서 BTC/USDT 무기한 선물 1시간봉 다운로드 (D15 — **API key 불필요**):

```powershell
python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" --timeframe 1h --since 2024-01-01 --until 2024-07-01
```

→ `data/processed/binance/BTC-USDT-USDT/swap/1h.parquet` 에 ~4380 봉 저장.

> 사실 이 단계는 건너뛰어도 됩니다 — `run_backtest.py` 가 config 의 데이터
> 범위를 보고 캐시에 없으면 자동으로 받아옵니다. 미리 받아두고 싶을 때만
> 위 명령을 쓰세요.

**다운로드한 데이터 점검 (선택)**:
```powershell
python scripts/inspect_data.py list
python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

`missing bars: 0` 이면 깨끗한 데이터. 결손 있어도 D13 정책으로 백테스트는 그대로 진행됨 (알고만 있으면 됨).

---

## 3. 전략 준비 (1분)

번들 예시 전략 `strategies/supertrend.py` 가 이미 들어 있습니다 — 따로 복사할
필요가 없습니다. SuperTrend 가 약세→강세로 flip 하면 롱, 강세→약세로 flip 하면
숏 진입하고, swing low/high 손절 + 1.5R 익절을 **봉 내부 합성 tick 마다** 검사하는
전형적인 Pattern 2 (on_bar 진입 + on_tick 청산) 전략입니다.

```powershell
# 내용 살펴보기
type strategies\supertrend.py
```

매매 파라미터는 `.py` 파일 상단의 모듈 상수로 들어가 있습니다 — json 사이드
파일 없음:

```python
ST_PERIOD = 10          # SuperTrend ATR 길이
ST_MULT = 3.0           # SuperTrend ATR 배수
SWING_LOOKBACK = 2      # swing low/high 확정에 필요한 양쪽 봉 수 (= 손절선)
TP_R = 1.5              # 익절 = TP_R * 리스크(진입~손절 거리)
SIZE_PCT = 0.2          # 진입당 가용 cash 의 20%
```

> 자기 전략을 새로 만들려면 `strategies/_starter.py` 를 복사해서 시작하세요:
> `copy strategies\_starter.py strategies\my_alpha.py`. 환경 설정(자본 / 종목 /
> 기간 / 비용 등)은 `configs/<env>.yaml` 에 있습니다.

---

## 4. 백테스트 실행 (1분)

SuperTrend 는 숏 진입이 있으므로 **선물 config (`configs/futures.yaml`)** 가
필요합니다. 기본 `configs/default.yaml` 은 spot 이라 숏을 거부합니다
(`SpotShortNotAllowedError`).

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml
```

진행 표시줄 (tqdm) 이 봉 단위로 갱신되고, 끝나면 결과 디렉토리 출력:

```
100% ██████████| 4368/4368 [00:04, 950bar/s, equity=10556]
final_equity = 10556.16 (initial = 10000.00, return = +5.56%)
```

**`--config` 자동 해석** — 확장자 포함 파일명(예: `futures.yaml`)은 `configs/`
아래에서 자동으로 찾습니다. `configs/futures.yaml` 처럼 경로 구분자를 넣으면
그대로 사용합니다.

**`--strategy` 자동 해석** — 다음 4 가지 입력 모두 동일하게 동작:

```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml
python scripts/run_backtest.py --strategy supertrend.py --config futures.yaml
python scripts/run_backtest.py --strategy strategies/supertrend.py --config futures.yaml
python scripts/run_backtest.py --strategy /abs/path/to/supertrend.py --config futures.yaml
```

> **(선택) 차트로 보기** — `--viz` 를 붙이면 백테스트 후 finplot 창이 열립니다.
> `--viz --stream` 은 봉이 tick 단위로 자라는 스트리밍 리플레이입니다.
> 먼저 `pip install -r requirements-viz.txt` 로 viz 의존성을 설치하세요.
> ```powershell
> python scripts/run_backtest.py --strategy supertrend --config futures.yaml --viz
> python scripts/run_backtest.py --strategy supertrend --config futures.yaml --viz --stream
> ```

---

## 5. 결과 확인 (5분)

```powershell
# reports/<strategy>_<UTC ts>/ 디렉토리 확인
dir reports
```

생성된 파일들:

| 파일 | 내용 |
|---|---|
| `report.html` | **브라우저로 열기** — metrics / equity curve / trades 표 한 페이지 |
| `metrics.json` | Sharpe / Sortino / MDD / CAGR / win_rate / profit_factor 등 |
| `equity_curve.png` | 자본 곡선 + drawdown 시각화 |
| `equity.parquet` | 매 봉 끝 equity 시계열 (pandas 로 분석 가능) |
| `trades.parquet` | 라운드트립 trade 표 (entry/exit/PnL) |
| `tick_summary.json` | "Tick Synthesis (proof)" — generator/seed/n_ticks 통계 |
| `config_snapshot.json` | 실행 시 사용된 config 전체 스냅샷 (재현용) |

`metrics.json` 예시 (위 실행 기준):

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
# Windows 에서 브라우저로 열기
start reports\supertrend_*\report.html
```

---

## 6. 파라미터 튜닝 (5분)

`strategies/supertrend.py` 상단의 모듈 상수 편집:

```python
# strategies/supertrend.py
ST_PERIOD = 14         # SuperTrend 를 더 둔감하게 (시그널 ↓, 노이즈 ↓)
ST_MULT = 2.5          # 밴드를 더 좁게 (flip 더 자주)
SWING_LOOKBACK = 3     # 손절선을 더 멀리 (확정 더 느림)
TP_R = 2.0             # 익절을 2R 로 (승률 ↓, 손익비 ↑)
SIZE_PCT = 0.3         # 진입당 30%
```

다시 실행:
```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml
```

`--out-dir` 로 결과 디렉토리 명시 가능 — 여러 파라미터 비교용:
```powershell
python scripts/run_backtest.py --strategy supertrend --config futures.yaml --out-dir reports/st_tp2
```

---

## 7. uniform vs bridge 비교 (선택, 5분)

같은 데이터/전략에 두 합성 알고리즘 비교 (D16 — 비교는 `compare_runs.py` 전용):

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

`on_bar` 만 쓰는 전략은 두 generator 결과가 동일합니다. 하지만 `supertrend` 는
손절/익절을 `on_tick` (봉 내부 합성 tick) 에서 검사하는 Pattern 2 전략이라
**두 결과가 갈립니다** — 합성 tick 경로가 청산 시점을 좌우하기 때문입니다.
바로 이 차이가 "합성 tick 이 일하고 있다" 는 증거입니다.

---

## 다음 단계

- [docs/strategy_authoring.md](strategy_authoring.md) — 자신만의 전략 작성하기
- [strategies/_reference.md](../strategies/_reference.md) — StrategyAPI 사전형 레퍼런스
- [docs/USER_GUIDE.md](USER_GUIDE.md) — 결과 해석 / 트러블슈팅 / 고급 워크플로

---

## FAQ

**Q. `Cannot MARKET SELL in spot mode` 에러가 납니다.**
A. SuperTrend 는 숏 진입이 있어 선물 config 가 필요합니다. `--config futures.yaml`
을 빠뜨리면 기본 spot config (default.yaml) 로 돌아가 숏 진입에서 막힙니다.
`--config futures.yaml` 을 붙여 실행하세요.

**Q. download_data 가 NetworkError 로 실패합니다.**
A. CCXT 가 Binance API 에 접속 못 함. (1) 인터넷 연결 확인 (2) 일부 회사/학교 네트워크는 거래소 API 차단 — 다른 네트워크에서 시도 (3) sandbox 환경에서는 안 됨 (실 PC 에서 실행).

**Q. 트레이드가 너무 적게 / 많이 나옵니다.**
A. SuperTrend flip 빈도는 `ST_PERIOD` 와 `ST_MULT` 가 좌우합니다. period 를 줄이거나
mult 를 낮추면 flip 이 잦아져 트레이드가 늘고, 반대로 하면 줄어듭니다. 6개월 데이터로
수십 건이 정상입니다 (위 예시는 41건).

**Q. 모든 수치가 0 또는 NaN 입니다.**
A. 워밍업 (SuperTrend 는 `ST_PERIOD` + 1 봉) 까지 진입 안 함. 데이터가 너무 짧으면
워밍업을 못 끝냅니다. 최소 100봉 이상 데이터 권장.

**Q. progress bar 가 너무 길어 보기 싫어요.**
A. `--no-progress` 플래그로 끄세요.

**Q. 매번 다른 결과가 나옵니다.**
A. 그래선 안 됩니다 (P3 결정성). 같은 seed 면 bit-exact 동일 결과. `configs/futures.yaml` 의 `tick_synthesis.seed` 가 고정인지 확인.

**Q. report.html 의 trades 가 fills 보다 적습니다.**
A. 라운드트립 (entry → exit) 이 완성된 trade 만 trades 로 셉니다. 진입/청산 체결이
각각 fill 이므로 fills 수가 더 많고, 마지막에 포지션이 열려있으면 그건 미완 trade.
