# tickweaver — Developer Guide

> 코드베이스 유지/확장하는 개발자 대상. 아키텍처, 확장 시나리오 6가지, 테스트,
> 디버깅, 릴리스 절차.
> 사용자용 문서: [`USER_GUIDE.md`](USER_GUIDE.md), 빠른 시작은
> [`backtest_quickstart.md`](backtest_quickstart.md).

---

## 1. 아키텍처 개요

### 1.1 한 줄 정의

```
CCXT OHLCV download
    -> normalize (P4 standard schema)
    -> ReplayFeed (BarEvent stream)
    -> tick_synthesis (uniform | bridge, C1~C7 contract)
    -> BacktestEngine
        -> strategy.on_tick / on_bar
        -> BacktestBroker (MARKET / LIMIT / STOP / STOP_LIMIT)
    -> analytics
        -> equity.parquet / trades.parquet / metrics.json
        -> equity_curve.png / sample_tick_paths.png
        -> report.html
```

### 1.2 최상위 디렉토리

```
tickweaver/
├── plan.md                 # 단일 진실 — 결정 / 마일스톤 / 위험표
├── pyproject.toml          # 빌드 + 의존성 (D5: pip + requirements*.txt)
├── requirements*.txt       # runtime / dev / live (live 는 archived)
├── src/tickweaver/         # 라이브러리 코드
├── scripts/                # typer CLI 얇은 래퍼
├── strategies/             # 사용자 영역 (gitignore)
├── tests/                  # unit + integration
├── configs/                # yaml 설정 (D17 default.yaml)
├── docs/                   # 본 가이드 + 사용자 가이드
└── data/, reports/, logs/  # gitignore
```

### 1.3 src/tickweaver 모듈 의존도

```
core/        # Protocol/ABC, dataclass, exceptions  (의존 없음)
utils/       # paths, seed, timeutils, logger, config
data/        # schema, normalizers, loaders/, feeds/
tick_synthesis/  # constraints, timestamps, validator, generator, strategies/
execution/   # fees, slippage, backtest_broker
strategy/    # api, file_strategy
engine/      # backtest_engine, runner
analytics/   # equity_curve, trades, metrics, report
```

import 방향은 위에서 아래로만. 레이어 위반은 PR 거절 (P5, plan.md §4.1).

---

## 2. 핵심 결정 (plan.md §11)

| ID | 결정 |
|---|---|
| D1 | 데이터 출처 거래소 우선순위: Binance → OKX → Gate.io |
| D2 | USDT-M Perpetual 우선 |
| D3 | 단일 자산 (multi-symbol 비목표) |
| D4 | Python 3.11+ |
| D5 | pip + requirements*.txt |
| D8 | 파일 기반 전략 (MT4 EA 스타일) + JSON 페어링 |
| D9 | 백테스트 = 항상 합성 tick 기반 |
| D10 | 현 단계 데이터 출처 = CCXT only |
| D11 | 현 단계 = backtest only (M5 archived) |
| D12 | 합성 tick 정밀도 = 현 수준 유지 (방법론) |
| D13 | 결손 OHLCV = skip-only |
| D14 | 단일 스레드 |
| D15 | API key 미사용 |
| D16 | uniform vs bridge 비교 = compare_runs.py 전용 |
| D17 | run_backtest CLI = `--strategy` 만 필수 + 자동 경로 해석 |

---

## 3. 핵심 인터페이스 (`core/interfaces.py`)

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

새 구현체는 이 Protocol 만 만족하면 됨. `runtime_checkable` 이라 `isinstance(x, Protocol)` 검증 가능.

---

## 4. 확장 시나리오 6가지

### 4.1 새 tick generator 추가

1. `src/tickweaver/tick_synthesis/strategies/<name>.py` 생성
2. `@register_tick_generator("<name>")` 로 클래스 등록
3. `generate(bar, n_ticks, rng) -> list[Tick]` 구현 (C1~C7 만족)
4. `tick_synthesis/strategies/__init__.py` 에 `from . import <name>` 추가 (등록 트리거)
5. `tick_synthesis/__init__.py` 의 import 도 갱신
6. `tests/unit/test_<name>_generator.py` — uniform 과 같은 hypothesis property suite 통과

