"""GUI 스모크 테스트 (오프스크린).

창을 실제로 띄우지 않고 위젯 생성 → 설정 수집 → 프로필 저장까지 확인한다.
GUI 코드의 오타/시그널 연결 오류를 CI 에서 잡는 용도.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from rune_hunter.config import AppConfig  # noqa: E402
from rune_hunter.gui.main_window import MainWindow  # noqa: E402
from rune_hunter.logging_bus import EventBus  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_window_builds_and_collects(app, tmp_path):
    config = AppConfig()
    window = MainWindow(config, EventBus(), demo=True)
    try:
        assert window.tabs.count() == 4
        assert window.demo_check.isChecked()

        window.hunt_row.key.select("V")
        window.hunt_row.interval.setValue(0.09)
        window.buff_rows[0].key.select("NUM1")
        window.buff_rows[0].interval.setValue(150.0)
        window.rune_enabled.setChecked(True)
        window.detect_scale.setValue(0.5)
        window.window_titles.setText("나루, MapleStory")
        window.collect()

        assert config.attack.hunt.key == "V"
        assert config.attack.hunt.interval == pytest.approx(0.09)
        assert config.attack.buffs[0].key == "NUM1"
        assert config.attack.buffs[0].interval == pytest.approx(150.0)
        assert config.rune.detect_scale == pytest.approx(0.5)
        assert config.general.window_titles == ["나루", "MapleStory"]

        path = config.save(tmp_path / "gui.json")
        assert AppConfig.load(path).attack.hunt.key == "V"
    finally:
        window.close()


def test_log_view_receives_bus_events(app):
    bus = EventBus()
    window = MainWindow(AppConfig(), bus, demo=True)
    try:
        bus.ok("테스트 메시지")
        window._on_tick()
        assert "테스트 메시지" in window.log.toPlainText()
    finally:
        window.close()


def test_engine_can_start_in_demo_mode(app):
    bus = EventBus()
    window = MainWindow(AppConfig(), bus, demo=True)
    try:
        window.start_engine()
        assert window.engine is not None and window.engine.running
        window._on_tick()
        assert "정지" not in window.state_label.text()
    finally:
        window.stop_engine()
        window.close()


def test_rune_detection_test_button_uses_demo_frame(app):
    bus = EventBus()
    window = MainWindow(AppConfig(), bus, demo=True)
    try:
        window._test_rune()
        window._test_arrows()
        messages = [e.message for e in bus.drain()]
        assert any("룬" in m for m in messages)
    finally:
        window.close()
