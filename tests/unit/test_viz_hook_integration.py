"""Phase 3 integration tests.

Validates that:
1. EventRecorder captures every event during a real backtest run.
2. V2 (determinism preservation): viz on/off must produce bit-exact same
   final_equity and same fills.
3. api.comment(text) propagates to chart_hook.on_comment.
4. api.comment(text) is a noop when chart_hook is None (V3).

데이터 주입: run_backtest 는 cfg.data 를 통해 CcxtLoader 로 OHLCV 를 로드한다.
테스트는 네트워크/디스크 fetch 를 피하려고 runner._load_data_from_config 를
monkeypatch 해서 합성 OHLCV + 고정 정밀도를 주입한다 (config 는 default.yaml).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.ohlcv import make_synthetic_ohlcv
from tickweaver.data.symbol_metadata import DEFAULT_PRECISION
from tickweaver.engine.runner import run_backtest
from tickweaver.viz import EventRecorder


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = PROJECT_ROOT / "configs" / "default.yaml"


class _StubLoader:
    """run_backtest 의 loader.get_symbol_precision 만 대체 (네트워크 차단)."""

    def get_symbol_precision(self, symbol: str):
        return DEFAULT_PRECISION


def _patch_data(monkeypatch, df) -> None:
    """runner._load_data_from_config 를 합성 df + stub loader 로 교체."""
    monkeypatch.setattr(
        "tickweaver.engine.runner._load_data_from_config",
        lambda cfg: (df, _StubLoader()),
    )


# ─────────────────────────────────────────────────────────
# (1) Recorder captures every event during a real backtest
# ─────────────────────────────────────────────────────────
def test_recorder_captures_during_real_backtest(tmp_path: Path, monkeypatch) -> None:
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=300, seed=42))
    strategy = PROJECT_ROOT / "strategies" / "buy_and_hold.py"

    rec = EventRecorder()
    res = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "out",
        show_progress=False,
        chart_hook=rec,
    )

    # n_bars captured
    assert rec.n_bars == 300
    # buy_and_hold should produce at least one fill
    assert rec.n_fills >= 1
    # init / deinit lifecycle reached
    assert rec._init_called
    assert rec._deinit_called
    # final_equity matches
    assert rec.final_equity == pytest.approx(res.final_equity, rel=0, abs=1e-9)


# ─────────────────────────────────────────────────────────
# (2) V2 — Determinism preservation
# ─────────────────────────────────────────────────────────
def test_viz_does_not_change_final_equity(tmp_path: Path, monkeypatch) -> None:
    """V2: chart_hook on/off must produce bit-exact same final_equity."""
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=200, seed=7))
    strategy = PROJECT_ROOT / "strategies" / "rsi_mean_reversion.py"

    res_no_viz = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "no_viz",
        show_progress=False,
        chart_hook=None,
    )
    res_with_recorder = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "with_recorder",
        show_progress=False,
        chart_hook=EventRecorder(),
    )

    assert res_no_viz.final_equity == pytest.approx(
        res_with_recorder.final_equity, rel=0, abs=1e-9
    )
    assert len(res_no_viz.fills) == len(res_with_recorder.fills)


def test_viz_does_not_change_fills(tmp_path: Path, monkeypatch) -> None:
    """V2: fill prices/qtys must be bit-exact regardless of chart_hook."""
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=300, seed=11))
    strategy = PROJECT_ROOT / "strategies" / "ema_cross.py"

    res_a = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "a",
        show_progress=False,
        chart_hook=None,
    )
    res_b = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "b",
        show_progress=False,
        chart_hook=EventRecorder(),
    )
    assert len(res_a.fills) == len(res_b.fills)
    for fa, fb in zip(res_a.fills, res_b.fills, strict=True):
        assert fa.price == pytest.approx(fb.price, rel=0, abs=1e-9)
        assert fa.qty == pytest.approx(fb.qty, rel=0, abs=1e-9)
        assert fa.side == fb.side


# ─────────────────────────────────────────────────────────
# (3) api.comment propagates to chart_hook.on_comment
# ─────────────────────────────────────────────────────────
def test_api_comment_propagates_to_recorder(tmp_path: Path, monkeypatch) -> None:
    sp = tmp_path / "comment_strategy.py"
    sp.write_text(
        "def on_bar(bar):\n"
        "    api.comment(f'price={bar.close:.2f}')\n",
        encoding="utf-8",
    )
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=20, seed=0))

    rec = EventRecorder()
    run_backtest(
        strategy_path=sp,
        config_path=_CONFIG,
        out_dir=tmp_path / "out",
        show_progress=False,
        chart_hook=rec,
    )

    # 20 bars -> 20 comment calls
    assert rec.n_comments == 20
    for c in rec.comments:
        assert c.text.startswith("price=")
        assert 0 <= c.bar_index < 20


def test_api_comment_includes_bar_index(tmp_path: Path, monkeypatch) -> None:
    sp = tmp_path / "bar_index_strategy.py"
    sp.write_text(
        "def on_bar(bar):\n"
        "    api.comment('hi')\n",
        encoding="utf-8",
    )
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=10, seed=0))

    rec = EventRecorder()
    run_backtest(
        strategy_path=sp,
        config_path=_CONFIG,
        out_dir=tmp_path / "out",
        show_progress=False,
        chart_hook=rec,
    )
    indices = [c.bar_index for c in rec.comments]
    assert indices == list(range(10))


# ─────────────────────────────────────────────────────────
# (4) V3 — api.comment is noop when chart_hook is None
# ─────────────────────────────────────────────────────────
def test_api_comment_noop_when_no_chart_hook(tmp_path: Path, monkeypatch) -> None:
    """V3: api.comment must not raise when chart_hook is None."""
    sp = tmp_path / "comment_strategy.py"
    sp.write_text(
        "def on_bar(bar):\n"
        "    api.comment('no viz')\n",
        encoding="utf-8",
    )
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=10, seed=0))

    # Without chart_hook - must not raise
    res = run_backtest(
        strategy_path=sp,
        config_path=_CONFIG,
        out_dir=tmp_path / "out",
        show_progress=False,
        chart_hook=None,
    )
    assert res.final_equity > 0  # Just sanity


# ─────────────────────────────────────────────────────────
# (5) Tick / fill counts in recorder match engine result
# ─────────────────────────────────────────────────────────
def test_recorder_fill_count_matches_result(tmp_path: Path, monkeypatch) -> None:
    _patch_data(monkeypatch, make_synthetic_ohlcv(n_bars=200, seed=99))
    strategy = PROJECT_ROOT / "strategies" / "rsi_mean_reversion.py"

    rec = EventRecorder()
    res = run_backtest(
        strategy_path=strategy,
        config_path=_CONFIG,
        out_dir=tmp_path / "out",
        show_progress=False,
        chart_hook=rec,
    )
    assert rec.n_fills == len(res.fills)
