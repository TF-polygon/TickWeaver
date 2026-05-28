"""KPI metric panel — single QWidget shared by static + streaming viz windows.

Renders a horizontal strip of 10 cards (Final Equity / Total Return / CAGR /
Sharpe / Sortino / Max DD / Calmar / Trades / Win / PF). Labels, formatting,
and sign-based color hint come from `analytics.metric_formatting` so the panel
and the HTML report stay in sync (single source of truth).

Usage:
    panel = MetricPanel()
    panel.update_from_metrics(compute_metrics(eq_df, trades, initial_cash))

Self-checkable: the ``QGroupBox`` title is a checkbox. Clicking it collapses
the card row so the user can free chart space without losing the toggle
itself (unlike ``setVisible(False)`` which hides the toggle along with the
content). The streaming/static windows do not need an external checkbox.

Dynamic resize (#11): font sizes scale with the panel's current width
relative to a 1920px reference, clamped to [8pt, 16pt]. Values that still
overflow their card get ellipsised via ``QFontMetrics.elidedText`` so a long
number never spills into an adjacent card. The original (unelided) text is
cached so subsequent resizes restore precision when there is room.

Graceful None path: :func:`trade_only_metrics` returns a partial dict
(final_equity / total_return / n_trades / win_rate / profit_factor) for when
the caller has no equity series to feed ``compute_metrics``. The four
equity-derived cards (sharpe / sortino / max_drawdown / calmar) render as "—"
in that case — explicitly "unavailable" rather than a misleading 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from tickweaver.analytics.metric_formatting import format_metric, sign_hint

if TYPE_CHECKING:
    from tickweaver.analytics.trades import Trade


# ── visual constants ────────────────────────────────────────────────
_LABEL_COLOR = "#8a98b0"     # light gray label
_VALUE_NEUTRAL = "#cfcfcf"   # matches viz FG
_VALUE_POS = "#7BC97B"       # light green (softer than candle BULL)
_VALUE_NEG = "#E08585"       # light red (softer than candle BEAR)
_CARD_BORDER = "#3A4A66"     # matches live_window _BORDER
_PANEL_BG = "#0B1424"        # matches live_window _DESC_BG

# Reference panel width for font scaling. At 1920 the panel uses the base
# label/value point sizes; narrower panels scale down (clamped to FONT_MIN_PT),
# wider panels scale up (clamped to FONT_MAX_PT).
_REF_WIDTH = 1920.0
_LABEL_BASE_PT = 9
_VALUE_BASE_PT = 12
_FONT_MIN_PT = 8
_FONT_MAX_PT = 16

# 10 KPIs in display order. Mirrors plans/eval_metrics.md §3.D mockup
# (initial_cash dropped — redundant with final_equity + total_return).
_DISPLAY_KEYS: tuple[str, ...] = (
    "final_equity",
    "total_return",
    "cagr",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "n_trades",
    "win_rate",
    "profit_factor",
)

# Tighter labels for narrow cards (PRETTY_LABELS strings are made for the
# HTML report's wide column).
_SHORT_LABELS: dict[str, str] = {
    "final_equity": "Final Eq.",
    "total_return": "Return",
    "cagr": "CAGR",
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "max_drawdown": "Max DD",
    "calmar": "Calmar",
    "n_trades": "Trades",
    "win_rate": "Win",
    "profit_factor": "PF",
}


def _value_color(hint: str) -> str:
    return (
        _VALUE_POS if hint == "pos"
        else _VALUE_NEG if hint == "neg"
        else _VALUE_NEUTRAL
    )


def _scaled_pt(base_pt: int, scale: float) -> int:
    pt = round(base_pt * scale)
    return max(_FONT_MIN_PT, min(_FONT_MAX_PT, pt))


class MetricPanel(QtWidgets.QGroupBox):
    """Horizontal KPI strip — 10 cards, one per displayed metric.

    Subclasses ``QGroupBox`` so the "Metrics" frame title is free. The group
    is checkable: unchecking collapses the card row, leaving only the title
    bar visible so the user can re-expand it any time.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Metrics", parent)
        self.setObjectName("metricPanel")
        self.setStyleSheet(
            f"QGroupBox#metricPanel {{"
            f"  background-color: {_PANEL_BG};"
            f"  border: 1px solid {_CARD_BORDER};"
            f"  border-radius: 4px;"
            f"  color: {_VALUE_NEUTRAL};"
            f"  font-family: Consolas, monospace;"
            f"  font-size: 10pt;"
            f"  margin-top: 8px;"
            f"  padding: 4px 6px 4px 6px;"
            f"}}"
            f"QGroupBox#metricPanel::title {{"
            f"  subcontrol-origin: margin;"
            f"  subcontrol-position: top left;"
            f"  left: 8px;"
            f"  padding: 0 4px;"
            f"  color: {_LABEL_COLOR};"
            f"}}"
        )
        # Title is a checkbox — clicking collapses the card row.
        self.setCheckable(True)
        self.setChecked(True)
        self.toggled.connect(self._on_toggle)

        # Per-card storage. ``_cards[key]`` is the value QLabel (kept as a
        # stable private API for tests / external readers); ``_card_state[key]``
        # holds the richer dict (label widget, raw text, hint, card frame)
        # used by the resize/elide machinery.
        self._cards: dict[str, QtWidgets.QLabel] = {}
        self._card_state: dict[str, dict] = {}
        self._row_widget: QtWidgets.QWidget | None = None
        self._build_cards()

    def _build_cards(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 4)
        outer.setSpacing(0)
        # The actual card row lives inside its own container so we can
        # hide/show all 10 children with one setVisible() on the row.
        row_widget = QtWidgets.QWidget(self)
        row = QtWidgets.QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for key in _DISPLAY_KEYS:
            card = self._make_card(_SHORT_LABELS[key], key)
            row.addWidget(card, stretch=1)
        outer.addWidget(row_widget)
        self._row_widget = row_widget

    def _make_card(self, label_text: str, key: str) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("metricCard")
        card.setStyleSheet(
            f"QFrame#metricCard {{"
            f"  border: 1px solid {_CARD_BORDER};"
            f"  border-radius: 3px;"
            f"  background-color: rgba(255,255,255,8);"
            f"}}"
        )
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(1)

        label = QtWidgets.QLabel(label_text)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {_LABEL_COLOR}; font-family: Consolas, monospace;")

        value = QtWidgets.QLabel("—")
        value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet(
            f"color: {_VALUE_NEUTRAL}; font-family: Consolas, monospace; "
            f"font-weight: 700;"
        )

        v.addWidget(label)
        v.addWidget(value)
        card.setMinimumWidth(36)   # narrow enough for ultra-shrunk windows
        self._cards[key] = value
        self._card_state[key] = {
            "card": card,
            "label": label,
            "value": value,
            "label_text": label_text,
            "value_text": "—",
            "hint": "neutral",
        }
        # Initial font apply (will be re-scaled on first resizeEvent).
        self._apply_card_fonts(self._card_state[key], _LABEL_BASE_PT, _VALUE_BASE_PT)
        return card

    # ── font/elide application (called from resizeEvent + updates) ──
    @staticmethod
    def _apply_card_fonts(card_state: dict, label_pt: int, value_pt: int) -> None:
        lf = card_state["label"].font()
        lf.setPointSize(label_pt)
        card_state["label"].setFont(lf)
        vf = card_state["value"].font()
        vf.setPointSize(value_pt)
        vf.setBold(True)
        card_state["value"].setFont(vf)

    @staticmethod
    def _apply_elide(card_state: dict, available_px: int) -> None:
        text = card_state["value_text"]
        fm = QtGui.QFontMetrics(card_state["value"].font())
        elided = fm.elidedText(
            text, QtCore.Qt.TextElideMode.ElideRight, max(8, available_px)
        )
        card_state["value"].setText(elided)
        # Tooltip preserves the precise value for hover when elided.
        card_state["value"].setToolTip(text if elided != text else "")

    def _rescale(self) -> None:
        if not self._card_state:
            return
        scale = max(0.1, self.width() / _REF_WIDTH)
        label_pt = _scaled_pt(_LABEL_BASE_PT, scale)
        value_pt = _scaled_pt(_VALUE_BASE_PT, scale)
        for state in self._card_state.values():
            self._apply_card_fonts(state, label_pt, value_pt)
            # Available text width inside the card = card width - layout margins.
            card_w = state["card"].width()
            avail = max(0, card_w - 12)   # 6+6 contents margins
            self._apply_elide(state, avail)

    # ── Qt overrides ───────────────────────────────────────────────
    def resizeEvent(self, event: "QtGui.QResizeEvent") -> None:
        super().resizeEvent(event)
        self._rescale()

    # ── public API ──────────────────────────────────────────────────
    def update_from_metrics(self, metrics: dict | None) -> None:
        """Apply a metrics dict (compute_metrics output) to the cards.

        Missing keys (e.g. trade_only_metrics for the sharpe/MDD/calmar/sortino
        slots when no equity series is available) render as "—".
        """
        for key in _DISPLAY_KEYS:
            state = self._card_state[key]
            if metrics is None or key not in metrics:
                text, hint = "—", "neutral"
            else:
                v = metrics[key]
                try:
                    text = format_metric(key, v)
                    hint = sign_hint(key, v)
                except Exception:
                    text, hint = "—", "neutral"
            state["value_text"] = text
            state["hint"] = hint
            color = _value_color(hint)
            state["value"].setStyleSheet(
                f"color: {color}; font-family: Consolas, monospace; "
                f"font-weight: 700;"
            )
            # Mirror the raw text into the value QLabel up-front so callers
            # reading via ``_cards[key].text()`` see the un-elided value when
            # the panel hasn't been laid out yet (e.g. pytest-qt smoke).
            state["value"].setText(text)
        # Re-apply elision against the current card widths (if visible).
        self._rescale()

    def clear(self) -> None:
        """Reset every card to its empty ("—" / neutral) state."""
        for state in self._card_state.values():
            state["value_text"] = "—"
            state["hint"] = "neutral"
            state["value"].setStyleSheet(
                f"color: {_VALUE_NEUTRAL}; font-family: Consolas, monospace; "
                f"font-weight: 700;"
            )
            state["value"].setText("—")
            state["value"].setToolTip("")
        self._rescale()

    # ── checkable / collapse ───────────────────────────────────────
    def _on_toggle(self, checked: bool) -> None:
        if self._row_widget is not None:
            self._row_widget.setVisible(bool(checked))


# ── trade-only metrics (graceful equity_curve=None path) ─────────────
def trade_only_metrics(
    trades: "list[Trade]",
    initial_cash: float,
    final_equity: float,
) -> dict:
    """Return the metrics that need no equity time series.

    Used when the caller has no engine equity_curve to feed
    ``compute_metrics`` (e.g. a hook opened without runner-side
    ``attach_equity_curve``). The four equity-derived keys
    (sharpe / sortino / max_drawdown / calmar) are deliberately absent — the
    panel renders them as "—" so the user reads "not available", not "0.0".
    """
    init = float(initial_cash) if initial_cash else 0.0
    final = float(final_equity) if final_equity is not None else init
    n = len(trades)
    out = {
        "final_equity": final,
        "total_return": (final / init - 1.0) if init > 0 else 0.0,
        "n_trades": n,
        "win_rate": 0.0,
        "profit_factor": 0.0,
    }
    if n == 0:
        return out
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    out["win_rate"] = len(wins) / n
    gross_profit = sum(t.pnl for t in wins) if wins else 0.0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0
    if gross_loss > 0:
        out["profit_factor"] = gross_profit / gross_loss
    elif wins:
        out["profit_factor"] = float("inf")
    # else 0.0 (already set)
    return out
