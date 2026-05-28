"""P5 — metric_formatting SSOT unit tests.

`analytics/metric_formatting.py` 의 라벨 / 포맷 / 부호힌트가 HTML 리포트
(`report.py::_metrics_table`) 와 char-for-char 일치해야 viz KPI 패널이 같은
값을 그릴 수 있다 (plan CP4). 이 파일은 그 계약을 가드한다.

다루는 케이스:
- % 키 양수 / 음수 / 0 / 정확한 부호 표기
- profit_factor +inf 처리
- 일반 float .4f 포맷
- int / 비수치 fallback
- PRETTY_LABELS 키 / 순서
- sign_hint (pos / neg / neutral) 전 분기
"""

from __future__ import annotations

import math

import pytest

from tickweaver.analytics.metric_formatting import (
    PERCENT_KEYS,
    PRETTY_LABELS,
    format_metric,
    sign_hint,
)


# ─────────────────────────────────────────────────────────
# PRETTY_LABELS — order + completeness
# ─────────────────────────────────────────────────────────
def test_pretty_labels_contains_all_metric_keys() -> None:
    """compute_metrics 가 리턴하는 모든 핵심 키가 라벨 사전에 있어야 한다."""
    expected = {
        "final_equity",
        "initial_cash",
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "n_trades",
        "win_rate",
        "profit_factor",
    }
    assert expected <= set(PRETTY_LABELS.keys())


def test_pretty_labels_insertion_order_is_display_order() -> None:
    """dict 삽입 순서 = 표시 순서. final_equity 가 첫번째여야 한다 (가장 큰 KPI)."""
    keys = list(PRETTY_LABELS.keys())
    assert keys[0] == "final_equity"
    # initial_cash 는 final_equity 바로 뒤에 와야 비교가 자연스러움
    assert keys[1] == "initial_cash"


# ─────────────────────────────────────────────────────────
# format_metric — percent keys
# ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", sorted(PERCENT_KEYS))
def test_format_metric_percent_keys_use_signed_two_decimal_percent(key: str) -> None:
    """0..1 ratio → '+XX.XX%' (양수는 + 부호 명시)."""
    assert format_metric(key, 0.2341) == "+23.41%"


def test_format_metric_percent_negative_drawdown() -> None:
    """max_drawdown 은 음수 — '-8.34%' 형태."""
    assert format_metric("max_drawdown", -0.0834) == "-8.34%"


def test_format_metric_percent_zero_keeps_plus_sign() -> None:
    """0% 도 + 부호 보존 (포맷 일관성)."""
    assert format_metric("total_return", 0.0) == "+0.00%"


def test_format_metric_percent_exact_one_hundred_percent() -> None:
    assert format_metric("cagr", 1.0) == "+100.00%"


# ─────────────────────────────────────────────────────────
# format_metric — profit_factor 특수 케이스
# ─────────────────────────────────────────────────────────
def test_format_metric_profit_factor_positive_inf_is_literal_inf() -> None:
    """무손실 시나리오 — 'inf' 문자열로 표시."""
    assert format_metric("profit_factor", float("inf")) == "inf"


def test_format_metric_profit_factor_finite_uses_general_float_format() -> None:
    """finite 값은 일반 float 포맷 (.4f) 으로 떨어진다."""
    assert format_metric("profit_factor", 1.78) == "1.7800"


def test_format_metric_profit_factor_zero_no_trades_case() -> None:
    """trade 0 케이스에서 0.0 — 'inf' 분기 타지 않아야 한다."""
    assert format_metric("profit_factor", 0.0) == "0.0000"


# ─────────────────────────────────────────────────────────
# format_metric — generic float / int / non-numeric
# ─────────────────────────────────────────────────────────
def test_format_metric_generic_float_uses_four_decimals() -> None:
    """sharpe / sortino / calmar 등 — '.4f' 포맷."""
    assert format_metric("sharpe", 1.85) == "1.8500"


def test_format_metric_negative_generic_float_keeps_minus() -> None:
    assert format_metric("calmar", -0.5) == "-0.5000"


def test_format_metric_final_equity_float_uses_four_decimals() -> None:
    """final_equity 는 percent 키가 아니므로 .4f."""
    assert format_metric("final_equity", 12340.5) == "12340.5000"


