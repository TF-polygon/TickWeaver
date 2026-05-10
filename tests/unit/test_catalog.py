"""data.catalog — list_processed / inspect_file 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tests.fixtures.ohlcv import make_synthetic_ohlcv
from tickweaver.data.catalog import (
    format_catalog_table,
    format_inspect_report,
    inspect_file,
    list_processed,
)
from tickweaver.data.loaders.parquet_loader import write_parquet


def _write_synthetic(tmp: Path, exchange: str, symbol_safe: str, mt: str, tf: str, n: int = 100):
    p = tmp / exchange / symbol_safe / mt / f"{tf}.parquet"
    df = make_synthetic_ohlcv(n_bars=n, timeframe=tf, exchange=exchange, symbol=symbol_safe)
    df.attrs["symbol"] = symbol_safe
    df.attrs["timeframe"] = tf
    df.attrs["exchange"] = exchange
    write_parquet(df, p)
    return p, df


# ─────────────────────────────────────────────────────────
# list_processed
# ─────────────────────────────────────────────────────────
def test_list_processed_finds_files(tmp_path: Path):
    _write_synthetic(tmp_path, "binance", "BTC-USDT-USDT", "swap", "1h", n=50)
    _write_synthetic(tmp_path, "binance", "ETH-USDT-USDT", "swap", "1h", n=80)

    entries = list_processed(tmp_path)
    assert len(entries) == 2
    symbols = {e.symbol for e in entries}
    assert symbols == {"BTC-USDT-USDT", "ETH-USDT-USDT"}
    for e in entries:
        assert e.exchange == "binance"
        assert e.market_type == "swap"
        assert e.timeframe == "1h"
        assert e.rows in (50, 80)


def test_list_processed_empty(tmp_path: Path):
    assert list_processed(tmp_path) == []


def test_format_catalog_table(tmp_path: Path):
    _write_synthetic(tmp_path, "binance", "BTC-USDT-USDT", "swap", "1h", n=10)
    entries = list_processed(tmp_path)
    table = format_catalog_table(entries)
    assert "binance" in table
    assert "BTC-USDT-USDT" in table
    assert "1h" in table


# ─────────────────────────────────────────────────────────
# inspect_file — clean data
# ─────────────────────────────────────────────────────────
def test_inspect_clean_file(tmp_path: Path):
    p, df = _write_synthetic(tmp_path, "binance", "BTC-USDT-USDT", "swap", "1h", n=200)
    rep = inspect_file(p)
    assert rep.schema_ok is True
    assert rep.schema_errors == []
    assert rep.rows == 200
    assert rep.duplicates == 0
    assert rep.high_lt_low == 0
    assert rep.nonpositive_price == 0
    assert rep.negative_volume == 0
    assert rep.missing_bars == 0
    assert rep.gap_examples == []


# ─────────────────────────────────────────────────────────
# inspect_file — gap detection (D13: 보고만)
# ─────────────────────────────────────────────────────────
def test_inspect_detects_gaps_without_failing(tmp_path: Path):
    p, df = _write_synthetic(tmp_path, "binance", "BTC-USDT-USDT", "swap", "1h", n=100)
    # 50번 봉 제거 (1h gap)
    df_with_gap = df.drop(df.index[50])
    df_with_gap.attrs.update(df.attrs)
    write_parquet(df_with_gap, p)

    rep = inspect_file(p)
    # 호출이 raise 하지 않고 보고만
    assert rep.schema_ok is True
    assert rep.rows == 99
    assert rep.missing_bars == 1
    assert len(rep.gap_examples) == 1


def test_inspect_detects_multiple_gaps(tmp_path: Path):
    p, df = _write_synthetic(tmp_path, "binance", "BTC-USDT-USDT", "swap", "1h", n=200)
    # 3개 봉 제거 (서로 떨어진 위치)
    df_with_gaps = df.drop(df.index[[30, 80, 150]])
    df_with_gaps.attrs.update(df.attrs)
    write_parquet(df_with_gaps, p)

    rep = inspect_file(p)
    assert rep.missing_bars == 3
    assert len(rep.gap_examples) == 3


# ─────────────────────────────────────────────────────────
# inspect_file — integrity violations (보고만)
# ─────────────────────────────────────────────────────────
def test_inspect_reports_corrupt_data_without_failing(tmp_path: Path):
    """high<low 같은 무결성 위반도 raise 안 하고 보고만."""
    # write_parquet 자체는 normalize_ohlcv 안 통하므로 직접 테이블을 만든다
    idx = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    idx.name = "timestamp"
    df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 10),
            "high": np.linspace(101, 111, 10),
            "low": np.linspace(99, 109, 10),
            "close": np.linspace(100.5, 110.5, 10),
            "volume": np.linspace(50, 100, 10),
        },
        index=idx,
    ).astype("float64")
    # 의도적으로 깨뜨리기
    df.iloc[3, df.columns.get_loc("low")] = 200.0  # high < low
    df.iloc[5, df.columns.get_loc("close")] = -1.0  # nonpositive
    df.attrs["symbol"] = "TEST"
    df.attrs["timeframe"] = "1h"
    df.attrs["exchange"] = "synthetic"
    p = tmp_path / "synthetic" / "TEST" / "swap" / "1h.parquet"
    write_parquet(df, p)

    rep = inspect_file(p)
    assert rep.schema_ok is True  # 스키마 자체는 OK
    assert rep.high_lt_low == 1
    assert rep.nonpositive_price == 1
    # 호출이 raise 안 함
    out = format_inspect_report(rep)
    assert "high < low" in out


# ─────────────────────────────────────────────────────────
# inspect_file — broken file
# ─────────────────────────────────────────────────────────
def test_inspect_missing_file(tmp_path: Path):
    rep = inspect_file(tmp_path / "does_not_exist.parquet")
    assert rep.schema_ok is False
    assert any("read failed" in e for e in rep.schema_errors)
