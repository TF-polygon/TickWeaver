"""future_demo.py - 무한 grid 교차 + take-profit 청산 (Phase F4.3 보수).

동작 흐름:

  1. RSI 신호 (mean reversion):
        RSI < OVERSOLD     -> 1번 LONG 진입
        RSI > OVERBOUGHT   -> 1번 SHORT 진입
     진입 직후 entry = base_price, trigger = base * (1 ∓ TRIGGER_PCT)
     (long → -0.2%, short → +0.2%, 즉 1번 포지션이 손해 가는 방향).

  2. 가격이 trigger 에 닿으면 반대 방향으로 교차 진입:
        new_qty = AMOUNT_SEQUENCE[i] / current_price
     이번 진입의 fill price 가 새 base_price 가 되고, 새 trigger 도
     base ∓ 0.2% 로 갱신. → 무한 그리드 교차.

     amount_sequence (USDT margin notional):
        [2, 4, 6, 10, 16, 26, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140]
     인덱스가 시퀀스 길이를 넘으면 마지막 값 (140) 클램프.

  3. 가상 PnL 합 (모든 진입의 PnL 합 - 누적 fee) 이 total_margin 의
     TAKE_PROFIT_PCT 비율 이상이 되면 api.close_position() 로 모두 청산.
     broker net 은 마지막 진입 방향 qty 하나이므로 한 번 close 호출로 끝.

  4. 청산 fill 후 state 리셋. 다음 RSI 신호까지 idle.

Broker 동작 (참고):
  - broker 는 단일 net 포지션 (D3) 만 보유. 교차 시 strategy 는
    (이전 진입 qty + 새 진입 qty) 만큼 반대 방향 발주 → broker 는
    close + reverse 한 fill 로 처리, net = 마지막 진입 방향 qty.
  - strategy 는 별도로 모든 진입의 (side / entry / qty) 를 추적하면서
    가상의 양방향 PnL 합을 계산.

mode='futures' 필수 — spot 으로 돌리면 첫 SHORT 진입 시 broker 가
SpotShortNotAllowedError 를 raise.

fee 설정:
  configs/*.yaml 의 execution.commission 으로 조정 (기본 0.05% per side ->
  open + close 0.1% total). future_demo 의 total_fees 추적은 broker 가 emit
  한 fill.fee 합산 — yaml 변경이 그대로 반영.

실행:
  python scripts/run_backtest.py --strategy future_demo --config futures.yaml --viz

trading parameters (edit here to tune):
"""

from typing import TYPE_CHECKING

from tickweaver.strategy.indicators import RSI

if TYPE_CHECKING:
    # Type stubs for IDE / linter only — never executed at runtime.
    # FileStrategy injects these names into the module namespace.
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


# ── trading parameters (module constants) ───────────────────
RSI_PERIOD = 14
OVERBOUGHT = 70.0
OVERSOLD = 30.0
TRIGGER_PCT = 0.002       # ±0.2%
TAKE_PROFIT_PCT = 0.20    # net PnL / total_margin ≥ 20% 시 모두 청산

# USDT margin notional 시퀀스. qty = AMOUNT_SEQUENCE[i] / current_price.
AMOUNT_SEQUENCE = [
    2, 4, 6, 10, 16, 26, 40,
    50, 60, 70, 80, 90, 100,
    110, 120, 130, 140,
]


# ── module-level state ───────────────────
rsi = None
phase = "idle"            # idle | pending_first | pending_cross | active | closing
amount_index = 0          # 다음 진입에 사용할 AMOUNT_SEQUENCE 인덱스
positions = []            # list[dict]: {'side': 'long'/'short', 'entry': float, 'qty': float}
total_fees = 0.0          # 모든 fill 의 fee 누적
next_side = None          # on_fill 직전에 set 되는 '다음 등록할' 진입 방향


def _reset():
    global phase, amount_index, positions, total_fees, next_side
    phase = "idle"
    amount_index = 0
    positions = []
    total_fees = 0.0
    next_side = None


def _last_position():
    return positions[-1] if positions else None


def _trigger_price():
    """마지막 진입을 기준으로 trigger 가격 (1 손해 방향 0.2%)."""
    last = _last_position()
    if last is None:
        return None
    base = last["entry"]
    if last["side"] == "long":
        return base * (1.0 - TRIGGER_PCT)
    else:
        return base * (1.0 + TRIGGER_PCT)


def _virtual_pnl(price: float) -> float:
    """모든 가상 포지션의 PnL 합 (gross, fee 미반영)."""
    total = 0.0
    for p in positions:
        if p["side"] == "long":
            total += (price - p["entry"]) * p["qty"]
        else:
            total += (p["entry"] - price) * p["qty"]
    return total


def _total_margin() -> float:
    return sum(p["entry"] * p["qty"] for p in positions)


