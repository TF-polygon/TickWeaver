# tickweaver — 통합 계획서 (plan.md)

> **OHLCV 데이터를 봉 내부 무작위 Tick 으로 합성한 뒤, 그 위에서 매매 전략을
> 백테스트하는 프로젝트.** 데이터 포맷이 표준 OHLCV (P4) 만 따른다면 출처는
> 원칙상 무관하지만, **현 단계에서는 CCXT 다운로드 경로만 구현**한다.
> 외부에서 다운로드한 OHLCV (CSV/Parquet/Binance ZIP 등) 직접 입력 및 실거래(Live) 는
> 모두 **현 단계 비대상** (각각 §5/§13, §7 M5 참고).
>
> 본 문서는 (a) 시스템 청사진 (b) 핵심 원칙 + Tick 계약 (c) 폴더/모듈 책임
> (d) 마일스톤 회고 (e) 사용자 워크플로 (f) 결정사항 변경 로그를 모두 담는
> **단일 진실(Source of Truth)** 입니다. 새 컨텍스트에서 처음 진입한 사람이
> 이 문서 하나로 시스템 전체를 파악할 수 있어야 합니다.

---

## 0. 한 줄 정의

**OHLCV 데이터를 받아 봉 내부 가격 경로를 합성 Tick 으로 재구성하고,
그 위에서 매매 전략 (`Strategy` 또는 file-mode `.py`) 을 백테스트한다.**

표준 OHLCV 스키마 (P4) 만 통과하면 데이터 출처는 무관 — 단, **현 단계에서는
CCXT 다운로드 한 가지 경로만 구현**한다 (§3.1 데이터 흐름).
외부 OHLCV 직접 입력과 실거래(Live) 는 모두 현 단계 비대상이며, 각각 §5/§13,
§7 M5 (archive) 에 별도 기재한다.

---

## 1. 문제 정의 + Tick 계약

### 1.1 사용자가 풀고 싶은 문제

OHLCV 위에서 동작하는 매매 전략을 신뢰 가능하게 백테스트하기 위함.
일반 OHLC 백테스트는 한 봉 안의 가격 경로를 모르므로 (Open/Close 점에서만 체결)
실제 봉 내부 거동과 괴리가 큼. Tick 데이터는 비싸거나 보존 기간이 짧음.
따라서 **OHLC 만 가지고 봉 내부 경로를 그럴듯하게 합성**해서
`Strategy.on_tick()` 을 호출한다.

데이터 출처는 P4 표준 OHLCV 스키마만 통과하면 무관하지만, **현 단계에서는
CCXT 다운로드 경로 한 가지만 구현**한다. 외부에서 다운로드한 OHLCV
(CSV / Binance ZIP / 임의 parquet 등) 직접 입력은 현 단계에서는 코드/계획 모두
**작업 대상이 아님** — 향후 검토 항목으로만 §5, §13 에 보존한다.

### 1.2 합성 Tick 의 수학적 계약 — C1~C7 (절대 불변)

봉 `bar = (O, H, L, C, t_open, t_close)` 에 대해 생성된 tick 시퀀스
`T = [p_0, p_1, ..., p_{n-1}]` 는 다음을 **반드시** 만족:

| # | 제약 | 의미 |
|---|---|---|
| C1 | `p_0 == O` | 시점 = Open |
| C2 | `p_{n-1} == C` | 종점 = Close |
| C3 | `min(T) == L` | 봉 내 최저가 = Low (어디든 OK) |
| C4 | `max(T) == H` | 봉 내 최고가 = High (어디든 OK) |
| C5 | `L <= p_i <= H ∀ i` | 모든 tick 은 [L, H] 안 |
| C6 | `n_min <= n <= n_max` | 사용자 설정 범위 (default 8~256) |
| C7 | 같은 `(bar, n, seed)` → bit-exact 동일 | 결정성 |

`tick_synthesis/validator.py` 가 이 7가지를 검증. 깨지면 `TickContractError` raise + fail-fast.

### 1.3 비목표 (현 단계)

- **실거래(Live Trading)** — M5 의 모든 코드/문서/스크립트는 `_archive_live/` 로 동결.
  복원 절차는 `_archive_live/README.md` 참조 (§7 M5).
- **외부에서 다운로드한 OHLCV 직접 입력** (CSV / Binance ZIP / 임의 parquet) —
  현 단계 미구현. 데이터는 CCXT 로만 받는다 (§3.1, §5, §11 D10).
- 호가창(orderbook) 시뮬레이션 (가격 경로만 합성, 슬리피지는 별도 모델)
- 옵션/파생 그릭(Greek)
- 자체 데이터 저장소(DB) 운영 — 파일(parquet) 기반

---

## 2. 핵심 원칙 P1~P10

| # | 원칙 | 한 문장 |
|---|---|---|
| P1 | Single-Strategy-Code | 백테스트/실거래에서 전략 코드 동일. 분기 금지. (현 단계는 backtest only — Live 복원 시에도 그대로 적용되도록 설계 의도 보존) |
| P2 | Tick Contract Inviolability | 합성 Tick 은 C1~C7 모두 만족. property-test 로 강제. |
| P3 | Reproducibility First | 같은 (data, config, seed) → bit-exact 동일 결과. `SeedManager` 단일 진실. |
| P4 | Standard OHLCV Schema | 엔진 진입 전 모든 데이터를 표준 OHLCV 로 정규화. |
| P5 | Separation of Concerns | 레이어 의존성 위반 import 금지 (import-linter 강제). |
| P6 | Fail Fast, Fail Loud | **타입/스키마/설정 위반**은 즉시 raise (침묵 금지). 단, OHLCV 봉 결손/중복은 raise 가 아닌 skip — 거래소 책임 (D13). |
| P7 | Realism Knobs Mandatory | 수수료/슬리피지/지연 명시 필수 (`none` 은 경고). |
| P8 | Test Pyramid + Property-Based | unit + hypothesis property + integration. |
| P9 | UTC Everywhere | naive datetime 인터페이스 경계에서 reject. |
| P10 | Configuration as Code | 매직 넘버 금지, 모든 값 config 노출 + 결과 폴더에 스냅샷 저장. |

---

## 3. 시스템 아키텍처

### 3.1 데이터 흐름 (현 단계 — Backtest only, CCXT only)

