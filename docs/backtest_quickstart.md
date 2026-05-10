# Backtest Quickstart — 30분 안에 첫 백테스트

> **목표**: 처음 시작하는 사용자가 30분 안에 BTC/USDT 1h 데이터로 RSI 전략을
> 굴려서 `report.html` 까지 보는 것.
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

**다운로드한 데이터 점검 (선택)**:
```powershell
python scripts/inspect_data.py list
python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

`missing bars: 0` 이면 깨끗한 데이터. 결손 있어도 D13 정책으로 백테스트는 그대로 진행됨 (알고만 있으면 됨).

---

## 3. 전략 준비 (2분)

`strategies/_starter.py` 와 `strategies/_starter.json` 을 복사:

```powershell
copy strategies\_starter.py    strategies\my_alpha.py
copy strategies\_starter.json  strategies\my_alpha.json
```

또는 이미 만들어둔 RSI 평균회귀 전략을 그대로 사용:

```powershell
# strategies/rsi_mean_reversion.py 가 이미 있음
type strategies\rsi_mean_reversion.py
```

---

## 4. 백테스트 실행 (1분)

D17 — `--strategy` 한 인자만 외우면 됨:

```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion
```

진행 표시줄 (tqdm) 이 봉 단위로 갱신되고, 끝나면 결과 디렉토리 출력:

```
100% ██████████| 4380/4380 [00:14, 305bar/s, equity=10412]
final_equity = 10412.78 (initial = 10000.00, return = +4.13%)
```

**`--strategy` 자동 해석** — 다음 4 가지 입력 모두 동일하게 동작:

```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion
python scripts/run_backtest.py --strategy rsi_mean_reversion.py
python scripts/run_backtest.py --strategy strategies/rsi_mean_reversion.py
python scripts/run_backtest.py --strategy /abs/path/to/x.py
```

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

```powershell
# Windows 에서 브라우저로 열기
start reports\rsi_mean_reversion_*\report.html
```

---

## 6. 파라미터 튜닝 (5분)

`strategies/rsi_mean_reversion.json` 편집:

```json
{
  "rsi_period": 21,
  "oversold": 25.0,
  "overbought": 75.0,
  "size_pct": 0.3
}
```

다시 실행:
```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion
```

`--out-dir` 로 결과 디렉토리 명시 가능 — 여러 파라미터 비교용:
```powershell
python scripts/run_backtest.py --strategy rsi_mean_reversion --out-dir reports/rsi_p21
```

---

## 7. uniform vs bridge 비교 (선택, 5분)

같은 데이터/전략에 두 합성 알고리즘 비교 (D16 — 비교는 `compare_runs.py` 전용):

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

`on_bar` 만 사용하는 전략은 두 결과가 동일 (정상). 차이는 `on_tick` 트레일링 사용 전략에서 발현.

---

## 다음 단계

- [docs/strategy_authoring.md](strategy_authoring.md) — 자신만의 전략 작성하기
- [strategies/_reference.md](../strategies/_reference.md) — StrategyAPI 사전형 레퍼런스
- [docs/USER_GUIDE.md](USER_GUIDE.md) — 결과 해석 / 트러블슈팅 / 고급 워크플로

---

## FAQ

**Q. download_data 가 NetworkError 로 실패합니다.**
A. CCXT 가 Binance API 에 접속 못 함. (1) 인터넷 연결 확인 (2) 일부 회사/학교 네트워크는 거래소 API 차단 — 다른 네트워크에서 시도 (3) sandbox 환경에서는 안 됨 (실 PC 에서 실행).

**Q. RSI 가 너무 적게 트리거됩니다.**
A. 21일치 데이터로는 시그널 1~2번 정도가 정상. 6개월~1년 데이터로 늘리거나, oversold/overbought 임계값을 35/65 로 완화해보세요.

**Q. 모든 수치가 0 또는 NaN 입니다.**
A. 워밍업 (RSI period+1 봉) 까지 진입 안 함. 데이터가 14봉 미만이면 RSI 가 워밍업 못 끝남. 최소 100봉 이상 데이터 권장.

**Q. progress bar 가 너무 길어 보기 싫어요.**
A. `--no-progress` 플래그로 끄세요.

**Q. 매번 다른 결과가 나옵니다.**
A. 그래선 안 됩니다 (P3 결정성). 같은 seed 면 bit-exact 동일 결과. `configs/backtest/default.yaml` 의 `tick_synthesis.seed` 가 고정인지 확인.

**Q. report.html 의 trades 가 0인데 fills 는 있습니다.**
A. 라운드트립 (entry → exit) 이 완성된 trade 만 표시. 마지막에 포지션이 열려있으면 그건 미완 trade.
