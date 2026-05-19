"""Phase F4.4 — engine must call strategy.on_fill after each broker fill."""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.ohlcv import make_synthetic_ohlcv
from tickweaver.core.types import StrategyContext
from tickweaver.engine.backtest_engine import BacktestEngine
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage
from tickweaver.strategy.api import StrategyAPI
from tickweaver.strategy.file_strategy import FileStrategy
from tickweaver.tick_synthesis.generator import get_tick_generator
from tickweaver.utils.seed import SeedManager


def _make_engine(strategy_path: Path, *, mode: str = "futures"):
    df = make_synthetic_ohlcv(n_bars=60, seed=7)
    broker = BacktestBroker(
        symbol="SYNTH",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
        mode=mode,
    )
    api = StrategyAPI(broker=broker, symbol="SYNTH", console_log=False)
    strategy = FileStrategy(strategy_path)
    context = StrategyContext(symbol="SYNTH", timeframe="1h", market_type="swap")
    engine = BacktestEngine(
        df=df,
        broker=broker,
        strategy=strategy,
        api=api,
        context=context,
        generator=get_tick_generator("uniform"),
        seed_manager=SeedManager(root=42),
        n_min=4,
        n_max=8,
        dump_ticks=0,
        show_progress=False,
        chart_hook=None,
    )
    return engine, strategy


def test_strategy_on_fill_is_called_for_each_fill(tmp_path: Path):
    """A strategy that increments a counter inside on_fill must end the run
    with counter == number of fills produced by the broker."""
    sp = tmp_path / "probe_on_fill.py"
    sp.write_text(
        '''
fills_seen = 0


def on_init():
    global fills_seen
    fills_seen = 0


def on_bar(bar):
    if api.is_flat():
        qty = api.size_from_cash_pct(0.1, bar.close)
        if qty > 0:
            api.market_buy(qty)


def on_fill(fill):
    global fills_seen
    fills_seen += 1
''',
        encoding="utf-8",
    )

    engine, strategy = _make_engine(sp)
    result = engine.run()

    fills_seen = getattr(strategy._module, "fills_seen", None)
    assert fills_seen is not None, "strategy module was not loaded"
    assert fills_seen == len(result.fills), (
        f"strategy.on_fill called {fills_seen} times but "
        f"{len(result.fills)} fills happened"
    )


def test_strategy_on_fill_runs_before_strategy_on_tick(tmp_path: Path):
    """Order check: on_fill should run during broker.on_market_event so that
    on_tick can act on phase changes from on_fill within the same tick."""
    sp = tmp_path / "probe_order.py"
    sp.write_text(
        '''
events = []
fired = False


def on_init():
    global events, fired
    events = []
    fired = False


def on_bar(bar):
    global fired
    if not fired and api.is_flat():
        qty = api.size_from_cash_pct(0.1, bar.close)
        if qty > 0:
            api.market_buy(qty)
            fired = True


def on_fill(fill):
    events.append(("fill", fill.qty))


def on_tick(tick):
    if len(events) < 20:
        events.append(("tick", float(tick.price)))
''',
        encoding="utf-8",
    )

    engine, strategy = _make_engine(sp)
    engine.run()
    events = getattr(strategy._module, "events", [])
    # Must have at least one fill event somewhere in the stream.
    kinds = [e[0] for e in events]
    assert "fill" in kinds
    # And the fill must come BEFORE the very next tick event (i.e. a fill
    # is observed before any tick following it).
    first_fill_idx = kinds.index("fill")
    # at this index 'fill', the next entry must be 'tick' (engine processes
    # fills inside broker.on_market_event then strategy.on_tick).
    if first_fill_idx + 1 < len(events):
        assert kinds[first_fill_idx + 1] == "tick"
