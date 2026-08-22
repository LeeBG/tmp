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
    cx, cy = int(round(x + rune.cx)), int(round(y + rune.cy))
    crop = frame[cy - 2 : cy + 3, cx - 2 : cx + 3]

    spec = MinimapVision.sample_color(crop)
    mm_config.rune.minimap.rune_color = spec
    again = MinimapVision(mm_config).read(frame)
    assert again.rune is not None
    assert abs(again.rune.cx - rune.cx) <= 1


# --- 정렬 + 해제 --------------------------------------------------------
def solver_for(mm_config, world, clock, backend, bus=None, vision=None):
    return RuneSolver(
        config=mm_config,
        vision=vision or _template_vision(mm_config),
        inputs=backend,
        frames=lambda: world.render(),
        bus=bus or _bus(),
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


def test_sample_color_ignores_dark_background(mm_config):
    """배경이 대부분인 영역을 드래그해도 표식 색을 뽑아야 한다."""
    import numpy as np

    from rune_hunter.vision.synth import MINIMAP_RUNE_BGR

    crop = np.full((7, 7, 3), (48, 42, 40), dtype=np.uint8)  # 미니맵 배경
    crop[3:5, 3:5] = MINIMAP_RUNE_BGR                        # 가운데 표식 몇 픽셀

    spec = MinimapVision.sample_color(crop)
    mm_config.rune.minimap.rune_color = spec

    clock = ManualClock()
    world = build_world(clock, offset=(280, 0))
    reading = MinimapVision(mm_config).read(world.render())
    assert reading.rune is not None, f"배경 색을 뽑았다: {spec.describe()}"
    assert reading.ambiguous is False
    assert reading.dx == pytest.approx(20, abs=2)


def test_covered_marker_counts_as_aligned(mm_config):
    """겹치는 순간 보라색이 노란색에 가려지는데, 이걸 '사라짐'으로 보면 안 된다."""
    clock = ManualClock()
    settings = DemoSettings(
        first_rune_after=0.0, activate_key="SPACE", minimap_occlude_px=3
    )
    world = build_world(clock, offset=(300, 0), settings=settings)
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()

    assert attempt.outcome is RuneOutcome.SUCCESS, attempt.detail
    assert world.solved == 1
    assert "SPACE" in backend.taps()


def test_marker_vanishing_far_away_is_still_a_failure(mm_config):
    """멀리서 표식이 사라지면(다른 사람이 먹은 경우) 실패로 처리해야 한다."""
    clock = ManualClock()
    world = build_world(clock, offset=(600, 0))
    backend = RecordingBackend(sink=world.on_key)
    solver = solver_for(mm_config, world, clock, backend)

    original = world.render
    calls = {"n": 0}

    def vanishing():
        calls["n"] += 1
        if calls["n"] > 2:
            world.rune_present = False
        return original()

    solver.frames = vanishing
    attempt = solver.solve()
    assert attempt.outcome is RuneOutcome.APPROACH_TIMEOUT
    assert "사라졌" in attempt.detail


def test_occluded_alignment_from_various_distances(mm_config):
    for offset in [(0, 0), (150, 0), (-420, 0), (100, 150)]:
        clock = ManualClock()
        settings = DemoSettings(
            first_rune_after=0.0, activate_key="SPACE", minimap_occlude_px=3
        )
        world = build_world(clock, offset=offset, settings=settings)
        backend = RecordingBackend(sink=world.on_key)
        attempt = solver_for(mm_config, world, clock, backend).solve()
        assert attempt.outcome is RuneOutcome.SUCCESS, f"{offset}: {attempt.detail}"


def test_detects_overlapping_color_ranges(mm_config):
    """룬 색과 캐릭터 색이 같은 표식을 가리키면 정렬 완료로 착각하면 안 된다."""
    clock = ManualClock()
    world = build_world(clock, offset=(300, 0))
    # 실수 재현: 룬 색을 캐릭터(노랑) 범위로 잡아버린 경우
    mm_config.rune.minimap.rune_color = mm_config.rune.minimap.char_color

    reading = MinimapVision(mm_config).read(world.render())
    assert reading.found
    assert reading.dx == pytest.approx(0, abs=0.5)  # 같은 표식이라 차이가 없다
    assert reading.ambiguous is True
    assert reading.overlap > 0.5
    assert reading.usable is False
    assert "겹칩니다" in reading.describe()


def test_ambiguous_colors_abort_with_clear_message(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(300, 0))
    mm_config.rune.minimap.rune_color = mm_config.rune.minimap.char_color
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()
    assert attempt.outcome is RuneOutcome.NO_RUNE or "겹" in attempt.detail
    assert world.solved == 0


def test_rune_present_is_false_when_colors_are_ambiguous(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(300, 0))
    mm_config.rune.minimap.rune_color = mm_config.rune.minimap.char_color
    assert MinimapVision(mm_config).rune_present(world.render()) is False


def test_ranges_overlap_helper(mm_config):
    mm = mm_config.rune.minimap
    assert MinimapVision.ranges_overlap(mm.rune_color, mm.rune_color) is True
    assert MinimapVision.ranges_overlap(mm.rune_color, mm.char_color) is False


def test_zero_tolerance_still_completes(mm_config):
    """허용 오차를 0 으로 둬도 무한 루프에 빠지지 않아야 한다."""
    mm_config.rune.minimap.align_tolerance = 0
    mm_config.rune.minimap.vertical_tolerance = 0
    clock = ManualClock()
    world = build_world(clock, offset=(200, 0))
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()
    assert attempt.outcome is RuneOutcome.SUCCESS


def test_subpixel_marker_coordinates(mm_config):
    """좌표가 소수점까지 유지되어야 미세한 차이를 구분할 수 있다."""
    clock = ManualClock()
    world = build_world(clock, offset=(210, 0))  # 210/14 = 15px
    reading = MinimapVision(mm_config).read(world.render())
    assert isinstance(reading.dx, float)
    assert reading.dx == pytest.approx(15, abs=1.5)


def test_debug_image_marks_both_markers(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(280, 0))
    image = MinimapVision(mm_config).debug_image(world.render(), scale=4)
    _, _, w, h = mm_config.rune.minimap.roi.to_pixels(1024, 768)
    assert image.shape[0] == h * 4 and image.shape[1] == w * 4


def test_nudges_and_retries_when_activation_fails(mm_config, bus):
    """정렬 후에도 스페이스바가 안 먹으면 미세 이동 후 다시 시도해야 한다."""
    clock = ManualClock()
    # 활성화 반경을 아주 좁혀서 첫 시도가 실패하도록 만든다
    settings = DemoSettings(
        first_rune_after=0.0, activate_key="SPACE", activate_radius_x=8
    )
    world = build_world(clock, offset=(30, 0), settings=settings)
    mm_config.rune.activate_taps = 4
    mm_config.rune.minimap.nudge_ms = 60
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()
    assert world.activate_presses >= 2, "활성화를 여러 번 시도해야 한다"
    assert attempt.outcome in (RuneOutcome.SUCCESS, RuneOutcome.ACTIVATE_TIMEOUT)


# --- 활성화 단계 (사용자가 실패한 지점) -----------------------------------
def test_zigzag_search_finds_the_exact_spot(mm_config):
    """미니맵 정렬 오차 안에 있어도 실제로는 몇십 px 어긋난다 — 지그재그로 찾아내야 한다.

    미니맵 1px = 실제 14px 이라 '정렬 완료' 시점에도 최대 28px 이 남는다.
    활성화 반경이 그보다 좁으면 첫 스페이스바는 반드시 빗나간다.
    """
    clock = ManualClock()
    settings = DemoSettings(
        first_rune_after=0.0, activate_key="SPACE", activate_radius_x=10
    )
    world = build_world(clock, offset=(20, 0), settings=settings)
    mm_config.rune.activate_taps = 5
    mm_config.rune.minimap.nudge_ms = 60  # 60ms ≒ 27px 이동
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()

    assert attempt.outcome is RuneOutcome.SUCCESS, attempt.summary
    assert world.activate_presses >= 2, "첫 시도는 빗나가고 미세 이동 후 성공해야 한다"
    assert world.solved == 1


def test_short_activation_press_is_reported_and_long_one_succeeds(mm_config):
    """활성화 키를 짧게 누르면 게임이 놓친다 — 누름 시간 설정이 실제로 전달되어야 한다."""
    settings = lambda: DemoSettings(  # noqa: E731
        first_rune_after=0.0, activate_key="SPACE", activate_press_min_ms=100
    )
    mm_config.rune.activate_taps = 2

    clock = ManualClock()
    world = build_world(clock, offset=(0, 0), settings=settings())
    mm_config.rune.activate_press_ms = 30
    attempt = solver_for(
        mm_config, world, clock, RecordingBackend(sink=world.on_key)
    ).solve()
    assert attempt.outcome is RuneOutcome.ACTIVATE_TIMEOUT
    assert world.short_press_ignored >= 1
    assert world.solved == 0

    clock = ManualClock()
    world = build_world(clock, offset=(0, 0), settings=settings())
    mm_config.rune.activate_press_ms = 120
    attempt = solver_for(
        mm_config, world, clock, RecordingBackend(sink=world.on_key)
    ).solve()
    assert attempt.outcome is RuneOutcome.SUCCESS, attempt.summary
    assert world.short_press_ignored == 0


def test_solves_even_when_character_slides_after_moving(mm_config):
    """방향키를 뗀 뒤 관성으로 미끄러져도 결국 해제해야 한다."""
    clock = ManualClock()
    settings = DemoSettings(
        first_rune_after=0.0,
        activate_key="SPACE",
        activate_radius_x=30,
        slide_px=40,
        slide_seconds=0.25,
    )
    world = build_world(clock, offset=(400, 0), settings=settings)
    mm_config.rune.activate_taps = 5
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend).solve()
    assert attempt.outcome is RuneOutcome.SUCCESS, attempt.summary


