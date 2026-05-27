"""e2e 스모크 — 합성 OHLCV → 백테스트 → report.html 까지 굴러가는지 확인.

run_backtest 는 cfg.data 를 통해 CcxtLoader 로 데이터를 받으므로, 네트워크
fetch 를 피하려고 runner._load_data_from_config 를 monkeypatch 해서 합성
OHLCV + 고정 정밀도를 주입한다 (config 는 default.yaml).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.ohlcv import make_synthetic_ohlcv
from tickweaver.data.symbol_metadata import DEFAULT_PRECISION
from tickweaver.engine.runner import run_backtest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = PROJECT_ROOT / "configs" / "default.yaml"


class _StubLoader:
    def get_symbol_precision(self, symbol: str):
        return DEFAULT_PRECISION


def _patch_data(monkeypatch, df) -> None:
    monkeypatch.setattr(
        "tickweaver.engine.runner._load_data_from_config",
        lambda cfg: (df, _StubLoader()),
    )


def test_buy_and_hold_e2e_smoke(tmp_path: Path, monkeypatch) -> None:
    # 1. 합성 OHLCV 를 loader 대신 주입
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=300, seed=42))

    # 2. buy_and_hold 전략 경로
    strategy = PROJECT_ROOT / "strategies" / "buy_and_hold.py"
    assert strategy.exists(), f"buy_and_hold.py not found at {strategy}"

    # 3. 백테스트 실행
    out_dir = tmp_path / "report_out"
    result = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=out_dir,
        show_progress=False,
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


def test_determinism_same_seed(tmp_path: Path, monkeypatch) -> None:
    """같은 seed → 같은 final_equity (P3, C7)."""
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=200, seed=7))

    strategy = PROJECT_ROOT / "strategies" / "buy_and_hold.py"

    r1 = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "r1",
        show_progress=False,
    )
    r2 = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "r2",
        show_progress=False,
    )
    assert r1.final_equity == pytest.approx(r2.final_equity, rel=0, abs=1e-9)
