"""엔진 통합 테스트 (실제 스레드 + 실시간, 각 케이스 1~4초).

가짜 게임 세계와 기록용 입력 백엔드를 쓰기 때문에 실제 키는 나가지 않는다.
"""

from __future__ import annotations

import time

from rune_hunter.demo import DemoSettings, DemoWorld
from rune_hunter.engine.engine import EngineState, MacroEngine
from rune_hunter.inputs.recorder import RecordingBackend
from rune_hunter.platform_layer.windows import VirtualWindowLocator, WindowInfo
from rune_hunter.vision.matcher import template_from_array
from rune_hunter.vision.synth import demo_templates


def _prepare(vision):
    for name, image in demo_templates().items():
        vision.register_template(name, template_from_array(image, name))
    return vision


def build_engine(config, vision, bus, world=None, locator=None, backend=None):
    _prepare(vision)
    world = world or DemoWorld(settings=DemoSettings(first_rune_after=9999), bus=bus)
    backend = backend or RecordingBackend(sink=world.on_key)
    locator = locator or VirtualWindowLocator(
        world.settings.width, world.settings.height, "테스트 창"
    )
    engine = MacroEngine(
        config=config,
        inputs=backend,
        capture=world,
        locator=locator,
        vision=vision,
        bus=bus,
    )
    return engine, world, backend


def run_for(engine, seconds: float) -> None:
    engine.start()
    time.sleep(seconds)
    engine.stop()


def test_hunt_key_repeats_at_configured_rate(config, vision, bus):
    config.rune.enabled = False
    config.attack.hunt.key = "U"
    config.attack.hunt.interval = 0.05
    for buff in config.attack.buffs:
        buff.enabled = False
    engine, _, backend = build_engine(config, vision, bus)

    run_for(engine, 1.0)

    presses = backend.count("U")
    assert 12 <= presses <= 28, f"1초에 {presses}회 (기대 약 20회)"


def test_hold_mode_keeps_key_down_and_releases_on_stop(config, vision, bus):
    config.rune.enabled = False
    config.attack.hunt.hold = True
    config.attack.hunt.key = "V"
    engine, _, backend = build_engine(config, vision, bus)

    engine.start()
    time.sleep(0.4)
    assert "V" in backend.held_keys
    engine.stop()

    assert backend.held_keys == set()
    assert backend.events[-1].action == "up"


def test_buffs_fire_once_at_start(config, vision, bus):
    config.rune.enabled = False
    config.attack.hunt.enabled = False
    config.attack.buffs[0].key = "Q"
    config.attack.buffs[0].interval = 120.0
    config.attack.buffs[1].key = "E"
    config.attack.buffs[1].interval = 120.0
    config.attack.buffs[1].enabled = True
    engine, _, backend = build_engine(config, vision, bus)

    run_for(engine, 0.6)

    assert backend.count("Q") == 1
    assert backend.count("E") == 1


def test_no_skill_input_while_solving_rune(config, vision, bus):
    """핵심 요구사항: 룬 해제 중에는 사냥·버프 키가 한 번도 나가면 안 된다."""
    config.attack.hunt.key = "U"
    config.attack.hunt.interval = 0.05
    config.rune.check_interval = 0.2
    world = DemoWorld(settings=DemoSettings(first_rune_after=0.4, respawn_after=99), bus=bus)

    violations: list[str] = []
    skill_keys = {"U", "Q", "W"}

    class Guarded(RecordingBackend):
        def _send(self, key: str, down: bool) -> None:
            if engine.state is EngineState.RUNE and key.upper() in skill_keys and down:
                violations.append(key.upper())
            super()._send(key, down)

    backend = Guarded(sink=world.on_key)
    engine, _, _ = build_engine(config, vision, bus, world=world, backend=backend)

    run_for(engine, 5.0)

    assert world.solved >= 1, "데모 세계에서 룬이 해제되지 않았다"
    assert violations == [], f"룬 해제 중 스킬 키 입력 발생: {violations}"
    assert engine.status().stats.rune_success >= 1


def test_hunting_resumes_after_rune(config, vision, bus):
    config.attack.hunt.key = "U"
    config.attack.hunt.interval = 0.05
    config.rune.check_interval = 0.2
    config.rune.cooldown_success = 5.0
    world = DemoWorld(settings=DemoSettings(first_rune_after=0.3, respawn_after=99), bus=bus)
    engine, _, backend = build_engine(config, vision, bus, world=world)

    engine.start()
    time.sleep(4.0)
    before = backend.count("U")
    time.sleep(1.0)
    after = backend.count("U")
    engine.stop()

    assert world.solved >= 1
    assert after - before >= 8, "룬 해제 후 사냥키 입력이 재개되지 않았다"