예시 — Volatility-aware:

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
        # ... 사용자 정의 로직 (반드시 C1~C7 만족)
        # 마지막에 validator 가 호출되니 안전
        ...
```

검증: `tests/unit/test_vol_aware_generator.py` 에서 uniform 의 hypothesis suite 그대로 복사.

### 4.2 새 indicator 추가

1. `src/tickweaver/strategy/indicators.py` 에 클래스 추가
2. 공통 contract: `update(...)` / `value` property / `is_warm: bool` / `reset()`
3. `__all__` 에 추가
4. `tests/unit/test_indicators.py` 에 단위 테스트 (수치 검증 + property test)
5. `strategies/_reference.md` §8 의 인디케이터 표 갱신

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

### 4.3 새 fee/slippage 모델 추가

1. `src/tickweaver/execution/fees.py` 또는 `slippage.py` 에 클래스 추가
2. `FeeModel` / `SlippageModel` Protocol 만족 (`fee()` / `adjust()`)
3. `configs/default.yaml` 에 yaml 키 노출 (필요시)
4. runner.py 의 yaml → 객체 매핑 보강

```python
# Volume-scaled slippage (스칠피지가 거래량 비율에 따라)
class VolumeBasedSlippage:
    def __init__(self, base_bps=2.0, alpha=0.5):
        self.base_bps = base_bps
        self.alpha = alpha
        self._last_volume = None

    def adjust(self, price, side):
        # alpha 가 클수록 큰 거래에서 슬리피지 증가
        ...
```

### 4.4 외부 OHLCV 로더 활성화 (D10 해제)

현재 `csv_loader.py` 와 `binance_zip_loader.py` 는 frozen. 활성화 절차:

1. `data/loaders/__init__.py` 에 export 추가
2. `data/loaders/csv_loader.py` 의 `CsvLoader` 동작 검증
3. `configs/data/external_template.yaml` 의 cleanup 정책 (D13 호환)
4. `inspect_data` CLI 에 `--from-csv` 같은 옵션 추가 (선택)
5. plan.md D10 의 "현 단계 코드/계획 동결" 문구 갱신
6. plan.md §5 의 "Future Work" 헤더 제거

핵심: 외부 OHLCV → `normalize_ohlcv()` 로 normalize → 그 후 흐름은 CCXT 와 동일.

### 4.5 새 분석 메트릭 추가

1. `src/tickweaver/analytics/metrics.py` 의 `compute_metrics()` 에 새 키 추가
2. `analytics/report.py` 의 `_metrics_table()` 의 pretty 매핑 갱신
3. `metrics.json` 형식이 호환되는지 (downstream 분석 스크립트 영향) 확인

```python
# 추가 예: Calmar 의 변형, Information Ratio
def compute_metrics(...):
    ...
    metrics["information_ratio"] = ...
    metrics["recovery_factor"] = ...
```

### 4.6 Live broker 복원 (D11 해제)

`_archive_live/` 안에 보존된 코드 복원 절차는 그쪽 README 에 있음. 핵심:

1. `_archive_live/{ccxt_broker.py, live_engine.py, monitoring/, run_live.py}` 를 원래 위치로 이동
2. `requirements-live.txt` 활성화
3. `monitoring/{kill_switch, alerts, healthcheck}` 검증
4. `docs/live_deployment_checklist.md` 의 24h testnet 무사고 체크
5. plan.md D11 archived 표시 제거

**중요**: P1 (single-strategy code) 를 깨지 않게 — 같은 전략 .py 가 backtest / live 둘 다에서 굴러가야 함.

---

## 5. 테스트 전략 (P8)

### 5.1 테스트 피라미드

```
        Integration (느림, 적게)
         tests/integration/test_e2e_smoke.py
              -> 합성 OHLCV → 백테스트 → report.html
              -> 결정성 회귀 (같은 seed → 같은 final equity)
        Unit + hypothesis (많이)
         tests/unit/  (10+ 파일)
              -> test_constraints / test_timestamps / test_validator
              -> test_uniform_generator / test_bridge_generator
              -> test_orders (LIMIT/STOP/STOP_LIMIT)
              -> test_indicators / test_ccxt_loader / test_catalog / test_paths
