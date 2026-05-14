"""Phase 3 (dev/adv_verbose) — StrategyAPI indicator binding + plot + engine sampling.

Pure unit tests against StrategyAPI: no real backtest, just a recorder hook
to assert what the API emits.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage
from tickweaver.strategy.api import StrategyAPI
from tickweaver.strategy.indicators import EMA, RSI, ATR, MACD, BollingerBands
from tickweaver.viz.events import (
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
)
from tickweaver.viz.hook import NullHook


def _broker() -> BacktestBroker:
    return BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
    )


class _Collector(NullHook):
    """Captures register/sample events without any other side effect."""

    def __init__(self) -> None:
        self.registrations: list[IndicatorRegistrationEvent] = []
        self.samples: list[IndicatorSampleEvent] = []

    def on_indicator_register(self, registration: IndicatorRegistrationEvent) -> None:
        self.registrations.append(registration)

    def on_indicator_sample(self, sample: IndicatorSampleEvent) -> None:
        self.samples.append(sample)


def _api(chart_hook=None) -> StrategyAPI:
    return StrategyAPI(
        broker=_broker(),
        symbol="T",
        console_log=False,
        chart_hook=chart_hook,
    )


# ─────────────────────────────────────────────────────────
# bind_indicator
# ─────────────────────────────────────────────────────────
def test_bind_indicator_noop_when_chart_hook_is_none():
    """No chart_hook -> no raise, no events. Strategy code stays valid."""
    api = _api(chart_hook=None)
    api.bind_indicator("EMA20", EMA(period=20))


def test_bind_indicator_emits_registration_with_default_panel():
    c = _Collector()
    api = _api(chart_hook=c)
    api.bind_indicator("EMA20", EMA(period=20))
    assert len(c.registrations) == 1
    assert c.registrations[0].name == "EMA20"
    assert c.registrations[0].panel == "price"  # EMA.PANEL
    assert c.registrations[0].style == {}


def test_bind_indicator_uses_rsi_panel():
    c = _Collector()
    api = _api(chart_hook=c)
    api.bind_indicator("RSI", RSI(period=14))
    assert c.registrations[0].panel == "rsi"


def test_bind_indicator_panel_override():
    c = _Collector()
    api = _api(chart_hook=c)
    api.bind_indicator("EMA20", EMA(period=20), panel="custom_panel")
    assert c.registrations[0].panel == "custom_panel"


def test_bind_indicator_style_kwargs_pass_through():
    c = _Collector()
    api = _api(chart_hook=c)
    api.bind_indicator("EMA20", EMA(period=20), color="#FF9800", width=2)
    assert c.registrations[0].style == {"color": "#FF9800", "width": 2}


def test_bind_indicator_bollinger_decomposes_into_three_subs():
    c = _Collector()
    api = _api(chart_hook=c)
    api.bind_indicator("BB", BollingerBands(period=20))
    names = [r.name for r in c.registrations]
    assert names == ["BB.middle", "BB.upper", "BB.lower"]
    # All sub-lines share parent panel.
    assert all(r.panel == "price" for r in c.registrations)


def test_bind_indicator_macd_decomposes_into_three_subs():
    c = _Collector()
    api = _api(chart_hook=c)
    api.bind_indicator("MACD", MACD())
    names = [r.name for r in c.registrations]
    assert names == ["MACD.macd", "MACD.signal", "MACD.histogram"]
    assert all(r.panel == "macd" for r in c.registrations)


# ─────────────────────────────────────────────────────────
# plot — low-level fallback
# ─────────────────────────────────────────────────────────
def test_plot_noop_when_chart_hook_is_none():
    api = _api(chart_hook=None)
    api._set_bar_context(0, pd.Timestamp("2024-01-01", tz="UTC"))
    api.plot("signal", 1.0)


def test_plot_first_call_registers_and_samples():
    c = _Collector()
    api = _api(chart_hook=c)
    api._set_bar_context(3, pd.Timestamp("2024-01-01 03:00", tz="UTC"))
    api.plot("signal", 42.0, panel="custom", color="#00F")
    assert len(c.registrations) == 1
    assert c.registrations[0].name == "signal"
    assert c.registrations[0].panel == "custom"
    assert c.registrations[0].style == {"color": "#00F"}
    assert len(c.samples) == 1
    assert c.samples[0].name == "signal"
    assert c.samples[0].bar_index == 3
    assert c.samples[0].value == 42.0


def test_plot_subsequent_calls_only_sample():
    c = _Collector()
    api = _api(chart_hook=c)
    api._set_bar_context(0, None)
    api.plot("signal", 1.0)
    api._set_bar_context(1, None)
    api.plot("signal", 2.0)
    api._set_bar_context(2, None)
    api.plot("signal", 3.0)
    assert len(c.registrations) == 1  # registered once
    assert [s.value for s in c.samples] == [1.0, 2.0, 3.0]


# ─────────────────────────────────────────────────────────
# _sample_indicators — engine integration entry point
# ─────────────────────────────────────────────────────────
def test_sample_indicators_noop_when_chart_hook_is_none():
    api = _api(chart_hook=None)
    api.bind_indicator("EMA20", EMA(period=20))  # safe noop
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))


def test_sample_indicators_skips_when_indicator_not_warm():
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=20)  # not warm yet
    api.bind_indicator("EMA20", ema)
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    # registration fired during bind; no sample because .value is None.
    assert len(c.samples) == 0


def test_sample_indicators_single_value_emits_value():
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=3)
    for v in [10.0, 11.0, 12.0]:  # warm now
        ema.update(v)
    api.bind_indicator("EMA3", ema)
    api._sample_indicators(5, pd.Timestamp("2024-01-01 05:00", tz="UTC"))
    assert len(c.samples) == 1
    assert c.samples[0].name == "EMA3"
    assert c.samples[0].bar_index == 5
    assert c.samples[0].value == ema.value


def test_sample_indicators_bollinger_emits_three_samples():
    c = _Collector()
    api = _api(chart_hook=c)
    bb = BollingerBands(period=3, mult=2.0)
    for v in [10.0, 11.0, 12.0]:  # warm
        bb.update(v)
    api.bind_indicator("BB", bb)
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    by_name = {s.name: s.value for s in c.samples}
    assert by_name["BB.middle"] == bb.middle
    assert by_name["BB.upper"] == bb.upper
    assert by_name["BB.lower"] == bb.lower


def test_sample_indicators_macd_emits_three_samples():
    c = _Collector()
    api = _api(chart_hook=c)
    m = MACD(fast=3, slow=5, signal=2)
    for v in [10.0, 11.0, 12.0, 11.5, 11.8, 12.5, 13.0, 12.7]:
        m.update(v)
    api.bind_indicator("MACD", m)
    api._sample_indicators(7, pd.Timestamp("2024-01-01 07:00", tz="UTC"))
    by_name = {s.name: s.value for s in c.samples}
    assert by_name["MACD.macd"] == m.macd
    assert by_name["MACD.signal"] == m.signal
    assert by_name["MACD.histogram"] == m.histogram


def test_sample_indicators_called_repeatedly_appends_samples():
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=2)
    api.bind_indicator("EMA2", ema)
    ema.update(10.0)
    ema.update(11.0)  # warm: value = 10.5
    api._sample_indicators(0, pd.Timestamp("2024-01-01 00:00", tz="UTC"))
    ema.update(12.0)
    api._sample_indicators(1, pd.Timestamp("2024-01-01 01:00", tz="UTC"))
    assert len(c.samples) == 2
    assert c.samples[0].bar_index == 0
    assert c.samples[1].bar_index == 1
