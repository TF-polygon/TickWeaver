"""P5 — MetricPanel headless smoke (Qt offscreen, pytest-qt qtbot).

`src/tickweaver/viz/metric_panel.py` 의 KPI strip 위젯이 update/clear/toggle
경로에서 정상 동작하는지 widget 단위 가드. memory `finplot_streaming_gotcha`
의 offscreen 패턴 — pytest-qt 가 자동으로 QApplication 을 헤드리스로 띄워주므로
QT_QPA_PLATFORM=offscreen 환경 변수에 의존하지 않아도 CI/로컬 양쪽 동작.

검증 항목 (계획 §7.C step 4 + 사용자 검수 #13 추가):
1. full metrics dict → 10 카드 모두 채워짐 + label/format/sign_hint 적용
2. None / {} / 누락 키 → "—" graceful
3. `trade_only_metrics` (equity-curve 없는 fallback path) → 5 카드 채움 +
   4 equity-derived 카드 "—" graceful
4. setVisible 토글 — show/hide 상태 반영
5. clear() — 전체 "—" / neutral 복귀
6. 결정성 가드: 동일 metrics 두 번 update → text/style 완전 동일 (panel 이
   숨겨진 부수효과 없음)
7. **#13-a — 동적 폰트 스케일링**: width 600/1280/1920/3200/3840 에서 라벨/값
   폰트 pt 가 reference 1920 기준 비례 + clamp [8, 16] 동작
8. **#13-a — elide + tooltip**: 카드가 좁아서 값이 안 들어가면 ElideRight
   적용 + tooltip 에 원본 raw text 보존
9. **#13-b — static layout 3-row vertical splitter**: `_attach_description_pane`
   + MetricPanel 삽입 후 children = [chart, MetricPanel, bottom] 순서/타입 가드
10. **#13-c — checkable title 토글 (D4)**: setChecked(False) → row 컨테이너
    숨김, setChecked(True) → 표시. 토글이 카드 데이터 변경 안 함.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from tickweaver.analytics.metric_formatting import format_metric, sign_hint
from tickweaver.analytics.trades import Trade
from tickweaver.core.types import Side

# pyqtgraph.Qt 가 import 안 되는 환경은 전체 모듈 skip (test_position_table 패턴).
try:
    from tickweaver.viz.metric_panel import (
        MetricPanel,
        _DISPLAY_KEYS,
        trade_only_metrics,
    )
    _HAS_QT = True
except Exception:
    _HAS_QT = False


pytestmark = pytest.mark.skipif(
    not _HAS_QT, reason="PyQt6 / pyqtgraph.Qt not available"
)


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────
def _full_metrics() -> dict:
    """compute_metrics 가 리턴하는 형태의 full dict (HTML 리포트와 동일 키셋).

    initial_cash 는 _DISPLAY_KEYS 에 없어서 카드에 표시 안 됨 — 일부러 포함시켜
    update_from_metrics 가 미사용 키 무시하는지 부수 가드.
    """
    return {
        "final_equity": 12340.5,
        "initial_cash": 10000.0,
        "total_return": 0.2341,
        "cagr": 0.182,
        "sharpe": 1.85,
        "sortino": 2.31,
        "max_drawdown": -0.0834,
        "calmar": 1.42,
        "n_trades": 47,
        "win_rate": 0.617,
        "profit_factor": 1.78,
    }


def _trade(pnl: float, side: Side = Side.BUY) -> Trade:
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    return Trade(
        entry_ts=ts,
        exit_ts=ts + pd.Timedelta(hours=1),
        side=side,
        qty=1.0,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        fee=0.0,
        pnl=pnl,
        first_entry_price=100.0,
    )


def _card_texts(panel) -> dict[str, str]:
    return {k: panel._cards[k].text() for k in _DISPLAY_KEYS}


# ─────────────────────────────────────────────────────────
# 1) 생성 + full update
# ─────────────────────────────────────────────────────────
def test_metric_panel_constructs_with_all_cards_at_dash(qtbot) -> None:
    """초기 상태: 10 카드 전부 '—', 라벨 미설정 시 neutral 색상."""
    p = MetricPanel()
    qtbot.addWidget(p)
    texts = _card_texts(p)
    assert set(texts.keys()) == set(_DISPLAY_KEYS)
    assert all(v == "—" for v in texts.values()), texts


def test_metric_panel_update_from_full_metrics_fills_all_ten_cards(qtbot) -> None:
    """compute_metrics full dict → 10 카드 모두 채워짐 + format_metric 결과 동일."""
    p = MetricPanel()
    qtbot.addWidget(p)
    metrics = _full_metrics()
    p.update_from_metrics(metrics)

    texts = _card_texts(p)
    for key in _DISPLAY_KEYS:
        expected = format_metric(key, metrics[key])
        assert texts[key] == expected, f"{key}: {texts[key]!r} vs {expected!r}"
    # initial_cash 는 _DISPLAY_KEYS 에 없으므로 카드 자체가 없다 — KeyError 안 남.
    assert "initial_cash" not in texts


def test_metric_panel_applies_sign_hint_styles(qtbot) -> None:
    """sign_hint 가 pos/neg/neutral 일 때 stylesheet 가 각기 다른 색을 쓴다."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())

    # total_return = +0.2341 → pos (green)
    pos_style = p._cards["total_return"].styleSheet()
    # max_drawdown = -0.0834 → neg (red)
    neg_style = p._cards["max_drawdown"].styleSheet()
    # final_equity → neutral
    neutral_style = p._cards["final_equity"].styleSheet()

    assert pos_style != neg_style
    assert pos_style != neutral_style
    assert neg_style != neutral_style
    # sign_hint contract sanity (도메인 회귀)
    assert sign_hint("total_return", 0.2341) == "pos"
    assert sign_hint("max_drawdown", -0.0834) == "neg"
    assert sign_hint("final_equity", 12340.5) == "neutral"


