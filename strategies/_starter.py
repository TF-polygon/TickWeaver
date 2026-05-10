"""
_starter.py — tickweaver 전략 보일러플레이트

이 파일을 복사해서 (예: my_alpha.py) on_bar 의 본문만 수정하세요.
함께 _starter.json 도 복사 (my_alpha.json) 하면 params 로 자동 주입됩니다.

레퍼런스: strategies/_reference.md
"""

# ─────────────────────────────────────────────────────────
# 모듈 전역 = MT4 EA 글로벌 변수
# 백테스트 동안 유지되며, on_init 에서 reset 하는 것이 안전합니다.
# ─────────────────────────────────────────────────────────
prev_close = 0.0
trade_count = 0


def on_init():
    """백테스트 시작 직전 1회 호출."""
    global prev_close, trade_count
    prev_close = 0.0
    trade_count = 0
    api.log("strategy initialized")


def on_bar(bar):
    """각 봉이 닫힌 직후 호출. 이 함수만 수정해도 충분합니다."""
    global prev_close, trade_count

    # 예시: 직전 봉 대비 1% 이상 상승하면 진입, flat 이면.
    threshold = params.get("up_threshold", 0.01)
    size_pct = params.get("size_pct", 0.1)

    if prev_close > 0 and api.is_flat():
        if bar.close > prev_close * (1.0 + threshold):
            qty = api.size_from_cash_pct(size_pct, bar.close)
            api.market_buy(qty)
            trade_count += 1

    prev_close = bar.close


def on_tick(tick):
    """봉 내부 합성 tick 마다 호출. 트레일링 스탑 등에 사용. (선택)

    예: 손절 LIMIT/STOP 발주
        api.stop_sell(qty, stop_price=entry * 0.99)
        api.limit_sell(qty, price=entry * 1.02)
    """
    pass


def on_fill(fill):
    """주문 체결 시 호출. (선택)"""
    pass


def on_deinit():
    """백테스트 종료 직후 1회 호출. (선택)"""
    api.log("strategy finished", trade_count=trade_count, final_equity=api.equity)