def test_format_metric_int_uses_str_no_decimals() -> None:
    """n_trades 같은 int 는 그대로 str(int)."""
    assert format_metric("n_trades", 47) == "47"


def test_format_metric_non_numeric_falls_back_to_str() -> None:
    """타입이 float/int 아닌 경우 str(value)."""
    assert format_metric("foo", "bar") == "bar"


def test_format_metric_matches_report_py_metrics_table_chars() -> None:
    """plan CP4 — report.py::_metrics_table 의 정확한 출력과 char-for-char 동일.

    metric_formatting 모듈이 SSOT 라는 것을 회귀로 가드. report.py 의 인라인
    포맷 로직과 분기 분기 같은 결과가 나오는지 베이스라인을 굳혀둔다.
    """
    metrics = {
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
    expected = {
        "final_equity": "12340.5000",
        "initial_cash": "10000.0000",
        "total_return": "+23.41%",
        "cagr": "+18.20%",
        "sharpe": "1.8500",
        "sortino": "2.3100",
        "max_drawdown": "-8.34%",
        "calmar": "1.4200",
        "n_trades": "47",
        "win_rate": "+61.70%",
        "profit_factor": "1.7800",
    }
    for k, v in metrics.items():
        assert format_metric(k, v) == expected[k], f"{k}: {format_metric(k, v)!r}"


# ─────────────────────────────────────────────────────────
# sign_hint — color coding
# ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["final_equity", "initial_cash", "n_trades"])
def test_sign_hint_cash_and_count_keys_are_always_neutral(key: str) -> None:
    """cash / count 류는 색상 코딩 의미가 없어 neutral 고정."""
    assert sign_hint(key, 12345.6) == "neutral"
    assert sign_hint(key, 0) == "neutral"


def test_sign_hint_positive_return_is_pos() -> None:
    assert sign_hint("total_return", 0.05) == "pos"


def test_sign_hint_negative_return_is_neg() -> None:
    assert sign_hint("total_return", -0.05) == "neg"


def test_sign_hint_zero_value_is_neutral() -> None:
    assert sign_hint("total_return", 0.0) == "neutral"


def test_sign_hint_max_drawdown_negative_is_neg() -> None:
    """MDD 는 항상 ≤ 0 이지만 부호 분기 자체는 일반 규칙을 따른다."""
    assert sign_hint("max_drawdown", -0.0834) == "neg"


def test_sign_hint_profit_factor_above_one_is_pos() -> None:
    assert sign_hint("profit_factor", 1.78) == "pos"


def test_sign_hint_profit_factor_below_one_is_neg() -> None:
    assert sign_hint("profit_factor", 0.8) == "neg"


def test_sign_hint_profit_factor_exact_one_is_neutral() -> None:
    """break-even 케이스."""
    assert sign_hint("profit_factor", 1.0) == "neutral"


def test_sign_hint_profit_factor_inf_is_pos() -> None:
    """무손실 시나리오 — 시각적으로 가장 좋은 색."""
    assert sign_hint("profit_factor", float("inf")) == "pos"


def test_sign_hint_non_numeric_is_neutral() -> None:
    """string / None / dataclass 등 비수치는 neutral fallback."""
    assert sign_hint("sharpe", "n/a") == "neutral"
    assert sign_hint("sharpe", None) == "neutral"


def test_sign_hint_bool_is_neutral_not_pos() -> None:
    """isinstance(True, int) 트랩 가드 — bool 은 색상 의미 없음."""
    assert sign_hint("sharpe", True) == "neutral"
    assert sign_hint("sharpe", False) == "neutral"


def test_sign_hint_returns_only_three_literals() -> None:
    """타입 안전 — pos/neg/neutral 외엔 절대 안 나옴."""
    samples = [
        ("total_return", 0.1),
        ("total_return", -0.1),
        ("total_return", 0.0),
        ("profit_factor", float("inf")),
        ("profit_factor", 0.5),
        ("final_equity", 12345.0),
        ("sharpe", math.nan),  # NaN 비교는 모두 False → neutral
    ]
    for k, v in samples:
        assert sign_hint(k, v) in {"pos", "neg", "neutral"}