```
                ┌──────────────────────┐
                │  CCXT Exchange API   │
                └──────────┬───────────┘
                           │ raw OHLCV (페이지네이션 + 디스크 캐시 + 재개)
                           ▼
                ┌──────────────────────────┐
                │  data/loaders/           │
                │    ccxt_loader.py        │
                └──────────┬───────────────┘
                           ▼
                ┌──────────────────────────────┐
                │  data/normalizers.py         │  ← P4 표준 OHLCV 게이트
                │  + data/schema.py 검증       │
                └──────────────┬───────────────┘
                               ▼
                   standard OHLCV DataFrame
                               │
                               ▼
                ┌────────────────────────────┐
                │ tick_synthesis             │
                │  (config 가 지정한 1가지 — │
                │   uniform 또는 bridge)     │
                │  + validator.py C1~C7      │
                └────────────┬───────────────┘
                             ▼
                ┌────────────────────────────┐
                │ engine/backtest_engine     │
                │  + tick_summary            │
                └────────────┬───────────────┘
                             ▼
                ┌────────────────────────────────┐
                │  strategy (file or registry)   │
                │   on_init/on_bar/on_tick/...   │
                └────────────┬───────────────────┘
                             │ orders
                             ▼
                ┌────────────────────────────────┐
                │ execution/backtest_broker.py   │
                │  + slippage + fees + latency   │
                └────────────┬───────────────────┘
                             ▼
                ┌────────────────────────────────┐
                │ analytics/ (metrics, plots,    │
                │              report.html)      │
                └────────────────────────────────┘
```

> **현 단계 비대상 경로** (참고용 — 작업하지 않음):
> - 외부 OHLCV (CSV / Binance ZIP / 임의 parquet) 입력 갈래 → §5 future work
> - Live 경로 (live_feed → live_engine → ccxt_broker → monitoring) → §7 M5 archive

### 3.2 핵심 인터페이스 (`core/interfaces.py`)

```python
class DataLoader(Protocol):
    def load(self, symbol, timeframe, since, until) -> pd.DataFrame: ...
    # 반환은 반드시 표준 OHLCV (P4)

class TickGenerator(Protocol):
    def generate(self, bar, n_ticks, rng) -> list[Tick]: ...
    # 반환은 반드시 C1~C7 만족

class Broker(Protocol):
    def submit(self, order) -> str: ...
    def cancel(self, order_id): ...
    def positions(self) -> dict[str, Position]: ...
    def set_fill_callback(self, cb): ...
    def on_market_event(self, tick) -> list[Fill]: ...

class Strategy(ABC):
    def setup(self, context, broker): ...
    def on_start(self) -> None: ...
    def on_bar(self, bar) -> None: ...
    def on_tick(self, tick) -> None: ...
    def on_fill(self, fill) -> None: ...
    def on_stop(self) -> None: ...
```

### 3.3 표준 OHLCV 스키마 (P4)

```
type    : pd.DataFrame
index   : pd.DatetimeIndex (tz='UTC', tz-aware, name='timestamp', 단조 증가, unique)
columns : open, high, low, close, volume   (모두 float64)
attrs   : {symbol, timeframe, exchange, source_uri}
```

`data/schema.py` 가 검증, `data/normalizers.py` 가 임의 DataFrame을 이 스키마로 변환.

---

## 4. 폴더 구조 + 책임 분리