```

### 5.2 hypothesis property tests

uniform 과 bridge 둘 다 같은 suite 통과 (C1~C7):

```python
@given(bar=bars(), n=st.integers(4, 256), seed=st.integers(0, 2**31 - 1))
@settings(max_examples=250)
def test_C1_to_C6(bar, n, seed):
    ticks = generator.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    validate_ticks(bar, ticks, n_min=4, n_max=512)
```

새 generator 추가 시 동일 suite 를 그대로 복사 — 통과해야만 등록.

### 5.3 결정성 회귀 (P3)

`tests/integration/test_e2e_smoke.py::test_determinism_same_seed` —
같은 seed 두 번 → bit-exact 동일 final_equity.

코드 수정 후 이 테스트가 깨지면 결과 변경 영향 발생 (의도일 수도, 버그일 수도).

### 5.4 Mock-only 거래소 테스트

`tests/unit/test_ccxt_loader.py` — `_FakeCcxtExchange` monkeypatch 패턴 (plan.md §8.4).
sandbox 네트워크 없이도 페이지네이션 + 캐시 + 재개 + 정규화 검증.

### 5.5 빠른 실행

```powershell
# 전체
pytest

# 특정 파일
pytest tests/unit/test_indicators.py -v

# hypothesis 통계 보기
pytest --hypothesis-show-statistics

# 결정성 회귀만
pytest tests/integration/test_e2e_smoke.py::test_determinism_same_seed -v
```

---

## 6. 디버깅

### 6.1 Windows mount + .pyc stale (자주 발생)

증상: 코드 변경했는데 동작이 안 바뀜.

원인: Edit 으로 .py 를 바꿨는데 mtime 이 갱신 안 돼 stale .pyc 가 우선 사용됨.

해결:
```powershell
# .py 의 mtime 갱신 → 다음 import 때 .pyc 무효화
find src -name "*.py" -exec touch {} +    # Linux/Mac/sandbox
# Windows PowerShell:
Get-ChildItem -Recurse src -Filter *.py | ForEach-Object { $_.LastWriteTime = Get-Date }

# 또는 .pyc 직접 삭제
find src -name "__pycache__" -type d -exec rm -rf {} +

# 또는 PYTHONDONTWRITEBYTECODE 사용
$env:PYTHONDONTWRITEBYTECODE="1"
python -B scripts/run_backtest.py ...
```

### 6.2 결정성 깨짐

증상: 같은 seed 인데 결과가 다름.

체크리스트:
- 멀티스레드 사용? D14 위반. 단일 스레드만.
- numpy reduction 함수 (sum, mean) 의 비결정적 구현?
- 외부 RNG (random.random() 등) 를 SeedManager 통하지 않고 직접 사용?
- dict / set 의 iteration 순서 의존? (Python 3.7+ 에서 dict 는 OK, set 은 비결정적)

### 6.3 Strategy 디버깅

`api.log("event", **kv)` 로 구조화 로그 — `--no-progress` 모드에서 콘솔 표시.

또는 Python `breakpoint()` 직접 사용:
```python
def on_bar(bar):
    if some_condition(bar):
        breakpoint()    # pdb 에서 api.position(), api.equity 검사
