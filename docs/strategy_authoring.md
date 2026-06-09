# Strategy Authoring Guide — 파일 기반 전략 작성

> **목표**: MT4 EA 스타일의 파일 기반 전략을 직접 작성하는 방법.
> 이 문서는 **튜토리얼 + 패턴 카탈로그**입니다. 시그니처/타입 사전은
> [`strategies/_reference.md`](../strategies/_reference.md), API 한 줄 명세는
> [plan.md §11.3](../plan.md) 을 참고하세요.

---

## 1. 한 파일 = 한 전략

```
strategies/
├── _starter.py              # 보일러플레이트 (커밋됨, 복사 시작점)
├── _reference.md            # API 사전형 레퍼런스
├── README.md
├── supertrend.py            # 번들 예시 전략 (Pattern 2)
└── my_alpha.py              # 사용자 전략 (gitignore 됨)
```

> 추가 예시 전략 (`buy_and_hold`, `ema_cross`, `rsi_mean_reversion`,
> `ema_market_sl_tp`, `limit_demo`) 은 `test_strategy/` 아래에 아카이브되어
> 있습니다.

핵심 규칙:
- 한 전략 = 하나의 `.py` 파일. 매매 파라미터는 **파일 상단의 모듈 상수**로 둠.
- 백테스트 환경 (자본 / 종목 / 기간 / 비용) 은 `configs/<env>.yaml` 에 둠.
- 전역 변수가 EA 글로벌처럼 백테스트 동안 유지됩니다.
- `on_init`, `on_bar`, `on_tick`, `on_fill`, `on_deinit` 5개 훅 중 필요한 것만 정의.
- 모듈 globals 에 엔진이 `api` 와 `context` 를 자동 주입.

---

## 2. 가장 단순한 시작 — 한 파일

```python
# strategies/my_first.py
def on_bar(bar):
    if api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.5, bar.close))
```

실행:
```powershell
python scripts/run_backtest.py --strategy my_first
```

이 한 줄 전략은 첫 봉에 가용 cash 의 50% 로 매수, 끝까지 보유 (buy-and-hold).

---

## 3. 5 가지 라이프사이클 훅

| 훅 | 시점 | 흔한 용도 |
|---|---|---|
| `on_init()` | 백테스트 시작 직전 1회 | 인디케이터 객체 생성, params 검증, 글로벌 변수 reset |
| `on_bar(bar)` | 각 봉 닫힌 직후 | 신호 생성, 진입/청산 결정 |
| `on_tick(tick)` | 봉 내부 합성 tick 마다 | 트레일링 스탑, 마진 체크 |
| `on_fill(fill)` | 주문 체결 시 | 체결 로그, 포지션 카운터 |
| `on_deinit()` | 백테스트 종료 직후 1회 | 최종 상태 dump |

**중요 — 룩어헤드 보호 (엔진이 강제)**:
- `on_bar(bar_t)` 안에서 발주한 주문은 **다음 봉의 첫 tick** 부터 체결 시도
- 즉 "이 봉의 close 가격에 즉시 체결" 은 불가능
- `bar.close` 를 시그널에 써도 안전

---

## 4. 주입 globals — `api` / `context`

전략 파일은 import 없이 바로 사용. 매매 파라미터는 파일 상단의 모듈 상수로 둠:

```python
FAST = 12                                    # 매매 파라미터 = 모듈 상수

def on_bar(bar):
    api.market_buy(0.05)                     # StrategyAPI - 주문 게이트웨이
    print(context.symbol, context.bar_index) # StrategyContext - 메타정보
```

| 객체 | 타입 | 역할 |
|---|---|---|
| `api` | `StrategyAPI` | 주문 / 포지션 / 계정 정보 (`_reference.md` §3) |
| `context` | `StrategyContext` | symbol, timeframe, bar_index, now (UTC) |

추가 편의 enum (자동 주입): `Side`, `OrderType`, `PositionSide`.

### 4.1 IDE 경고 끄기 — `TYPE_CHECKING` 표준 블록

위 globals 는 모두 **런타임 주입**이라 IDE / 정적 분석기 (Pylance, Pyright, mypy) 는 모릅니다. `api`, `Side`, `PositionSide` 같은 이름이 "undefined" 로 빨갛게 표시되기 쉽습니다. 끄려면 모든 전략 파일 상단에 아래 표준 블록을 넣어주세요. 런타임에는 평가되지 않으니 동작에 영향이 전혀 없습니다.

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type stubs for IDE / linter only — never executed at runtime.
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


def on_bar(bar: "OHLCBar") -> None:   # forward-ref 어노테이션
    api.market_buy(0.05)