# ─────────────────────────────────────────────────────────
# 2) Graceful — None / empty / 누락 키
# ─────────────────────────────────────────────────────────
def test_metric_panel_update_with_none_renders_all_dashes(qtbot) -> None:
    """update_from_metrics(None) — 전 카드 '—'."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())  # 먼저 채워두고
    p.update_from_metrics(None)
    assert all(v == "—" for v in _card_texts(p).values())


def test_metric_panel_update_with_empty_dict_renders_all_dashes(qtbot) -> None:
    """update_from_metrics({}) — 전 카드 '—' (None 과 동일 동작)."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())
    p.update_from_metrics({})
    assert all(v == "—" for v in _card_texts(p).values())


def test_metric_panel_missing_keys_render_dash_others_render_value(qtbot) -> None:
    """부분 dict: 있는 키만 채우고 나머지 '—'."""
    p = MetricPanel()
    qtbot.addWidget(p)
    partial = {"final_equity": 10_500.0, "total_return": 0.05}
    p.update_from_metrics(partial)

    texts = _card_texts(p)
    assert texts["final_equity"] == format_metric("final_equity", 10_500.0)
    assert texts["total_return"] == format_metric("total_return", 0.05)
    # 나머지 8 키는 미입력이므로 "—".
    other_keys = [k for k in _DISPLAY_KEYS if k not in partial]
    for k in other_keys:
        assert texts[k] == "—", f"{k} expected dash, got {texts[k]!r}"


# ─────────────────────────────────────────────────────────
# 3) trade_only_metrics — equity-curve 없는 fallback path
# ─────────────────────────────────────────────────────────
def test_trade_only_metrics_returns_five_keys_no_equity_derived() -> None:
    """trade_only_metrics 의 키셋 — sharpe/sortino/MDD/calmar 의도적 누락."""
    trades = [_trade(+50.0), _trade(-20.0), _trade(+30.0)]
    out = trade_only_metrics(trades, initial_cash=10_000.0, final_equity=10_060.0)
    assert set(out.keys()) == {
        "final_equity",
        "total_return",
        "n_trades",
        "win_rate",
        "profit_factor",
    }
    # 의도적 누락 — viz 패널에서 "—" 로 보여야 사용자가 '값 0' 으로 오해 안 함.
    for missing in ("sharpe", "sortino", "max_drawdown", "calmar", "cagr"):
        assert missing not in out