```
tickweaver/
├── plan.md                    ← 본 문서
├── README.md                  ← 빠른 시작
├── pyproject.toml             ← editable install + ruff/mypy/pytest/import-linter
├── requirements.txt           ← 런타임 (ccxt, pandas, numpy, pyarrow, pydantic, ...)
├── requirements-dev.txt       ← + pytest/hypothesis/ruff/mypy/import-linter
├── requirements-live.txt      ← (archived) 실거래 머신용 — _archive_live/ 와 함께 동결
├── .env.example               ← (archived) API key 템플릿. 현 단계 백테스트는 .env 미사용 (D15)
├── .gitignore                 ← data/, logs/, reports/, strategies/* (단 _starter.*, _reference.md, README.md 예외)
│
├── configs/                   ← P10. 모든 실행 설정의 단일 진실
│   ├── backtest/{default,quickstart_demo}.yaml
│   ├── live/default.yaml      ← (archived) M5 와 함께 동결
│   ├── strategies/ema_cross.yaml
│   └── data/external_template.yaml  ← (frozen) 외부 OHLCV future work 용 — §5
│
├── data/                      ← gitignore. 절대 커밋 금지.
│   ├── raw/                   책임: 다운로드 원본
│   ├── processed/             책임: 표준 OHLCV parquet 캐시
│   │   └── {exchange}/{symbol_safe}/{market_type}/{timeframe}.parquet
│   └── ticks_cache/           책임: 합성 tick 캐시 (선택)
│
├── strategies/                ← 사용자 영역 (gitignore, MT4 EA 스타일)
│   ├── README.md              ← 디렉토리 안내 (커밋됨)
│   ├── _reference.md          ← ★ MT4 F1 스타일 API 레퍼런스 사전 (커밋됨)
│   ├── _starter.py            ← 보일러플레이트 (커밋됨)
│   ├── _starter.json          ← 파라미터 템플릿 (커밋됨)
│   └── my_alpha.py + .json    ← 사용자 전략 (커밋 안 됨)
│
├── reports/                   ← gitignore. 백테스트 결과
│   └── <strategy>_<ts>/
│       ├── report.html, equity_curve.png, trade_pnl.png
│       ├── sample_tick_paths.png + sample_ticks.parquet (--dump-ticks 시)
│       ├── equity.parquet, trades.parquet
│       └── metrics.json, tick_summary.json, config_snapshot.json
│
├── src/tickweaver/
│   │
│   ├── core/                  ★ 다른 모든 모듈의 최하위 의존
│   │   ├── interfaces.py      Protocol/ABC: DataLoader, TickGenerator, Broker,
│   │   │                      SlippageModel, FeeModel, Strategy
│   │   ├── types.py           OHLCBar, Tick, Order, Fill, Position,
│   │   │                      StrategyContext, Side/OrderType/PositionSide/MarketType Enum
│   │   ├── events.py          BarEvent, TickEvent, OrderEvent, FillEvent, CancelEvent
│   │   └── exceptions.py      PyCryptoBacktestError + 12개 도메인 예외
│   │
│   ├── data/                  ★ 외부 데이터 → 표준 OHLCV
│   │   ├── schema.py          표준 스키마 정의 + validate_ohlcv_{schema,integrity}
│   │   ├── normalizers.py     normalize_ohlcv() — 컬럼 매핑/ts unit/tz/dedup/검증.
│   │   │                       **결손 봉은 skip-only (D13)** — 발견해도 raise 안 함.
│   │   ├── loaders/
│   │   │   ├── base.py        slice_period, assert_symbol_timeframe_match
│   │   │   ├── ccxt_loader.py ★ CcxtLoader — 페이지네이션 + 캐시 + 재개 다운로드
│   │   │   │                  현 단계 유일하게 활성 유지되는 외부 데이터 로더
│   │   │   ├── parquet_loader.py + write_parquet/read_parquet_with_attrs (attrs 보존)
│   │   │   │                  현 단계 사용처: data/processed/ 내부 캐시 read/write 만
│   │   │   ├── csv_loader.py         (frozen) 외부 OHLCV 입력용 — 현 단계 미사용
│   │   │   └── binance_zip_loader.py (frozen) 외부 OHLCV 입력용 — 현 단계 미사용
│   │   ├── feeds/
│   │   │   ├── replay_feed.py 백테스트 BarEvent stream
│   │   │   └── live_feed.py   (archived → _archive_live/) 실거래 REST polling
│   │   └── catalog.py         processed/ 인덱싱
│   │
│   ├── tick_synthesis/        ★★ 본 프로젝트의 핵심 차별화
│   │   ├── constraints.py     synthesize_prices_uniform + clamp_n_ticks
│   │   ├── timestamps.py      distribute_uniform (봉 내 시간 분배)
│   │   ├── validator.py       validate_ticks (C1~C6) + verify_determinism (C7)
│   │   ├── generator.py       @register_tick_generator + get/list_tick_generator(s)
│   │   └── strategies/
│   │       ├── uniform.py     UniformTickGenerator (M2, default)
│   │       └── bridge.py      BrownianBridgeTickGenerator (M4, log-space GBM)
│   │
│   ├── strategy/              ★ 사용자 전략 작성 영역
│   │   ├── base_strategy.py   BaseStrategy (concrete)
│   │   ├── indicators.py      EMA, SMA (streaming)
│   │   ├── order_helpers.py   market_order/limit_order/stop_order (멱등성 키)
│   │   ├── registry.py        @register_strategy + get/list_strategies (registry 모드)
│   │   ├── api.py             ★ StrategyAPI + ParamsView (file 모드 사용자에게 주입)
│   │   ├── file_strategy.py   ★ FileStrategy — .py 동적 로드, on_init/on_bar/.. 디스패치
│   │   ├── examples/
│   │   │   └── ema_cross.py   레지스트리 예시 (테스트용)
│   │   └── templates/
│   │       └── _starter.py    클래스 기반 템플릿 (참고용)
│   │
│   ├── execution/             ★ 주문 실행 (현 단계: backtest broker 만)
│   │   ├── fees.py            BpsFeeModel / NoFee
│   │   ├── slippage.py        FixedBps / VolatilityScaled / NoSlippage + build_slippage()
│   │   ├── order_validator.py MarketRules + validate_order_against_rules + balance check
│   │   ├── margin.py          unrealized_pnl, initial_margin, liquidation_price_isolated
│   │   ├── backtest_broker.py ★ BacktestBroker — MARKET/LIMIT/STOP/STOP_LIMIT, 룩어헤드 방지
│   │   └── ccxt_broker.py     (archived → _archive_live/) Binance/OKX/Gate.io 어댑터
│   │
│   ├── engine/                ★ 오케스트레이션 (현 단계: backtest 만)
│   │   ├── backtest_engine.py ★ BacktestEngine — feed→tick→strategy→broker→equity, TickSummary
│   │   ├── live_engine.py     (archived → _archive_live/) LiveEngine + kill_switch + flatten
│   │   └── runner.py          run_backtest(config, loader=, ...) — file/registry 분기
│   │
│   ├── analytics/             ★ 결과 분석
│   │   ├── equity_curve.py    EquityCurve (sampling)
│   │   ├── trades.py          extract_trades — fills → 라운드트립 매칭
│   │   ├── metrics.py         Sharpe/Sortino/CAGR/MDD/Calmar/win_rate/profit_factor
│   │   ├── plots.py           equity + drawdown 2단 / per-trade PnL
│   │   └── report.py          HTML 리포트 + Tick Synthesis (proof) 섹션
│   │
│   ├── monitoring/            (archived → _archive_live/) 실거래 운영용
│   │   ├── kill_switch.py     KillSwitch + KillSwitchConfig (4가지 위험 한도)
│   │   ├── alerts.py          Slack/Telegram/Stdout/Fanout Notifier
│   │   └── healthcheck.py     clock_skew, data_freshness, broker_reachable
│   │
│   └── utils/
│       ├── paths.py           프로젝트 경로 상수 + ensure_runtime_dirs
│       ├── seed.py            ★ SeedManager (P3 단일 진실, SHA256 결정적 spawn)
│       ├── timeutils.py       UTC 강제, timeframe→ms, parse_iso_utc
│       ├── logger.py          structlog 설정 (PrintLogger 호환)
│       └── config.py          BacktestConfig / StrategySpec (file xor registry).
│                               LiveConfig 는 archive 와 함께 동결.
│
├── tests/
│   ├── unit/  (29 파일, ~220 테스트)
│   │   ├── test_smoke.py                    M0 import + 타입 검증
│   │   ├── test_schema.py / test_normalizers.py
│   │   ├── test_loaders.py / test_ccxt_loader.py (mock)
│   │   ├── test_constraints.py / test_timestamps.py / test_validator.py
│   │   ├── test_uniform_generator.py        (hypothesis 600+ 케이스)
│   │   ├── test_bridge_generator.py         (hypothesis 500+ 케이스)
│   │   ├── test_execution.py / test_strategy.py / test_analytics.py
│   │   ├── test_monitoring.py / test_alerts.py            (archived 와 함께 동결)
│   │   ├── test_ccxt_broker.py (mock) / test_live_engine.py (mock)  (archived)
│   │   ├── test_file_strategy.py            (FileStrategy + StrategyAPI + ParamsView)
│   │   └── test_replay_feed.py / test_catalog.py
│   ├── integration/
│   │   └── test_backtest_e2e.py             합성 OHLCV → 백테스트 → 메트릭 → HTML
│   └── fixtures/
│       └── ohlcv.py                         테스트용 OHLCV/binance klines 생성
│
├── scripts/                   ← typer CLI (얇은 래퍼)
│   ├── download_data.py       ★ CCXT 다운로드 (현 단계 유일 데이터 진입점)
│   ├── inspect_data.py        list / inspect (스키마/integrity/gap 리포트). 리포트만 생성, fail 안 함 (D13)
│   ├── synthesize_ticks.py    단일 봉 합성 tick 시각화
│   ├── run_backtest.py        ★ --strategy <path> --params <path> --auto-period --dump-ticks N
│   ├── compare_runs.py        preview / backtest (uniform vs bridge 비교)
│   └── run_live.py            (archived → _archive_live/) --i-understand-real-money 이중 가드
│
└── docs/
    ├── USER_GUIDE.md                    ★ 사용자 종단 흐름 (설치~백테스트)
    ├── DEVELOPER_GUIDE.md               ★ 개발자 유지보수 + 확장 시나리오
    ├── backtest_quickstart.md           30분 안에 첫 백테스트
    ├── strategy_authoring.md            ★ 파일 기반 전략 작성 (MT4 EA 스타일)
    └── live_deployment_checklist.md     (archived → _archive_live/) 실거래 체크리스트
```