```

훅의 `bar` / `tick` / `fill` 인자에도 문자열 forward-ref 로 어노테이션을 붙이면 `bar.close`, `tick.price` 등 멤버 자동완성이 켜집니다. `strategies/_starter.py` 가 표준 템플릿이며 `strategies/*.py` 모든 전략이 이 패턴을 따릅니다. 자세한 설명은 `strategies/_reference.md` §0.4.

---

## 5. 패턴 카탈로그

### 5.1 Buy-and-Hold

```python
def on_bar(bar):
    if api.is_flat():
        api.market_buy(api.size_from_cash_pct(0.99, bar.close))
```

벤치마크 비교용으로 항상 함께 굴려보면 좋습니다.

---

### 5.2 EMA 크로스 (트렌드 추종)

```python
from tickweaver.strategy.indicators import EMA

# Trading parameters as module constants
EMA_FAST = 12
EMA_SLOW = 26
SIZE_PCT = 0.2

ema_fast = None
ema_slow = None
prev_diff = None

def on_init():
    global ema_fast, ema_slow, prev_diff
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)
    prev_diff = None

def on_bar(bar):
    global prev_diff
    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if not (ema_fast.is_warm and ema_slow.is_warm):
        return
    diff = ema_fast.value - ema_slow.value
    if prev_diff is None:
        prev_diff = diff
        return
    if prev_diff <= 0 < diff and api.is_flat():
        api.market_buy(api.size_from_cash_pct(SIZE_PCT, bar.close))
    elif prev_diff >= 0 > diff and not api.is_flat():
        api.close_position()
    prev_diff = diff
```

핵심: **이전 diff 의 부호와 현재 diff 의 부호가 다를 때** 만 트리거 (cross over).

---

### 5.3 RSI 평균회귀 (역추세)

```python
from tickweaver.strategy.indicators import RSI

# Trading parameters as module constants
RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0
SIZE_PCT = 0.2

rsi = None

def on_init():
    global rsi
    rsi = RSI(period=RSI_PERIOD)

def on_bar(bar):
    rsi.update(bar.close)
    if not rsi.is_warm:
        return
    if rsi.value < OVERSOLD and api.is_flat():
        api.market_buy(api.size_from_cash_pct(SIZE_PCT, bar.close))
    elif rsi.value > OVERBOUGHT and not api.is_flat():
        api.close_position()
```

전체 코드: `test_strategy/rsi_mean_reversion.py`.

---

### 5.4 LIMIT 진입 + STOP/LIMIT 청산 (브라켓)

```python
def on_bar(bar):
    if api.is_flat() and signal_now(bar):
        # 약간 낮은 가격에 LIMIT 매수 (체결 안 되면 버려짐)
        limit_buy_price = bar.close * 0.997
        qty = api.size_from_cash_pct(0.3, limit_buy_price)
        if qty > 0:
            api.limit_buy(qty, limit_buy_price)

def on_fill(fill):
    # 진입 체결되면 즉시 SL/TP 동시 발주
    pos = api.position()
    if pos.side == PositionSide.LONG and fill.side == Side.BUY:
        api.stop_sell(pos.qty, stop_price=pos.entry_price * 0.99)   # 손절 -1%
        api.limit_sell(pos.qty, price=pos.entry_price * 1.015)      # 익절 +1.5%
```

전체 코드: `test_strategy/limit_demo.py`.

**주의**: 손절과 익절 둘 중 하나가 체결되면 다른 하나는 자동으로 취소되지 **않습니다**. 한쪽 체결을 `on_fill` 에서 감지해 다른 주문을 `api.cancel(order_id)` 로 명시 취소하거나, position size 가 0 이 됐을 때 broker 가 알아서 처리하도록 하세요.

---

### 5.5 트레일링 스탑 (on_tick 사용)

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

`on_tick` 을 사용하면 봉 내부 합성 tick 경로에 따라 결과가 달라집니다 (compare_runs 비교 시 차이 발현).

번들 예시 `strategies/supertrend.py` 가 바로 이 Pattern 2 (on_bar 진입 + on_tick SL/TP 청산) 의 완성형 레퍼런스입니다 — 실제로 굴러가는 전체 전략을 보려면 이 파일을 참고하세요.

### 5.X 지표 시각화 (`--viz`)

전략에서 쓰는 indicator를 차트에 한 줄로 노출:

```python
def on_init():
    global ema, rsi
    ema = EMA(period=20)
    rsi = RSI(period=14)
    api.bind_indicator("EMA 20", ema)    # PANEL='price' (default) → candle overlay
    api.bind_indicator("RSI",    rsi)    # PANEL='rsi'   (default) → sub-panel
```

- `--viz` 가 꺼져 있으면 모든 viz 호출은 noop이므로 production 코드에 그대로 두어도 안전.
- Indicator 클래스는 `PANEL`(필수, str) + `SUBVALUES`(`None` 또는 tuple) 메타데이터를 가져야 함. 기본 11종 (`SMA` / `EMA` / `RSI` / `ATR` / `ADX` / `SuperTrend` / `MACD` / `BollingerBands` / `Stochastic` / `Pivot` / `HARSI`) 은 이미 정의됨.
- 커스텀 indicator 작성, multi-value 분해 (BB / MACD), style override (`color=`/`width=`), 외부 계산값 fallback (`api.plot(name, value)`) — 자세한 계약과 함정 체크리스트는 [`strategies/_reference.md` §9](../strategies/_reference.md#9-지표-시각화---viz) 참고.

---

## 6. 흔한 함정

### 6.1 워밍업 검사 누락
```python
def on_bar(bar):
    rsi.update(bar.close)
    if rsi.value < 30:    # ❌ 워밍업 전이면 None < 30 -> TypeError
        ...
```

→ 항상 `if not rsi.is_warm: return` 또는 `if rsi.value is None: return` 먼저.

### 6.2 룩어헤드 가정
```python
def on_bar(bar):
    # ❌ 미래 봉 가격을 어딘가에서 읽어오면 룩어헤드
    future_close = read_future(bar.timestamp)
```

엔진이 막을 수 있는 룩어헤드는 "submit ≠ fill" 까지. 외부 데이터를 끌어오는 건 사용자 책임.

### 6.3 같은 시그널 중복 발주
```python
def on_bar(bar):
    if signal:
        api.market_buy(...)    # 매 봉 시그널 만족하는 동안 반복 발주
```

→ `if signal and api.is_flat(): ...` 로 한 포지션만 보유.

### 6.4 결손 봉 가정
```python
def on_bar(bar):
    bars_held += 1
    if bars_held >= 12:        # ❌ "12봉 = 12시간" 가정
        api.close_position()
```

D13 정책상 결손 봉은 skip 됩니다. 시간 차로 봉 인덱스를 추정하지 말고 `bars_held` 카운터 사용 (위 코드는 카운터라서 OK 지만, "12 시간 후" 로 해석하면 틀림).

### 6.5 Float 동치 비교
```python
if rsi.value == 30.0:    # ❌ float 정확 비교 위험
```

→ `if rsi.value < 30.0` 같이 부등호 사용, 또는 `math.isclose(rsi.value, 30.0)`.

---

## 7. 디버깅

### 7.1 api.log 활용

`api.log("event_name", **kv)` 로 구조화 로그를 남기면 콘솔에 출력됩니다 (단, progress bar 켜진 모드에서는 silent — `--no-progress` 또는 `show_progress=False` 로 보임).

```python
def on_bar(bar):
    api.log("bar_open", close=bar.close, equity=api.equity)
```

### 7.2 트랜잭션 따라가기

`reports/<run>/trades.parquet` 을 pandas 로 열어 entry/exit 시점과 PnL 분석:

```python
import pandas as pd
df = pd.read_parquet("reports/my_alpha_xxx/trades.parquet")
print(df.head())
print(df["pnl"].describe())
```

### 7.3 결정성 활용

같은 (data, config, seed) 면 bit-exact 동일 결과 (P3). 처음 결과를 baseline 으로 저장한 뒤 코드 수정하면 변경 영향만 정확히 비교 가능.

### 7.4 작은 데이터 + dump_ticks

```powershell
# 5개 봉의 tick stream 을 PNG/parquet 으로 dump
python scripts/run_backtest.py --strategy supertrend --config futures.yaml --dump-ticks 5
```

`reports/<run>/sample_tick_paths.png` 로 합성 tick 경로 확인 가능.

---

## 8. 단위 테스트

전략 코드 자체를 unit test 로 보호하고 싶으면, 미리 다운로드된 데이터를
사용하는 별도 yaml 을 만들어 `--config` 로 가리키거나, 동작 한 번을 회귀
baseline 으로 잠가두는 형태를 권장:

```python
# tests/strategies/test_supertrend_regression.py
import pytest
from tickweaver.engine.runner import run_backtest

def test_supertrend_regression(tmp_path):
    res = run_backtest(
        strategy_path="strategies/supertrend.py",
        config_path="configs/futures.yaml",
        out_dir=tmp_path / "out",
        show_progress=False,
    )
    # baseline 은 처음 한 번 측정해서 잠금
    assert res.final_equity == pytest.approx(10556.16, rel=0, abs=1e-2)
    assert len(res.fills) > 0
```

`configs/futures.yaml` 안의 `tick_synthesis.seed` 가 고정이면 결과는
bit-exact 재현되므로 회귀 보호에 충분.

---

## 9. 다음 단계

- 인디케이터 사전: [strategies/_reference.md §3.7~3.16](../strategies/_reference.md)
- 다른 generator 와의 비교: `python scripts/compare_runs.py backtest --strategy <your>`
- 결과 해석 / 트러블슈팅: [docs/USER_GUIDE.md](USER_GUIDE.md)
- 새 인디케이터 / fee 모델 추가: [docs/DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