def test_activation_failure_summary_and_snapshot(mm_config, bus, tmp_path, monkeypatch):
    """끝내 활성화가 안 되면 단계별 요약과 실패 화면이 남아야 한다."""
    from rune_hunter import diagnostics

    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path)
    clock = ManualClock()
    settings = DemoSettings(
        first_rune_after=0.0, activate_key="SPACE", activate_radius_x=-1
    )  # 반경 -1 = 어디서 눌러도 활성화되지 않는 세계
    world = build_world(clock, offset=(0, 0), settings=settings)
    mm_config.rune.activate_taps = 2
    mm_config.rune.max_retries = 1
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(mm_config, world, clock, backend, bus=bus).solve()

    assert attempt.outcome is RuneOutcome.ACTIVATE_TIMEOUT
    assert "감지 O" in attempt.summary and "활성화 X" in attempt.summary
    assert "UI 미출현" in attempt.summary
    assert attempt.trace.activate_taps >= 2

    messages = [e.message for e in bus.drain()]
    assert any("룬 해제 실패 요약" in m for m in messages), messages
    assert any("확인할 것" in m for m in messages)
    assert any("실패 시점 화면 저장" in m for m in messages)

    saved = list(tmp_path.glob("activate_fail_*.png"))
    assert saved, "활성화 실패 시 화면이 저장되어야 한다"
    assert any("minimap" in p.name for p in saved), "미니맵 진단 이미지도 함께 저장한다"


