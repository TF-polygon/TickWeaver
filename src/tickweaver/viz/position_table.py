"""position_table.py — 포지션 히스토리 표 (QTableWidget) 위젯.

`analytics.positions.build_position_history` 의 결과 (`list[PositionRow]`)
를 받아 chart window 의 dock 으로 들어갈 widget 을 생성한다.

기본 8 컬럼:
    # | Timestamp | Order # | Side | Margin (USDT) | Entry Price | PnL (USDT) | Cum. PnL (USDT)

옵션 9 번째 컬럼 (`Holding Bars`) 은 상단 체크박스로 토글. default OFF.

가로 스크롤은 없도록 짧은 컬럼은 ResizeToContents, 금액 컬럼은 남은 공간
Stretch 로 분배. 세로 스크롤은 행이 많을 때 자동 표시.

Read-only 표 (편집 불가). vertical header 는 숨김 — `#` 컬럼이 그 역할.

추후 작업 후보 (지금 미구현):
    * Fee 컬럼 (거래소별 fee 모델 통합 후)
    * row 색상 (Long/Short/Close 배경, PnL 부호 색상)
    * 표 우클릭 → CSV export
    * 종목별 가격 정밀도 자동 (현재 BTC/USDT 기준 둘째 자리 hardcode)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyqtgraph.Qt import QtCore, QtWidgets

if TYPE_CHECKING:
    from tickweaver.analytics.positions import PositionRow


# ── 컬럼 정의 ───────────────────────────────────────────────
_COLUMNS: tuple[str, ...] = (
    "#",
    "Timestamp",
    "Order #",
    "Side",
    "Margin (USDT)",
    "Entry Price",
    "PnL (USDT)",
    "Cum. PnL (USDT)",
    "Holding Bars",
)
_HOLDING_BARS_COL: int = 8

# ResizeToContents 로 맞출 컬럼 (짧은 컬럼) vs Stretch (남은 공간 분배)
_FIXED_COLS: tuple[int, ...] = (0, 1, 2, 3, 8)   # #, Timestamp, Order #, Side, Holding Bars
_STRETCH_COLS: tuple[int, ...] = (4, 5, 6, 7)    # Margin, Entry, PnL, Cum. PnL


# ── 포맷터 헬퍼 ─────────────────────────────────────────────
def _format_money(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}"


def _format_signed_money(v: float | None) -> str:
    return "" if v is None else f"{v:+.2f}"


def _format_price(v: float, decimals: int = 2) -> str:
    """가격 표기. decimals 는 종목별 정밀도 (Polish C, runner 가 CCXT 에서 추출)."""
    return f"{v:.{decimals}f}"


def _format_ts(ts) -> str:
    """timestamp 를 'YYYY-MM-DD HH:MM:SS' 로. tz-aware/naive 둘 다 OK."""
    try:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


# ── 위젯 본체 ───────────────────────────────────────────────
class PositionTableWidget(QtWidgets.QWidget):
    """Position history table widget.

    `show_replay()` 의 chart window dock 으로 추가될 컴포넌트.

    Args:
        rows: build_position_history() 가 반환한 PositionRow 리스트.
        parent: Qt parent (보통 dock 컨테이너).
        price_decimals: Entry Price 표기 소수 자릿수 (Polish C, 종목별 정밀도).
    """

    def __init__(
        self,
        rows: "list[PositionRow]",
        parent: QtWidgets.QWidget | None = None,
        price_decimals: int = 2,
    ) -> None:
        super().__init__(parent)
        self._rows = list(rows)
        self._price_decimals = int(price_decimals)

        # 레이아웃: 상단 체크박스 + 표
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Holding Bars 토글 체크박스
        self._hb_checkbox = QtWidgets.QCheckBox("Show Holding Bars")
        self._hb_checkbox.setChecked(False)   # default OFF
        self._hb_checkbox.stateChanged.connect(self._on_hb_toggle)
        layout.addWidget(self._hb_checkbox)

        # 표 본체
        self._table = QtWidgets.QTableWidget(self)
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))

        # 컬럼별 resize mode
        header = self._table.horizontalHeader()
        for col in _FIXED_COLS:
            header.setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
        for col in _STRETCH_COLS:
            header.setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.Stretch
            )

        # 가로 스크롤 비활성, 세로 스크롤은 행 많으면 자동
        self._table.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._table.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Read-only + 행 단위 selection + vertical header 숨김
        self._table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.verticalHeader().setVisible(False)

        # default OFF — Holding Bars 컬럼 hide
        self._table.setColumnHidden(_HOLDING_BARS_COL, True)

        layout.addWidget(self._table, stretch=1)

        # 데이터 채우기
        self._populate()

    # ── 내부 ────────────────────────────────────────────────
    def _populate(self) -> None:
        """`self._rows` → 표 셀."""
        self._table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            cells = (
                str(i + 1),                                   # #
                _format_ts(row.timestamp),                    # Timestamp
                str(row.order_no),                            # Order #
                row.side,                                     # Side
                _format_money(row.margin),                    # Margin (USDT)
                _format_price(row.entry_price, self._price_decimals),  # Entry Price
                _format_signed_money(row.pnl),                # PnL (USDT)
                _format_signed_money(row.cum_pnl),            # Cum. PnL (USDT)
                "" if row.holding_bars is None
                else str(row.holding_bars),                   # Holding Bars
            )
            for j, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                # 숫자/순번 컬럼은 우측 정렬, 텍스트 컬럼은 좌측
                if j in (0, 2, 4, 5, 6, 7, 8):
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignRight
                        | QtCore.Qt.AlignmentFlag.AlignVCenter
                    )
                else:
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignLeft
                        | QtCore.Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(i, j, item)

    def _on_hb_toggle(self, _state: int) -> None:
        """체크박스 토글 → Holding Bars 컬럼 hide/show."""
        self._table.setColumnHidden(
            _HOLDING_BARS_COL, not self._hb_checkbox.isChecked()
        )

    # ── 외부 API ───────────────────────────────────────────
    def set_rows(self, rows: "list[PositionRow]") -> None:
        """행 데이터 갱신. (현재는 backtest 종료 1 회 호출 용도, 향후 라이브 갱신 확장 여지.)"""
        self._rows = list(rows)
        self._populate()

    @property
    def n_rows(self) -> int:
        return self._table.rowCount()

    @property
    def holding_bars_visible(self) -> bool:
        return not self._table.isColumnHidden(_HOLDING_BARS_COL)
