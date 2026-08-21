"""미니맵 기반 룬 탐색 검증.

이 서버의 룬 해제 방식은 "미니맵의 노란 캐릭터 표식이 보라색 룬 표식을 덮도록
이동 → 스페이스바 → 방향키" 이므로, 미니맵 좌표 인식과 정렬 로직이 핵심이다.
룬이 화면 밖에 있어도 동작해야 한다.
"""

from __future__ import annotations

import pytest

from rune_hunter.config import AppConfig, Roi
from rune_hunter.demo import DemoSettings, DemoWorld
from rune_hunter.engine.clock import ManualClock
from rune_hunter.engine.rune_solver import RuneOutcome, RuneSolver
from rune_hunter.inputs.recorder import RecordingBackend
from rune_hunter.vision import synth
from rune_hunter.vision.minimap import MinimapVision

MM_X, MM_Y, MM_W, MM_H = synth.MINIMAP_RECT


def minimap_roi(width: int = 1024, height: int = 768) -> Roi:
    return Roi(MM_X / width, MM_Y / height, MM_W / width, MM_H / height)


@pytest.fixture
def mm_config(config: AppConfig) -> AppConfig:
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.roi = minimap_roi()
    config.rune.activate_key = "SPACE"
    config.rune.minimap.max_seconds = 30.0
    return config


def build_world(clock, offset=(0, 0), settings: DemoSettings | None = None) -> DemoWorld:
    world = DemoWorld(
        settings=settings or DemoSettings(first_rune_after=0.0, activate_key="SPACE"),
        time_fn=clock.now,
    )
    world.rune_present = True
    world.rune_offset = offset
    world.next_spawn = float("inf")
    return world


# --- 인식 ---------------------------------------------------------------
def test_reads_rune_and_character_markers(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(280, 0))
    reading = MinimapVision(mm_config).read(world.render())

    assert reading.found
    assert reading.dx == pytest.approx(20, abs=2)  # 280px / 배율 14 = 20
    assert reading.dy == pytest.approx(0, abs=1)


@pytest.mark.parametrize(
    "offset,expect_dx,expect_dy",
    [
        ((0, 0), 0, 0),
        ((560, 0), 40, 0),
        ((-280, 0), -20, 0),
        ((0, 140), 0, -10),   # 룬이 위 → 미니맵 y 는 더 작다
        ((0, -140), 0, 10),   # 룬이 아래
    ],
)
def test_marker_offsets_match_expected_direction(mm_config, offset, expect_dx, expect_dy):
    clock = ManualClock()
    world = build_world(clock, offset=offset)
    reading = MinimapVision(mm_config).read(world.render())
    assert reading.dx == pytest.approx(expect_dx, abs=2)
    assert reading.dy == pytest.approx(expect_dy, abs=2)


def test_no_rune_marker_when_rune_absent(mm_config):
    clock = ManualClock()
    world = build_world(clock)
    world.rune_present = False
    frame = world.render()
    vision = MinimapVision(mm_config)

    assert vision.rune_present(frame) is False
    reading = vision.read(frame)
    assert reading.rune is None
    assert reading.char is not None  # 캐릭터 표식은 항상 있다


def test_roi_outside_minimap_finds_nothing(mm_config):
    clock = ManualClock()
    world = build_world(clock)
    mm_config.rune.minimap.roi = Roi(0.6, 0.6, 0.3, 0.3)
    reading = MinimapVision(mm_config).read(world.render())
    assert reading.rune is None and reading.char is None


def test_detects_rune_that_is_off_screen(mm_config):
    """화면 밖 룬(스프라이트가 안 보임)도 미니맵으로는 감지된다."""
    clock = ManualClock()
    world = build_world(clock, offset=(700, 0))  # 화면 밖
    frame = world.render()

    from rune_hunter.vision import RuneVision
    from rune_hunter.vision.matcher import template_from_array
    from rune_hunter.vision.synth import demo_templates

    template_vision = RuneVision(mm_config)
    for name, image in demo_templates().items():
        template_vision.register_template(name, template_from_array(image, name))

    assert template_vision.detect_rune(frame) is None, "화면에는 룬이 없어야 한다"
    assert MinimapVision(mm_config).rune_present(frame) is True


