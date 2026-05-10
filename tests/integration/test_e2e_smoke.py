"""e2e 스모크 — 합성 OHLCV → 백테스트 → report.html 까지 굴러가는지 확인."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.ohlcv import make_synthetic_ohlcv
from tickweaver.data.loaders.parquet_loader import write_parquet
from tickweaver.engine.runner import run_backtest


def test_buy_and_hold_e2e_smoke(tmp_path: Path) -> None:
    # 1. 합성 OHLCV → parquet 저장
    df = make_synthetic_ohlcv(n_bars=300, seed=42)
    src = tmp_path / "synthetic.parquet"
    write_parquet(df, src)

    # 2. buy_and_hold 전략 경로
    project_root = Path(__file__).resolve().parents[2]
    strategy = project_root / "strategies" / "buy_and_hold.py"
    assert strategy.exists(), f"buy_and_hold.py not found at {strategy}"

    # 3. 백테스트 실행
    out_dir = tmp_path / "report_out"
    result = run_backtest(
        strategy_path=strategy,
        out_dir=out_dir,
        source=src,
        auto_period=True,
    )

    # 4. 산출물 확인
    assert (out_dir / "report.html").exists()
    assert (out_dir / "metrics.json").exists()
    assert (out_dir / "tick_summary.json").exists()
    assert (out_dir / "equity_curve.png").exists()
    assert (out_dir / "config_snapshot.json").exists()

    # 5. 결과 내용 sanity
    assert result.tick_summary.n_bars == 300
    assert result.tick_summary.n_ticks_total > 0
    # buy_and_hold 는 최소 1번 매수 발생해야 함
    assert len(result.fills) >= 1


def test_determinism_same_seed(tmp_path: Path) -> None:
    """같은 seed → 같은 final_equity (P3, C7)."""
    df = make_synthetic_ohlcv(n_bars=200, seed=7)
    src = tmp_path / "synthetic.parquet"
    write_parquet(df, src)

    project_root = Path(__file__).resolve().parents[2]
    strategy = project_root / "strategies" / "buy_and_hold.py"

    r1 = run_backtest(
        strategy_path=strategy,
        out_dir=tmp_path / "r1",
        source=src,
    )
    r2 = run_backtest(
        strategy_path=strategy,
        out_dir=tmp_path / "r2",
        source=src,
    )
    assert r1.final_equity == pytest.approx(r2.final_equity, rel=0, abs=1e-9)