def test_waits_for_character_to_settle_before_activating(mm_config):
    """이동 직후 바로 누르면 관성 때문에 빗나간다 — 안정화 대기가 실제로 들어가야 한다."""
    clock = ManualClock()
    world = build_world(clock, offset=(300, 0))
    mm_config.rune.activate_settle = 0.5
    stamps: list[tuple[float, str, str]] = []

    def sink(event):
        stamps.append((clock.now(), event.key, event.action))
        world.on_key(event)

    solver_for(mm_config, world, clock, RecordingBackend(sink=sink)).solve()

    space_at = next(t for t, k, a in stamps if k == "SPACE" and a == "down")
    moves = [t for t, k, a in stamps if k in ("LEFT", "RIGHT") and a == "up" and t < space_at]
    assert moves, "이동이 한 번은 있어야 하는 상황이다"
    assert space_at - max(moves) >= 0.5


def test_arrow_ui_appeared_but_templates_missing_is_distinguished(mm_config, bus, tmp_path, monkeypatch):
    """스페이스바는 먹었는데 화살표 템플릿이 없어서 못 읽는 상황을 구분해야 한다.

    이 경우 사용자에게 '활성화가 안 된다' 가 아니라 '템플릿을 확인하라' 고 알려야 한다.
    """
    from rune_hunter import diagnostics
    from rune_hunter.vision import RuneVision

    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path)
    mm_config.rune.template_dir = str(tmp_path)  # 화살표 템플릿이 없는 폴더
    mm_config.rune.activate_taps = 2
    mm_config.rune.max_retries = 0
    clock = ManualClock()
    world = build_world(clock, offset=(0, 0))
    backend = RecordingBackend(sink=world.on_key)

    attempt = solver_for(
        mm_config, world, clock, backend, bus=bus, vision=RuneVision(mm_config)
    ).solve()

    assert attempt.outcome is RuneOutcome.ACTIVATE_TIMEOUT
    assert attempt.trace.ui_changed is True
    assert "화면은 변함" in attempt.summary
    messages = [e.message for e in bus.drain()]
    assert any("화살표 템플릿" in m for m in messages), messages


def test_does_not_move_when_already_aligned(mm_config):
    clock = ManualClock()
    world = build_world(clock, offset=(0, 0))
    backend = RecordingBackend(sink=world.on_key)
    solver_for(mm_config, world, clock, backend).solve()

    assert moves_before_activation(backend) == []
