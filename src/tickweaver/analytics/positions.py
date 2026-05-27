"""positions.py — Fill 시퀀스 → 포지션 히스토리 / marker tooltip 변환.

두 가지 헬퍼를 제공:

1. `build_position_history` — UI 표 (`viz/position_table.py`) 용.
   각 진입 fill 에 백테스트 시작 이래 1-based 의 고유 Order # 를
   부여하고, 청산 fill 은 FIFO 로 매칭해서 N 개의 분할 Close row
   로 풀어낸다. 마틴게일 N add → 한 close fill 이 N Close row 로
   분할.

2. `build_marker_tooltips` — chart marker hover tooltip
   (`viz/live_window.py`) 용. `_classify_fills_by_intent` 와 정확히
   같은 매칭 로직으로 4 종 intent (open_long / close_long /
   open_short / close_short) 별 리스트를 emit. 각 marker 에
   Order # / margin (open) / closed_orders + pnl (close) 메타데이터
   를 부여한다. reverse fill 은 close + open 두 marker 로 분할.

두 함수 다 동일한 FIFO simulation 로직을 사용하므로 Order # 는 일관됨.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from tickweaver.core.types import Fill


_QTY_EPS = 1e-12


@dataclass
class PositionRow:
    """포지션 히스토리 표의 한 row.

    Attributes:
        timestamp: fill 의 timestamp (entry 또는 exit).
        order_no: 진입 고유 ID. 같은 Order # 의 Long/Short row 와
            Close row 가 짝.
        side: "Long" / "Short" / "Close".
        margin: open row 만 — `price * qty / leverage`. close row 는 None.
        entry_price: open 은 진입가, close 는 청산가 (해당 fill 의 price).
        pnl: close row 만 — `(exit - entry) * matched_qty` (long;
            short 는 부호 반전). open 은 None.
        cum_pnl: close row 만 — 누적 합. open 은 None.
        holding_bars: close row 만 + `bar_timestamps` 가 주어진 경우만.
            아니면 None.
        fee: 그 row 가 대응하는 fill 의 수수료 (Polish A). open row 는 open
            fill fee (그 row 가 연 qty 비율), close row 는 close fill fee 를
            matched qty 비율로 분배 (`fill.fee * matched / fill.qty`).
        cum_fee: open/close 가리지 않고 row 순 running sum.
    """

    timestamp: pd.Timestamp
    order_no: int
    side: str
    margin: float | None
    entry_price: float
    pnl: float | None
    cum_pnl: float | None
    holding_bars: int | None
    fee: float | None = None
    cum_fee: float | None = None


def build_position_history(
    fills: Sequence[Fill],
    leverage: float = 1.0,
    bar_timestamps: pd.DatetimeIndex | None = None,
) -> list[PositionRow]:
    """Fill 시퀀스를 포지션 히스토리 row 리스트로 변환.

    Algorithm (FIFO):
      - 진입 fill (시작 또는 같은 방향 add) 마다 새 Order # 부여.
      - 반대 방향 fill 은 open 큐의 가장 오래된 항목부터 FIFO 매칭.
        - 한 close fill 의 qty 가 큐의 한 항목보다 크면 다음 항목까지
          연쇄 매칭 (N add cycle 의 한 번 close 가 N row 로 분할).
        - 큐의 항목보다 작으면 부분 close (해당 항목 잔여로 유지).
        - 큐 비운 후에도 잔여 qty 가 있으면 반대 방향 새 진입 (reverse fill).

    Args:
        fills: 시간 순으로 정렬된 Fill 시퀀스.
        leverage: margin = `price * qty / leverage`. 기본 1.0.
        bar_timestamps: Holding Bars 계산용. None 이면 holding_bars=None.

    Returns:
        시간 순으로 정렬된 `PositionRow` 리스트. Open row 와 Close row
        가 섞여있다. UI 는 그대로 row 순으로 표시.
    """
    rows: list[PositionRow] = []
    open_longs: list[dict] = []   # [{order_no, ts, price, qty_remaining}]
    open_shorts: list[dict] = []
    next_order_no = 1
    cum_pnl = 0.0
    cum_fee = 0.0   # Polish A: open/close 가리지 않고 row 순 running sum

    def _bar_index(ts: pd.Timestamp) -> int | None:
        if bar_timestamps is None:
            return None
        return int(bar_timestamps.searchsorted(ts, side="right") - 1)

    for fill in fills:
        side = fill.side.value if hasattr(fill.side, "value") else str(fill.side)
        qty_remaining = float(fill.qty)
        ts = pd.Timestamp(fill.timestamp)
        price = float(fill.price)
        # Polish A: 이 fill 의 fee 를 qty 비율로 분배 (per-unit).
        fill_qty = float(fill.qty)
        fee_per_unit = (float(fill.fee) / fill_qty) if fill_qty > 0 else 0.0

        if side == "buy":
            # Close shorts FIFO 먼저, 잔여는 새 long 으로.
            while qty_remaining > _QTY_EPS and open_shorts:
                s = open_shorts[0]
                matched = min(s["qty_remaining"], qty_remaining)
                pnl = (s["price"] - price) * matched   # short PnL 부호 반전
                cum_pnl += pnl
                close_fee = fee_per_unit * matched
                cum_fee += close_fee
                hb = (
                    None
                    if bar_timestamps is None
                    else _bar_index(ts) - _bar_index(s["ts"])
                )
                rows.append(
                    PositionRow(
                        timestamp=ts,
                        order_no=s["order_no"],
                        side="Close",
                        margin=None,
                        entry_price=price,
                        pnl=pnl,
                        cum_pnl=cum_pnl,
                        holding_bars=hb,
                        fee=close_fee,
                        cum_fee=cum_fee,
                    )
                )
                s["qty_remaining"] -= matched
                qty_remaining -= matched
                if s["qty_remaining"] <= _QTY_EPS:
                    open_shorts.pop(0)
            if qty_remaining > _QTY_EPS:
                # 새 long 진입
                order_no = next_order_no
                next_order_no += 1
                margin = price * qty_remaining / leverage
                open_fee = fee_per_unit * qty_remaining
                cum_fee += open_fee
                rows.append(
                    PositionRow(
                        timestamp=ts,
                        order_no=order_no,
                        side="Long",
                        margin=margin,
                        entry_price=price,
                        pnl=None,
                        cum_pnl=None,
                        holding_bars=None,
                        fee=open_fee,
                        cum_fee=cum_fee,
                    )
                )
                open_longs.append(
                    {
                        "order_no": order_no,
                        "ts": ts,
                        "price": price,
                        "qty_remaining": qty_remaining,
                    }
                )
        else:  # sell — mirror
            while qty_remaining > _QTY_EPS and open_longs:
                lng = open_longs[0]
                matched = min(lng["qty_remaining"], qty_remaining)
                pnl = (price - lng["price"]) * matched   # long PnL
                cum_pnl += pnl
                close_fee = fee_per_unit * matched
                cum_fee += close_fee
                hb = (
                    None
                    if bar_timestamps is None
                    else _bar_index(ts) - _bar_index(lng["ts"])
                )
                rows.append(
                    PositionRow(
                        timestamp=ts,
                        order_no=lng["order_no"],
                        side="Close",
                        margin=None,
                        entry_price=price,
                        pnl=pnl,
                        cum_pnl=cum_pnl,
                        holding_bars=hb,
                        fee=close_fee,
                        cum_fee=cum_fee,
                    )
                )
                lng["qty_remaining"] -= matched
                qty_remaining -= matched
                if lng["qty_remaining"] <= _QTY_EPS:
                    open_longs.pop(0)
            if qty_remaining > _QTY_EPS:
                # 새 short 진입
                order_no = next_order_no
                next_order_no += 1
                margin = price * qty_remaining / leverage
                open_fee = fee_per_unit * qty_remaining
                cum_fee += open_fee
                rows.append(
                    PositionRow(
                        timestamp=ts,
                        order_no=order_no,
                        side="Short",
                        margin=margin,
                        entry_price=price,
                        pnl=None,
                        cum_pnl=None,
                        holding_bars=None,
                        fee=open_fee,
                        cum_fee=cum_fee,
                    )
                )
                open_shorts.append(
                    {
                        "order_no": order_no,
                        "ts": ts,
                        "price": price,
                        "qty_remaining": qty_remaining,
                    }
                )

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# build_marker_tooltips — chart marker hover tooltip 용 데이터
# ─────────────────────────────────────────────────────────────────────────────


def build_marker_tooltips(
    fills: Sequence[Fill],
    leverage: float = 1.0,
) -> dict[str, list[dict]]:
    """fill 시퀀스 → 4 종 intent 별 marker tooltip 데이터.

    `viz/live_window.py` 의 `_classify_fills_by_intent` 와 *정확히 같은*
    포지션 시뮬레이션 로직을 사용하므로, 반환된 4 개 intent 리스트의
    길이와 순서는 `_classify_fills_by_intent` 의 결과와 1:1 매칭. 즉
    `result["open_long"][i]` 와 `intent_groups["open_long"][i]` 가 같은
    marker 의 메타데이터.

    Args:
        fills: 시간 순으로 정렬된 Fill 시퀀스.
        leverage: margin = `price * qty / leverage`. 기본 1.0.

    Returns:
        ``{"open_long": [...], "close_long": [...],
           "open_short": [...], "close_short": [...]}``

        각 tooltip dict 형식:
            공통: ``"timestamp"``, ``"price"``, ``"intent"``
            open*: ``"order_no"`` (int), ``"margin"`` (float)
            close*: ``"closed_orders"`` (list[int] — FIFO 매칭),
                    ``"pnl"`` (float — 매칭된 PnL 합)

    Reverse fill (한 fill 에 close + 새 진입) 은 close marker + open
    marker 두 개로 분할되어 각각 별도 dict 로 emit.
    """
    result: dict[str, list[dict]] = {
        "open_long": [],
        "close_long": [],
        "open_short": [],
        "close_short": [],
    }
    open_longs: list[dict] = []   # FIFO 큐: [{order_no, price, qty}, ...]
    open_shorts: list[dict] = []
    next_order_no = 1

    cur_side: str | None = None   # 'long' / 'short' / None (FLAT)
    cur_qty: float = 0.0

    for fill in fills:
        side_value = (
            fill.side.value if hasattr(fill.side, "value") else str(fill.side)
        )
        ts = pd.Timestamp(fill.timestamp)
        price = float(fill.price)
        qty = float(fill.qty)

        if cur_side is None:
            # FLAT → 새 open
            order_no = next_order_no
            next_order_no += 1
            margin = price * qty / leverage
            entry = {
                "timestamp": ts,
                "price": price,
                "intent": "open_long" if side_value == "buy" else "open_short",
                "order_no": order_no,
                "margin": margin,
            }
            if side_value == "buy":
                cur_side = "long"
                cur_qty = qty
                open_longs.append(
                    {"order_no": order_no, "price": price, "qty": qty}
                )
                result["open_long"].append(entry)
            else:
                cur_side = "short"
                cur_qty = qty
                open_shorts.append(
                    {"order_no": order_no, "price": price, "qty": qty}
                )
                result["open_short"].append(entry)
            continue

        if cur_side == "long":
            if side_value == "buy":
                # Same-side add
                order_no = next_order_no
                next_order_no += 1
                margin = price * qty / leverage
                cur_qty += qty
                open_longs.append(
                    {"order_no": order_no, "price": price, "qty": qty}
                )
                result["open_long"].append(
                    {
                        "timestamp": ts,
                        "price": price,
                        "intent": "open_long",
                        "order_no": order_no,
                        "margin": margin,
                    }
                )
            else:
                # SELL while LONG: close (+ possibly reverse to short)
                close_qty = min(cur_qty, qty)
                # FIFO match
                qty_to_match = close_qty
                closed_orders: list[int] = []
                total_pnl = 0.0
                while qty_to_match > _QTY_EPS and open_longs:
                    lng = open_longs[0]
                    matched = min(lng["qty"], qty_to_match)
                    closed_orders.append(lng["order_no"])
                    total_pnl += (price - lng["price"]) * matched
                    lng["qty"] -= matched
                    qty_to_match -= matched
                    if lng["qty"] <= _QTY_EPS:
                        open_longs.pop(0)
                result["close_long"].append(
                    {
                        "timestamp": ts,
                        "price": price,
                        "intent": "close_long",
                        "closed_orders": closed_orders,
                        "pnl": total_pnl,
                    }
                )
                cur_qty -= close_qty
                if cur_qty <= _QTY_EPS:
                    cur_side = None
                    cur_qty = 0.0
                    leftover = qty - close_qty
                    if leftover > _QTY_EPS:
                        # Reverse: open short with leftover
                        order_no = next_order_no
                        next_order_no += 1
                        margin = price * leftover / leverage
                        cur_side = "short"
                        cur_qty = leftover
                        open_shorts.append(
                            {"order_no": order_no, "price": price, "qty": leftover}
                        )
                        result["open_short"].append(
                            {
                                "timestamp": ts,
                                "price": price,
                                "intent": "open_short",
                                "order_no": order_no,
                                "margin": margin,
                            }
                        )
        else:  # cur_side == "short"
            if side_value == "sell":
                # Same-side add
                order_no = next_order_no
                next_order_no += 1
                margin = price * qty / leverage
                cur_qty += qty
                open_shorts.append(
                    {"order_no": order_no, "price": price, "qty": qty}
                )
                result["open_short"].append(
                    {
                        "timestamp": ts,
                        "price": price,
                        "intent": "open_short",
                        "order_no": order_no,
                        "margin": margin,
                    }
                )
            else:
                # BUY while SHORT: close (+ possibly reverse to long)
                close_qty = min(cur_qty, qty)
                qty_to_match = close_qty
                closed_orders = []
                total_pnl = 0.0
                while qty_to_match > _QTY_EPS and open_shorts:
                    s = open_shorts[0]
                    matched = min(s["qty"], qty_to_match)
                    closed_orders.append(s["order_no"])
                    total_pnl += (s["price"] - price) * matched
                    s["qty"] -= matched
                    qty_to_match -= matched
                    if s["qty"] <= _QTY_EPS:
                        open_shorts.pop(0)
                result["close_short"].append(
                    {
                        "timestamp": ts,
                        "price": price,
                        "intent": "close_short",
                        "closed_orders": closed_orders,
                        "pnl": total_pnl,
                    }
                )
                cur_qty -= close_qty
                if cur_qty <= _QTY_EPS:
                    cur_side = None
                    cur_qty = 0.0
                    leftover = qty - close_qty
                    if leftover > _QTY_EPS:
                        order_no = next_order_no
                        next_order_no += 1
                        margin = price * leftover / leverage
                        cur_side = "long"
                        cur_qty = leftover
                        open_longs.append(
                            {"order_no": order_no, "price": price, "qty": leftover}
                        )
                        result["open_long"].append(
                            {
                                "timestamp": ts,
                                "price": price,
                                "intent": "open_long",
                                "order_no": order_no,
                                "margin": margin,
                            }
                        )

    return result
