"""실행 진입점 검증.

"창이 뜨자마자 닫힌다" 는 상황에서 원인을 반드시 남겨야 한다:
예외는 logs/crash.log 에 기록되고 종료 코드는 1 이어야 한다.
"""

from __future__ import annotations

import os

import pytest

from rune_hunter import app as app_module
from rune_hunter.app import diagnose, parse_args, report_crash
from rune_hunter.config import AppConfig


def test_parse_args_defaults():
    args = parse_args([])
    assert args.demo is False
    assert args.headless == 0.0
    assert args.diagnose is False
    assert args.no_admin is False


def test_parse_args_flags():
    args = parse_args(["--demo", "--no-admin", "--headless", "5", "--profile", "x.json"])
    assert args.demo and args.no_admin
    assert args.headless == 5.0
    assert args.profile == "x.json"


def test_diagnose_reports_installed_modules(capsys):
    code = diagnose(AppConfig())
    out = capsys.readouterr().out
    assert code == 0
    assert "PySide6" in out and "cv2" in out
    assert "실행 가능" in out


def test_report_crash_writes_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(app_module, "LOG_DIR", tmp_path)
    try:
        raise RuntimeError("테스트용 실패")
    except RuntimeError as exc:
        path = report_crash(exc, show_dialog=False)

    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "테스트용 실패" in text
    assert "RuntimeError" in capsys.readouterr().err


def test_main_survives_startup_failure(tmp_path, monkeypatch):
    """GUI 초기화가 실패해도 조용히 닫히지 않고 종료 코드 1 과 로그를 남긴다."""
    monkeypatch.setattr(app_module, "LOG_DIR", tmp_path)
    monkeypatch.setenv("RUNE_HUNTER_NO_DIALOG", "1")

    def boom(_argv):
        raise RuntimeError("Qt 초기화 실패 시뮬레이션")

    monkeypatch.setattr(app_module, "_main", boom)
    assert app_module.main([]) == 1
    assert (tmp_path / "crash.log").exists()


def test_main_diagnose_path_returns_zero(monkeypatch):
    monkeypatch.setenv("RUNE_HUNTER_NO_DIALOG", "1")
    assert app_module.main(["--diagnose"]) == 0


def test_hold_console_does_not_block_without_tty():
    """stdin 이 콘솔이 아니면 입력을 기다리지 않아야 한다 (자동 실행 환경 대비)."""
    app_module.hold_console("무시됨")


@pytest.mark.skipif(os.name == "nt", reason="비 Windows 동작 확인")
def test_relaunch_arguments_keep_module_form(monkeypatch):
    """python -m rune_hunter 로 실행했으면 승격 재실행도 -m 형태를 유지해야 한다."""
    from rune_hunter.platform_layer.admin import relaunch_arguments

    monkeypatch.setattr("sys.argv", ["/some/path/rune_hunter/__main__.py", "--demo"])
    assert relaunch_arguments(["--elevated"]) == [
        "-m",
        "rune_hunter",
        "--demo",
        "--elevated",
    ]

    monkeypatch.setattr("sys.argv", ["run_macro.py"])
    args = relaunch_arguments()
    assert args[0].endswith("run_macro.py")
