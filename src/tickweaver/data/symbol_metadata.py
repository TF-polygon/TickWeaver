"""종목별 정밀도 (Polish Work C).

CCXT market info 의 `precision` 을 표시/라운딩에 쓰는 두 값으로 환원한다:

    * price_decimals — Entry Price 등 가격 표기 소수 자릿수
    * qty_step       — 수량 최소 단위 (broker dust epsilon / api.round_qty)

CCXT 의 precision 은 거래소마다 두 모드다 (`exchange.precisionMode`):
    * DECIMAL_PLACES — 값이 자릿수 (price=2, amount=6)
    * TICK_SIZE      — 값이 최소 단위 (price=0.01, amount=0.001)

둘 다 위 두 값으로 정규화한다. precision 누락 시 ValueError 를 던지고,
호출부(CcxtLoader.get_symbol_precision)가 DEFAULT_PRECISION 으로 fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import ccxt


@dataclass(frozen=True)
class SymbolPrecision:
    price_decimals: int
    qty_step: float


# 기존 BTC/USDT 하드코딩 동작 (= 가격 둘째 자리, qty 1e-6) 을 fallback default 로.
DEFAULT_PRECISION = SymbolPrecision(price_decimals=2, qty_step=1e-6)


def _tick_to_decimals(tick: float) -> int:
    """tick size (0.01) → 소수 자릿수 (2)."""
    if tick <= 0:
        return DEFAULT_PRECISION.price_decimals
    return max(0, int(round(-math.log10(tick))))


def precision_from_ccxt_market(
    market: dict, precision_mode: int | None
) -> SymbolPrecision:
    """ccxt `exchange.market(symbol)` dict → SymbolPrecision.

    precision_mode 는 `exchange.precisionMode` (TICK_SIZE / DECIMAL_PLACES).
    price/amount precision 이 없으면 ValueError.
    """
    prec = (market or {}).get("precision") or {}
    price_p = prec.get("price")
    amount_p = prec.get("amount")
    if price_p is None or amount_p is None:
        raise ValueError(f"missing price/amount precision: {prec!r}")

    if precision_mode == ccxt.TICK_SIZE:
        price_decimals = _tick_to_decimals(float(price_p))
        qty_step = float(amount_p)
    else:
        # DECIMAL_PLACES (및 그 외) — 값이 자릿수.
        price_decimals = int(round(float(price_p)))
        qty_step = 10.0 ** (-int(round(float(amount_p))))

    return SymbolPrecision(price_decimals=price_decimals, qty_step=qty_step)
