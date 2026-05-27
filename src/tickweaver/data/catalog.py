"""data/processed 인덱싱 + 단일 parquet 리포트.

plan.md §M1 retrospective: gap 검사는 D13 으로 인한 "리포트만, fail 안 함".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from tickweaver.data.loaders.parquet_loader import read_parquet_with_attrs
from tickweaver.utils.paths import DATA_PROCESSED_DIR
from tickweaver.utils.timeutils import timeframe_to_ms


@dataclass
class CatalogEntry:
    """data/processed 안의 한 파일에 대한 요약."""

    path: str
    exchange: str
    symbol: str
    market_type: str
    timeframe: str
    rows: int
    start: str
    end: str
    size_bytes: int


@dataclass
class IntegrityReport:
    """단일 parquet 의 검사 리포트 (D13 — fail 안 함, 보고만)."""

    path: str
    schema_ok: bool
    schema_errors: list[str] = field(default_factory=list)
    rows: int = 0
    duplicates: int = 0
    high_lt_low: int = 0
    nonpositive_price: int = 0
    negative_volume: int = 0
    expected_bars: int = 0
    missing_bars: int = 0
    gap_examples: list[tuple[str, str, int]] = field(default_factory=list)
    start: str | None = None
    end: str | None = None
    timeframe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_processed(root: Path | None = None) -> list[CatalogEntry]:
    """data/processed 의 모든 parquet 을 인덱싱.

    경로 규칙: <root>/<exchange>/<symbol_safe>/<market_type>/<timeframe>.parquet
    """
    base = Path(root or DATA_PROCESSED_DIR)
    entries: list[CatalogEntry] = []
    if not base.exists():
        return entries

    for p in sorted(base.rglob("*.parquet")):
        try:
            df = read_parquet_with_attrs(p)
        except Exception:  # 손상된 파일은 skip
            continue

        attrs = df.attrs
        rel = p.relative_to(base) if p.is_relative_to(base) else p
        parts = rel.parts
        # fallback: attrs 가 없으면 디렉토리 구조에서 추론
        exchange = attrs.get("exchange", parts[0] if len(parts) >= 1 else "")
        symbol = attrs.get("symbol", parts[1] if len(parts) >= 2 else "")
        market_type = parts[2] if len(parts) >= 3 else ""
        timeframe = attrs.get("timeframe", p.stem)

        start = str(df.index.min()) if not df.empty else ""
        end = str(df.index.max()) if not df.empty else ""
        entries.append(
            CatalogEntry(
                path=str(p),
                exchange=str(exchange),
                symbol=str(symbol),
                market_type=str(market_type),
                timeframe=str(timeframe),
                rows=int(len(df)),
                start=start,
                end=end,
                size_bytes=p.stat().st_size,
            )
        )
    return entries


def inspect_file(path: str | Path, *, max_gap_examples: int = 5) -> IntegrityReport:
    """단일 parquet 의 스키마 + 무결성 + 결손 봉 리포트."""
    p = Path(path)
    rep = IntegrityReport(path=str(p), schema_ok=False)

    try:
        df = read_parquet_with_attrs(p)
    except Exception as e:
        rep.schema_errors.append(f"read failed: {e}")
        return rep

    # 스키마 검사 (raise 안 하고 사유 누적)
    errs: list[str] = []
    needed = ("open", "high", "low", "close", "volume")
    for c in needed:
        if c not in df.columns:
            errs.append(f"missing column: {c}")
    if not isinstance(df.index, pd.DatetimeIndex):
        errs.append(f"index not DatetimeIndex: {type(df.index).__name__}")
    elif df.index.tz is None:
        errs.append("index not tz-aware")

    rep.schema_ok = len(errs) == 0
    rep.schema_errors = errs
    rep.rows = int(len(df))
    if not df.empty and isinstance(df.index, pd.DatetimeIndex):
        rep.start = str(df.index.min())
        rep.end = str(df.index.max())

    if not rep.schema_ok:
        return rep

    # 무결성 (D13 — 검출만, raise 안 함)
    rep.duplicates = int(df.index.duplicated().sum())
    rep.high_lt_low = int((df["high"] < df["low"]).sum())
    rep.nonpositive_price = int(
        ((df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)).sum()
    )
    rep.negative_volume = int((df["volume"] < 0).sum())

    # 결손 봉 — timeframe 알아야 한다
    tf = df.attrs.get("timeframe") or p.stem
    rep.timeframe = str(tf)
    try:
        tf_ms = timeframe_to_ms(tf)
    except Exception:
        rep.schema_errors.append(f"unknown timeframe in attrs: {tf!r}")
        return rep

    if rep.rows >= 2:
        idx_ns = df.index.asi8
        diffs_ms = (pd.Series(idx_ns).diff().dropna() / 1_000_000).astype("int64")
        gaps_mask = diffs_ms > tf_ms
        n_missing = int(((diffs_ms[gaps_mask] // tf_ms) - 1).sum())
        rep.missing_bars = n_missing

        # span 으로 추정한 expected bars
        span_ms = int((df.index.max() - df.index.min()).total_seconds() * 1000)
        rep.expected_bars = int(span_ms // tf_ms) + 1

        # 예시 gap 위치 (앞에서 max_gap_examples 개)
        for i, big in enumerate(gaps_mask.values):
            if not big:
                continue
            ts_before = df.index[i]
            ts_after = df.index[i + 1]
            missed_here = int(diffs_ms.iloc[i] // tf_ms - 1)
            rep.gap_examples.append((str(ts_before), str(ts_after), missed_here))
            if len(rep.gap_examples) >= max_gap_examples:
                break

    return rep


def format_catalog_table(entries: list[CatalogEntry]) -> str:
    """간단한 plain-text 표 — 사용자가 콘솔에서 바로 읽기."""
    if not entries:
        return "(no parquet files in data/processed/)"
    headers = ["exchange", "symbol", "market_type", "timeframe", "rows", "range", "size_kb"]
    rows: list[list[str]] = [headers]
    for e in entries:
        rng = f"{e.start[:19]} -> {e.end[:19]}" if e.start and e.end else "-"
        rows.append(
            [
                e.exchange,
                e.symbol,
                e.market_type,
                e.timeframe,
                str(e.rows),
                rng,
                f"{e.size_bytes / 1024:.1f}",
            ]
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(headers))]
    out_lines: list[str] = []
    for row in rows:
        out_lines.append("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    return "\n".join(out_lines)


def format_inspect_report(rep: IntegrityReport) -> str:
    """단일 파일 리포트 — plain text."""
    lines = [
        f"path        : {rep.path}",
        f"timeframe   : {rep.timeframe}",
        f"rows        : {rep.rows}",
        f"range       : {rep.start} -> {rep.end}",
        f"schema_ok   : {rep.schema_ok}",
    ]
    if rep.schema_errors:
        lines.append("schema_errors:")
        for e in rep.schema_errors:
            lines.append(f"  - {e}")
    lines.extend(
        [
            f"duplicates       : {rep.duplicates}",
            f"high < low       : {rep.high_lt_low}",
            f"nonpositive price: {rep.nonpositive_price}",
            f"negative volume  : {rep.negative_volume}",
            f"missing bars     : {rep.missing_bars} "
            f"(expected_span={rep.expected_bars}, observed={rep.rows})",
        ]
    )
    if rep.gap_examples:
        lines.append("gap examples (first 5):")
        for before, after, n in rep.gap_examples:
            lines.append(f"  - {before}  -> {after}  (missed={n})")
    return "\n".join(lines)