def test_metric_panel_renders_trade_only_fallback_with_dashes(qtbot) -> None:
    """fallback dict 입력 → 5 카드 채움 + sharpe/sortino/MDD/calmar/cagr '—'."""
    p = MetricPanel()
    qtbot.addWidget(p)
    trades = [_trade(+50.0), _trade(-20.0), _trade(+30.0)]
    fallback = trade_only_metrics(trades, initial_cash=10_000.0, final_equity=10_060.0)
    p.update_from_metrics(fallback)

    texts = _card_texts(p)
    # 채워진 5 키
    for k in ("final_equity", "total_return", "n_trades", "win_rate", "profit_factor"):
        assert texts[k] == format_metric(k, fallback[k]), f"{k}: {texts[k]!r}"
    # equity-derived 5 키 (cagr 포함) — 모두 "—"
    for k in ("cagr", "sharpe", "sortino", "max_drawdown", "calmar"):
        assert texts[k] == "—", f"{k} expected dash, got {texts[k]!r}"


def test_trade_only_metrics_zero_trades_safe() -> None:
    """edge — trades=[] 도 안전, profit_factor=0, win_rate=0."""
    out = trade_only_metrics([], initial_cash=10_000.0, final_equity=10_000.0)
    assert out["n_trades"] == 0
    assert out["win_rate"] == 0.0
    assert out["profit_factor"] == 0.0
    assert out["total_return"] == 0.0


def test_trade_only_metrics_all_winning_infinite_pf() -> None:
    """모두 winning — profit_factor=inf, format_metric 가 'inf' 로 표시."""
    trades = [_trade(+10.0), _trade(+20.0)]
    out = trade_only_metrics(trades, initial_cash=1_000.0, final_equity=1_030.0)
    assert out["profit_factor"] == float("inf")
    assert format_metric("profit_factor", out["profit_factor"]) == "inf"


# ─────────────────────────────────────────────────────────
# 4) Visibility toggle — show/hide
# ─────────────────────────────────────────────────────────
def test_metric_panel_visibility_toggle(qtbot) -> None:
    """setVisible(False) → isVisible() False, 다시 True 면 True."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.show()                # qtbot 환경에선 명시 show 필요
    qtbot.waitExposed(p)
    assert p.isVisible() is True

    p.setVisible(False)
    assert p.isVisible() is False

    p.setVisible(True)
    assert p.isVisible() is True


def test_metric_panel_hidden_state_does_not_affect_data(qtbot) -> None:
    """visibility 토글이 카드 텍스트/스타일에 부수효과 없음 (CP2 — viz on/off
    가 final_equity 안 바꿈, 위젯 단위로 가드)."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())
    before_texts = _card_texts(p)
    before_styles = {k: p._cards[k].styleSheet() for k in _DISPLAY_KEYS}

    p.setVisible(False)
    p.setVisible(True)

    assert _card_texts(p) == before_texts
    assert {k: p._cards[k].styleSheet() for k in _DISPLAY_KEYS} == before_styles


# ─────────────────────────────────────────────────────────
# 5) clear() — 명시 reset
# ─────────────────────────────────────────────────────────
def test_metric_panel_clear_resets_all_cards(qtbot) -> None:
    """clear() — 모든 카드 '—' + neutral style 로 복귀."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())
    assert _card_texts(p)["final_equity"] != "—"  # 채워졌는지 확인 먼저

    p.clear()
    assert all(v == "—" for v in _card_texts(p).values())
    # neutral 스타일이 일관 적용됐는지 — initial("—" 상태) 와 동일
    neutral_initial = MetricPanel()
    qtbot.addWidget(neutral_initial)
    for k in _DISPLAY_KEYS:
        assert (
            p._cards[k].styleSheet() == neutral_initial._cards[k].styleSheet()
        ), f"{k} style not reset"


# ─────────────────────────────────────────────────────────
# 6) 결정성 — 동일 입력 두 번 → 완전 동일 출력
# ─────────────────────────────────────────────────────────
def test_metric_panel_idempotent_update(qtbot) -> None:
    """같은 dict 두 번 적용 → text/style 완전 동일 (hidden state 없음)."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())
    t1 = _card_texts(p)
    s1 = {k: p._cards[k].styleSheet() for k in _DISPLAY_KEYS}

    p.update_from_metrics(_full_metrics())
    t2 = _card_texts(p)
    s2 = {k: p._cards[k].styleSheet() for k in _DISPLAY_KEYS}

    assert t1 == t2
    assert s1 == s2