### 4.1 책임 치트시트

| 레이어 | 입력 | 출력 | 절대 하지 말 것 |
|---|---|---|---|
| 0. core/ | — | Protocol, dataclass | 어떤 구현도 금지 |
| 1. data/loaders | symbol/timeframe/range | raw DataFrame | 정규화/검증 |
| 2. data/normalizers | raw DataFrame | 표준 OHLCV | 거래소 호출 |
| 3. tick_synthesis | OHLCBar, n, rng | List[Tick] (C1~C7) | 거래 의사결정 |
| 4. strategy | Bar/Tick/Fill | Order | 거래소 직접 호출, 데이터 다운로드 |
| 5. execution | Order | Fill | 시그널 생성, 데이터 다운로드 |
| 6. engine | feed + strategy + broker | Trade log + equity + TickSummary | 비즈니스 로직 |
| 7. analytics | Trade log + equity | metrics + plots + report | 데이터 수집, 주문 |
| 8. monitoring | (archived) live 이벤트 | (archived) 알림 + kill | 본 단계에서는 import 금지 |
| 9. scripts | 사용자 명령 | 위 레이어 호출 | 비즈니스 로직 |

위 표의 "절대 하지 말 것" 컬럼을 위반하는 import 가 발견되면 PR 거절. import-linter 가 CI에서 자동 검사 (`pyproject.toml`).
8 번 monitoring 은 archived. 본 문서가 다루는 현 단계 코드는 monitoring 을 import 하지 않는다.

---

## 5. 외부 OHLC 데이터 표준화 — ⚠️ Future Work (현 단계 미구현)

> **경고**: 본 섹션은 향후 외부에서 다운로드한 OHLCV (CSV / Parquet / Binance ZIP)
> 를 입력으로 받는 시나리오를 위한 **참고용 설계**일 뿐, **현 단계에서는 작업하지 않는다**.
> 현 단계 데이터 출처는 §3.1 의 CCXT 경로 한 가지 (D10).
> `data/loaders/{csv_loader, binance_zip_loader}.py` 는 frozen — 호출되지 않는다.
> `configs/data/external_template.yaml` 도 같은 의미로 frozen.

### 5.1 권장 입력 포맷 (호환성 높은 순)

1. **Parquet** — `.parquet`, columns: `timestamp, open, high, low, close, volume`
2. **CSV (Binance Vision 스타일)** — open_time, ohlcv, close_time, ...12-column
3. **CSV (단순)** — `timestamp, open, high, low, close, volume` (헤더 필수)

### 5.2 외부 데이터 정규화 config (예시)

```yaml
# configs/data/external_template.yaml
source:
  type: csv  # csv | parquet | binance_zip
  path: ./data/raw/btc_1h.csv
  symbol: BTC/USDT:USDT
  timeframe: 1h
  exchange: external

mapping:
  timestamp: open_time     # 외부→표준 컬럼명
  open: open
  high: high
  low: low
  close: close
  volume: volume

timestamp:
  unit: ms                 # ms | s | ns | iso8601
  timezone: UTC

cleanup:
  drop_duplicates: true
  on_missing_bar: skip  # D13 — skip-only (보간/fail 비대상)
  reject_if_high_lt_low: true
```

### 5.3 데이터 카탈로그

`data/processed/{exchange}/{symbol_safe}/{market_type}/{timeframe}.parquet` 규칙.
`Catalog` 클래스가 인덱싱. `scripts/inspect_data.py list --deep` 으로 조회.

---

## 6. Tick 합성 알고리즘

### 6.1 `uniform` (M2, default, 가장 보수적)

```
입력: bar=(O, H, L, C), n_target ∈ [n_min, n_max], rng

1. n = clamp(n_target, n_min, n_max). 단 n >= 4. (zero-range 봉은 별도 처리)
2. interior = rng.uniform(L, H, size=n-4) (n=4면 비어있음)
3. middle = shuffle([L, H, *interior])  ← 길이 n-2
4. P = [O] + middle + [C]               ← 길이 n
5. validator (C1~C7) 통과
```

엣지케이스:
- `H == L`: P = [O] * n (모든 가격 동일)
- `O == L` 또는 `O == H`: middle 의 명시 L/H 와 중복돼도 OK

### 6.2 `bridge` (M4, log-space Geometric Brownian Bridge)

```
입력: bar, n, rng

1. log_O, log_C, log_L, log_H = log of OHLC
2. sigma = (log_H - log_L) * sigma_factor (default 0.5)
3. 표준 BB at points i/(n-1) for i=0..n-1 with endpoints (log_O, log_C):
       bridge_i = BM_i - (i/(n-1)) * BM_{n-1}
       log_p_i = log_O + t_norm_i*(log_C - log_O) + sigma*bridge_i
4. exp() → 가격
5. reflective barrier: [L, H] 밖이면 안쪽으로 reflect (최대 6 pass + final clip)
6. prices[0] = O, prices[-1] = C 강제 (C1, C2)
7. interior argmax → H 치환 (max < H일 때), interior argmin → L 치환 (min > L일 때) ← C3, C4
8. validator 통과
```

`uniform` 과 `bridge` 는 서로 다른 가정 하의 두 가지 옵션이며, **일반 백테스트는
config 가 지정한 한 가지로만 진행한다**. 두 알고리즘의 직접 비교 (같은 데이터에
대해 trades 동일 / Sharpe 차이 등) 는 **`scripts/compare_runs.py` 전용 기능**이며,
`scripts/run_backtest.py` 및 본 시스템의 다른 어떤 경로에서도 비교 결과를 산출하지
않는다 (D16). 이는 결과 리포트가 "어떤 알고리즘이 더 낫다" 같은 결론을 암시하지
않게 하기 위함이다.

### 6.3 등록 패턴

```python
# src/.../tick_synthesis/strategies/<name>.py
@register_tick_generator("uniform")
class UniformTickGenerator:
    def generate(self, bar, n_ticks, rng) -> list[Tick]: ...
```

`tick_synthesis/strategies/__init__.py` 에 `from . import <name>` 한 줄로 등록 트리거.

---

## 7. 마일스톤 회고 (M0~M6 모두 완료)

### M0 — 부트스트랩 ✅
- requirements*.txt 3종 분리, pyproject.toml (build + ruff + mypy + pytest + import-linter)
- core/{types, interfaces, exceptions, events} 완성 (구현 0줄, 타입만)
- utils/{paths, seed, timeutils, logger, config} 완성
- 24 smoke tests 통과
- 산출물: import 만 성공하고 아무 일 안 하는 패키지

