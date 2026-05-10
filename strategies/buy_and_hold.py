"""
buy_and_hold.py — 가장 단순한 e2e 검증용 전략.

첫 봉에 가용 현금의 99% 로 매수하고 끝까지 보유. 백테스트 파이프라인이 굴러가는지
스모크 테스트할 때 사용합니다.

레퍼런스: strategies/_reference.md
"""


def on_bar(bar):
    if api.is_flat():
        qty = api.size_from_cash_pct(0.99, bar.close)
        if qty > 0:
            api.market_buy(qty)


def on_deinit():
    api.log("buy_and_hold finished",
            final_equity=api.equity,
            position_qty=api.position().qty)
