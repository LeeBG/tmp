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


def test_minimap_controls_round_trip(app, tmp_path):
    config = AppConfig()
    window = MainWindow(config, EventBus(), demo=True)
    try:
        window.source_minimap.setChecked(True)
        window.mm_tolerance.setValue(3)
        window.mm_ms_per_px.setValue(60.0)
        window.mm_max_hold.setValue(500)
        window.mm_auto.setChecked(False)
        window.activate_key.select("SPACE")
        window.collect()

        assert config.rune.source == "minimap"
        assert config.rune.use_minimap is True
        assert config.rune.minimap.align_tolerance == 3
        assert config.rune.minimap.ms_per_px == pytest.approx(60.0)
        assert config.rune.minimap.auto_calibrate is False
        assert config.rune.activate_key == "SPACE"

        path = config.save(tmp_path / "mm.json")
        loaded = AppConfig.load(path)
        assert loaded.rune.use_minimap is True
        assert loaded.rune.minimap.ms_per_px == pytest.approx(60.0)
        assert loaded.rune.minimap.rune_color.lower == config.rune.minimap.rune_color.lower
    finally:
        window.close()


def test_minimap_test_button_reports_markers(app):
    """데모 모드에서 미니맵 인식 테스트가 좌표를 보고해야 한다."""
    bus = EventBus()
    config = AppConfig()
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    window = MainWindow(config, bus, demo=True)
    try:
        window.source_minimap.setChecked(True)
        window._test_minimap()
        messages = [e.message for e in bus.drain()]
        assert any("미니맵" in m for m in messages)
        assert any("캐릭터" in m or "룬" in m for m in messages)
    finally:
        window.close()


def test_diagnostics_button_reports_each_stage(app):
    """진단 버튼은 설정 점검과 단계별 결과를 로그로 남겨야 한다."""
    bus = EventBus()
    config = AppConfig()
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.activate_key = "UP"  # 설정 실수 재현
    window = MainWindow(config, bus, demo=True)
    try:
        window._run_diagnostics()
        messages = [e.message for e in bus.drain()]
        assert any("룬 해제 진단 시작" in m for m in messages)
        assert any("스페이스바" in m for m in messages), messages
        assert any("방향별 최고 점수" in m for m in messages)
        assert any("진단 결과" in m for m in messages)
    finally:
        window.close()


def test_activation_settings_round_trip(app):
    """스페이스바 문제 해결에 쓰는 항목들이 설정에 반영되어야 한다."""
    config = AppConfig()
    window = MainWindow(config, EventBus(), demo=True)
    try:
        window.activate_press.setValue(180)
        window.activate_settle.setValue(0.45)
        window.activate_gap.setValue(0.9)
        window.activate_taps.setValue(4)
        window.nudge_ms.setValue(120)
        window.collect()

        assert config.rune.activate_press_ms == 180
        assert config.rune.activate_settle == pytest.approx(0.45)
        assert config.rune.activate_gap == pytest.approx(0.9)
        assert config.rune.activate_taps == 4
        assert config.rune.minimap.nudge_ms == 120

        window.refresh_from_config()
        assert window.activate_press.value() == 180
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
