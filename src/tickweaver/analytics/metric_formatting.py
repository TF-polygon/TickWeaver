"""Metric label/format/color hint — Single Source of Truth.

`report.py::_metrics_table` (HTML 리포트) 와 `viz/metric_panel.py` (Qt KPI 패널)
가 같은 라벨/포맷을 사용하도록 모은 모듈. 새 지표를 추가할 때 이 파일 한 곳만
수정하면 두 출력이 동시에 갱신된다.

값 → 문자열 규칙 (기존 `report.py::_metrics_table` 와 char-for-char 동일):
- % 키 (total_return, cagr, max_drawdown, win_rate) : ``f"{v*100:+.2f}%"``
- profit_factor 이면서 inf : ``"inf"``
- 기타 float : ``f"{v:.4f}"``
- 그 외 (int 등) : ``str(v)``
"""

from __future__ import annotations

from typing import Any, Literal

# HTML 표와 KPI 패널이 공유하는 라벨. dict 삽입 순서가 표시 순서.
PRETTY_LABELS: dict[str, str] = {
    "final_equity": "Final Equity",
    "initial_cash": "Initial Cash",
    "total_return": "Total Return",
    "cagr": "CAGR",
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "max_drawdown": "Max Drawdown",
    "calmar": "Calmar",
    "n_trades": "Trades",
    "win_rate": "Win rate",
    "profit_factor": "Profit factor",
}

# 0..1 비율로 저장돼 있고 표시할 땐 100배 + % 부호 + 부호기호.
PERCENT_KEYS: frozenset[str] = frozenset(
    {"total_return", "cagr", "max_drawdown", "win_rate"}
)

# 부호 기반 색상 코딩에서 항상 neutral 로 처리할 키. viz 만 사용.
_NEUTRAL_KEYS: frozenset[str] = frozenset(
    {"final_equity", "initial_cash", "n_trades"}
)

SignHint = Literal["pos", "neg", "neutral"]


def format_metric(key: str, value: Any) -> str:
    """key 의 의미에 맞춰 metric value 를 사람-읽기용 문자열로 포맷.

    기존 `report.py::_metrics_table` 와 동일 결과 보장.
    """
    if isinstance(value, float):
        if key in PERCENT_KEYS:
            return f"{value * 100:+.2f}%"
        if key == "profit_factor" and value == float("inf"):
            return "inf"
        return f"{value:.4f}"
    return str(value)


def sign_hint(key: str, value: Any) -> SignHint:
    """KPI 카드의 색상 결정용 부호 힌트.

    - cash / count 류 키는 항상 neutral.
    - profit_factor: >1 또는 inf → pos, <1 → neg, ==1 → neutral.
    - 그 외 수치: >0 → pos, <0 → neg, ==0 → neutral.
    - 수치가 아니면 neutral.
    """
    if key in _NEUTRAL_KEYS:
        return "neutral"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "neutral"
    if key == "profit_factor":
        if value == float("inf") or value > 1.0:
            return "pos"
        if value < 1.0:
            return "neg"
        return "neutral"
    if value > 0:
        return "pos"
    if value < 0:
        return "neg"
    return "neutral"