# --- 색 추출 ------------------------------------------------------------
def test_sample_color_from_marker_crop(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(280, 0))
    frame = world.render()
    reading = MinimapVision(mm_config).read(frame)
    rune = reading.rune
    assert rune is not None

    # 미니맵 좌표 → 화면 좌표로 옮겨서 표식 주변을 잘라낸다
    x, y, _, _ = reading.roi
    cx, cy = x + rune.cx, y + rune.cy
    crop = frame[cy - 2 : cy + 3, cx - 2 : cx + 3]

    spec = MinimapVision.sample_color(crop)
    mm_config.rune.minimap.rune_color = spec
    again = MinimapVision(mm_config).read(frame)
    assert again.rune is not None
    assert abs(again.rune.cx - rune.cx) <= 1


# --- 정렬 + 해제 --------------------------------------------------------
def solver_for(mm_config, world, clock, backend):
    return RuneSolver(
        config=mm_config,
        vision=_template_vision(mm_config),
        inputs=backend,
        frames=lambda: world.render(),
        bus=_bus(),
        clock=clock,
    )


def _template_vision(config):
    from rune_hunter.vision import RuneVision
    from rune_hunter.vision.matcher import template_from_array
    from rune_hunter.vision.synth import demo_templates

    vision = RuneVision(config)
    for name, image in demo_templates().items():
        vision.register_template(name, template_from_array(image, name))
    return vision


def _bus():
    from rune_hunter.logging_bus import EventBus

    return EventBus()


def moves_before_activation(backend: RecordingBackend) -> list[str]:
    """활성화(SPACE) 이전에 누른 좌우 이동 키만 센다.

    활성화 이후의 방향키는 룬 해제용 화살표 입력이라 이동이 아니다.
    """
    taps = backend.taps()
    if "SPACE" in taps:
        taps = taps[: taps.index("SPACE")]
    return [k for k in taps if k in ("LEFT", "RIGHT")]


@pytest.mark.parametrize("offset", [(0, 0), (300, 0), (-450, 0), (700, 0)])
def test_aligns_on_minimap_then_solves_with_space(mm_config, offset):
    clock = ManualClock()
    world = build_world(clock, offset=offset)
    backend = RecordingBackend(sink=world.on_key)
    attempt = solver_for(mm_config, world, clock, backend).solve()

    assert attempt.outcome is RuneOutcome.SUCCESS, attempt.detail
    assert world.solved == 1
    assert "SPACE" in backend.taps(), "활성화는 스페이스바로 해야 한다"
    tolerance_px = mm_config.rune.minimap.align_tolerance * world.settings.minimap_scale
    assert abs(world.rune_offset[0]) <= tolerance_px + 15


def test_alignment_converges_in_few_moves(mm_config):
    """자동 보정이 동작하면 몇 번의 이동으로 정렬이 끝나야 한다."""
    clock = ManualClock()
    world = build_world(clock, offset=(600, 0))
    backend = RecordingBackend(sink=world.on_key)
    solver_for(mm_config, world, clock, backend).solve()

    moves = moves_before_activation(backend)
    assert world.solved == 1
    assert len(moves) <= 8, f"이동 횟수가 너무 많다: {len(moves)}"


def test_climbs_with_rope_when_rune_is_above(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(0, 150))
    backend = RecordingBackend(sink=world.on_key)
    attempt = solver_for(mm_config, world, clock, backend).solve()

    assert attempt.outcome is RuneOutcome.SUCCESS
    assert mm_config.keys.rope in backend.taps()


def test_gives_up_when_rune_marker_disappears(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(500, 0))
    backend = RecordingBackend(sink=world.on_key)
    solver = solver_for(mm_config, world, clock, backend)

    original = world.render
    calls = {"n": 0}

    def vanishing():
        calls["n"] += 1
        if calls["n"] > 2:  # 이동 도중 다른 사람이 룬을 먹은 상황
            world.rune_present = False
        return original()

    solver.frames = vanishing
    attempt = solver.solve()
    assert attempt.outcome is RuneOutcome.APPROACH_TIMEOUT
    assert "사라졌" in attempt.detail


def test_reports_missing_character_marker(mm_config):
    """캐릭터 색 설정이 틀리면 원인을 알 수 있게 보고해야 한다."""
    clock = ManualClock()
    world = build_world(clock, offset=(300, 0))
    mm_config.rune.minimap.char_color.lower = [90, 200, 200]
    mm_config.rune.minimap.char_color.upper = [95, 255, 255]
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()
    assert attempt.outcome is RuneOutcome.APPROACH_TIMEOUT
    assert "캐릭터" in attempt.detail


def test_does_not_move_when_already_aligned(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(0, 0))
    backend = RecordingBackend(sink=world.on_key)
    solver_for(mm_config, world, clock, backend).solve()

    assert moves_before_activation(backend) == []
