"""CCXT public OHLCV downloader.

D15: no API key required. Uses CCXT public endpoints only.
Pagination + disk cache + resume.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd

from tickweaver.data.loaders.base import slice_period
from tickweaver.data.symbol_metadata import (
    DEFAULT_PRECISION,
    SymbolPrecision,
    precision_from_ccxt_market,
)
from tickweaver.data.loaders.parquet_loader import (
    read_parquet_with_attrs,
    write_parquet,
)
from tickweaver.data.normalizers import normalize_ohlcv
from tickweaver.utils.logger import get_logger
from tickweaver.utils.paths import DATA_PROCESSED_DIR, symbol_to_safe, to_rel_path
from tickweaver.utils.timeutils import parse_iso_utc, timeframe_to_ms


_LOG = get_logger("ccxt_loader")


class CcxtLoader:
    """OHLCV public download. No API key (D15)."""

    def __init__(
        self,
        exchange: str,
        market_type: str = "swap",
        cache_dir: Path | None = None,
        rate_limit_sleep: float = 0.2,
    ) -> None:
        cls = getattr(ccxt, exchange, None)
        if cls is None:
            raise ValueError(f"unknown ccxt exchange: {exchange}")
        # No apiKey/secret. Public endpoints only.
        self.client = cls(
            {
                "enableRateLimit": True,
                "options": {"defaultType": market_type},
            }
        )
        self.exchange = exchange
        self.market_type = market_type
        self.cache_dir = cache_dir or DATA_PROCESSED_DIR
        self.rate_limit_sleep = rate_limit_sleep

    def cache_path(self, symbol: str, timeframe: str) -> Path:
        return (
            self.cache_dir
            / self.exchange
            / symbol_to_safe(symbol)
            / self.market_type
            / f"{timeframe}.parquet"
        )

    def precision_cache_path(self) -> Path:
        return self.cache_dir / self.exchange / f"precision_{self.market_type}.json"

    def get_symbol_precision(self, symbol: str) -> SymbolPrecision:
        """종목별 가격/qty 정밀도. 디스크 캐시 → 1회 load_markets → fallback (C).

        디스크에 캐시되면 이후 백테스트는 네트워크 호출 없이 재사용한다.
        market info 누락/예외 시 DEFAULT_PRECISION 으로 안전 fallback.
        """
        cache_path = self.precision_cache_path()
        data: dict[str, dict] = {}
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8")) or {}
            except Exception:
                data = {}
            entry = data.get(symbol)
            if entry is not None:
                return SymbolPrecision(
                    price_decimals=int(entry["price_decimals"]),
                    qty_step=float(entry["qty_step"]),
                )

        try:
            self.client.load_markets()
            market = self.client.market(symbol)
            prec = precision_from_ccxt_market(
                market, getattr(self.client, "precisionMode", None)
            )
        except Exception as e:
            _LOG.warning(
                "symbol_precision_fallback", symbol=symbol, error=str(e)
            )
            return DEFAULT_PRECISION

        data[symbol] = {
            "price_decimals": prec.price_decimals,
            "qty_step": prec.qty_step,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            _LOG.warning(
                "symbol_precision_cache_write_failed", symbol=symbol, error=str(e)
            )
        return prec

    def load(
        self,
        symbol: str,
        timeframe: str,
        since: pd.Timestamp | str | None = None,
        until: pd.Timestamp | str | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Cache first, then fetch missing range. Returns standard OHLCV."""
        since_ts = parse_iso_utc(since)
        until_ts = parse_iso_utc(until)
        path = self.cache_path(symbol, timeframe)

        cached: pd.DataFrame | None = None
        if path.exists() and not force_refresh:
            cached = read_parquet_with_attrs(path)
            _LOG.info("cache_hit", path=to_rel_path(path), rows=len(cached))

        # Cache absent or insufficient -> fetch.
        # When comparing against `until`, allow 1 timeframe of slack so the
        # last cached bar (close ts == until - tf) does not look insufficient.
        tf_td = pd.Timedelta(milliseconds=timeframe_to_ms(timeframe))
        need_fetch = (
            cached is None
            or (since_ts is not None and (cached.empty or cached.index.min() > since_ts))
            or (
                until_ts is not None
                and (cached.empty or cached.index.max() + tf_td < until_ts)
            )
        )

        if need_fetch:
            fetched = self._fetch_paginated(symbol, timeframe, since_ts, until_ts)
            if cached is not None and not cached.empty:
                merged = pd.concat([cached, fetched])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            else:
                merged = fetched
            merged.attrs.update(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "exchange": self.exchange,
                    "source_uri": f"ccxt://{self.exchange}/{symbol}/{timeframe}",
                }
            )
            write_parquet(merged, path)
            _LOG.info("cache_write", path=to_rel_path(path), rows=len(merged))
            df = merged
        else:
            df = cached  # type: ignore[assignment]

        return slice_period(df, since_ts, until_ts)

    def _fetch_paginated(
        self,
        symbol: str,
        timeframe: str,
        since_ts: pd.Timestamp | None,
        until_ts: pd.Timestamp | None,
    ) -> pd.DataFrame:
        tf_ms = timeframe_to_ms(timeframe)
        cursor_ms: int | None = None
        if since_ts is not None:
            cursor_ms = int(since_ts.timestamp() * 1000)
        until_ms = int(until_ts.timestamp() * 1000) if until_ts is not None else None

        rows: list[list[Any]] = []
        limit = 1000
        max_iters = 1000
        prev_last_ms: int | None = None

        for _ in range(max_iters):
            batch = self.client.fetch_ohlcv(symbol, timeframe, since=cursor_ms, limit=limit)
            if not batch:
                break
            rows.extend(batch)
            last_ms = batch[-1][0]
            if prev_last_ms is not None and last_ms <= prev_last_ms:
                break
            prev_last_ms = last_ms
            cursor_ms = last_ms + tf_ms
            if until_ms is not None and cursor_ms >= until_ms:
                break
            # NOTE: do NOT stop on `len(batch) < limit`. Some exchanges (e.g. OKX)
            # cap a single fetch_ohlcv call well below `limit` (300/call), so a
            # short batch does not mean "no more data". Termination is handled by
            # the empty-batch (above), non-advancing-cursor (above), until_ms, and
            # max_iters guards instead.
            time.sleep(self.rate_limit_sleep)

        if not rows:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
            ).astype("float64")

        df_raw = pd.DataFrame(
            rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df_raw = df_raw.drop_duplicates(subset=["timestamp"])
        df = normalize_ohlcv(
            df_raw,
            symbol=symbol,
            timeframe=timeframe,
            exchange=self.exchange,
            source_uri=f"ccxt://{self.exchange}/{symbol}/{timeframe}",
            timestamp_col="timestamp",
            timestamp_unit="ms",
        )
        if until_ts is not None:
            df = df[df.index < until_ts]
        return df