### M1 — 데이터 레이어 ✅ (단, 일부 로더는 frozen)
- data/{schema, normalizers} — P4 표준 OHLCV 게이트
- data/loaders/{ccxt, csv, parquet, binance_zip} — M1 시점에는 4가지 출처 모두 표준화
  - **현 단계 active**: `ccxt_loader` (외부 데이터 진입), `parquet_loader` (내부 캐시 read/write)
  - **현 단계 frozen**: `csv_loader`, `binance_zip_loader` — 외부 OHLCV future work 용 (§5)
- data/feeds/replay_feed — BarEvent stream
- data/catalog — processed/ 인덱싱
- scripts/{download_data, inspect_data}
- ParquetLoader 의 attrs 보존 (pyarrow schema metadata 활용)
- CcxtLoader 페이지네이션 + 디스크 캐시 + 재개 다운로드 (현 단계 핵심 진입점)
- API key 미사용 검증 (D15) + cache hit (until 비교 시 timeframe 여유 보정) + 재개 다운로드
- D13 검증: 결손 봉이 있어도 raise 없이 그대로 통과 (test_skip_only_no_gap_fail)
- mock-only test_ccxt_loader 9건 — sandbox 네트워크 없이도 페이지네이션 + 캐시 + 재개 + 정규화 경로 fuzz (plan.md §8.4)
- **data/catalog.py** — list_processed (인덱싱) + inspect_file (스키마/무결성/결손봉 리포트, D13 — fail 안 함)
- **scripts/inspect_data.py** (typer CLI) — `list` / `inspect <path>` 두 명령. 백테스트 전 데이터 품질 확인 + 결과 디버깅의 첫 단추
- test_catalog 8건 (clean / gap / multi-gap / corrupt high<low / missing file)
- 49 tests 통과 (catalog 8 + ccxt_loader 9 + 기타 32)

### M2 — Tick 합성 ✅ (본 프로젝트의 핵심)
- constraints / timestamps / validator / generator 레지스트리
- strategies/uniform.py — baseline
- **hypothesis property tests 2100+ 케이스** 로 C1~C7 fuzz 검증
  (constraints 800 / timestamps 700 / generator integration 600)
- scripts/synthesize_ticks.py — 단일 봉 시각화
- 30 unit tests 통과 (test_constraints / test_timestamps / test_validator / test_uniform_generator)

### M3 — 백테스트 엔진 ✅
- execution: fees / slippage / order_validator / margin / **backtest_broker** (MARKET / LIMIT / STOP / STOP_LIMIT 모두 지원)
- strategy: base_strategy / **indicators (SMA/EMA/RSI/ATR/MACD/BollingerBands streaming)** / order_helpers / registry / examples/ema_cross
- engine: backtest_engine / runner
- analytics: equity_curve / trades / metrics / plots / report
- scripts/run_backtest.py
- 룩어헤드 방지 (submit ≠ fill, 다음 tick 에서 체결)
- LIMIT 은 maker (limit 가격 체결, 슬리피지 X), STOP 은 트리거 즉시 시장가 + 슬리피지, STOP_LIMIT 은 트리거 후 LIMIT 동작
- indicators 는 update 호출 횟수 기반 (D13 결손 봉 무관), `value` / `is_warm` / `reset()` 공통 패턴
- **tqdm 진행상황 표시**: 봉 단위 progress bar + 100봉마다 `equity` / `fills` postfix 라이브 갱신, `disable=None` 으로 비-tty 자동 disable, `--no-progress` 로 명시적 끄기
- 40 tests + indicators 19 tests 추가

### M4 — Brownian Bridge + 비교 도구 ✅
- `tick_synthesis/strategies/bridge.py` — log-space GBM bridge + reflective barrier (max 6 pass) + final clip + post-hoc H/L touch
- `scripts/compare_runs.py` (`preview` / `backtest`) — **uniform vs bridge 비교는 이 스크립트 전용 (D16)**
  - `preview`: 단일 봉에 두 generator 의 tick 경로 PNG
  - `backtest`: 같은 데이터/전략에 `--generator-override` 로 두 번 실행 후 metrics 비교 표
- `engine/runner.py` 의 `run_backtest()` 에 `generator_override` 인자 추가 (compare_runs 가 사용)
- 같은 데이터에서 on_bar-only 전략 (ema_cross 같은) 은 trades 동일, on_tick 트레일링 사용 전략은 차이 발현
- 9 bridge tests 추가 (hypothesis 250+200=450 케이스, C1~C7 + zero-range + edge bars)

### M5 — 실거래 + 안전장치 ✅ → ⚠️ **archived (백테스트 집중 모드)**
> 모든 코드는 `_archive_live/` 에 보존. 복원 절차는 `_archive_live/README.md`.

- execution/ccxt_broker.py — Binance/OKX/Gate.io 어댑터, 멱등성, 재시도, polling fills
- data/feeds/live_feed.py — REST polling BarEvent + TickEvent
- monitoring/{kill_switch, alerts, healthcheck}
- engine/live_engine.py — kill_switch 통합, graceful shutdown 시 자동 청산
- scripts/run_live.py — `--i-understand-real-money` + symbol 입력 이중 가드
- docs/live_deployment_checklist.md
- 37 tests 추가

### M6 — 추가 사용성/검증 (사용자 피드백 반영) ✅

#### 6.1 인코딩 / structlog 호환성
- `requirements*.txt` + `pyproject.toml` ASCII-only (Windows cp949 환경 호환)
- `utils/logger.py` 의 `add_logger_name` processor 제거 (PrintLogger.name 에러 방지)

#### 6.2 CLI 사용성
- `--auto-period`: 데이터 파일의 실제 범위로 config period 자동 덮어쓰기
- `--dump-ticks N`: 샘플 N개 봉의 tick stream → parquet + PNG 로 dump

#### 6.3 Tick 합성 검증 가시화
- `BacktestResult.tick_summary` (TickSummary): generator/seed/n_ticks_total/per-bar 통계
- `BacktestResult.sample_ticks` (DataFrame): 샘플 봉의 raw tick
- `report.html` 에 **"Tick Synthesis (proof)"** 섹션 + sample_tick_paths.png 자동 첨부
- `tick_summary.json` 별도 저장

