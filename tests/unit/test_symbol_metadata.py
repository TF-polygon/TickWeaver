"""symbol_metadata — CCXT market info 에서 종목별 정밀도 추출 (Polish Work C).

`precision_from_ccxt_market` 는 순수 함수라 네트워크 없이 검증.
`CcxtLoader.get_symbol_precision` 는 _FakeExchange monkeypatch 로 load_markets
+ 디스크 캐시 + fallback 경로를 검증한다 (test_ccxt_loader.py 패턴 재사용).
"""

from __future__ import annotations

import sys
import types

import ccxt
import pytest


# ─────────────────────────────────────────────────────────
# Fake CCXT exchange — market info + precisionMode 제어
# ─────────────────────────────────────────────────────────
class _FakeExchange:
    """ccxt exchange 행세. load_markets / market(symbol) / precisionMode 제공."""

    def __init__(self, options: dict | None = None) -> None:
        self.options = options or {}
        self.id = "fake"
        self.precisionMode = ccxt.DECIMAL_PLACES
        self._markets: dict[str, dict] = {}
        self._load_markets_calls = 0
        self._raise_on_market = False

    def load_markets(self, reload: bool = False) -> dict:
        self._load_markets_calls += 1
        return self._markets

    def market(self, symbol: str) -> dict:
        if self._raise_on_market or symbol not in self._markets:
            raise KeyError(f"no market: {symbol}")
        return self._markets[symbol]


def _make_fake_ccxt_module() -> types.ModuleType:
    fake = types.ModuleType("ccxt")
    fake.binance = _FakeExchange
    # precisionMode 상수도 전달 (loader 가 self.client.precisionMode 를 읽음)
    fake.DECIMAL_PLACES = ccxt.DECIMAL_PLACES
    fake.SIGNIFICANT_DIGITS = ccxt.SIGNIFICANT_DIGITS
    fake.TICK_SIZE = ccxt.TICK_SIZE
    return fake


@pytest.fixture
def fake_ccxt(monkeypatch):
    fake_module = _make_fake_ccxt_module()
    monkeypatch.setitem(sys.modules, "ccxt", fake_module)
    import tickweaver.data.loaders.ccxt_loader as loader_mod

    monkeypatch.setattr(loader_mod, "ccxt", fake_module)
    return fake_module


@pytest.fixture
def loader(fake_ccxt, tmp_path):
    from tickweaver.data.loaders.ccxt_loader import CcxtLoader

    return CcxtLoader(exchange="binance", market_type="swap", cache_dir=tmp_path)


# ─────────────────────────────────────────────────────────
# 1~3. precision_from_ccxt_market (순수 함수)
# ─────────────────────────────────────────────────────────
def test_decimal_places_mode():
    """DECIMAL_PLACES: price=2 자리, amount=6 자리 → step 1e-6."""
    from tickweaver.data.symbol_metadata import (
        SymbolPrecision,
        precision_from_ccxt_market,
    )

    market = {"precision": {"price": 2, "amount": 6}}
    prec = precision_from_ccxt_market(market, ccxt.DECIMAL_PLACES)
    assert isinstance(prec, SymbolPrecision)
    assert prec.price_decimals == 2
    assert prec.qty_step == pytest.approx(1e-6)


def test_tick_size_mode():
    """TICK_SIZE: price tick=0.01 → 2 자리, amount tick=0.001 → step 그대로."""
    from tickweaver.data.symbol_metadata import precision_from_ccxt_market

    market = {"precision": {"price": 0.01, "amount": 0.001}}
    prec = precision_from_ccxt_market(market, ccxt.TICK_SIZE)
    assert prec.price_decimals == 2
    assert prec.qty_step == pytest.approx(0.001)


def test_decimal_places_eth_like():
    """종목별 step 차이 — amount=3 자리 → step 1e-3."""
    from tickweaver.data.symbol_metadata import precision_from_ccxt_market

    market = {"precision": {"price": 2, "amount": 3}}
    prec = precision_from_ccxt_market(market, ccxt.DECIMAL_PLACES)
    assert prec.price_decimals == 2
    assert prec.qty_step == pytest.approx(1e-3)


# ─────────────────────────────────────────────────────────
# 4~6. CcxtLoader.get_symbol_precision
# ─────────────────────────────────────────────────────────
def test_get_symbol_precision_happy(loader):
    """load_markets + market(symbol) 파싱 → SymbolPrecision + JSON 캐시 기록."""
    from tickweaver.data.symbol_metadata import SymbolPrecision

    loader.client.precisionMode = ccxt.DECIMAL_PLACES
    loader.client._markets["BTC/USDT:USDT"] = {
        "precision": {"price": 2, "amount": 6}
    }
    prec = loader.get_symbol_precision("BTC/USDT:USDT")
    assert prec == SymbolPrecision(price_decimals=2, qty_step=1e-6)

    # 디스크 캐시 파일이 생성됐고 symbol 이 들어있어야 함
    import json

    cache_files = list((loader.cache_dir / "binance").glob("precision*.json"))
    assert cache_files, "precision cache json not written"
    data = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert "BTC/USDT:USDT" in data


def test_get_symbol_precision_cache_hit(loader):
    """2번째 호출은 디스크 캐시에서 — load_markets 재호출 없음."""
    loader.client.precisionMode = ccxt.DECIMAL_PLACES
    loader.client._markets["ETH/USDT:USDT"] = {
        "precision": {"price": 2, "amount": 3}
    }
    p1 = loader.get_symbol_precision("ETH/USDT:USDT")
    calls_after_first = loader.client._load_markets_calls
    assert calls_after_first >= 1

    p2 = loader.get_symbol_precision("ETH/USDT:USDT")
    assert loader.client._load_markets_calls == calls_after_first  # 추가 fetch 없음
    assert p1 == p2


def test_get_symbol_precision_fallback(loader):
    """market(symbol) 예외 / precision 누락 → DEFAULT_PRECISION, 예외 안 남."""
    from tickweaver.data.symbol_metadata import DEFAULT_PRECISION

    loader.client._raise_on_market = True
    prec = loader.get_symbol_precision("DOGE/USDT:USDT")
    assert prec == DEFAULT_PRECISION