# ─────────────────────────────────────────────────────────
# 7) #13-a — 동적 폰트 스케일 (reference 1920, clamp [8, 16])
# ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "width,exp_label_pt,exp_value_pt",
    [
        (600, 8, 8),     # MIN clamp 양쪽 다 적중 (9*0.31→3, 12*0.31→4)
        (1280, 8, 8),    # 12 * 1280/1920 = 8.0 → 8 (label 9*0.667=6→8 clamp)
        (1920, 9, 12),   # reference — base 그대로
        (3200, 15, 16),  # label 9*1.667=15 (no clamp), value 12*1.667=20→16 ceil
        (3840, 16, 16),  # 양쪽 다 MAX clamp 적중
    ],
)
def test_metric_panel_resize_scales_fonts_within_clamp(
    qtbot, width: int, exp_label_pt: int, exp_value_pt: int
) -> None:
    """`scale = width()/1920`, pt = round(base*scale), clamp [8, 16]."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.resize(width, 80)
    # show 없이도 _rescale() 은 self.width() 를 신뢰하므로 직접 호출.
    p._rescale()
    for key in _DISPLAY_KEYS:
        state = p._card_state[key]
        assert state["label"].font().pointSize() == exp_label_pt, key
        assert state["value"].font().pointSize() == exp_value_pt, key


def test_metric_panel_resize_elides_long_value_with_tooltip(qtbot) -> None:
    """좁은 카드 폭에서 긴 값은 ElideRight + tooltip 에 raw text 보존.

    show + waitExposed 로 실제 layout 을 강제해 card.width() 가 elide 함수에
    의미 있는 값이 되도록 한다 (offscreen 플랫폼에서도 동작).
    """
    p = MetricPanel()
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    p.update_from_metrics({"final_equity": 12_345_678.9012})
    p.resize(600, 80)  # 매우 좁은 폭 — 각 카드 ~54px
    qtbot.wait(0)

    state = p._card_state["final_equity"]
    raw = state["value_text"]
    rendered = state["value"].text()
    tooltip = state["value"].toolTip()

    assert raw == format_metric("final_equity", 12_345_678.9012)
    # 좁은 카드에 너무 길어서 elide 발생 — 렌더링된 텍스트는 raw 보다 짧다.
    assert len(rendered) < len(raw), f"expected elide, got rendered={rendered!r}"
    assert rendered.endswith("…")  # Qt ElideRight 의 ellipsis
    # tooltip 은 원본 raw 보존 (사용자가 hover 로 정밀값 확인 가능).
    assert tooltip == raw


def test_metric_panel_resize_wide_restores_raw_text_when_room(qtbot) -> None:
    """좁아서 elide 됐어도, 다시 넓혀지면 raw text 가 카드에 풀려 나온다."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    p.update_from_metrics({"final_equity": 12_345_678.9012})

    p.resize(600, 80)
    qtbot.wait(0)
    elided_text = p._card_state["final_equity"]["value"].text()
    assert elided_text.endswith("…")  # 사전 조건 — elide 발생

    p.resize(3200, 80)
    qtbot.wait(0)
    wide_text = p._card_state["final_equity"]["value"].text()
    raw = p._card_state["final_equity"]["value_text"]
    assert wide_text == raw
    assert p._card_state["final_equity"]["value"].toolTip() == ""


