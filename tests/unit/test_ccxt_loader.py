"""CcxtLoader — _FakeCcxtExchange 로 monkeypatch 검증.

sandbox 네트워크가 차단된 환경에서도 페이지네이션 + 캐시 + 재개 + 정규화 경로를
검증한다. 실제 `ccxt.binance` 의 통신 동작은 사용자 PC 에서 `download_data.py` 로
체크.

plan.md §8.4 mock-only 거래소 테스트 패턴.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────
# Fake CCXT exchange — fetch_ohlcv 응답을 in-memory 로 제어
# ─────────────────────────────────────────────────────────
class _FakeCcxtExchange:
    """ccxt.binance 행세를 하는 mock. fetch_ohlcv 가 미리 채운 데이터를 페이지네이션."""

    def __init__(self, options: dict | None = None) -> None:
        self.options = options or {}
        self.id = "fake_binance"
        self._all_rows: list[list] = []
        self._fetch_calls: list[dict] = []  # 호출 이력 (테스트 용도)
        self.options.setdefault("enableRateLimit", True)

    def set_rows(self, rows: list[list]) -> None:
        """[ts_ms, o, h, l, c, v] 시퀀스로 미리 채운다."""
        self._all_rows = list(rows)

    # ccxt 인터페이스
    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None, params=None):
        self._fetch_calls.append(
            {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        )
        rows = self._all_rows
        if since is not None:
            rows = [r for r in rows if r[0] >= since]
        if limit is not None:
            rows = rows[: int(limit)]
        return [list(r) for r in rows]


def _make_fake_ccxt_module(exchange_name: str = "binance") -> types.ModuleType:
    """ccxt 모듈 행세 — `getattr(ccxt, exchange_name)` 가 _FakeCcxtExchange 반환."""
    fake = types.ModuleType("ccxt")
    setattr(fake, exchange_name, _FakeCcxtExchange)
    return fake


def _make_klines(n: int, start_ms: int, tf_ms: int = 3_600_000) -> list[list]:
    """테스트용 OHLCV (binance kline 형식: [open_ts, o, h, l, c, v])."""
    rng = np.random.default_rng(0)
    rows = []
    price = 30000.0
    for i in range(n):
        ts = start_ms + i * tf_ms
        o = price
        c = price * (1 + rng.normal(0, 0.002))
        h = max(o, c) * (1 + rng.uniform(0, 0.003))
        l = min(o, c) * (1 - rng.uniform(0, 0.003))
        v = float(rng.uniform(50, 200))
        rows.append([ts, float(o), float(h), float(l), float(c), v])
        price = c
    return rows


# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────
@pytest.fixture
def fake_ccxt(monkeypatch):
    """sys.modules['ccxt'] 를 _FakeCcxtExchange 로 교체."""
    fake_module = _make_fake_ccxt_module("binance")
    monkeypatch.setitem(sys.modules, "ccxt", fake_module)
    # ccxt_loader 가 이미 import 됐을 수 있으니 그쪽 ref 도 교체
    import tickweaver.data.loaders.ccxt_loader as loader_mod

    monkeypatch.setattr(loader_mod, "ccxt", fake_module)
    return fake_module


@pytest.fixture
def loader(fake_ccxt, tmp_path):
    from tickweaver.data.loaders.ccxt_loader import CcxtLoader

    return CcxtLoader(exchange="binance", market_type="swap", cache_dir=tmp_path)


# ─────────────────────────────────────────────────────────
# 테스트
# ─────────────────────────────────────────────────────────
def test_loader_no_api_key_used(fake_ccxt, tmp_path):
    """D15 — CcxtLoader 가 어떤 API key 도 전달하지 않는지."""
    from tickweaver.data.loaders.ccxt_loader import CcxtLoader

    loader = CcxtLoader(exchange="binance", market_type="swap", cache_dir=tmp_path)
    # mock exchange 의 options 에 apiKey 같은 게 없어야 함
    assert "apiKey" not in loader.client.options
    assert "secret" not in loader.client.options


def test_basic_load_paginated_and_cached(fake_ccxt, loader):
    """기본 로드 → 페이지네이션 + 정규화 + 캐시."""
    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    fake_ccxt.binance().set_rows  # ensure fake exists
    fake_ex = loader.client
    # 2500 rows 로 채워서 페이지네이션 (limit=1000 * 3 페이지)
    fake_ex.set_rows(_make_klines(2500, start_ms))

    df = loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-04-15", tz="UTC"),
    )
    # 정규화된 표준 OHLCV
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) in ("UTC", "tzutc()", "UTC+00:00")
    assert df.index.name == "timestamp"
    # 페이지네이션 — limit=1000 으로 3번 이상 호출됐어야 함
    fetch_count = len(fake_ex._fetch_calls)
    assert fetch_count >= 3, f"expected >= 3 fetch calls, got {fetch_count}"
    # since 가 ms (int) 로 넘어갔는지
    assert all(c["since"] is None or isinstance(c["since"], int) for c in fake_ex._fetch_calls)


def test_cache_hit_avoids_refetch(fake_ccxt, loader, tmp_path):
    """두 번째 load 는 캐시에서 바로 반환 (fetch 호출 추가 없음)."""
    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    fake_ex = loader.client
    fake_ex.set_rows(_make_klines(500, start_ms))

    df1 = loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-21", tz="UTC"),  # 480h
    )
    calls_after_first = len(fake_ex._fetch_calls)
    assert calls_after_first >= 1

    # 같은 범위 다시 — 캐시 hit
    df2 = loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-21", tz="UTC"),
    )
    assert len(fake_ex._fetch_calls) == calls_after_first  # 추가 fetch 없음
    pd.testing.assert_frame_equal(df1, df2)


def test_cache_path_layout(loader):
    """캐시 경로가 plan.md §4 의 명세대로 — exchange/symbol/market_type/timeframe.parquet."""
    p = loader.cache_path("BTC/USDT:USDT", "1h")
    parts = p.parts
    assert "binance" in parts
    assert "BTC-USDT-USDT" in parts
    assert "swap" in parts
    assert p.name == "1h.parquet"


def test_attrs_are_attached(fake_ccxt, loader):
    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    fake_ex = loader.client
    fake_ex.set_rows(_make_klines(100, start_ms))
    df = loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-05", tz="UTC"),
    )
    assert df.attrs.get("symbol") == "BTC/USDT:USDT"
    assert df.attrs.get("timeframe") == "1h"
    assert df.attrs.get("exchange") == "binance"
    assert "ccxt://" in df.attrs.get("source_uri", "")


def test_skip_only_no_gap_fail(fake_ccxt, loader):
    """D13 — gap 이 있어도 fail 하지 않고 그대로 통과."""
    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    rows = _make_klines(100, start_ms)
    # 50번째 봉 제거 (1시간 gap)
    rows_with_gap = rows[:50] + rows[51:]
    fake_ex = loader.client
    fake_ex.set_rows(rows_with_gap)
    # raise 하지 않고 99 rows 그대로 반환되어야 함
    df = loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-06", tz="UTC"),
    )
    assert len(df) == 99


def test_writes_parquet_file(fake_ccxt, loader, tmp_path):
    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    fake_ex = loader.client
    fake_ex.set_rows(_make_klines(100, start_ms))
    loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-05", tz="UTC"),
    )
    cached = loader.cache_path("BTC/USDT:USDT", "1h")
    assert cached.exists()
    assert cached.stat().st_size > 0


def test_unknown_exchange_raises(fake_ccxt):
    """등록 안 된 거래소는 즉시 ValueError (P6)."""
    from tickweaver.data.loaders.ccxt_loader import CcxtLoader

    with pytest.raises(ValueError):
        CcxtLoader(exchange="does_not_exist")


def test_resume_partial_cache(fake_ccxt, loader, tmp_path):
    """캐시가 일부만 있을 때, 부족한 범위만 추가 fetch 한 후 머지."""
    start_ms = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    fake_ex = loader.client
    fake_ex.set_rows(_make_klines(200, start_ms))

    # 1차: 100h 만
    loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-05 04:00:00", tz="UTC"),  # 100h
    )
    calls_first = len(fake_ex._fetch_calls)

    # 2차: 200h 까지 — 추가 페치 발생
    df2 = loader.load(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        since=pd.Timestamp("2024-01-01", tz="UTC"),
        until=pd.Timestamp("2024-01-09 08:00:00", tz="UTC"),  # 200h
    )
    assert len(fake_ex._fetch_calls) > calls_first  # 추가 fetch 있었음
    assert len(df2) >= 100  # 총 데이터가 늘어남
