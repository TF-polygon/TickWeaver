"""Fill 시퀀스 -> 라운드트립 trade 매칭 (단일 자산, FIFO)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tickweaver.core.types import Fill, Side


@dataclass
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    side: Side  # 진입 방향
    qty: float
    entry_price: float                     # 가중평균 진입가 (마틴게일 add 합산)
    exit_price: float
    fee: float
    pnl: float
    first_entry_price: float = 0.0         # Phase V6: 첫 fill 의 실제 가격

    def to_dict(self) -> dict:
        return {
            "entry_ts": self.entry_ts.isoformat() if self.entry_ts else None,
            "exit_ts": self.exit_ts.isoformat() if self.exit_ts else None,
            "side": self.side.value,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "first_entry_price": self.first_entry_price,
            "exit_price": self.exit_price,
            "fee": self.fee,
            "pnl": self.pnl,
        }


def extract_trades(fills: list[Fill]) -> list[Trade]:
    """Fill 들을 FIFO 로 매칭해 라운드트립 trade 만듦.

    단순화: 단일 자산 (D3) 가정. 같은 방향 추가 fill 은 평균 진입가로 합산.
    반대 방향 fill 이 들어오면 보유 중인 포지션을 줄이며 trade 가 종결.

    Phase F4.2 fix: 반대 방향 fill 이 보유 qty 보다 크면 잔여 qty 를 새 진입
    (reverse) 으로 처리. 양방향 strategy 의 viz pair line 이 마커와 일치하도록.
    """
    trades: list[Trade] = []

    cur_side: Side | None = None
    cur_qty: float = 0.0
    cur_entry_price: float = 0.0
    cur_first_entry_price: float = 0.0
    cur_entry_ts: pd.Timestamp | None = None
    cur_fee: float = 0.0

    for f in fills:
        if cur_side is None or cur_qty <= 1e-12:
            # 신규 진입
            cur_side = f.side
            cur_qty = f.qty
            cur_entry_price = f.price
            cur_first_entry_price = f.price   # Phase V6
            cur_entry_ts = f.timestamp
            cur_fee = f.fee
            continue

        if f.side == cur_side:
            # 같은 방향 추가
            new_qty = cur_qty + f.qty
            cur_entry_price = (
                cur_entry_price * cur_qty + f.price * f.qty
            ) / new_qty
            cur_qty = new_qty
            cur_fee += f.fee
        else:
            # 반대 방향 — 청산 (부분/전체) 및 가능 시 reverse 진입
            close_qty = min(cur_qty, f.qty)
            if cur_side == Side.BUY:
                pnl = (f.price - cur_entry_price) * close_qty
            else:
                pnl = (cur_entry_price - f.price) * close_qty
            trade_fee = cur_fee * (close_qty / max(cur_qty, 1e-12)) + f.fee * (
                close_qty / max(f.qty, 1e-12)
            )
            trades.append(
                Trade(
                    entry_ts=cur_entry_ts or f.timestamp,
                    exit_ts=f.timestamp,
                    side=cur_side,
                    qty=close_qty,
                    entry_price=cur_entry_price,
                    exit_price=f.price,
                    fee=trade_fee,
                    pnl=pnl - trade_fee,
                    first_entry_price=cur_first_entry_price,
                )
            )
            remaining = cur_qty - close_qty
            if remaining > 1e-12:
                # 부분 청산 — 같은 방향 유지
                cur_qty = remaining
                cur_fee = cur_fee - cur_fee * (
                    close_qty / max(cur_qty + close_qty, 1e-12)
                )
            else:
                # 전부 청산. 이 fill 의 잔여 qty 가 있으면 reverse 진입으로 시작.
                leftover_open = f.qty - close_qty
                if leftover_open > 1e-12:
                    cur_side = f.side
                    cur_qty = leftover_open
                    cur_entry_price = f.price
                    cur_first_entry_price = f.price   # Phase V6 (reverse leg)
                    cur_entry_ts = f.timestamp
                    cur_fee = f.fee * (leftover_open / max(f.qty, 1e-12))
                else:
                    cur_side = None
                    cur_qty = 0.0
                    cur_entry_price = 0.0
                    cur_first_entry_price = 0.0
                    cur_entry_ts = None
                    cur_fee = 0.0

    return trades


def trades_to_df(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=[
                "entry_ts",
                "exit_ts",
                "side",
                "qty",
                "entry_price",
                "exit_price",
                "fee",
                "pnl",
            ]
        )
    return pd.DataFrame([t.to_dict() for t in trades])