```

### 6.4 Tick 합성 검증

`--dump-ticks N` 옵션으로 N 개 봉의 합성 tick 을 PNG / parquet 으로 저장:
```powershell
python scripts/run_backtest.py --strategy my_alpha --dump-ticks 10
# -> reports/<run>/sample_tick_paths.png
# -> reports/<run>/sample_ticks.parquet
```

`compare_runs.py preview` 로 단일 봉의 uniform vs bridge 시각화.

### 6.5 OHLCV 데이터 점검

`inspect_data inspect <path>` 로 결손/무결성 위반/스키마 점검 (D13 — 보고만).

---

## 7. 릴리스 절차

현 단계는 internal use 이므로 PyPI 배포는 미정 (plan.md §13.4).

릴리스 시 절차:

1. **plan.md changelog** (§11.4) 에 변경 항목 추가
2. **__init__.py** 의 `__version__` 업데이트 (semver)
3. 전체 테스트 통과 확인 (`pytest --hypothesis-show-statistics`)
4. **git tag** (예: `v0.2.0`)
5. (선택) `python -m build` 로 wheel 빌드

semver 가이드:
- MAJOR: 사용자 전략 코드 / config yaml / public API 깨지는 변경
- MINOR: 신규 기능 (새 인디케이터, 새 generator 등)
- PATCH: 버그 수정

---

## 8. 코드 스타일

- **Ruff** 강제 (line-length=100, py311 target). PR 전 `ruff check src/ tests/ scripts/` 통과.
- **mypy** 권장 (strict=False). 점진 적용.
- **import-linter** (plan.md §4.1) — 레이어 위반 import 차단. CI 시 자동 검증.
- **한국어 docstring 회피** — Windows mount 환경의 cp949 ↔ UTF-8 race condition 발생.
  내부 코드 주석은 ASCII, 사용자 문서 (md) 만 한국어.
- **type hints** — `from __future__ import annotations` + `|` syntax 일관 사용.

### 8.1 의존성 추가

`requirements.txt` + `pyproject.toml` 둘 다 수정. dev-only 는 `requirements-dev.txt` + `[project.optional-dependencies] dev`.

---

## 9. 위험 요소 + 대응 (plan.md §10)

| 위험 | 영향 | 대응 |
|---|---|---|
| 합성 tick microstructure 한계 | 외삽 한계 | D12 — 정밀도 추구 비목표. 슬리피지 모델로 흡수 |
| OHLC 결손 | 일부 봉 누락 | D13 — skip-only |
| 룩어헤드 | 과적합 | engine 의 submit≠fill 강제. 외부 데이터는 사용자 책임 |
| 결정성 깨짐 | 재현 불가 | 단일 스레드 (D14), SeedManager, 회귀 테스트 |
| Windows .pyc stale | 디버깅 혼란 | `touch` mtime 갱신, `__pycache__` 삭제 |
| Sandbox 네트워크 차단 | 실 다운로드 검증 불가 | mock-only 테스트 (`_FakeCcxtExchange`). 실 PC 검증 |

---

## 10. 자주 묻는 개발 질문

**Q. 새 거래소 (Bybit, Coinbase) 추가하려면?**
A. CCXT 가 이미 지원하면 데이터 다운로드 측면은 즉시 됨 — `--exchange bybit` 만 바꿔서 시도. broker 측 어댑터는 `_archive_live/ccxt_broker.py` 의 `_BinanceAdapter` / `_OkxAdapter` 패턴 참고.

**Q. 멀티 자산 백테스트?**
A. D3 단일 자산 가정이 깊게 박혀 있음 (Position 단수, BacktestBroker 단일 symbol). multi 는 plan.md §13.1 의 future work — `Engine` 과 `Broker` 대대적 수정 필요.

**Q. config yaml 의 새 섹션 추가?**
A. `utils/config.py` 의 `BacktestConfig` 에 새 dataclass 추가 + `configs/default.yaml` 갱신.

**Q. logger 출력을 file 로 redirect?**
A. `utils/logger.py` 의 `configure_logging()` 에 file handler 추가. 현재는 stdout 만.

**Q. CI 추가?**
A. `.github/workflows/ci.yml` (plan.md §13.4) — pytest + ruff + mypy + import-linter. 미구현, future work.

---

## 11. 참고 문서

- [plan.md](../plan.md) — 단일 진실 (결정 / 마일스톤 / 위험표)
- [strategies/_reference.md](../strategies/_reference.md) — StrategyAPI 사전형 레퍼런스
- [docs/strategy_authoring.md](strategy_authoring.md) — 전략 작성 튜토리얼
- [docs/USER_GUIDE.md](USER_GUIDE.md) — 사용자 종단 흐름
- [docs/backtest_quickstart.md](backtest_quickstart.md) — 30분 첫 백테스트

---

## 12. 다음 단계 후보 (plan.md §13)

13.1 Backtest 확장:
- MT4 strategy tester 같은 verbose 시각화
- 추가 tick generator (volume-weighted, regime-switching)
- 추가 거래소 데이터 로더 검증

13.2 외부 OHLCV 입력 활성화 (D10 해제 시):
- csv_loader / binance_zip_loader 활성화
- external 입력 → CCXT 캐시 우회 경로

13.3 Live 복원 (D11 해제 시):
- WebSocket live feed (ccxt.pro)
- Hedge mode
- 추가 broker 어댑터

13.4 인프라:
- GitHub Actions CI
- PyPI 배포 (`python -m build`)
