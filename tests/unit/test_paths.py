"""utils.paths.resolve_strategy_path — auto strategies/ + auto .py 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from tickweaver.utils.paths import STRATEGIES_DIR, resolve_strategy_path


def test_resolve_passes_through_existing_path(tmp_path: Path):
    p = tmp_path / "my.py"
    p.write_text("# noop\n", encoding="utf-8")
    # cwd 기준이 아닌 absolute path 도 그대로 통과
    assert resolve_strategy_path(p) == p


def test_resolve_rejects_missing_absolute(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        resolve_strategy_path(tmp_path / "does_not_exist.py")


def test_resolve_finds_in_strategies_dir(monkeypatch, tmp_path: Path):
    # 임시 strategies/ 만들고 STRATEGIES_DIR 을 monkeypatch
    sdir = tmp_path / "strategies"
    sdir.mkdir()
    (sdir / "rsi_demo.py").write_text("# noop\n", encoding="utf-8")
    monkeypatch.setattr("tickweaver.utils.paths.STRATEGIES_DIR", sdir)

    # cwd 를 tmp_path 로 바꿔야 'rsi_demo' 가 cwd 에서 안 보이고 strategies/ 로 fallback
    monkeypatch.chdir(tmp_path)

    # 1. .py 없이 + strategies/ 없이 입력
    out = resolve_strategy_path("rsi_demo")
    assert out == sdir / "rsi_demo.py"

    # 2. .py 만 있는 경우
    out = resolve_strategy_path("rsi_demo.py")
    assert out == sdir / "rsi_demo.py"

    # 3. 명시적 strategies/ prefix 도 그대로
    out = resolve_strategy_path("strategies/rsi_demo.py")
    assert out == Path("strategies/rsi_demo.py")  # cwd 기준 상대로 존재


def test_resolve_prefers_cwd_over_strategies(monkeypatch, tmp_path: Path):
    """cwd 에 같은 이름의 .py 가 있으면 그게 우선."""
    sdir = tmp_path / "strategies"
    sdir.mkdir()
    (sdir / "x.py").write_text("# in strategies\n", encoding="utf-8")
    (tmp_path / "x.py").write_text("# in cwd\n", encoding="utf-8")
    monkeypatch.setattr("tickweaver.utils.paths.STRATEGIES_DIR", sdir)
    monkeypatch.chdir(tmp_path)

    out = resolve_strategy_path("x.py")
    # cwd 의 x.py 가 우선 매칭
    assert out == Path("x.py")


def test_resolve_helpful_error_when_missing(monkeypatch, tmp_path: Path):
    sdir = tmp_path / "strategies"
    sdir.mkdir()
    monkeypatch.setattr("tickweaver.utils.paths.STRATEGIES_DIR", sdir)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError) as exc:
        resolve_strategy_path("nonexistent")
    msg = str(exc.value)
    assert "tried" in msg
    assert "hint" in msg


def test_resolve_dotted_path_does_not_search_strategies(monkeypatch, tmp_path: Path):
    """경로 구분자가 있으면 strategies/ fallback 안 함 (사용자가 명시적 경로 의도)."""
    sdir = tmp_path / "strategies"
    sdir.mkdir()
    (sdir / "x.py").write_text("# in strategies\n", encoding="utf-8")
    monkeypatch.setattr("tickweaver.utils.paths.STRATEGIES_DIR", sdir)
    monkeypatch.chdir(tmp_path)

    # "subdir/x.py" 처럼 구분자 있는 경로는 cwd 기준으로만 찾음 (strategies/ fallback 안 함)
    with pytest.raises(FileNotFoundError):
        resolve_strategy_path("subdir/x.py")
