from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rune_hunter.config import AppConfig  # noqa: E402
from rune_hunter.inputs.recorder import RecordingBackend  # noqa: E402
from rune_hunter.logging_bus import EventBus  # noqa: E402
from rune_hunter.vision import RuneVision  # noqa: E402
from rune_hunter.vision.matcher import template_from_array  # noqa: E402
from rune_hunter.vision.synth import demo_templates  # noqa: E402


@pytest.fixture
def config() -> AppConfig:
    cfg = AppConfig()
    # 테스트는 짧고 결정적으로: 대기 시간을 줄인다
    cfg.rune.arrow_wait = 1.0
    cfg.rune.activate_gap = 0.3
    cfg.rune.confirm_timeout = 1.5
    cfg.rune.arrow_gap = 0.05
    cfg.rune.cooldown_success = 1.0
    cfg.rune.cooldown_fail = 1.0
    return cfg


@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path, monkeypatch):
    """테스트가 저장소의 logs/ 를 어지럽히지 않게 한다."""
    from rune_hunter import diagnostics

    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path / "logs")


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def vision(config: AppConfig) -> RuneVision:
    v = RuneVision(config)
    for name, image in demo_templates().items():
        v.register_template(name, template_from_array(image, name))
    return v


@pytest.fixture
def recorder() -> RecordingBackend:
    return RecordingBackend()