#### 6.4 ★ 파일 기반 전략 시스템 (MT4 EA 스타일)
- `strategy/api.py` — StrategyAPI (market_buy/sell/limit/stop/close, position(), cash, equity, round_qty, size_from_cash_pct, log) + ParamsView (.get/.require/.contains)
- `strategy/file_strategy.py` — `.py` 동적 로드 → 모듈 globals 에 `api`/`params`/`context` 주입 → on_init/on_bar/on_tick/on_fill/on_deinit 디스패치 + JSON 자동 페어링
- `utils/config.py` 의 `StrategySpec` 에 `path` / `params_path` 추가 + `model_validator` 로 `name xor path` 강제. 기존 registry 모드와 공존.
- `engine/runner.py` 의 `_build_strategy_and_params(spec)` 분기
- `scripts/run_backtest.py` 에 `--strategy <path> --params <path>` 플래그 추가
- `strategies/` 루트 디렉토리 + `_starter.py` + `_starter.json` + `README.md` + **`_reference.md` (MT4 F1 스타일 API 사전, D17 와 함께 추가)**
- `.gitignore` 에 `strategies/*` 무시 + `_starter.*`/`_reference.md`/`README.md` 만 예외
- 19개 신규 테스트 (`test_file_strategy.py`)

#### 6.5 문서
- `docs/USER_GUIDE.md` — 설치~실거래 종단 흐름 (11 섹션)
- `docs/DEVELOPER_GUIDE.md` — 아키텍처 + 확장 시나리오 6가지 + 테스트 + 디버깅 + 릴리스 (12 섹션)
- `docs/strategy_authoring.md` — 파일 기반 우선으로 재작성
- `docs/backtest_quickstart.md` — 30분 안에 첫 백테스트 (시나리오 A 합성 데이터 우선)

**최종: 237/237 tests passed in ~4s**

---

## 8. 검증 전략 (P8)

### 8.1 테스트 피라미드

```
        E2E (느림, 적게)
         tests/integration/test_backtest_e2e.py
              ├─ 합성 OHLCV → 백테스트 → 메트릭 → HTML
              └─ 결정성 회귀 (같은 seed → 같은 final equity)
       Unit + Property (많이)
         tests/unit/  (29 파일)
              ├─ test_smoke.py            (M0 import + 타입 검증)
              ├─ test_{schema,normalizers,loaders,ccxt_loader,replay_feed,catalog}
              ├─ test_{constraints,timestamps,validator}
              ├─ test_{uniform,bridge}_generator  (hypothesis 1000+ 케이스)
              ├─ test_{execution,strategy,analytics}
              ├─ test_{monitoring,alerts,ccxt_broker,live_engine}  (archived 와 함께 동결)
              └─ test_file_strategy  (FileStrategy + StrategyAPI + ParamsView)
```

### 8.2 hypothesis property-based (필수)

`uniform` / `bridge` 둘 다 동일한 property suite 통과:
```python
@given(ohlc=ohlc_floats(), n=integers(4, 512), seed=integers(0, 2**31-1))
def test_property_C1_to_C5_uniform(ohlc, n, seed):
    ticks = generator.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    validate_ticks(bar, ticks, n_min=4, n_max=512)  # C1~C6 전부
```

새 generator 추가 시 동일 스위트를 통과해야만 등록.

### 8.3 결정성 회귀 (P3)

E2E 테스트가 같은 seed 로 두 번 돌려 `metrics.final_equity` bit-exact 비교.

### 8.4 mock-only 거래소 테스트 (archived)

> Broker 측 `_FakeCcxtExchange` 패턴은 archive 와 함께 동결.
> 현 단계의 CCXT 는 **데이터 다운로드용** 이므로 `tests/unit/test_ccxt_loader.py` 에서
> CCXT exchange 객체를 mock 한 다운로드 경로 검증만 수행한다.

### 8.5 실거래 pre-deployment (archived)

> `docs/live_deployment_checklist.md` 와 함께 archive 로 동결. 현 단계 비대상.
> 복원 시 `_archive_live/docs/live_deployment_checklist.md` 의 항목 통과 후 실계 진입.

---

## 9. 의존성

```
runtime (requirements.txt):                              ★ 현 단계 active
  ccxt, pandas, numpy, pyarrow, pydantic, PyYAML, typer, structlog,
  matplotlib, tqdm
  (※ ccxt 는 현 단계에서 데이터 다운로드 용도로만 사용)
  (※ tqdm 은 run_backtest 진행상황 표시용. non-tty 자동 disable)

dev (requirements-dev.txt):                              ★ 현 단계 active
  + pytest, pytest-cov, hypothesis, ruff, mypy, import-linter,
    pre-commit, ipython, jupyter, plotly, pandas-stubs, types-PyYAML

live (requirements-live.txt):                            ⚠️ archived (D11)
  + (ccxt 4.x 가 ws 포함, 추가 없음) — _archive_live/ 와 함께 동결
```

Python 3.11+. 패키지 매니저는 pip + requirements*.txt (D5). 현 단계 설치 대상은 runtime + dev.

---

## 10. 위험 요소와 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 합성 tick 이 실제 microstructure 와 다름 | 백테스트 ↔ forward test 간극 | 슬리피지 모델 + uniform / bridge 두 가지 옵션. **합성 tick 은 간극 완화용 방법론일 뿐, 그 이상의 정밀도 추구는 비목표 (D12)**. |
| OHLC 결측 / 중복 / 거래소 응답 결손 | 일부 봉 누락 | **skip-only**. 1번 봉 다음에 (결측된 2번 봉을 건너뛰고) 3번 봉이 와도 그대로 1→3 으로 진행. 보간/resample/fail 모두 비대상 — 데이터 결손은 거래소 책임으로 위임 (D13). |
| 룩어헤드 바이어스 | 백테스트 과적합 | engine 이 submit≠fill 강제, on_bar 이후 다음 tick 에서만 체결. 그 외 룩어헤드 회피는 전략 코딩 책임. |
| 결정성 깨짐 (numpy reduction 등) | 재현 불가 | **단일 스레드 (D14)**, SeedManager 단일 진실, 결정성 회귀 테스트 |
| Windows mount 환경 .pyc stale | 디버깅 혼란 | `PYTHONDONTWRITEBYTECODE=1 python -B`, heredoc 으로 파일 통째 작성, 또는 `find <src> -name '*.py' -exec touch {} +` 로 .py mtime 갱신 |
| sandbox 네트워크에서 거래소 API 차단 | 실 다운로드 검증 불가 | mock-only 테스트 (test_ccxt_loader, _FakeCcxtExchange 패턴) 로 코드 경로 cover. 사용자 PC 에서 download_data.py 로 실 검증 |

> **API key 위험은 현 단계 비해당 (D15)**: TickWeaver 백테스트 모드는 어떤 단계에서도
> API key / secret 가 필요하지 않음. CCXT 다운로드는 public OHLCV endpoint 만 사용
> (인증 불필요). 따라서 `.env` 파일도 사용하지 않는다.
>
> Live 운영 관련 위험 (거래소 broker quirk, kill_switch 미발동, testnet→실계 sequencing 등)
> 은 archive 와 함께 동결. 복원 시 `_archive_live/` 의 위험 분석 참조.

---

## 11. 확정된 결정 (Decisions Locked)

