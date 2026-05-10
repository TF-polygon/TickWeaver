"""rsi_mean_reversion.py — RSI 평균 회귀 전략 (간단한 단일 자산).

논리 (가장 흔한 RSI mean reversion 패턴):
  - RSI 가 oversold 임계값(기본 30) 아래로 내려가면 매수 진입
  - RSI 가 overbought 임계값(기본 70) 위로 올라가면 청산
  - 한 시점에 한 포지션만 보유 (D3 단일 자산)

핵심 안전장치:
  - on_bar 에서만 시그널/주문 (룩어헤드 방지는 엔진이 강제)
  - RSI 워밍업 끝나기 전에는 아무 것도 하지 않음 (rsi.is_warm 체크)
  - api.size_from_cash_pct() 로 사이즈를 cash 비율로 잡아 자본 곡선이 자동 스케일

params (strategies/rsi_mean_reversion.json):
  rsi_period   : RSI 기간 (기본 14)
  oversold     : 매수 임계값 (기본 30)
  overbought   : 청산 임계값 (기본 70)
  size_pct     : 가용 cash 의 몇 % 를 한 진입에 쓸지 (기본 0.2 = 20%)

레퍼런스: strategies/_reference.md
"""

from tickweaver.strategy.indicators import RSI

rsi = None


def on_init():
    global rsi
    rsi = RSI(period=params.get("rsi_period", 14))


def on_bar(bar):
    rsi.update(bar.close)
    if not rsi.is_warm:
        return  # 워밍업 동안 거래 X

    oversold = params.get("oversold", 30.0)
    overbought = params.get("overbought", 70.0)

    if rsi.value < oversold and api.is_flat():
        qty = api.size_from_cash_pct(params.get("size_pct", 0.2), bar.close)
        if qty > 0:
            api.market_buy(qty)
            api.log("entry_oversold", rsi=round(rsi.value, 2), price=bar.close)

    elif rsi.value > overbought and not api.is_flat():
        api.close_position()
        api.log("exit_overbought", rsi=round(rsi.value, 2), price=bar.close)


def on_fill(fill):
    api.log("fill", side=fill.side.name, price=round(fill.price, 2),
            qty=fill.qty, pnl_realized=round(fill.pnl_realized, 2))


def on_deinit():
    api.log("rsi_mean_reversion finished",
            final_equity=round(api.equity, 2),
            position_qty=api.position().qty)