def test_pending_buff_is_used_after_rune(config, vision, bus):
    """해제 중 주기가 지난 버프는 재개 직후 사용된다."""
    config.attack.hunt.enabled = False
    config.attack.buffs[0].key = "Q"
    config.attack.buffs[0].interval = 1.0
    for buff in config.attack.buffs[1:]:
        buff.enabled = False
    config.rune.check_interval = 0.2
    world = DemoWorld(settings=DemoSettings(first_rune_after=0.5, respawn_after=99), bus=bus)
    engine, _, backend = build_engine(config, vision, bus, world=world)

    run_for(engine, 4.0)

    assert world.solved >= 1
    assert backend.count("Q") >= 2


def test_minimap_mode_solves_rune_that_is_off_screen(config, vision, bus):
    """미니맵 모드: 룬이 화면에 안 보여도 미니맵으로 찾아 이동 후 해제한다."""
    from rune_hunter.config import Roi
    from rune_hunter.vision import synth

    mm_x, mm_y, mm_w, mm_h = synth.MINIMAP_RECT
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.roi = Roi(mm_x / 1024, mm_y / 768, mm_w / 1024, mm_h / 768)
    config.rune.activate_key = "SPACE"
    config.rune.check_interval = 0.25
    config.rune.cooldown_success = 10.0
    config.attack.hunt.key = "U"
    config.attack.hunt.interval = 0.05

    world = DemoWorld(
        settings=DemoSettings(
            first_rune_after=0.3,
            respawn_after=99,
            activate_key="SPACE",
            max_offset_x=430,
        ),
        bus=bus,
    )
    engine, _, backend = build_engine(config, vision, bus, world=world)

    engine.start()
    time.sleep(12.0)
    engine.stop()

    assert world.spawned >= 1
    assert world.solved >= 1, "미니맵 정렬 후 해제가 완료되지 않았다"
    assert engine.status().stats.rune_success >= 1
    assert "SPACE" in backend.taps()
    assert backend.count("U") > 10, "해제 후 사냥이 재개되어야 한다"


def test_start_warns_about_broken_rune_settings(config, vision, bus):
    """시작할 때 룬 해제를 망가뜨리는 설정을 미리 알려줘야 한다."""
    config.rune.enabled = False  # 실제 해제는 돌리지 않고 경고만 확인
    config.attack.hunt.enabled = False
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.rune_color = config.rune.minimap.char_color
    config.rune.activate_key = "UP"
    engine, _, _ = build_engine(config, vision, bus)

    config.rune.enabled = True
    engine._warn_about_config()
    messages = [e.message for e in bus.drain()]

    assert any("설정 점검" in m and "겹칩니다" in m for m in messages), messages
    assert any("스페이스바" in m for m in messages), messages


def test_no_input_when_window_missing(config, vision, bus):
    class Missing:
        def find(self, titles):
            return None

        def refresh(self, info):
            return None

        def is_foreground(self, info):
            return False

    engine, _, backend = build_engine(config, vision, bus, locator=Missing())
    run_for(engine, 0.8)

    assert backend.events == []
    assert engine.status().state is EngineState.STOPPED


def test_no_input_when_window_not_focused(config, vision, bus):
    class Background(VirtualWindowLocator):
        def is_foreground(self, info: WindowInfo) -> bool:  # noqa: ARG002
            return False

    config.general.only_when_focused = True
    engine, _, backend = build_engine(config, vision, bus, locator=Background())
    run_for(engine, 0.8)

    assert backend.events == []


def test_control_loop_does_not_spin_cpu(config, vision, bus):
    """할 일이 없을 때 루프가 CPU 를 태우지 않아야 한다 (과거 회귀 버그)."""
    config.attack.hunt.interval = 0.5
    config.rune.check_interval = 5.0
    config.rune.cooldown_success = 5.0
    engine, _, _ = build_engine(config, vision, bus)

    run_for(engine, 1.0)

    loops = engine.status().stats.loops
    assert loops < 8000, f"1초에 {loops:,}회 루프 — 스핀 상태"


def test_stats_track_detection_cost(config, vision, bus):
    config.rune.check_interval = 0.15
    engine, _, _ = build_engine(config, vision, bus)
    run_for(engine, 1.2)

    stats = engine.status().stats
    assert stats.detections >= 3
    assert 0 < stats.detect_ms_avg < 200
    assert stats.capture_count >= stats.detections


def test_engine_restart_is_clean(config, vision, bus):
    config.rune.enabled = False
    config.attack.hunt.interval = 0.05
    engine, _, backend = build_engine(config, vision, bus)

    run_for(engine, 0.5)
    first = backend.count(config.attack.hunt.key)
    run_for(engine, 0.5)
    second = backend.count(config.attack.hunt.key)

    assert second > first
    assert backend.held_keys == set()
    assert engine.running is False