# ─────────────────────────────────────────────────────────
# 8) #13-b — static layout 3-row vertical splitter
# ─────────────────────────────────────────────────────────
def test_static_layout_three_row_vertical_splitter(qtbot) -> None:
    """`_attach_description_pane` + show_replay 의 MetricPanel insertWidget(1) 후
    splitter children 이 [chart, MetricPanel, bottom_pane] 순서/타입으로 잡힌다.

    show_replay 자체는 finplot/recorder 필요 — 본 테스트는 그 함수가 의존하는
    splitter 조립 contract 만 가드. mock fplt 로 _attach_description_pane 호출.
    """
    from pyqtgraph.Qt import QtCore, QtWidgets

    from tickweaver.viz.live_window import _attach_description_pane

    chart = QtWidgets.QWidget()
    qtbot.addWidget(chart)
    # fplt.windows 는 list 여야 함 (.remove 호출됨). chart 는 reparent 가능한 QWidget.
    fake_fplt = SimpleNamespace(windows=[chart])

    wrapper, app = _attach_description_pane(fake_fplt, "<p>test</p>", table_widget=None)
    assert wrapper is not None, "wrapper build failed"
    qtbot.addWidget(wrapper)

    splitter = wrapper._main_splitter
    assert splitter.orientation() == QtCore.Qt.Orientation.Vertical
    # 초기엔 2 children: chart + desc
    assert splitter.count() == 2
    assert splitter.widget(0) is chart

    # show_replay 가 하는 것과 동일하게 MetricPanel 을 index 1 로 삽입.
    metric_panel = MetricPanel()
    qtbot.addWidget(metric_panel)
    splitter.insertWidget(1, metric_panel)

    # 검증: 3-row vertical, 순서 = [chart, MetricPanel, desc-or-bottom]
    assert splitter.count() == 3
    assert splitter.orientation() == QtCore.Qt.Orientation.Vertical
    assert splitter.widget(0) is chart
    assert splitter.widget(1) is metric_panel
    # 자식 2 는 desc QTextEdit 또는 bottom QSplitter — 정확한 타입은 인터널이지만
    # MetricPanel 이 *아닌* 다른 위젯이어야 한다 (회귀 가드).
    assert splitter.widget(2) is not metric_panel
    assert splitter.widget(2) is not chart


# ─────────────────────────────────────────────────────────
# 9) #13-c — checkable title 토글 (D4)
# ─────────────────────────────────────────────────────────
def test_metric_panel_is_checkable_with_initial_checked(qtbot) -> None:
    """D4 — title 이 체크박스. 기본 ON."""
    p = MetricPanel()
    qtbot.addWidget(p)
    assert p.isCheckable() is True
    assert p.isChecked() is True


def test_metric_panel_uncheck_collapses_row_widget(qtbot) -> None:
    """setChecked(False) → _row_widget 명시적 hide. 다시 True 면 표시."""
    p = MetricPanel()
    qtbot.addWidget(p)
    # 초기 — row 위젯은 명시적으로 숨겨지지 않은 상태.
    assert p._row_widget is not None
    assert p._row_widget.isHidden() is False

    p.setChecked(False)
    assert p._row_widget.isHidden() is True

    p.setChecked(True)
    assert p._row_widget.isHidden() is False


def test_metric_panel_checked_toggle_preserves_card_data(qtbot) -> None:
    """check off → on 사이클이 카드 텍스트/스타일/raw 캐시 부수효과 없음."""
    p = MetricPanel()
    qtbot.addWidget(p)
    p.update_from_metrics(_full_metrics())
    before_texts = {k: p._card_state[k]["value_text"] for k in _DISPLAY_KEYS}
    before_hints = {k: p._card_state[k]["hint"] for k in _DISPLAY_KEYS}

    p.setChecked(False)
    p.setChecked(True)

    after_texts = {k: p._card_state[k]["value_text"] for k in _DISPLAY_KEYS}
    after_hints = {k: p._card_state[k]["hint"] for k in _DISPLAY_KEYS}
    assert after_texts == before_texts
    assert after_hints == before_hints


# ─────────────────────────────────────────────────────────
# 10) #15 — streaming wrapper layout (#14 v2 채택 구조)
# ─────────────────────────────────────────────────────────
# 메인 vertical splitter (static viz 와 동일한 3-row shape, 2 handles):
#   [0] chart_widget
#   [1] MetricPanel  (Maximum vertical policy)
#   [2] lower QWidget
#        └ QVBoxLayout:
#            [0] bottom QWidget
#                 └ QHBoxLayout → QSplitter horizontal [table | curve_box]
#            [1] controls (Fixed height, footer)


