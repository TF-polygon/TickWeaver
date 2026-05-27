"""Issue 4 Step 3 — PositionTableWidget UI 검증.

pytest-qt 의 qtbot fixture 로 위젯 생성 + 토글 동작 확인. 헤드리스 환경에서도 동작.
"""

from __future__ import annotations

import csv

import pandas as pd
import pytest

from tickweaver.analytics.positions import PositionRow

try:
    from tickweaver.viz.position_table import PositionTableWidget
    _HAS_QT = True
except Exception:
    _HAS_QT = False


pytestmark = pytest.mark.skipif(
    not _HAS_QT, reason="PyQt6 / pyqtgraph.Qt not available"
)


# ── 헬퍼 ────────────────────────────────────────────────────
def _open_row(
    order_no: int, side: str = "Long", fee: float | None = None
) -> PositionRow:
    return PositionRow(
        timestamp=pd.Timestamp("2024-01-01 00:00:00", tz="UTC"),
        order_no=order_no,
        side=side,
        margin=30.0,
        entry_price=45000.0,
        pnl=None,
        cum_pnl=None,
        holding_bars=None,
        fee=fee,
        cum_fee=fee,
    )


def _close_row(
    order_no: int,
    pnl: float,
    cum_pnl: float,
    holding_bars: int | None = 5,
    fee: float | None = None,
    cum_fee: float | None = None,
) -> PositionRow:
    return PositionRow(
        timestamp=pd.Timestamp("2024-01-01 00:10:00", tz="UTC"),
        order_no=order_no,
        side="Close",
        margin=None,
        entry_price=45100.0,
        pnl=pnl,
        cum_pnl=cum_pnl,
        holding_bars=holding_bars,
        fee=fee,
        cum_fee=cum_fee,
    )


# ── 위젯 생성 / 데이터 채우기 ──────────────────────────────
def test_empty_rows_yields_empty_table(qtbot):
    w = PositionTableWidget(rows=[])
    qtbot.addWidget(w)
    assert w.n_rows == 0


def test_single_open_row_populates_cells(qtbot):
    rows = [_open_row(order_no=1, side="Long")]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w.n_rows == 1
    # 셀 텍스트 검증
    assert w._table.item(0, 0).text() == "1"               # #
    assert w._table.item(0, 1).text().startswith("2024-01-01")
    assert w._table.item(0, 2).text() == "1"               # Order #
    assert w._table.item(0, 3).text() == "Long"
    assert w._table.item(0, 4).text() == "30.00"           # Margin
    assert w._table.item(0, 5).text() == "45000.00"        # Entry Price
    assert w._table.item(0, 6).text() == ""                # PnL (open row 는 빈 셀)
    assert w._table.item(0, 7).text() == ""                # Cum. PnL (open 빈 셀)


