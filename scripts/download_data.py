"""scripts/download_data.py — CCXT public OHLCV 다운로드 (D15: API key 불필요).

예시:
    python scripts/download_data.py --exchange binance \\
        --symbol "BTC/USDT:USDT" --timeframe 1h \\
        --since 2024-01-01 --until 2024-07-01
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

import typer  # noqa: E402

from tickweaver.data.loaders.ccxt_loader import CcxtLoader  # noqa: E402
from tickweaver.utils.logger import configure_logging  # noqa: E402
from tickweaver.utils.paths import ensure_runtime_dirs  # noqa: E402

app = typer.Typer(add_completion=False, help="CCXT OHLCV 다운로더 (public, no API key)")


@app.command()
def main(
    exchange: str = typer.Option("binance", "--exchange", "-e"),
    symbol: str = typer.Option("BTC/USDT:USDT", "--symbol", "-s"),
    timeframe: str = typer.Option("1h", "--timeframe", "-t"),
    since: str = typer.Option(..., "--since", help="ISO 또는 YYYY-MM-DD"),
    until: str | None = typer.Option(None, "--until", help="ISO 또는 YYYY-MM-DD"),
    market_type: str = typer.Option("swap", "--market-type", help="swap | future | spot"),
    force_refresh: bool = typer.Option(False, "--force-refresh"),
) -> None:
    configure_logging("INFO")
    ensure_runtime_dirs()
    loader = CcxtLoader(exchange=exchange, market_type=market_type)
    df = loader.load(
        symbol=symbol,
        timeframe=timeframe,
        since=since,
        until=until,
        force_refresh=force_refresh,
    )
    path = loader.cache_path(symbol, timeframe)
    typer.echo(
        f"\ndownloaded {len(df)} rows -> {path}\n"
        f"  range: {df.index.min()} ~ {df.index.max()}"
    )


if __name__ == "__main__":
    app()
