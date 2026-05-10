"""scripts/inspect_data.py — data/processed 카탈로그 + 단일 parquet 리포트.

D13 정책: 결손/무결성 위반은 raise 안 함, 리포트만 생성.

예시:
    python scripts/inspect_data.py list
    python scripts/inspect_data.py list --json
    python scripts/inspect_data.py inspect data/processed/binance/BTC-USDT-USDT/swap/1h.parquet
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

import typer  # noqa: E402

from tickweaver.data.catalog import (  # noqa: E402
    format_catalog_table,
    format_inspect_report,
    inspect_file,
    list_processed,
)
from tickweaver.utils.paths import DATA_PROCESSED_DIR  # noqa: E402

app = typer.Typer(add_completion=False, help="tickweaver data inspector")


@app.command(name="list")
def list_cmd(
    root: Path | None = typer.Option(
        None, "--root", help="기본은 data/processed/. 다른 경로 명시 가능."
    ),
    json_out: bool = typer.Option(False, "--json", help="JSON 으로 출력"),
) -> None:
    """data/processed/ 안의 parquet 파일 인덱싱."""
    entries = list_processed(root or DATA_PROCESSED_DIR)
    if json_out:
        typer.echo(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2))
    else:
        typer.echo(format_catalog_table(entries))


@app.command(name="inspect")
def inspect_cmd(
    path: Path = typer.Argument(..., help="단일 parquet 경로"),
    json_out: bool = typer.Option(False, "--json", help="JSON 으로 출력"),
) -> None:
    """단일 parquet 의 스키마 + 무결성 + 결손 봉 리포트 (D13)."""
    rep = inspect_file(path)
    if json_out:
        typer.echo(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        typer.echo(format_inspect_report(rep))


if __name__ == "__main__":
    app()