def test_close_row_shows_signed_pnl_and_cum(qtbot):
    rows = [_close_row(order_no=1, pnl=3.0, cum_pnl=3.0)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w.n_rows == 1
    assert w._table.item(0, 3).text() == "Close"
    assert w._table.item(0, 4).text() == ""                # Margin (close 는 빈 셀)
    assert w._table.item(0, 6).text() == "+3.00"           # PnL 부호 포함
    assert w._table.item(0, 7).text() == "+3.00"           # Cum. PnL 부호 포함


def test_negative_pnl_shows_minus_sign(qtbot):
    rows = [_close_row(order_no=1, pnl=-2.5, cum_pnl=-2.5)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w._table.item(0, 6).text() == "-2.50"
    assert w._table.item(0, 7).text() == "-2.50"


def test_multiple_rows_sorted_in_input_order(qtbot):
    """build_position_history 가 시간 순으로 반환하니 그대로 순서 유지."""
    rows = [
        _open_row(order_no=1),
        _open_row(order_no=2),
        _close_row(order_no=1, pnl=3.0, cum_pnl=3.0),
        _close_row(order_no=2, pnl=4.0, cum_pnl=7.0),
    ]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w.n_rows == 4
    # # 컬럼이 1~4 순서로
    assert [w._table.item(i, 0).text() for i in range(4)] == ["1", "2", "3", "4"]
    # Order # 컬럼은 row 별 order_no
    assert [w._table.item(i, 2).text() for i in range(4)] == ["1", "2", "1", "2"]


# ── Holding Bars 토글 ─────────────────────────────────────
def test_holding_bars_column_hidden_by_default(qtbot):
    w = PositionTableWidget(rows=[_close_row(order_no=1, pnl=1.0, cum_pnl=1.0)])
    qtbot.addWidget(w)
    assert w.holding_bars_visible is False
    assert w._table.isColumnHidden(10) is True


def test_holding_bars_column_shown_after_toggle(qtbot):
    w = PositionTableWidget(rows=[_close_row(order_no=1, pnl=1.0, cum_pnl=1.0, holding_bars=7)])
    qtbot.addWidget(w)
    # 체크 → show
    w._hb_checkbox.setChecked(True)
    assert w.holding_bars_visible is True
    assert w._table.isColumnHidden(10) is False
    # 셀 값 확인
    assert w._table.item(0, 10).text() == "7"


def test_holding_bars_toggle_back_to_hidden(qtbot):
    w = PositionTableWidget(rows=[_close_row(order_no=1, pnl=1.0, cum_pnl=1.0, holding_bars=7)])
    qtbot.addWidget(w)
    w._hb_checkbox.setChecked(True)
    assert w.holding_bars_visible is True
    w._hb_checkbox.setChecked(False)
    assert w.holding_bars_visible is False


def test_holding_bars_empty_cell_when_none(qtbot):
    """open row 등 holding_bars=None 인 경우 빈 셀."""
    w = PositionTableWidget(rows=[_open_row(order_no=1)])
    qtbot.addWidget(w)
    assert w._table.item(0, 10).text() == ""


# ── Fee 컬럼 (Polish Work A) ───────────────────────────────
def test_close_row_shows_fee_and_cum_fee(qtbot):
    """close row 의 Fee(8) / Cum. Fee(9) 셀 표시."""
    rows = [_close_row(order_no=1, pnl=3.0, cum_pnl=3.0, fee=0.0475, cum_fee=0.19)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w._table.item(0, 8).text() == "0.05"   # Fee (2 decimals)
    assert w._table.item(0, 9).text() == "0.19"   # Cum. Fee


def test_open_row_fee_shown_when_present(qtbot):
    """open row 도 자기 fee 표시 (per-row 설계)."""
    rows = [_open_row(order_no=1, fee=0.05)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w._table.item(0, 8).text() == "0.05"   # Fee
    assert w._table.item(0, 9).text() == "0.05"   # Cum. Fee


def test_fee_cell_blank_when_none(qtbot):
    """fee=None 이면 빈 셀."""
    rows = [_open_row(order_no=1, fee=None)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    assert w._table.item(0, 8).text() == ""
    assert w._table.item(0, 9).text() == ""


# ── set_rows 외부 API ─────────────────────────────────────
def test_set_rows_refreshes_table(qtbot):
    w = PositionTableWidget(rows=[])
    qtbot.addWidget(w)
    assert w.n_rows == 0
    w.set_rows([_open_row(order_no=1), _close_row(order_no=1, pnl=2.0, cum_pnl=2.0)])
    assert w.n_rows == 2
    assert w._table.item(1, 6).text() == "+2.00"


# ── CSV export (Polish Work B) ─────────────────────────────
def _read_csv(path) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_export_csv_empty_only_header(qtbot, tmp_path):
    """빈 표 → 보이는 컬럼 header 만, 데이터 row 없음. Holding Bars(숨김) 제외."""
    w = PositionTableWidget(rows=[])
    qtbot.addWidget(w)
    out = tmp_path / "empty.csv"
    w.export_csv(out)
    data = _read_csv(out)
    assert len(data) == 1
    assert data[0][0] == "#"
    assert "Fee (USDT)" in data[0]
    assert "Cum. Fee (USDT)" in data[0]
    assert "Holding Bars" not in data[0]   # default hidden → 제외


def test_export_csv_single_row_precise_values(qtbot, tmp_path):
    """값은 표(반올림)보다 정밀하게 — Fee 표시 0.05 이어도 CSV 는 0.0475."""
    rows = [_close_row(order_no=1, pnl=3.0, cum_pnl=3.0, fee=0.0475, cum_fee=0.0475)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    out = tmp_path / "single.csv"
    w.export_csv(out)
    header, row = _read_csv(out)
    assert row[header.index("Side")] == "Close"
    assert row[header.index("PnL (USDT)")] == "3"        # 정밀 numeric (no +/.00)
    assert row[header.index("Fee (USDT)")] == "0.0475"   # 정밀 (표는 0.05)


def test_export_csv_multiple_with_holding_bars(qtbot, tmp_path):
    """Holding Bars 토글 ON → 컬럼 포함, 값 채워짐. open row holding bars 는 빈 칸."""
    rows = [
        _open_row(order_no=1, fee=0.05),
        _close_row(
            order_no=1, pnl=3.0, cum_pnl=3.0, holding_bars=7, fee=0.0475, cum_fee=0.0975
        ),
    ]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    w._hb_checkbox.setChecked(True)
    out = tmp_path / "multi.csv"
    w.export_csv(out)
    data = _read_csv(out)
    assert len(data) == 3                      # header + 2 rows
    assert "Holding Bars" in data[0]
    hb = data[0].index("Holding Bars")
    assert data[2][hb] == "7"                  # close row
    assert data[1][hb] == ""                   # open row (None)


def test_export_csv_excludes_hidden_holding_bars(qtbot, tmp_path):
    """기본(토글 OFF) → Holding Bars 컬럼 CSV 에서 제외."""
    rows = [_close_row(order_no=1, pnl=1.0, cum_pnl=1.0, holding_bars=5)]
    w = PositionTableWidget(rows=rows)
    qtbot.addWidget(w)
    out = tmp_path / "hidden.csv"
    w.export_csv(out)
    data = _read_csv(out)
    assert "Holding Bars" not in data[0]
