# tickweaver — Strategy Reference (전략 작성 사전)

> **이 문서가 무엇인가?**
> MT4 EA 편집기에서 F1 을 누르면 뜨는 도움말 같은 **사전형 레퍼런스**입니다.
> 파일 기반 전략 (`strategies/<your_name>.py`) 을 직접 코딩할 때 필요한
> 라이프사이클 훅, 주입 변수, API 메서드, 타입을 한 파일에서 찾을 수 있습니다.
>
> 가이드/튜토리얼은 `docs/strategy_authoring.md` 를 보세요. 이 파일은 **사전**입니다.
>
> 시그니처/타입의 권위 있는 출처는 언제나 실제 소스입니다:
> `src/tickweaver/core/types.py` · `src/tickweaver/strategy/api.py` ·
> `src/tickweaver/strategy/indicators.py` · `src/tickweaver/strategy/file_strategy.py`.

---

## 목차

0. [시작하기 전에](#0-시작하기-전에)
1. [라이프사이클 훅](#1-라이프사이클-훅-on_init--on_bar--on_tick--on_fill--on_deinit)
2. [주입된 globals](#2-주입된-globals--api--context--enums)
3. [StrategyAPI 메서드 사전](#3-strategyapi-메서드-사전)
4. [트레이딩 파라미터 — 모듈 상수](#4-트레이딩-파라미터--모듈-상수)
5. [타입 사전](#5-타입-사전)
6. [자주 쓰는 패턴](#6-자주-쓰는-패턴)
7. [함정과 주의사항](#7-함정과-주의사항)
8. [FAQ](#8-faq)
9. [지표 시각화 (`--viz`)](#9-지표-시각화---viz)

---

## 0. 시작하기 전에

### 0.1 한 파일 = 한 전략, json 페어링 없음

전략은 `.py` **한 개** 입니다. 트레이딩 파라미터는 그 `.py` 안의 **모듈 상수**로
관리합니다. 별도 `.json` 파라미터 파일은 **없습니다**. 환경(심볼/기간/비용/tick 합성)은
`configs/` 아래 yaml 이 정의합니다.

```
strategies/
├── _starter.py        ← 보일러플레이트 (이거 복사해서 시작)
├── _reference.md      ← 본 문서
├── README.md
├── supertrend.py      ← 번들 예제 (Pattern 2)
├── goldrun.py         ← 번들 예제
└── my_alpha.py        ← 너의 전략
```

### 0.2 실행 한 줄

```powershell
python scripts/run_backtest.py --strategy my_alpha
```

`--strategy` 는 자동 해석됩니다 — 아래 4가지 입력 모두 동일하게 동작:

```powershell
python scripts/run_backtest.py --strategy my_alpha               # stem 만
python scripts/run_backtest.py --strategy my_alpha.py            # basename
python scripts/run_backtest.py --strategy strategies/my_alpha.py # 명시적 경로
python scripts/run_backtest.py --strategy /abs/path/my_alpha.py  # 절대 경로
```

`--config` 는 bare 파일명이면 `configs/` 아래에서 찾고, 생략 시 `configs/default.yaml`
(spot) 이 기본값입니다. short 를 여는 전략은 `--config futures.yaml` 이 필요합니다 (§7.8).

### 0.3 모듈 전역 = MT4 글로벌

전략 파일의 모듈 전역 변수는 MT4 EA 의 글로벌 변수처럼 백테스트 동안 유지됩니다.

```python
# strategies/my_alpha.py
prev_close = 0.0          # ← 모듈 전역 = EA 글로벌
trade_count = 0

def on_init():
    global prev_close, trade_count
    prev_close = 0.0
    trade_count = 0
```

엔진은 `on_init` 호출 직전에 모듈 globals 에 **`api`, `context`, 그리고 enum 3종
(`Side` / `OrderType` / `PositionSide`)** 을 주입합니다 (§2). 그 이후로 어떤 훅에서든
그냥 `api.market_buy(...)` 처럼 쓸 수 있습니다.

### 0.4 IDE 경고 끄기 — `TYPE_CHECKING` 표준 블록

`api`, `context`, `Side` / `OrderType` / `PositionSide` 같은 이름들은 모두 FileStrategy 가
모듈 namespace 에 **런타임 주입**합니다. 즉 정적 분석기 (Pylance / Pyright / mypy) 가
그 사실을 모르고 "undefined variable" 경고를 띄웁니다.

이걸 끄려면 모든 전략 파일 상단에 아래 **TYPE_CHECKING 표준 블록**을 넣어주세요. 런타임에는
`TYPE_CHECKING == False` 라서 안쪽 import 와 변수 선언은 절대 실행되지 않습니다 — 순수 IDE
힌트입니다.

```python
"""my_alpha.py - 한 줄 요약."""

from typing import TYPE_CHECKING

# 런타임에 실제로 사용할 import 는 여기에. (예: indicators)
from tickweaver.strategy.indicators import RSI

if TYPE_CHECKING:
    # Type stubs for IDE / linter only — never executed at runtime.
    # FileStrategy injects these names into the module namespace right
    # before on_init/on_bar/... are called.
    from tickweaver.core.types import (
        Fill,
        OHLCBar,
        OrderType,
        PositionSide,
        Side,
        StrategyContext,
        Tick,
    )
    from tickweaver.strategy.api import StrategyAPI

    api: StrategyAPI
    context: StrategyContext
```

훅 시그니처에도 forward-ref 어노테이션을 붙이면 `bar.close`, `tick.price`, `fill.qty` 같은
멤버 자동완성이 켜집니다:

```python
def on_init() -> None: ...
def on_bar(bar: "OHLCBar") -> None: ...
def on_tick(tick: "Tick") -> None: ...
def on_fill(fill: "Fill") -> None: ...
def on_deinit() -> None: ...
```

**왜 forward-ref (`"OHLCBar"`) 인가**: 어노테이션 값이 문자열이면 Python 이 import 시점에
평가하지 않습니다. `OHLCBar` 등은 `TYPE_CHECKING` 블록 안에서만 import 되었으므로 (런타임에는
정의되지 않음), 어노테이션을 그냥 `OHLCBar` 로 쓰면 NameError 가 납니다. 문자열 forward-ref 가
안전한 표준입니다.

복사해 쓸 수 있는 완전한 템플릿은 `strategies/_starter.py` 에 들어있습니다.

---

## 1. 라이프사이클 훅 (`on_init` / `on_bar` / `on_tick` / `on_fill` / `on_deinit`)

각 훅은 **선택적**입니다. 정의되지 않은 훅은 noop 으로 취급됩니다.

### 1.1 `on_init() -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 백테스트 시작 직전 1회 |
| 인자 | 없음 |
| 사용 가능 | `api`, `context`, enum 모두 주입 완료 |
| 일반 용도 | 전역 상태 초기화, 인디케이터 객체 생성, 모듈 상수 정합성 검증 |

```python
from tickweaver.strategy.indicators import EMA

EMA_FAST = 12          # 모듈 상수 (파라미터)
EMA_SLOW = 26

ema_fast = None        # 상태 (on_init 에서 생성)
ema_slow = None

def on_init():
    global ema_fast, ema_slow
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)
    api.log("strategy initialized", fast=EMA_FAST, slow=EMA_SLOW)
```

---

### 1.2 `on_bar(bar: OHLCBar) -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 각 봉이 **닫힌 직후** (다음 봉이 시작되기 전) |
| 인자 | `bar` — 방금 닫힌 OHLCBar |
| 일반 용도 | 신호 생성, 진입/청산 결정 |

**중요 — 룩어헤드 방지**: `on_bar` 안에서 낸 주문은 **다음 봉의 첫 tick** 부터 체결 시도됩니다.
즉 "이 봉의 close 를 보고 이 봉의 close 가격에 체결" 은 불가능합니다 (engine 이 강제). 따라서
안심하고 `bar.close` 를 시그널 입력으로 써도 룩어헤드가 발생하지 않습니다.

```python
def on_bar(bar):
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if ema_fast.value is None or ema_slow.value is None:
        return
    if ema_fast.value > ema_slow.value and api.is_flat():
        qty = api.size_from_cash_pct(0.1, bar.close)
        api.market_buy(qty)
```

---

### 1.3 `on_tick(tick: Tick) -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 봉 내부 합성 tick 마다 |
| 인자 | `tick` — 합성된 가격 한 점 |
| 일반 용도 | tick 단위 트레일링 스탑, 손절 모니터링, 마진 체크 |

**중요**: tick 은 OHLC 로부터 합성된 **그럴듯한 가격 경로** 일 뿐, 실제 호가창/체결 동작이
아닙니다 (D12). tick 단위로 너무 세밀한 가정 (예: 0.001 점프 단위, microstructure noise) 을
두는 전략은 forward test 에서 깨지기 쉽습니다.

```python
TRAIL_PCT = 0.02

def on_tick(tick):
    pos = api.position()
    if pos.side != PositionSide.LONG:
        return
    high_water = max(pos.entry_price, getattr(on_tick, "_hw", pos.entry_price))
    high_water = max(high_water, tick.price)
    on_tick._hw = high_water
    if tick.price < high_water * (1 - TRAIL_PCT):
        api.close_position()
```

---

### 1.4 `on_fill(fill: Fill) -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 주문이 체결될 때마다 |
| 인자 | `fill` — 체결 정보 |
| 일반 용도 | 체결 로그, 포지션 사이즈 갱신, 리스크 카운터 |

```python
def on_fill(fill):
    api.log("filled",
            side=fill.side.name,
            price=fill.price,
            qty=fill.qty,
            fee=fill.fee)
```

---

### 1.5 `on_deinit() -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 백테스트 종료 직후 1회 |
| 인자 | 없음 |
| 일반 용도 | 최종 상태 로깅, 사용자 정의 메트릭 dump |

---

## 2. 주입된 globals — `api` / `context` / enums

`on_init` 호출 직전에 엔진(`FileStrategy.load`)이 모듈 globals 에 주입하는 객체들입니다.
따로 import 할 필요 없이 어떤 훅에서든 그냥 사용하면 됩니다.

| 이름 | 타입 | 역할 |
|---|---|---|
| `api` | `StrategyAPI` | 주문 / 포지션 / 계정 정보 접근의 단일 게이트웨이 (§3) |
| `context` | `StrategyContext` | 현재 시점 / 봉 인덱스 / 심볼·타임프레임 메타정보 (§5.7) |
| `Side` | `Enum` | BUY / SELL (편의용) |
| `OrderType` | `Enum` | MARKET / LIMIT / STOP / STOP_LIMIT (편의용) |
| `PositionSide` | `Enum` | LONG / SHORT / FLAT (편의용) |

> **`params` 는 없습니다.** 트레이딩 파라미터는 `.py` 안의 모듈 상수로 관리합니다 (§4).
> `<strategy>.json` 페어링 파일 방식은 더 이상 존재하지 않습니다.

`context` 는 일반적으로 직접 건드릴 일이 적습니다. `bar` 인자에 timestamp/symbol 정보가 이미
들어 있고, 메타가 더 필요하면 `context.symbol`, `context.timeframe` 정도를 읽는 용도로
사용합니다.

---

## 3. StrategyAPI 메서드 사전

> 모든 주문 메서드는 **멱등성 키 (`client_order_id`) 가 자동 부여**됩니다. 같은 봉/같은
> 시그널에서 두 번 호출되면 두 번째는 거부될 수 있으니, "한 시그널 = 한 호출" 패턴을 지키세요.
>
> 주문 메서드의 **공통 반환**: `order_id (str)`. `cancel()` 만 `bool`,
> `close_position()` 은 `str | None`, `close_all()` 은 `list[str]` 반환.
> 모든 `qty` 인자는 내부적으로 `round_qty()` 가 자동 적용되며, 0 이하로 떨어지면 주문은
> 발주되지 않고 **빈 문자열 `""`** 을 반환하면서 `zero_qty_order` 경고를 남깁니다 (raise 아님).

### 3.1 주문 메서드

| 메서드 | 인자 | 체결 동작 | 슬리피지 |
|---|---|---|---|
| `api.market_buy(qty)` | `qty: float` (양수) | 다음 tick 가격에 즉시 체결 | 적용 |
| `api.market_sell(qty)` | `qty: float` (양수) | 다음 tick 가격에 즉시 체결 (long 청산 또는 short 진입) | 적용 |
| `api.limit_buy(qty, price)` | `qty`, `price` (목표 매수가) | tick 가격 ≤ `price` 인 첫 tick 에서 **`price` 로** 체결 | 미적용 (maker) |
| `api.limit_sell(qty, price)` | `qty`, `price` (목표 매도가) | tick 가격 ≥ `price` 인 첫 tick 에서 **`price` 로** 체결 | 미적용 (maker) |
| `api.stop_buy(qty, stop_price)` | `qty`, `stop_price` (트리거) | tick ≥ `stop_price` 도달 시 시장가 매수로 전환 (브레이크아웃 진입 / 숏 손절) | 적용 |
| `api.stop_sell(qty, stop_price)` | `qty`, `stop_price` (트리거) | tick ≤ `stop_price` 도달 시 시장가 매도로 전환 (롱 손절) | 적용 |
| `api.stop_limit_buy(qty, stop_price, limit_price)` | `qty`, `stop_price` (트리거), `limit_price` (체결 한도) | trigger 이후 `limit_buy(qty, limit_price)` 와 동일하게 동작 | 미적용 |
| `api.stop_limit_sell(qty, stop_price, limit_price)` | `qty`, `stop_price` (트리거), `limit_price` (체결 한도) | trigger 이후 `limit_sell(qty, limit_price)` 와 동일하게 동작 | 미적용 |
| `api.cancel(order_id)` | `order_id: str` | 대기 중인 주문 취소. 이미 체결됐으면 `False` 반환 | — |

수수료는 모든 체결에 config 의 `commission` 으로 자동 적용. 슬리피지는 위 표의 "적용" 행만
`slippage` 로 자동 적용. **FLAT 상태에서 short 를 여는 `market_sell` / `limit_sell` /
`stop_sell` 은 `mode: futures` config 에서만 허용**됩니다 (spot 이면
`SpotShortNotAllowedError`, §7.8).

```python
api.market_buy(0.05)
api.limit_buy(0.05, bar.close * 0.997)              # 0.3% 아래 LIMIT BUY
api.stop_sell(pos.qty, pos.entry_price * 0.99)      # 진입가 -1% 손절 STOP
```

---

### 3.2 청산 메서드

| 메서드 | 반환 | 동작 |
|---|---|---|
| `api.close_position()` | `order_id (str)` 또는 `None` | 현재 포지션을 보유 방향의 반대 시장가 주문으로 청산. 포지션 없으면 `None` |
| `api.close_all()` | `list[str]` | 현 단계 D3 (단일 자산) 에서는 사실상 `close_position()` 과 동일 (체결 시 `[order_id]`, 없으면 `[]`). 미래 multi-symbol 확장을 위한 alias |

---

### 3.3 조회 메서드 / 프로퍼티

| 이름 | 형태 | 반환 | 비고 |
|---|---|---|---|
| `api.position()` | method | `Position` (§5.5) | 포지션 없으면 `Position(side=FLAT, qty=0, ...)` |
| `api.is_flat()` | method | `bool` | `api.position().side == PositionSide.FLAT` 의 편의 함수 |
| `api.cash` | property | `float` | 현재 현금 잔고 |
| `api.equity` | property | `float` | `cash + 미실현 PnL` |
| `api.leverage` | property | `float` | config 의 `run.leverage` 전달값 (spot 이면 1.0). 전략에서 보통 수량 배수로 사용: `qty = notional * api.leverage / price`. 브로커 회계 자체는 leverage 무관 — 현금은 full notional 로 차감됨 (마진 거래 시맨틱은 미구현) |

---

### 3.4 헬퍼 / 로깅 / 차트 메서드

| 메서드 | 인자 | 반환 | 용도 |
|---|---|---|---|
| `api.round_qty(qty)` | `qty: float` | `float` | 거래소 step_size 에 맞춰 내림. 주문 메서드는 내부에서 이미 호출하지만 직접 사이즈 계산을 검증할 때 사용 |
| `api.size_from_cash_pct(pct, price)` | `pct: float (0~1)`, `price: float` | `float` | `cash × pct ÷ price` 를 `round_qty` 적용해 반환. 자본 곡선에 자동 스케일하는 사이즈 계산 (`price <= 0` 이면 0.0) |
| `api.log(msg, **kwargs)` | `msg: str`, 임의 `**kwargs` | `None` | 콘솔 로거. progress 바가 켜진 실행에서는 silent (`console_log=False` → noop). `--no-progress` 로 보임. `report.html` 에는 미반영 |
| `api.comment(text)` | `text: str` | `None` | MT4 `Comment()` 등가물 (D21). `--viz` 차트 좌상단 라벨에 텍스트 표시 (`\n` 으로 줄바꿈, 빈 문자열이면 라벨 클리어). viz off 면 noop |
| `api.bind_indicator(name, indicator, panel=None, **style)` | §9.1 | `None` | streaming 인디케이터를 차트에 등록 (viz off 면 noop, idempotent). §9 참조 |
| `api.plot(name, value, panel="price", **style)` | §9.6 | `None` | 외부 계산값을 차트 라인으로 직접 emit (viz off 면 noop). §9.6 참조 |

```python
qty = api.size_from_cash_pct(0.1, bar.close)   # 현금의 10%
api.market_buy(qty)

api.log("entry signal", price=bar.close, ema=ema_fast.value)
api.comment(f"entry @ {bar.close:.2f}")        # --viz 일 때만 화면에 보임
```

---

## 4. 트레이딩 파라미터 — 모듈 상수

전략의 튜닝 파라미터(기간, 임계값, 사이즈 비율 등)는 `.py` **상단의 모듈 상수**로 둡니다.
`params` 주입이나 `<strategy>.json` 페어링은 **없습니다** — 한 파일 안에 로직과 파라미터가
함께 삽니다.

```python
# ── trading parameters (edit here to tune) ──────────────────
EMA_FAST = 12
EMA_SLOW = 26
SIZE_PCT = 0.1          # 10% of available cash per entry
TRAIL_PCT = 0.02
```

관습:

- **대문자 상수** 로 작성해 "튜닝 노브" 임을 시각적으로 구분 (`SIZE_PCT`, `ST_PERIOD` 등).
- 인디케이터 객체 등 **상태(state)** 는 소문자 모듈 변수로 두고 `on_init` 에서 생성·리셋
  (§7.7).
- 파라미터 정합성 검증은 `on_init` 에서 `raise` 로 fail-fast (§6.4).

환경 파라미터(심볼/타임프레임/기간/초기자본/수수료/슬리피지/tick 합성)는 전략이 아니라
`configs/<env>.yaml` 이 정의합니다. 같은 `.py` 를 다른 yaml 과 페어링해 환경만 바꿔
돌릴 수 있습니다.

```powershell
python scripts/run_backtest.py --strategy my_alpha                      # configs/default.yaml (spot)
python scripts/run_backtest.py --strategy my_alpha --config futures.yaml # 동일 전략, 선물 환경
```

---

## 5. 타입 사전

> 모든 dataclass / Enum 정의는 `src/tickweaver/core/types.py` 에 있습니다. 본 사전은 사용자가
> 자주 만나는 필드 위주로 정리했습니다.

### 5.1 `OHLCBar` (frozen)

| 필드 | 타입 | 설명 |
|---|---|---|
| `timestamp` | `pd.Timestamp` (UTC) | 봉의 close time (단조 증가) |
| `open` / `high` / `low` / `close` | `float` | OHLC |
| `volume` | `float` | 거래량 |
| `symbol` | `str` | 예: `"BTC/USDT:USDT"` |
| `timeframe` | `str` | 예: `"1h"` |

### 5.2 `Tick` (frozen)

| 필드 | 타입 | 설명 |
|---|---|---|
| `timestamp` | `pd.Timestamp` (UTC) | 합성 tick 시각 |
| `price` | `float` | 합성 가격 |
| `bar_index` | `int` | 어느 봉에 속하는지 |
| `tick_index_in_bar` | `int` | 봉 내부 tick 순번 |
| `symbol` | `str` | 기본 `""` |

### 5.3 `Order`

| 필드 | 타입 | 설명 |
|---|---|---|
| `order_id` | `str` | 엔진 발급 ID |
| `client_order_id` | `str` | 멱등성 키 (자동 부여) |
| `symbol` | `str` | 심볼 |
| `side` | `Side` | BUY / SELL |
| `type` | `OrderType` | MARKET / LIMIT / STOP / STOP_LIMIT |
| `qty` | `float` | 수량 (round_qty 후) |
| `price` | `float \| None` | LIMIT / STOP_LIMIT 일 때만 |
| `stop_price` | `float \| None` | STOP / STOP_LIMIT 만 |
| `created_at` | `pd.Timestamp \| None` | 발주 시각 |
| `status` | `str` | `open` / `filled` / `cancelled` |

### 5.4 `Fill`

| 필드 | 타입 | 설명 |
|---|---|---|
| `order_id` | `str` | 어떤 주문의 체결인지 |
| `symbol` | `str` | 심볼 |
| `side` | `Side` | BUY / SELL |
| `qty` | `float` | 실제 체결 수량 |
| `price` | `float` | 슬리피지 적용 후 체결가 |
| `fee` | `float` | 수수료 |
| `timestamp` | `pd.Timestamp` (UTC) | 체결 시각 |
| `pnl_realized` | `float` | 이 체결에서 확정된 PnL (포지션 축소 시) |

### 5.5 `Position`

| 필드 | 타입 | 설명 |
|---|---|---|
| `symbol` | `str` | 심볼 |
| `side` | `PositionSide` | LONG / SHORT / FLAT |
| `qty` | `float` | 절대 수량 (방향은 side 로 표현) |
| `entry_price` | `float` | 평균 진입가 |
| `mark_price` | `float` | 현재 mark 가격 |
| `unrealized_pnl` | `float` | 미실현 PnL |
| `liquidation_price` | `float \| None` | 선물 격리 마진 청산가 |

편의 프로퍼티: `pos.is_flat` → `side == FLAT or qty == 0` (bool).

### 5.6 Enum

```python
class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

class MarketType(str, Enum):
    SPOT = "spot"
    USDT_M_PERPETUAL = "usdt_m_perpetual"
```

모두 `str` 혼합 Enum 이라 `pos.side.value == "long"` 같은 문자열 비교도 동작합니다.
`Side` / `OrderType` / `PositionSide` 는 globals 로 주입되므로 import 없이 바로 쓸 수 있고,
명시적으로 import 하려면:

```python
from tickweaver.core.types import Side, OrderType, PositionSide, MarketType
```

### 5.7 `StrategyContext`

`context` 로 주입됩니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `symbol` | `str` | 심볼 |
| `timeframe` | `str` | 타임프레임 |
| `market_type` | `MarketType` | 기본 `USDT_M_PERPETUAL` |
| `bar_index` | `int` | 현재 봉 인덱스 |
| `now` | `pd.Timestamp \| None` | 현재 시점 |
| `extras` | `dict[str, Any]` | 확장용 |

---

## 6. 자주 쓰는 패턴

### 6.1 단순 EMA 크로스

```python
from tickweaver.strategy.indicators import EMA

EMA_FAST = 12
EMA_SLOW = 26
SIZE_PCT = 0.1

ema_fast = None
ema_slow = None

def on_init():
    global ema_fast, ema_slow
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)

def on_bar(bar):
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if ema_fast.value is None or ema_slow.value is None:
        return
    bullish = ema_fast.value > ema_slow.value
    if bullish and api.is_flat():
        api.market_buy(api.size_from_cash_pct(SIZE_PCT, bar.close))
    elif (not bullish) and not api.is_flat():
        api.close_position()
```

### 6.2 진입은 `on_bar`, 청산 트레일은 `on_tick`

```python
TRAIL_PCT = 0.02
high_water = None

def on_init():
    global high_water
    high_water = None

def on_bar(bar):
    global high_water
    if some_entry_signal(bar) and api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.1, bar.close))
        high_water = bar.close

def on_tick(tick):
    global high_water
    pos = api.position()
    if pos.side != PositionSide.LONG or high_water is None:
        return
    high_water = max(high_water, tick.price)
    if tick.price < high_water * (1 - TRAIL_PCT):
        api.close_position()
        high_water = None
```

### 6.3 N개 봉 보유 후 자동 청산

```python
HOLD_N = 5
bars_held = 0

def on_init():
    global bars_held
    bars_held = 0

def on_bar(bar):
    global bars_held
    if not api.is_flat():
        bars_held += 1
        if bars_held >= HOLD_N:
            api.close_position()
            bars_held = 0
        return
    if some_entry_signal(bar):
        api.market_buy(api.size_from_cash_pct(0.1, bar.close))
        bars_held = 0
```

### 6.4 파라미터 검증 (fail-fast)

```python
EMA_FAST = 12
EMA_SLOW = 26

def on_init():
    if EMA_FAST >= EMA_SLOW:
        raise ValueError(f"EMA_FAST({EMA_FAST}) must be < EMA_SLOW({EMA_SLOW})")
```

---

## 7. 함정과 주의사항

### 7.1 룩어헤드는 엔진이 막아준다, 그러나…

엔진은 "on_bar 에서 발주한 주문은 다음 봉 첫 tick 에서 체결" 을 강제하므로, `bar.close` 를
시그널 입력으로 써도 안전합니다. 그러나 다음 두 패턴은 사용자가 직접 망칠 수 있습니다:

- 미래 정보를 외부 파일/캐시에서 읽어오기
- `context` 에서 미래 봉 인덱스를 추정해 액세스

→ 전략 안에서는 **현재까지 도착한 데이터** 만 본다.

### 7.2 합성 tick 의 한계 (D12)

`on_tick` 에 들어오는 tick 은 OHLC 로부터 합성된 가격 경로입니다. 다음을 가정/요구하면 forward
test 에서 깨집니다:

- microstructure noise (호가 점프 패턴) 가정
- tick 간 정확한 시간 간격 가정 (uniform 분배일 뿐)
- volume-weighted tick 가정 (현 단계 미지원)

합성 tick 은 backtest ↔ forward 간극 완화용 **방법론**일 뿐이라는 점을 잊지 마세요.

### 7.3 결손 봉은 그냥 건너뛴다 (D13)

거래소가 일부 봉을 누락한 경우, TickWeaver 는 **그 봉을 skip 하고 다음 봉으로 이어붙여
진행**합니다. 보간/재샘플링/실패 모두 일어나지 않습니다.

따라서:

- `bar.timestamp` 의 간격이 항상 `timeframe` 과 일치한다고 **가정 금지**
- 시간 차로 봉 인덱스를 추정하지 말고, 실제 들어온 bar 를 카운트
- "12개 봉 보유 = 12시간 보유" 같은 등식 금지

### 7.4 단일 스레드 전제 (D14)

전략 안에서 무거운 연산을 하면 백테스트 전체가 느려집니다. heavy ML 추론은 권장되지 않습니다.

### 7.5 멱등성 키와 중복 발주

`on_bar` 안에서 같은 시그널로 두 번 `market_buy` 를 호출하면 두 번째는 (자동 client_order_id
충돌로) 거부될 수 있습니다. "한 시그널 = 한 호출" 패턴을 지키세요. 진입 후 추가 진입이 필요하면
명시적으로 다른 트리거에서 호출.

### 7.6 Float 동치 비교 금지

```python
if ema_fast.value == ema_slow.value:    # ❌ NaN/float 비교는 위험
if math.isclose(ema_fast.value, ema_slow.value, rel_tol=1e-9):    # ✅
```

### 7.7 모듈 globals 초기화

`on_init` 에서 globals 를 항상 초기화하세요. 백테스트가 같은 인터프리터에서 두 번 실행되면
잔재가 남습니다. 모듈 상수(대문자)는 reset 할 필요 없지만, **상태 변수(인디케이터 객체,
카운터, high_water 등)는 반드시 `on_init` 에서 재초기화**합니다.

```python
prev_close = 0.0   # 모듈 로드 시 1회

def on_init():
    global prev_close
    prev_close = 0.0   # ← 매 실행마다 다시 reset
```

### 7.8 spot 에서 short 진입 금지

`configs/default.yaml` 은 `mode: spot` 입니다. spot 에서 `market_sell` 은 **기존 LONG 청산**
용도로만 합법이며, FLAT 상태에서 short 를 열려고 하면 `SpotShortNotAllowedError` 가 납니다.
양방향(롱/숏) 전략은 `--config futures.yaml` (`mode: futures`) 로 돌리세요.

### 7.9 zero-qty 주문은 조용히 무시된다

`round_qty` 후 수량이 0 이하면 주문 메서드는 발주하지 않고 빈 문자열 `""` 을 반환하며
`zero_qty_order` 경고만 남깁니다 (예외 아님). 현금이 부족하거나 `size_from_cash_pct` 결과가
step_size 미만일 때 발생하므로, 사이즈가 0 일 가능성이 있으면 `if size > 0:` 으로 가드하세요.

---

## 8. FAQ

**Q. 인디케이터 라이브러리가 있나?**
A. `src/tickweaver/strategy/indicators.py` 에 streaming 형태로 11개:

| 클래스 | 시그니처 | 워밍업 |
|---|---|---|
| `SMA(period)` | `update(price) -> mid \| None` | period 봉 |
| `EMA(period)` | `update(price) -> ema \| None` (SMA 시드 후 alpha 가중) | period 봉 |
| `RSI(period=14)` | `update(price) -> rsi \| None` (Wilder smoothing) | period+1 봉 |
| `ATR(period=14)` | `update(high, low, close)` 또는 `update_bar(bar)` | period 봉 |
| `ADX(period=14)` | `update(high, low, close)` 또는 `update_bar(bar)` → `.value(=ADX) / .adx / .plus_di / .minus_di` (Wilder ADX + DMI) | +DI/-DI: period+1 봉, ADX: 2*period 봉 |
| `SuperTrend(period=10, multiplier=3.0)` | `update(high, low, close)` 또는 `update_bar(bar)` → `.value / .direction` (ATR 기반 추세 필터 / flip 라인) | period 봉 |
| `MACD(fast=12, slow=26, signal=9)` | `update(price)` → `.macd / .signal / .histogram` | slow + signal 봉 |
| `BollingerBands(period=20, mult=2.0)` | `update(price) -> (mid, upper, lower) \| None`, `.middle / .upper / .lower` | period 봉 |
| `Stochastic(period=14, k_smooth=3, d_smooth=3)` | `update(high, low, close) -> (K, D)`, `.K / .D` (이중 평활 %K/%D 오실레이터) | 약 period + k_smooth + d_smooth 봉 |
| `Pivot(period=5)` | `update(high, low)` → `.last_pivot_high / .last_pivot_low / .second_pivot_high / .second_pivot_low`, `is_higher_low()` / `is_lower_high()` (Williams 프랙탈 스윙 고점/저점) | ≥ 2*period+1 봉 |
| `HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)` | `update(open, high, low, close)` → HA 캔들 + `.overlay`, `.dot_signal()`, `.harsi_long / .harsi_short` (Heikin-Ashi RSI 캔들 + RSI overlay) | harsi_len + 1 봉 |

공통 패턴: `value` (None until warm), `is_warm: bool`, `reset()`. 모두 `Indicator` 베이스
클래스를 상속하며 결정론적(P3)입니다.

```python
from tickweaver.strategy.indicators import EMA, RSI

ema_fast = EMA(period=12)
rsi = RSI(period=14)

def on_bar(bar):
    ema_fast.update(bar.close)
    rsi.update(bar.close)
    if ema_fast.is_warm and rsi.is_warm:
        if rsi.value < 30 and bar.close > ema_fast.value:
            api.market_buy(api.size_from_cash_pct(0.1, bar.close))
```

추가가 필요하면 사용자 모듈에서 직접 클래스를 만들어 모듈 globals 로 들고 다니세요.

**Q. 자체 인디케이터를 만들고 싶다.**
A. 모듈 globals 에 dict / class 인스턴스로 상태를 들고, `on_bar(bar)` 에서 `update(bar.close)`
를 호출하는 패턴이 가장 간단합니다. 차트에 띄우려면 §9.4 의 커스텀 indicator 계약을 따르세요.

**Q. 트레이딩 파라미터는 어디에 두나? json 파일이 필요한가?**
A. 아니오. `.py` 상단의 모듈 상수로 둡니다 (§4). `<strategy>.json` 페어링은 더 이상
존재하지 않습니다.

**Q. multi-symbol 가능?**
A. 현 단계 D3 (단일 자산) 만 지원합니다.

**Q. multi-strategy 동시 실행?**
A. 같은 D3 이유로 미지원.

**Q. API key 가 필요한가?**
A. 아니오 (D15). 백테스트 모드는 어떤 단계에서도 API key 가 필요하지 않습니다. CCXT 다운로드도
public OHLCV endpoint 만 씁니다. `.env` 파일도 사용하지 않습니다.

**Q. uniform 과 bridge 중 뭐가 더 좋은가?**
A. 어느 쪽이 더 좋다 / 나쁘다 라는 비교는 본 시스템이 답하지 않습니다 (D16). 필요하면
`scripts/compare_runs.py` 로 같은 데이터/전략에 두 알고리즘을 돌려 직접 확인하세요.

**Q. `bar.timestamp` 가 timeframe 그대로 일정한가?**
A. 아니오 (D13). 결손 봉은 skip 됩니다. 시간 간격이 일정하다고 가정하지 마세요.

**Q. 룩어헤드를 진짜 막아주나?**
A. 엔진 레벨에서는 "submit ≠ fill, 다음 tick 에서 체결" 을 강제합니다. 그러나 사용자가 외부
파일/미래 데이터를 직접 끌어오면 막을 수 없습니다 — 그건 전략 코딩 책임입니다.

**Q. 한 봉 안에서 진입 → 청산 가능?**
A. `on_bar` 에서 발주한 매수는 다음 봉 첫 tick 에서 체결됩니다. 그 후 `on_tick` 에서 청산
조건이 트리거되면 같은 봉 내부에서 청산도 가능합니다.

**Q. 로그를 report.html 에 띄울 수 있나?**
A. 현 단계 `api.log` 는 콘솔 출력만. report 첨부는 미지원.

**Q. 결과 파일 위치?**
A. `--out-dir` 미지정 시 `reports/<strategy_stem>_<UTC_timestamp>/` 자동 생성 (D17).
`report.html`, `metrics.json`, `equity.parquet`, `trades.parquet`, `fills.csv` 등이
들어옵니다.

---

## 9. 지표 시각화 (`--viz`)

### 9.1 개념

전략에서 사용하는 streaming indicator (`EMA` / `RSI` / `BollingerBands` / 커스텀 등) 를 차트에
라인으로 표시합니다. `--viz` 플래그가 없으면 모든 viz 호출은 noop이므로 production 전략에 그대로
두어도 안전합니다.

```python
def on_init():
    global ema
    ema = EMA(period=20)
    api.bind_indicator("EMA 20", ema)   # 한 줄로 등록

def on_bar(bar):
    ema.update(bar.close)               # 일반 indicator 사용
                                        # 엔진이 매 bar 끝에 .value 를 자동 sampling
```

`bind_indicator(name, indicator, panel=None, **style)` 는 idempotent — 같은 `name` 으로
두 번 호출해도 sample 이 중복 누적되지 않습니다 (style/panel 변경은 last-write-wins).

### 9.2 Indicator 계약

viz layer가 indicator 객체에 요구하는 인터페이스:

| 항목 | 종류 | 역할 |
|---|---|---|
| `PANEL` | class variable, str | `"price"` 면 캔들 위에 overlay, 그 외 문자열이면 그 id 의 sub-panel |
| `SUBVALUES` | class variable, `tuple[str, ...] \| None` | `None` = single-value (`.value` 만 사용), tuple = multi-value (각 원소가 attribute 이름이어야 함) |
| `.value` | attribute / property | single-value일 때 매 bar 의 최신 값. `None` 이면 warm-up 미완으로 간주해서 skip. scalar 아님(tuple)/NaN/inf 도 자동 skip |
| `getattr(self, sub)` for `sub` in `SUBVALUES` | property/attribute | multi-value일 때 각 sub-line 의 값 |

> `update(...)` 시그니처는 viz 가 강제하지 않습니다. strategy 가 알아서 호출 (`.update(bar.close)`,
> `.update_bar(bar)`, `.update(h, l, c)` 등). `.value` property 가 raise 해도 backtest 는 안
> 깨지고 해당 bar sample 만 skip + WARNING (V2: viz 는 read-only 관찰자).

### 9.3 기본 11종 indicator 의 default 메타데이터

| 클래스 | `PANEL` | `SUBVALUES` |
|---|---|---|
| `SMA` | `"price"` | `None` |
| `EMA` | `"price"` | `None` |
| `RSI` | `"rsi"` | `None` |
| `ATR` | `"atr"` | `None` |
| `ADX` | `"adx"` | `("adx", "plus_di", "minus_di")` |
| `SuperTrend` | `"price"` | `None` |
| `MACD` | `"macd"` | `("macd", "signal", "histogram")` |
| `BollingerBands` | `"price"` | `("middle", "upper", "lower")` |
| `Stochastic` | `"stoch"` | `("K", "D")` |
| `Pivot` | `"price"` | `None` |
| `HARSI` | `"harsi"` | `("ha_open", "ha_high", "ha_low", "ha_close", "overlay")` |

### 9.4 커스텀 indicator 작성

**single-value** — 봉의 진폭 (`high - low`)

```python
class BarRange:
    PANEL = "price"
    SUBVALUES = None

    def __init__(self):
        self._value = None

    def update_bar(self, bar):
        self._value = float(bar.high - bar.low)

    @property
    def value(self):
        return self._value
```

**multi-value** — Keltner Channel

```python
class KeltnerChannel:
    PANEL = "price"
    SUBVALUES = ("middle", "upper", "lower")   # attribute 이름과 정확히 일치

    def __init__(self, period=20, k=2.0):
        self.period = period
        self.k = k
        self._mid = None
        self._upper = None
        self._lower = None

    def update_bar(self, bar):
        ...  # 계산 후 self._mid / self._upper / self._lower 갱신

    @property
    def middle(self): return self._mid

    @property
    def upper(self):  return self._upper

    @property
    def lower(self):  return self._lower
```

`api.bind_indicator("KC", kc)` 한 번 호출하면 `"KC.middle"`, `"KC.upper"`, `"KC.lower"` 세
sub-line 이 자동 생성, 같은 panel 에 묶입니다.

### 9.5 Style override

```python
api.bind_indicator("EMA 20", ema, color="#FF9800", width=2)
api.bind_indicator("RSI",    rsi, panel="oscillators")   # PANEL 디폴트 덮어쓰기
```

지원 키:

- `color` — hex 색상 (예: `"#FF9800"`)
- `width` — line 두께 (정수)
- `style` — pyqtgraph line style (`"--"`, finplot 버전에 따라 무시될 수 있음)

생략 시 자동 팔레트 (8색 사이클; BUY/SELL 파랑·주황 회피) 에서 결정성 있게 할당.

### 9.6 외부 계산값 fallback — `api.plot`

streaming 클래스를 만들 정도가 아닌 임시 signal 시각화:

```python
def on_bar(bar):
    score = some_external_score(bar)
    api.plot("score", score, panel="score_panel", color="#E91E63")
```

`plot(name, value, panel="price", **style)` — 첫 호출에 자동 register (panel/style), 이후엔
sample 만 emit. `bind_indicator` 와 달리 `PANEL` 계약을 안 거치고 직접 `panel=` 인자로 지정.

### 9.7 함정 체크리스트

| 함정 | 증상 | 회피 |
|---|---|---|
| `SUBVALUES` 의 sub 이름이 attribute 와 불일치 | sub-line 이 빈 라인 (sample skip) | `SUBVALUES = ("middle",)` 이면 `self.middle` 또는 `@property middle` 존재 필수 |
| `.value` 가 tuple 인데 `SUBVALUES = None` | sample 자동 skip (scalar 아님) | multi-value 면 `SUBVALUES` 정의 필수 |
| `.value` property 에서 raise | sample skip + WARNING 로그 — backtest 는 안 깨짐 | property 안 코드 방어적으로 |
| `bind_indicator` 를 `on_bar` 에서 호출 | idempotent 라 안전하지만 의도 불명 | `on_init` 에 두는 것이 관습 |
| `PANEL` 안 정의 | `"price"` overlay 로 fallback | oscillator 처럼 단위가 다르면 명시 권장 |
| viz off / on 결과 비교 안 함 | viz 가 backtest 결과를 바꾸는지 미검증 | `--viz` 켜고 끄고 둘 다 돌려서 `final_equity` / fills 일치 확인 |

### 9.8 결정성 (V2) 보장

`chart_hook=None` (즉 `--viz` 없는 실행) 일 때 모든 viz 호출은 noop. `bind_indicator` / `plot`
어느 쪽도 internal state 를 누적하지 않습니다. 따라서 `--viz` 켜고 끈 backtest 의
`final_equity` / fills 는 비트-정확하게 동일해야 합니다. 어긋난다면 indicator 의 `.value` 가
viz 경로에서만 발동하는 부작용을 일으키는 구현일 가능성 — indicator 본문 다시 점검.

---

## 부록 — 최소 동작 전략 한 줄

```python
# strategies/buy_and_hold.py — 첫 봉에 사고 가만히 둔다
def on_bar(bar):
    if api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.99, bar.close))
```

```powershell
python scripts/run_backtest.py --strategy strategies/buy_and_hold.py
```

이게 전부입니다. `_starter.py` 를 복사해서 더 정교한 전략을 키워나가세요.

---

*시그니처/타입의 권위 있는 출처는 언제나 `src/tickweaver/core/types.py`,
`src/tickweaver/strategy/api.py`, `src/tickweaver/strategy/indicators.py`,
`src/tickweaver/strategy/file_strategy.py` 입니다. 코드가 바뀌면 본 사전도 함께 갱신하세요.*
