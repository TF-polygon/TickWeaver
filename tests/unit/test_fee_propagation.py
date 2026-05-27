"""Fee rate propagation (Polish Work A).

yaml 입력값 `cfg.execution.commission` (percent) 이 `fee_bps` property (×100) →
`BpsFeeModel` → broker 의 `fill.fee` 까지 정확히 전달되는지 end-to-end 검증.

거래소별 다른 commission 은 사용자가 yaml 을 거래소별로 관리 (configs/binance.yaml
vs configs/bybit.yaml). 같은 데이터/전략을 두 config 로 돌려 fill.fee 가 commission
에 비례하는지 본다. 네트워크/디스크 fetch 는 `_load_data_from_config` monkeypatch
로 차단 (합성 OHLCV + DEFAULT 정밀도).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.ohlcv import make_synthetic_ohlcv
from tickweaver.data.symbol_metadata import DEFAULT_PRECISION
from tickweaver.engine.runner import run_backtest
from tickweaver.viz import EventRecorder


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STRATEGY = PROJECT_ROOT / "strategies" / "buy_and_hold.py"


class _StubLoader:
    """run_backtest 의 loader.get_symbol_precision 만 대체 (네트워크 차단)."""

    def get_symbol_precision(self, symbol: str):
        return DEFAULT_PRECISION


@pytest.fixture
def patched_data(monkeypatch):
    df = make_synthetic_ohlcv(n_bars=300, seed=1)
    monkeypatch.setattr(
        "tickweaver.engine.runner._load_data_from_config",
        lambda cfg: (df, _StubLoader()),
    )
    return df


def _run(config_name: str, out: Path) -> EventRecorder:
    rec = EventRecorder()
    run_backtest(
        strategy_path=_STRATEGY,
        config_path=PROJECT_ROOT / "configs" / config_name,
        out_dir=out,
        show_progress=False,
        chart_hook=rec,
    )
    return rec


@pytest.mark.parametrize(
    "config_name,commission",
    [("binance.yaml", 0.05), ("bybit.yaml", 0.06)],
)
def test_yaml_commission_propagates_to_fill_fee(
    patched_data, tmp_path, config_name, commission
):
    """fill.fee == exec_price * qty * commission/100 (첫 fill spot-check)."""
    rec = _run(config_name, tmp_path / "out")
    assert rec.n_fills >= 1
    f = rec.fills[0]
    expected = abs(f.price * f.qty) * (commission / 100.0)
    assert f.fee == pytest.approx(expected), (
        f"{config_name}: fill.fee={f.fee} != price*qty*comm={expected}"
    )


def test_fee_scales_with_commission(patched_data, tmp_path):
    """동일 데이터/전략, commission 만 다른 두 config → 첫 fill fee 가 비례."""
    f_binance = _run("binance.yaml", tmp_path / "b").fills[0]
    f_bybit = _run("bybit.yaml", tmp_path / "by").fills[0]
    # 같은 데이터/seed → 같은 exec_price/qty, fee 만 commission 비율로 차이
    assert f_bybit.fee == pytest.approx(f_binance.fee * (0.06 / 0.05))


def test_execution_section_commission_to_fee_bps():
    """ExecutionSection.commission (percent) → fee_bps property (×100)."""
    from tickweaver.execution.fees import BpsFeeModel
    from tickweaver.utils.config import ExecutionSection

    for commission, expected_bps in [(0.05, 5.0), (0.02, 2.0), (0.1, 10.0), (0.0, 0.0)]:
        sec = ExecutionSection(commission=commission)
        assert sec.fee_bps == pytest.approx(expected_bps)
        # BpsFeeModel(fee_bps).fee(100, 1) == price*qty*commission/100
        fee = BpsFeeModel(sec.fee_bps).fee(100.0, 1.0)
        assert fee == pytest.approx(100.0 * commission / 100.0)