| # | 항목 | 결정 |
|---|---|---|
| D1 | 데이터 출처 거래소 우선순위 | Binance → OKX → Gate.io (CCXT 다운로드 기준) |
| D2 | 자산 유형 | 선물(USDT-M Perpetual) 우선, config 로 spot 토글 |
| D3 | 자산 개수 | 단일 자산 (multi-symbol 명시적 비목표) |
| D4 | Python 버전 | 3.11+ |
| D5 | 패키지 매니저 | pip + requirements*.txt (3종 분리, live 는 archived) |
| D6 | Tick 개수 기본값 | n_min=8, n_max=256 |
| D7 | 합성 알고리즘 순서 | M2: uniform → M4: bridge |
| D8 | 사용자 전략 형태 | **파일 기반 (MT4 EA 스타일)** + JSON 페어링 (M6 추가) |
| D9 | 백테스트 데이터 | **항상 합성 tick 기반**. tick_summary 로 증명. (M6 명시) |
| D10 | 현 단계 데이터 출처 | **CCXT 다운로드 한 가지만**. 외부 OHLCV (CSV/Parquet/Binance ZIP) 직접 입력은 future work — 현 단계 코드/계획에서 동결 (§5). |
| D11 | 현 단계 운영 모드 | **Backtest only**. M5 Live 코드는 `_archive_live/` 로 동결, 본 문서는 backtest 단일 진실. |
| D12 | 합성 tick 정밀도 정책 | 합성 tick 은 backtest ↔ forward 간극 완화 **방법론**. 현 수준 (uniform / bridge) 유지하고 그 이상의 microstructure 정밀도 추구는 **비목표**. |
| D13 | 결손 OHLCV 처리 | **skip-only**. 결측 봉이 있으면 그 봉을 건너뛰고 다음 봉으로 그대로 진행. 보간/resample/fail 일체 비대상. 데이터 결손은 거래소 책임. |
| D14 | 실행 모델 | **단일 스레드** 강제. 결정성 (P3) + 디버그 단순성. multiprocessing/asyncio 비목표. |
| D15 | API key 정책 | 현 단계 백테스트 모드는 어떤 단계에서도 API key 가 **불필요**. CCXT 다운로드는 public endpoint 만 사용. **`.env` 파일 사용 안 함**. (Live 복원 시 archive 와 함께 별도 정책 적용) |
| D16 | uniform vs bridge 비교 위치 | uniform 과 bridge 의 **직접 비교는 `scripts/compare_runs.py` 전용**. `run_backtest.py` + 본 시스템의 다른 어떤 경로도 비교 결과를 산출하지 않는다. 일반 백테스트는 config 가 지정한 한 가지 알고리즘만 사용. |
| D17 | run_backtest CLI 인자 | 사용자가 입력해야 하는 필수 인자는 `--strategy <path>` 하나. `--out-dir`/`--config`/`--source` 모두 **기본값 보유** (§12.4). `--strategy` 는 자동 해석: `rsi`/`rsi.py`/`strategies/rsi.py`/abs path 모두 동일하게 동작 (`utils/paths.resolve_strategy_path`). |

### 11.1 거래소 어댑터 (D1)
- CCXT unified API 사용. 현 단계에서는 **데이터 다운로드 측면**의 거래소 우선순위 (Binance → OKX → Gate.io).
  - `data/loaders/ccxt_loader.py` 가 거래소 quirk 를 흡수 (페이지네이션 한도, rate limit, since/limit 동작 등).
- 실거래(broker) 측 어댑터 (`_BinanceAdapter` / `_OkxAdapter` / `_GateioAdapter`) 는
  `execution/ccxt_broker.py` 와 함께 archive 로 동결 → 복원 시 `_archive_live/` 참조.

### 11.2 의존성 3분할 (D5)
- runtime / dev / live 분리. **현 단계 active**: runtime + dev 만.
  `requirements-live.txt` 는 archive 와 함께 동결.

### 11.3 파일 기반 전략 (D8) — MT4 EA 스타일

```python
# strategies/my_alpha.py — 한 파일 = 한 전략
prev_close = 0.0  # 모듈 전역 = MT4 글로벌 변수

def on_init():
    global prev_close
    prev_close = 0.0

def on_bar(bar):
    global prev_close
    if bar.close > prev_close * 1.01 and api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.1, bar.close))
    prev_close = bar.close
```

엔진이 `on_init` 직전에 모듈 globals 에 `api`, `params`, `context` 주입.
호출: `python scripts/run_backtest.py --strategy strategies/my_alpha.py`

### 11.4 결정 변경 로그 (Changelog)

| 날짜 | 변경 | 사유 |
|---|---|---|
| 2026-05-09 | D1~D7 초기 확정 | 사용자 답변 |
| 2026-05-09 | D8 추가 (파일 기반 전략) | 사용자 요구: MT4 EA 스타일이 학습/실험에 가장 좋음 |
| 2026-05-09 | D9 명시 | 사용자 확인: 백테스트는 항상 합성 tick 전제 |
| 2026-05-09 | requirements/pyproject ASCII-only | Windows cp949 환경 pip 깨짐 |
| 2026-05-09 | structlog add_logger_name 제거 | PrintLogger.name 에러 |
| 2026-05-09 | **D10 신설** — 현 단계 데이터 출처 = CCXT only. 외부 OHLCV 입력은 future work | 사용자 결정: 본 프로젝트는 "CCXT 자동매매 전용 백테스트" 가 아니라 "OHLCV → 합성 tick → 백테스트" 가 본질. 다만 외부 OHLCV 직접 입력은 현 단계에서 작업하지 않음 |
| 2026-05-09 | **D11 신설** — 현 단계 운영 모드 = backtest only. M5 + 모든 Live 관련 자산 archive 로 동결 | 사용자 결정: 앞으로 작업은 backtest 에 집중. Live 는 추후 복원 옵션 |
| 2026-05-09 | §0/§1.1/§1.3/§3.1/§4/§5/§7 M1/§10/§11/§12/§13 톤 정리 | D10·D11 반영 — Live 잔재 + 외부 OHLCV 잔재 정리 |
| 2026-05-09 | **D12 신설** — 합성 tick 정밀도 = 현 수준 유지 (방법론) | 사용자: 합성 tick 은 backtest↔forward 간극 완화용 도구일 뿐, 그 이상의 정밀도 추구는 비목표 |
| 2026-05-09 | **D13 신설** — 결손 OHLCV = skip-only (보간/fail 비대상) | 사용자: 결손은 거래소 책임. 1번→3번으로 그대로 진행. P6 도 함께 수정 |
| 2026-05-09 | **D14 신설** — 단일 스레드 강제 | 사용자 결정 |
| 2026-05-09 | **D15 신설** — 백테스트 모드 = API key 일체 미사용. `.env` 사용 안 함 | 사용자: CCXT public OHLCV 다운로드는 인증 불필요. §10 위험표에서 API key 행 제거 |
| 2026-05-09 | **D16 신설** — uniform vs bridge 비교 = compare_runs.py 전용 | 사용자: run_backtest 외 모든 경로에서 비교 결과 산출 금지. §3.1/§6.2/§7 M4 톤 정리 |
| 2026-05-09 | **D17 신설** — run_backtest CLI 단순화 (`--strategy` 만 필수) | 사용자: Python 비숙련자에게 `--config`/`--source` 입력 부담. §12.4 재작성 |
| 2026-05-09 | strategies/_reference.md 추가 + .gitignore 예외 갱신 | 사용자: MT4 F1 도움말 같은 사전형 레퍼런스. 커밋 대상 |