def _streaming_wrapper(qtbot):
    """Helper — `_wrap_streaming_window` 를 mock fplt 로 invoke 해 wrapper 반환.

    실제 finplot 없이 splitter assembly contract 만 가드. 모든 자식 widget 은
    qtbot 에 등록되어 teardown 안전.
    """
    from pyqtgraph.Qt import QtCore, QtWidgets

    from tickweaver.viz.streaming_window import _wrap_streaming_window

    chart = QtWidgets.QWidget()
    controls = QtWidgets.QWidget()
    table_widget = QtWidgets.QWidget()
    curve_box = QtWidgets.QWidget()
    qtbot.addWidget(chart)
    qtbot.addWidget(controls)
    qtbot.addWidget(table_widget)
    qtbot.addWidget(curve_box)

    metric_panel = MetricPanel()
    qtbot.addWidget(metric_panel)

    fake_fplt = SimpleNamespace(windows=[chart], refresh=lambda: None)

    wrapper, app = _wrap_streaming_window(
        fake_fplt, QtWidgets, QtCore, controls, table_widget,
        metric_panel, curve_box, 240, "test stream",
    )
    assert wrapper is not None, "streaming wrapper build failed"
    qtbot.addWidget(wrapper)
    return {
        "wrapper": wrapper,
        "chart": chart,
        "controls": controls,
        "table_widget": table_widget,
        "curve_box": curve_box,
        "metric_panel": metric_panel,
        "QtWidgets": QtWidgets,
        "QtCore": QtCore,
    }


def test_streaming_main_splitter_is_vertical_with_chart_metric_and_lower(qtbot) -> None:
    """메인 splitter: Vertical, count=3, [chart, MetricPanel, lower] (#14 v2)."""
    ctx = _streaming_wrapper(qtbot)
    QtCore = ctx["QtCore"]
    splitter = ctx["wrapper"].centralWidget()
    assert splitter.orientation() == QtCore.Qt.Orientation.Vertical
    assert splitter.count() == 3
    assert splitter.widget(0) is ctx["chart"]
    assert splitter.widget(1) is ctx["metric_panel"]
    lower = splitter.widget(2)
    assert lower is not ctx["chart"]
    assert lower is not ctx["metric_panel"]


def test_streaming_lower_pane_stacks_bottom_then_controls(qtbot) -> None:
    """lower QVBoxLayout 자식 = [bottom, controls] 정확 순서 (#14 v2).

    metric_panel 이 더 이상 lower 안에 없음 — 메인 splitter row 로 승격됐고,
    lower 는 [table | curve] 와 controls footer 만 담는다.
    """
    ctx = _streaming_wrapper(qtbot)
    splitter = ctx["wrapper"].centralWidget()
    lower = splitter.widget(2)
    layout = lower.layout()
    assert layout is not None
    assert layout.count() == 2
    # bottom 은 새 QWidget — table/curve 를 내부 splitter 안에 둠.
    bottom = layout.itemAt(0).widget()
    assert bottom is not ctx["table_widget"]
    assert bottom is not ctx["curve_box"]
    assert bottom is not ctx["metric_panel"]
    # controls footer 는 itemAt(1).
    assert layout.itemAt(1).widget() is ctx["controls"]


def test_streaming_bottom_is_horizontal_splitter_table_then_curve(qtbot) -> None:
    """bottom 컨테이너 안의 horizontal splitter [table | curve_box] 순서 회귀."""
    from pyqtgraph.Qt import QtCore, QtWidgets

    ctx = _streaming_wrapper(qtbot)
    splitter = ctx["wrapper"].centralWidget()
    lower = splitter.widget(2)
    bottom = lower.layout().itemAt(0).widget()

    # bottom 안에 QSplitter horizontal 이 있어야 함 — QHBoxLayout 의 첫 item.
    bl = bottom.layout()
    assert bl is not None and bl.count() == 1
    bottom_split = bl.itemAt(0).widget()
    assert isinstance(bottom_split, QtWidgets.QSplitter)
    assert bottom_split.orientation() == QtCore.Qt.Orientation.Horizontal
    assert bottom_split.count() == 2
    assert bottom_split.widget(0) is ctx["table_widget"]
    assert bottom_split.widget(1) is ctx["curve_box"]


def test_streaming_metric_panel_vertical_policy_is_maximum(qtbot) -> None:
    """metric_panel.setSizePolicy(Preferred, Maximum) — 메인 handle drag 시 metric 이
    여유 세로공간을 흡수하지 않고 bottom 이 가져간다 (#14 디자인)."""
    from pyqtgraph.Qt import QtWidgets

    ctx = _streaming_wrapper(qtbot)
    policy = ctx["metric_panel"].sizePolicy()
    assert policy.verticalPolicy() == QtWidgets.QSizePolicy.Policy.Maximum