def _next_qty(price: float) -> float:
    """qty = AMOUNT_SEQUENCE[clamped] * api.leverage / price.

    Phase F4.5: 시퀀스 값은 'margin' 의미. api.leverage 를 곱해서 실제
    거래 notional 을 얻고, 그것을 가격으로 나눠 qty 산출. round_qty 는
    호출처에서.
    """
    if price <= 0:
        return 0.0
    idx = min(amount_index, len(AMOUNT_SEQUENCE) - 1)
    margin_usdt = float(AMOUNT_SEQUENCE[idx])
    notional = margin_usdt * float(api.leverage)
    return notional / price


def on_init() -> None:
    global rsi
    rsi = RSI(period=RSI_PERIOD)
    api.bind_indicator("RSI", rsi)
    _reset()


def on_bar(bar: "OHLCBar") -> None:
    """idle 상태에서만 RSI mean reversion 으로 1번 진입을 시도."""
    global phase, next_side

    rsi.update(bar.close)
    if not rsi.is_warm:
        return
    if phase != "idle":
        return

    qty_raw = _next_qty(bar.close)
    qty = api.round_qty(qty_raw)
    if qty <= 0:
        return

    if rsi.value < OVERSOLD:
        next_side = "long"
        api.market_buy(qty)
        phase = "pending_first"
    elif rsi.value > OVERBOUGHT:
        next_side = "short"
        api.market_sell(qty)
        phase = "pending_first"


def on_tick(tick: "Tick") -> None:
    """매 tick: take profit + trigger 교차 평가."""
    global phase, next_side

    if phase != "active":
        return

    last = _last_position()
    if last is None:
        return

    # 1) Take profit
    margin = _total_margin()
    if margin > 0:
        net = _virtual_pnl(tick.price) - total_fees
        if net / margin >= TAKE_PROFIT_PCT:
            api.close_position()
            api.log(
                "take_profit_close",
                net_pnl=round(net, 2),
                margin=round(margin, 2),
                ratio_pct=round(100.0 * net / margin, 2),
                n_positions=len(positions),
            )
            phase = "closing"
            return

    # 2) Trigger 도달 → 반대 방향 교차 진입
    trigger = _trigger_price()
    if trigger is None:
        return

    if last["side"] == "long" and tick.price <= trigger:
        next_side = "short"
        new_qty = api.round_qty(_next_qty(tick.price))
        if new_qty > 0:
            api.market_sell(last["qty"] + new_qty)
            phase = "pending_cross"
    elif last["side"] == "short" and tick.price >= trigger:
        next_side = "long"
        new_qty = api.round_qty(_next_qty(tick.price))
        if new_qty > 0:
            api.market_buy(last["qty"] + new_qty)
            phase = "pending_cross"


def on_fill(fill: "Fill") -> None:
    global phase, amount_index, total_fees, next_side

    total_fees += float(fill.fee)

    if phase == "pending_first":
        # 1번 진입 fill 확정. positions 에 첫 항목 등록.
        positions.append(
            {
                "side": next_side,
                "entry": float(fill.price),
                "qty": float(fill.qty),
            }
        )
        amount_index = 1
        phase = "active"
        api.comment(
            f"#1 {next_side.upper()} @ {float(fill.price):.4f}\n"
            f"trigger {_trigger_price():.4f}  "
            f"notional={AMOUNT_SEQUENCE[0]} USDT"
        )

    elif phase == "pending_cross":
        # 교차 fill: broker 한 fill 에 (이전 net close + 새 진입) 합산.
        # 새 진입 qty = fill.qty - 이전 last position qty (broker net 만큼 close 된 부분).
        last = _last_position()
        broker_close_qty = last["qty"] if last else 0.0
        new_qty = float(fill.qty) - broker_close_qty
        if new_qty < 1e-12:
            # 안전 가드: 예상 못한 fill qty 면 통째로 새 진입으로 기록.
            new_qty = float(fill.qty)
        positions.append(
            {
                "side": next_side,
                "entry": float(fill.price),
                "qty": new_qty,
            }
        )
        amount_index = min(amount_index + 1, len(AMOUNT_SEQUENCE) - 1)
        phase = "active"
        api.comment(
            f"#{len(positions)} {next_side.upper()} @ {float(fill.price):.4f}\n"
            f"trigger {_trigger_price():.4f}  "
            f"notional={AMOUNT_SEQUENCE[min(amount_index, len(AMOUNT_SEQUENCE)-1)]} USDT"
        )

    elif phase == "closing":
        # 청산 fill — broker FLAT 도달 시 사이클 리셋.
        if api.is_flat():
            api.comment(f"Cycle closed. equity={api.equity:.2f}")
            _reset()


def on_deinit() -> None:
    api.log(
        "future_demo finished",
        final_equity=round(api.equity, 2),
        n_active_positions=len(positions),
        amount_index=amount_index,
        phase=phase,
    )