---

## 12. 사용자 워크플로 (요약)

### 12.1 설치
```powershell
cd <project-root>
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
```

### 12.2 데이터 준비 (현 단계: CCXT 메인, 합성은 빠른 테스트용)
- **B (메인 경로)**: CCXT 다운로드 —
  `python scripts/download_data.py --exchange binance --symbol "BTC/USDT:USDT" --timeframe 1h --since 2024-01-01 --until 2024-07-01`
- **A (옵션, 빠른 sanity check 용)**: 테스트 픽스처에서 합성 OHLCV parquet 생성 (네트워크 X) —
  단위 테스트/스모크 검증 수준에서만 사용
- ~~**C**: 외부 ZIP/CSV — Binance Vision → BinanceZipLoader~~
  → **현 단계 미지원** (§5 future work, D10). `csv_loader` / `binance_zip_loader` 는 frozen.

### 12.3 전략 작성
```powershell
copy strategies\_starter.py    strategies\my_alpha.py
copy strategies\_starter.json  strategies\my_alpha.json
# my_alpha.py 의 on_bar(bar) 만 수정
```

### 12.4 백테스트 (D17 — 인자 단순화)

사용자가 외워야 하는 인자는 **`--strategy` 하나**. 나머지는 모두 기본값 보유.

```powershell
# 최소 호출 — 전략 stem 만 입력하면 자동으로 strategies/<stem>.py 로 해석
python scripts/run_backtest.py --strategy my_alpha

# 아래 4가지 입력 모두 동일하게 동작 (utils/paths.resolve_strategy_path)
python scripts/run_backtest.py --strategy my_alpha
python scripts/run_backtest.py --strategy my_alpha.py
python scripts/run_backtest.py --strategy strategies/my_alpha.py
python scripts/run_backtest.py --strategy /abs/path/to/my_alpha.py
```

기본값 동작:

| 플래그 | 기본값 | 동작 |
|---|---|---|
| `--strategy <path>` | (필수) | 사용자 전략 .py 파일 경로 |
| `--out-dir <path>` | `reports/<strategy_stem>_<UTC_timestamp>/` | 자동 생성 |
| `--config <path>` | `configs/backtest/default.yaml` | 커밋된 sensible default |
| `--source <path>` | `data/processed/` 의 가장 최근 mtime parquet. 비어 있으면 친절한 에러로 `python scripts/download_data.py ...` 사용법 안내 |
| `--params <path>` | `<strategy>.json` 자동 페어링 (있으면) | M6.4 기존 동작 유지 |
| `--dump-ticks N` | `0` (미수행) | 사용자 명시 시만 수행 |
| `--auto-period` | `True` (자동) | 데이터 파일 실제 범위로 config period 자동 덮어쓰기 |

```powershell
# 자주 쓰는 형태
python scripts/run_backtest.py --strategy strategies/my_alpha.py --out-dir reports/run01

# 고급 — config / source 직접 지정
python scripts/run_backtest.py `
    --strategy strategies/my_alpha.py `
    --config configs/backtest/quickstart_demo.yaml `
    --source data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
```

> Python 에 익숙하지 않은 사용자는 첫 줄만 외우면 충분하다.
> uniform vs bridge 비교가 필요하면 별도로 `scripts/compare_runs.py` 사용 (D16).

### 12.5 결과 확인
`reports/run01/report.html` 브라우저로 열기:
- Metrics (Sharpe, MDD, Win rate, ...)
- **Tick Synthesis (proof)** 섹션 — generator/seed/per-bar 통계
- **Sample tick paths PNG** — 5개 봉의 실제 합성 tick 경로
- Equity Curve + drawdown
- Trades 표

### 12.6 실거래 (testnet → 실계) — ⚠️ archived
> 현재 backtest-only mode. 실거래는 `_archive_live/` 에 보존된 코드를
> 복원해야 사용 가능. 복원 절차는 `_archive_live/README.md`.
> 복원 후의 절차는 `docs/live_deployment_checklist.md` (archive 안에 있음) 참조.

---

## 13. 다음 단계 (선택사항)

이미 M0~M6 가 완료되었고, 본 문서는 **backtest 단일 진실 (D11)** 로 정리된 상태.
향후 확장 가능한 영역을 카테고리별로 정리:

### 13.1 Backtest 기능 확장 (현 단계 연장선)
1. **MT4 strategy tester 같은 시각화** (verbose) — matplotlib animation 또는 web UI 로
   봉 + 합성 tick + 주문 marker 실시간 표시 (보류 중)
2. **추가 tick generator** — volume-weighted timestamp, regime-switching 등
3. **추가 CCXT 거래소 데이터 로더 검증** — Bybit, Coinbase 등 (D1 우선순위 외)
4. **Multi-asset / Multi-strategy** — D3 변경 + engine 대대적 수정

### 13.2 외부 OHLCV 입력 활성화 (D10 해제 시)
5. **`csv_loader` / `binance_zip_loader` 활성화** — §5 의 frozen 상태 해제,
   `configs/data/external_template.yaml` 정상 흐름화, e2e 테스트 추가
6. **외부 입력 → CCXT 캐시 우회 경로 정리** — `data/processed/external/` 네임스페이스 정의

### 13.3 Live 복원 (D11 해제 시 — `_archive_live/` 복원 후)
7. **WebSocket live feed** — 현재 REST polling, ccxt.pro ws 로 업그레이드
8. **Hedge mode** — 양방향 동시 보유 (현재 one-way only)
9. **추가 broker 거래소 어댑터** — Bybit, Coinbase 등 (broker 측)

### 13.4 인프라/배포
10. **GitHub Actions CI** — `.github/workflows/ci.yml` (DEVELOPER_GUIDE §8 참고)
11. **PyPI 배포** — wheel 빌드 (`python -m build`)

---

*본 plan.md 는 살아있는 문서다. 결정이 바뀌면 §11.4 changelog 에 기록한다.
새 마일스톤 완료 시 §7 회고에 추가한다.*