def test_streaming_metric_panel_not_inside_curve_or_table_stack(qtbot) -> None:
    """negative 가드 — metric_panel 이 bottom horizontal splitter 안에 있으면 안 됨.

    (#14 v1 이전 안 들에서 metric_panel 이 right_stack 컨테이너에 curve 와
    같이 들어가 좁은 우측 컬럼에서 잘렸음. 본 가드가 그 회귀를 잡아낸다.
    v2 부터 metric_panel 은 메인 splitter 의 row 1 직속 — bottom 과 무관.)
    """
    ctx = _streaming_wrapper(qtbot)
    splitter = ctx["wrapper"].centralWidget()
    lower = splitter.widget(2)
    bottom = lower.layout().itemAt(0).widget()
    bottom_split = bottom.layout().itemAt(0).widget()
    for i in range(bottom_split.count()):
        assert not isinstance(bottom_split.widget(i), MetricPanel)
    # metric_panel 의 parent 가 splitter 인지 직접 확인 (lower 아님).
    assert ctx["metric_panel"].parentWidget() is splitter


# ─────────────────────────────────────────────────────────
# 11) #15 추가 가드 — 리사이즈 거동 (sizePolicy + stretch factor)
# ─────────────────────────────────────────────────────────
# 위 구조 가드는 "어디에 무엇이 있는가" 를 잡지만, 리사이즈 시 *어떻게* 거동
# 하느냐는 stretch factor + sizePolicy 가 결정한다. 메인 핸들을 드래그하거나
# 윈도우를 키울 때 사용자 의도 (chart 가 늘어남, controls 는 footer 유지,
# table 은 폭 고정, curve 가 가로 흡수) 가 무너지면 시각적으론 미세하게만
# 비뚤어져 회귀가 늦게 발견됨. 본 가드가 그걸 명시화한다.


def test_streaming_controls_vertical_policy_is_fixed_for_footer(qtbot) -> None:
    """controls.setSizePolicy(Preferred, Fixed) — footer 는 세로 흡수 0.

    Fixed 가 아니면 메인 핸들 드래그 시 controls 가 여유 공간을 가져가 footer
    영역이 두꺼워지고 미디어플레이어 패턴이 깨진다.
    """
    from pyqtgraph.Qt import QtWidgets

    ctx = _streaming_wrapper(qtbot)
    policy = ctx["controls"].sizePolicy()
    assert policy.verticalPolicy() == QtWidgets.QSizePolicy.Policy.Fixed


def test_streaming_main_splitter_stretch_factors_keep_metric_tight(qtbot) -> None:
    """메인 splitter 의 stretch factor: [chart=6, metric=0, lower=2].

    metric row 가 stretch 0 이어야 (size policy Maximum 과 함께) 핸들 드래그가
    metric 의 두께를 변경하지 못한다 — chart 와 lower 가 metric 을 위/아래에서
    "감싸고 미는" 동작이 유지됨.

    Qt: `QSplitter.setStretchFactor(idx, n)` 은 자식 위젯의 sizePolicy 의
    stretch 값에 기록된다 (vertical splitter → verticalStretch).
    """
    ctx = _streaming_wrapper(qtbot)
    splitter = ctx["wrapper"].centralWidget()
    assert splitter.widget(0).sizePolicy().verticalStretch() == 6   # chart
    assert splitter.widget(1).sizePolicy().verticalStretch() == 0   # metric tight
    assert splitter.widget(2).sizePolicy().verticalStretch() == 2   # lower


def test_streaming_bottom_split_table_fixed_curve_absorbs(qtbot) -> None:
    """bottom_split stretch: [table=0, curve=1] — 폭 변경 시 curve 가 가로 흡수.

    역순(table=1, curve=0) 으로 회귀하면 윈도우를 가로로 늘릴 때 테이블이
    빈 컬럼만 키우고 curve 가 시각적으로 압축된다 — 사용자 의도 정반대.

    horizontal splitter 라 horizontalStretch 에 기록됨.
    """
    ctx = _streaming_wrapper(qtbot)
    splitter = ctx["wrapper"].centralWidget()
    lower = splitter.widget(2)
    bottom = lower.layout().itemAt(0).widget()
    bottom_split = bottom.layout().itemAt(0).widget()
    assert bottom_split.widget(0).sizePolicy().horizontalStretch() == 0   # table
    assert bottom_split.widget(1).sizePolicy().horizontalStretch() == 1   # curve
