# tickweaver — Strategy Reference (전략 작성 사전)

> **이 문서가 무엇인가?**
> MT4 EA 편집기에서 F1 을 누르면 뜨는 도움말 같은 **사전형 레퍼런스**입니다.
> 파일 기반 전략 (`strategies/<your_name>.py`) 을 직접 코딩할 때 필요한
> 라이프사이클 훅, 주입 변수, API 메서드, 타입을 한 파일에서 찾을 수 있습니다.
>
> 가이드/튜토리얼은 `docs/strategy_authoring.md` 를 보세요. 이 파일은 **사전**입니다.
>
> 본 레퍼런스의 모든 시그니처는 `plan.md` 의 §3.2 (`core/interfaces.py`) /
> §11.3 (D8 파일 기반 전략) / §M6.4 (StrategyAPI · ParamsView · FileStrategy) 를
> 단일 진실 소스로 합니다.

---

## 목차

0. [시작하기 전에](#0-시작하기-전에)
1. [라이프사이클 훅](#1-라이프사이클-훅-on_init--on_bar--on_tick--on_fill--on_deinit)
2. [주입된 globals](#2-주입된-globals--api--params--context)
3. [StrategyAPI 메서드 사전](#3-strategyapi-메서드-사전)
4. [ParamsView 메서드](#4-paramsview-메서드-paramsget--paramsrequire--paramscontains)
5. [타입 사전](#5-타입-사전)
6. [자주 쓰는 패턴](#6-자주-쓰는-패턴)
7. [함정과 주의사항](#7-함정과-주의사항)
8. [FAQ](#8-faq)

---

## 0. 시작하기 전에

### 0.1 한 파일 = 한 전략

```
strategies/
├── _starter.py        ← 보일러플레이트 (이거 복사해서 시작)
├── _starter.json      ← 파라미터 템플릿
├── _reference.md      ← 본 문서
├── README.md
└── my_alpha.py        ← 너의 전략
└── my_alpha.json      ← (선택) 파라미터 — 같은 이름의 .json 이면 자동 페어링
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

`--config` / `--source` / `--out-dir` 모두 기본값이 잡혀 있으므로 위 한 줄이면 동작합니다 (D17, plan.md §12.4).

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

엔진은 `on_init` 호출 직전에 모듈 globals 에 `api`, `params`, `context` 세 개를 주입합니다. 그 이후로 어떤 훅에서든 그냥 `api.market_buy(...)` 처럼 쓸 수 있습니다.

---

## 1. 라이프사이클 훅 (`on_init` / `on_bar` / `on_tick` / `on_fill` / `on_deinit`)

각 훅은 **선택적**입니다. 정의되지 않은 훅은 noop 으로 취급됩니다.

### 1.1 `on_init() -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 백테스트 시작 직전 1회 |
| 인자 | 없음 |
| 사용 가능 | `api`, `params`, `context` 모두 주입 완료 |
| 일반 용도 | 전역 상태 초기화, `params` 필수값 검증, 인디케이터 객체 생성 |

```python
from tickweaver.strategy.indicators import EMA

ema_fast = None
ema_slow = None

def on_init():
    global ema_fast, ema_slow
    ema_fast = EMA(period=params.require("ema_fast"))
    ema_slow = EMA(period=params.require("ema_slow"))
    api.log("strategy initialized", fast=params.get("ema_fast"))
```

---

### 1.2 `on_bar(bar: OHLCBar) -> None`

| 항목 | 내용 |
|---|---|
| 호출 시점 | 각 봉이 **닫힌 직후** (다음 봉이 시작되기 전) |
| 인자 | `bar` — 방금 닫힌 OHLCBar |
| 일반 용도 | 신호 생성, 진입/청산 결정 |

**중요 — 룩어헤드 방지**: `on_bar` 안에서 낸 주문은 **다음 봉의 첫 tick** 부터 체결 시도됩니다. 즉 "이 봉의 close 를 보고 이 봉의 close 가격에 체결" 은 불가능합니다 (engine 이 강제). 따라서 안심하고 `bar.close` 를 시그널 입력으로 써도 룩어헤드가 발생하지 않습니다.

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

**중요**: tick 은 OHLC 로부터 합성된 **그럴듯한 가격 경로** 일 뿐, 실제 호가창/체결 동작이 아닙니다 (D12). tick 단위로 너무 세밀한 가정 (예: 0.001 점프 단위, microstructure noise) 을 두는 전략은 forward test 에서 깨지기 쉽습니다.

```python
trail_pct = 0.02

def on_tick(tick):
    pos = api.position()
    if pos.side != PositionSide.LONG:
        return
    high_water = max(pos.entry_price, getattr(on_tick, "_hw", pos.entry_price))
    high_water = max(high_water, tick.price)
    on_tick._hw = high_water
    if tick.price < high_water * (1 - trail_pct):
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

## 2. 주입된 globals — `api` / `params` / `context`

`on_init` 호출 직전에 엔진이 모듈 globals 에 주입하는 3개 객체입니다. 따로 import 할 필요 없이 어떤 훅에서든 그냥 사용하면 됩니다.

| 이름 | 타입 | 역할 |
|---|---|---|
| `api` | `StrategyAPI` | 주문 / 포지션 / 계정 정보 접근의 단일 게이트웨이 (§3) |
| `params` | `ParamsView` | `<strategy>.json` 페어링 파일에서 읽힌 파라미터의 read-only view (§4) |
| `context` | `StrategyContext` | 현재 시점 / 봉 인덱스 / 심볼·타임프레임 메타정보 |

`context` 는 일반적으로 직접 건드릴 일이 적습니다. `bar` 인자에 timestamp/symbol 정보가 이미 들어 있고, 메타가 더 필요하면 `context.symbol`, `context.timeframe` 정도를 읽는 용도로 사용합니다.

---

## 3. StrategyAPI 메서드 사전

> 모든 주문 메서드는 **멱등성 키 (`client_order_id`) 가 자동 부여**됩니다. 같은 봉/같은 시그널에서 두 번 호출되면 두 번째는 거부될 수 있으니, "한 시그널 = 한 호출" 패턴을 지키세요.
>
> 주문 메서드의 **공통 반환**: `order_id (str)`. `cancel()` 만 `bool` 반환.
> 모든 `qty` 인자는 내부적으로 `round_qty()` 가 자동 적용됨.

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

수수료는 모든 체결에 config 의 `commission` 으로 자동 적용. 슬리피지는 위 표의 "적용" 행만 `slippage` 로 자동 적용.

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
| `api.close_all()` | `list[str]` | 현 단계 D3 (단일 자산) 에서는 사실상 `close_position()` 과 동일. 미래 multi-symbol 확장을 위한 alias |

---

### 3.3 조회 메서드 / 프로퍼티

| 이름 | 형태 | 반환 | 비고 |
|---|---|---|---|
| `api.position()` | method | `Position` (§5.5) | 포지션 없으면 `Position(side=FLAT, qty=0, ...)` |
| `api.is_flat()` | method | `bool` | `api.position().side == PositionSide.FLAT` 의 편의 함수 |
| `api.cash` | property | `float` | 현재 현금 잔고 |
| `api.equity` | property | `float` | `cash + 미실현 PnL` |

---

### 3.4 헬퍼 메서드

| 메서드 | 인자 | 반환 | 용도 |
|---|---|---|---|
| `api.round_qty(qty)` | `qty: float` | `float` | 거래소 step_size 에 맞춰 내림. 주문 메서드는 내부에서 이미 호출하지만 직접 사이즈 계산을 검증할 때 사용 |
| `api.size_from_cash_pct(pct, price)` | `pct: float (0~1)`, `price: float` | `float` | `cash × pct ÷ price` 를 `round_qty` 적용해 반환. 자본 곡선에 자동 스케일하는 사이즈 계산 |
| `api.log(event, **kwargs)` | `event: str`, 임의 `**kwargs` | `None` | 콘솔 로거. 출력: `<ts> [info] [<component>] <event>  key=value ...`. progress 모드에서는 silent (`--no-progress` 로 보임). `report.html` 에는 미반영 |

```python
qty = api.size_from_cash_pct(0.1, bar.close)   # 현금의 10%
api.market_buy(qty)

api.log("entry signal", price=bar.close, ema=ema_fast.value)
```

---

## 4. ParamsView 메서드 — `params.get` / `params.require` / `params.contains`

전략 파일 옆의 `<strategy>.json` 이 자동 페어링되어 `params` 로 주입됩니다.

```json
// strategies/my_alpha.json
{
  "ema_fast": 12,
  "ema_slow": 26,
  "size_pct": 0.1
}
```

#### `params.get(key: str, default=None)`

키가 있으면 값, 없으면 `default`.

```python
fast = params.get("ema_fast", 12)
```

#### `params.require(key: str)`

키가 없으면 `KeyError` raise (P6 fail-fast). 필수 파라미터에 사용.

```python
fast = params.require("ema_fast")   # 없으면 시작 단계에서 즉시 실패
```

#### `params.contains(key: str) -> bool`

`in` 연산자 등가물.

```python
if params.contains("trail_pct"):
    use_trailing_stop = True
```

---

## 5. 타입 사전

> 모든 dataclass / Enum 정의는 `src/tickweaver/core/types.py` 에 있습니다. 본 사전은 사용자가 자주 만나는 필드 위주로 정리했습니다.

### 5.1 `OHLCBar`

| 필드 | 타입 | 설명 |
|---|---|---|
| `timestamp` | `pd.Timestamp` (UTC) | 봉의 close time (단조 증가) |
| `open` / `high` / `low` / `close` | `float` | OHLC |
| `volume` | `float` | 거래량 |
| `symbol` | `str` | 예: `"BTC/USDT:USDT"` |
| `timeframe` | `str` | 예: `"1h"` |

### 5.2 `Tick`

| 필드 | 타입 | 설명 |
|---|---|---|
| `timestamp` | `pd.Timestamp` (UTC) | 합성 tick 시각 |
| `price` | `float` | 합성 가격 |
| `bar_index` | `int` | 어느 봉에 속하는지 |
| `tick_index_in_bar` | `int` | 봉 내부 tick 순번 |

### 5.3 `Order`

| 필드 | 타입 | 설명 |
|---|---|---|
| `order_id` | `str` | 엔진 발급 ID |
| `client_order_id` | `str` | 멱등성 키 (자동 부여) |
| `side` | `Side` | BUY / SELL |
| `type` | `OrderType` | MARKET / LIMIT / STOP / STOP_LIMIT |
| `qty` | `float` | 수량 (round_qty 후) |
| `price` | `float \| None` | LIMIT 일 때만 |
| `stop_price` | `float \| None` | STOP 계열만 |

### 5.4 `Fill`

| 필드 | 타입 | 설명 |
|---|---|---|
| `order_id` | `str` | 어떤 주문의 체결인지 |
| `side` | `Side` | BUY / SELL |
| `qty` | `float` | 실제 체결 수량 |
| `price` | `float` | 슬리피지 적용 후 체결가 |
| `fee` | `float` | 수수료 |
| `timestamp` | `pd.Timestamp` (UTC) | 체결 시각 |
| `pnl_realized` | `float` | 이 체결에서 확정된 PnL (포지션 축소 시) |

### 5.5 `Position`

| 필드 | 타입 | 설명 |
|---|---|---|
| `side` | `PositionSide` | LONG / SHORT / FLAT |
| `qty` | `float` | 절대 수량 (방향은 side 로 표현) |
| `entry_price` | `float` | 평균 진입가 |
| `mark_price` | `float` | 현재 mark 가격 |
| `unrealized_pnl` | `float` | 미실현 PnL |
| `liquidation_price` | `float \| None` | 선물 격리 마진 청산가 |

### 5.6 Enum

```python
class Side(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

class MarketType(Enum):
    SPOT = "spot"
    USDT_M_PERPETUAL = "usdt_m_perpetual"
```

전략 코드에서 import 하려면:

```python
from tickweaver.core.types import Side, OrderType, PositionSide
```

---

## 6. 자주 쓰는 패턴

### 6.1 단순 EMA 크로스

```python
from tickweaver.strategy.indicators import EMA

ema_fast = None
ema_slow = None

def on_init():
    global ema_fast, ema_slow
    ema_fast = EMA(period=params.require("ema_fast"))
    ema_slow = EMA(period=params.require("ema_slow"))

def on_bar(bar):
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if ema_fast.value is None or ema_slow.value is None:
        return
    bullish = ema_fast.value > ema_slow.value
    if bullish and api.is_flat():
        api.market_buy(api.size_from_cash_pct(params.get("size_pct", 0.1), bar.close))
    elif (not bullish) and not api.is_flat():
        api.close_position()
```

### 6.2 진입은 `on_bar`, 청산 트레일은 `on_tick`

```python
trail_pct = 0.02
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
    if tick.price < high_water * (1 - trail_pct):
        api.close_position()
        high_water = None
```

### 6.3 N개 봉 보유 후 자동 청산

```python
bars_held = 0
hold_n = 5

def on_bar(bar):
    global bars_held
    if not api.is_flat():
        bars_held += 1
        if bars_held >= hold_n:
            api.close_position()
            bars_held = 0
        return
    if some_entry_signal(bar):
        api.market_buy(api.size_from_cash_pct(0.1, bar.close))
        bars_held = 0
```

### 6.4 파라미터 검증

```python
def on_init():
    fast = params.require("ema_fast")
    slow = params.require("ema_slow")
    if fast >= slow:
        raise ValueError(f"ema_fast({fast}) must be < ema_slow({slow})")
```

---

## 7. 함정과 주의사항

### 7.1 룩어헤드는 엔진이 막아준다, 그러나…

엔진은 "on_bar 에서 발주한 주문은 다음 봉 첫 tick 에서 체결" 을 강제하므로, `bar.close` 를 시그널 입력으로 써도 안전합니다. 그러나 다음 두 패턴은 사용자가 직접 망칠 수 있습니다:

- 미래 정보를 외부 파일/캐시에서 읽어오기
- `context` 에서 미래 봉 인덱스를 추정해 액세스

→ 전략 안에서는 **현재까지 도착한 데이터** 만 본다.

### 7.2 합성 tick 의 한계 (D12)

`on_tick` 에 들어오는 tick 은 OHLC 로부터 합성된 가격 경로입니다. 다음을 가정/요구하면 forward test 에서 깨집니다:

- microstructure noise (호가 점프 패턴) 가정
- tick 간 정확한 시간 간격 가정 (uniform 분배일 뿐)
- volume-weighted tick 가정 (현 단계 미지원)

합성 tick 은 backtest ↔ forward 간극 완화용 **방법론**일 뿐이라는 점을 잊지 마세요.

### 7.3 결손 봉은 그냥 건너뛴다 (D13)

거래소가 일부 봉을 누락한 경우, TickWeaver 는 **그 봉을 skip 하고 다음 봉으로 이어붙여 진행**합니다. 보간/재샘플링/실패 모두 일어나지 않습니다.

따라서:

- `bar.timestamp` 의 간격이 항상 `timeframe` 과 일치한다고 **가정 금지**
- 시간 차로 봉 인덱스를 추정하지 말고, 실제 들어온 bar 를 카운트
- "12개 봉 보유 = 12시간 보유" 같은 등식 금지

### 7.4 단일 스레드 전제 (D14)

전략 안에서 무거운 연산을 하면 백테스트 전체가 느려집니다. heavy ML 추론은 권장되지 않습니다.

### 7.5 멱등성 키와 중복 발주

`on_bar` 안에서 같은 시그널로 두 번 `market_buy` 를 호출하면 두 번째는 (자동 client_order_id 충돌로) 거부될 수 있습니다. "한 시그널 = 한 호출" 패턴을 지키세요. 진입 후 추가 진입이 필요하면 명시적으로 다른 트리거에서 호출.

### 7.6 Float 동치 비교 금지

```python
if ema_fast.value == ema_slow.value:    # ❌ NaN/float 비교는 위험
if math.isclose(ema_fast.value, ema_slow.value, rel_tol=1e-9):    # ✅
```

### 7.7 모듈 globals 초기화

`on_init` 에서 globals 를 항상 초기화하세요. 백테스트가 같은 인터프리터에서 두 번 실행되면 잔재가 남습니다.

```python
prev_close = 0.0   # 모듈 로드 시 1회

def on_init():
    global prev_close
    prev_close = 0.0   # ← 매 실행마다 다시 reset
```

---

## 8. FAQ

**Q. 인디케이터 라이브러리가 있나?**
A. `src/tickweaver/strategy/indicators.py` 에 streaming 형태로 6개 (메인 세트):

| 클래스 | 시그니처 | 워밍업 |
|---|---|---|
| `SMA(period)` | `update(price) -> mid \| None` | period 봉 |
| `EMA(period)` | `update(price) -> ema \| None` (SMA 시드 후 alpha 가중) | period 봉 |
| `RSI(period=14)` | `update(price) -> rsi \| None` (Wilder smoothing) | period+1 봉 |
| `ATR(period=14)` | `update(high, low, close)` 또는 `update_bar(bar)` | period 봉 |
| `MACD(fast=12, slow=26, signal=9)` | `update(price)` → `.macd / .signal / .histogram` | slow + signal 봉 |
| `BollingerBands(period=20, mult=2.0)` | `update(price) -> (mid, upper, lower) \| None` | period 봉 |

공통 패턴: `value` (None until warm), `is_warm: bool`, `reset()`.

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
A. 모듈 globals 에 dict / class 인스턴스로 상태를 들고, `on_bar(bar)` 에서 `update(bar.close)` 를 호출하는 패턴이 가장 간단합니다.

**Q. multi-symbol 가능?**
A. 현 단계 D3 (단일 자산) 만 지원합니다. multi 는 §13.1 의 future work.

**Q. multi-strategy 동시 실행?**
A. 같은 D3 이유로 미지원.

**Q. API key 가 필요한가?**
A. 아니오 (D15). 백테스트 모드는 어떤 단계에서도 API key 가 필요하지 않습니다. CCXT 다운로드도 public OHLCV endpoint 만 씁니다. `.env` 파일도 사용하지 않습니다.

**Q. uniform 과 bridge 중 뭐가 더 좋은가?**
A. 어느 쪽이 더 좋다 / 나쁘다 라는 비교는 본 시스템이 답하지 않습니다 (D16). 필요하면 `scripts/compare_runs.py` 로 같은 데이터/전략에 두 알고리즘을 돌려 직접 확인하세요.

**Q. `bar.timestamp` 가 timeframe 그대로 일정한가?**
A. 아니오 (D13). 결손 봉은 skip 됩니다. 시간 간격이 일정하다고 가정하지 마세요.

**Q. 룩어헤드를 진짜 막아주나?**
A. 엔진 레벨에서는 "submit ≠ fill, 다음 tick 에서 체결" 을 강제합니다. 그러나 사용자가 외부 파일/미래 데이터를 직접 끌어오면 막을 수 없습니다 — 그건 전략 코딩 책임입니다.

**Q. 한 봉 안에서 진입 → 청산 가능?**
A. `on_bar` 에서 발주한 매수는 다음 봉 첫 tick 에서 체결됩니다. 그 후 `on_tick` 에서 청산 조건이 트리거되면 같은 봉 내부에서 청산도 가능합니다.

**Q. 로그를 report.html 에 띄울 수 있나?**
A. 현 단계 `api.log` 는 콘솔 출력만. report 첨부는 미지원.

**Q. 결과 파일 위치?**
A. `--out-dir` 미지정 시 `reports/<strategy_stem>_<UTC_timestamp>/` 자동 생성 (D17). `report.html`, `metrics.json`, `equity.parquet`, `trades.parquet`, `tick_summary.json` 이 들어옵니다.

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

*본 레퍼런스는 plan.md 의 변경에 맞춰 업데이트됩니다. 시그니처/타입의 권위 있는 출처는
언제나 `src/tickweaver/core/types.py` 와 `src/tickweaver/strategy/api.py` 입니다.*
