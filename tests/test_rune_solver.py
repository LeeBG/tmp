"""룬 해제 상태 머신 검증.

가상 시계 + 가짜 게임 세계(DemoWorld)로 접근 → 활성화 → 판독 → 입력 → 확인
전 과정을 실시간 대기 없이 돌린다.
"""

from __future__ import annotations

import numpy as np
import pytest

from rune_hunter.demo import DemoSettings, DemoWorld
from rune_hunter.engine.clock import ManualClock
from rune_hunter.engine.rune_solver import RuneOutcome, RuneSolver
from rune_hunter.inputs.recorder import RecordingBackend
from rune_hunter.keys import ARROW_KEYS
from rune_hunter.vision.synth import render_screen


def build(config, vision, bus, offset=(0, 0), approach=True, abort=None):
    clock = ManualClock()
    world = DemoWorld(
        settings=DemoSettings(first_rune_after=0.0),
        bus=bus,
        time_fn=clock.now,
    )
    world.rune_present = True
    world.rune_offset = offset
    world.next_spawn = float("inf")
    backend = RecordingBackend(sink=world.on_key)
    config.rune.approach.enabled = approach
    solver = RuneSolver(
        config=config,
        vision=vision,
        inputs=backend,
        frames=lambda: world.render(),
        bus=bus,
        clock=clock,
        abort=abort or (lambda: False),
    )
    return solver, world, backend, clock


def test_solves_rune_in_front_of_character(config, vision, bus):
    solver, world, backend, _ = build(config, vision, bus, offset=(0, 0))
    attempt = solver.solve()

    assert attempt.outcome is RuneOutcome.SUCCESS
    assert world.solved == 1
    assert world.wrong_inputs == 0
    assert attempt.arrows == world.expected or len(attempt.arrows) == 4
    arrows_sent = [k for k in backend.taps() if k in ARROW_KEYS][1:]  # 첫 UP 은 활성화 입력
    assert arrows_sent[: len(attempt.arrows)] == attempt.arrows


def test_reads_the_exact_sequence_shown(config, vision, bus):
    """판독 결과가 화면에 표시된 순서와 정확히 같아야 한다."""
    for seed in range(4):
        solver, world, _, _ = build(config, vision, bus)
        world.rng.seed(seed)
        attempt = solver.solve()
        assert attempt.outcome is RuneOutcome.SUCCESS
        assert attempt.arrows == world.expected


def test_approach_moves_horizontally_when_rune_is_far(config, vision, bus):
    solver, world, backend, _ = build(config, vision, bus, offset=(260, 0))
    attempt = solver.solve()

    assert attempt.outcome is RuneOutcome.SUCCESS
    assert "RIGHT" in backend.taps()[:6], "룬이 오른쪽에 있으면 오른쪽으로 이동해야 한다"
    assert abs(world.rune_offset[0]) <= config.rune.approach.deadzone_px


def test_approach_uses_rope_when_rune_is_above(config, vision, bus):
    config.rune.approach.use_rope = True
    solver, world, backend, _ = build(config, vision, bus, offset=(0, 150))
    attempt = solver.solve()

    assert attempt.outcome is RuneOutcome.SUCCESS
    assert config.keys.rope in backend.taps(), "위쪽 룬은 로프 커넥트로 올라가야 한다"


def test_approach_uses_down_jump_when_rune_is_below(config, vision, bus):
    solver, world, backend, _ = build(config, vision, bus, offset=(0, -150))
    solver.solve()
    events = backend.taps()
    assert "DOWN" in events and config.keys.jump in events


def test_no_rune_returns_quickly(config, vision, bus):
    clock = ManualClock()
    backend = RecordingBackend()
    solver = RuneSolver(
        config=config,
        vision=vision,
        inputs=backend,
        frames=lambda: render_screen(seed=1),
        bus=bus,
        clock=clock,
    )
    attempt = solver.solve()
    assert attempt.outcome is RuneOutcome.NO_RUNE
    assert backend.events == []


def test_abort_stops_immediately(config, vision, bus):
    flag = {"stop": False}
    solver, world, backend, _ = build(
        config, vision, bus, offset=(300, 0), abort=lambda: flag["stop"]
    )
    flag["stop"] = True
    attempt = solver.solve()
    assert attempt.outcome is RuneOutcome.ABORTED
    assert backend.held_keys == set()


def test_verify_failure_gives_up_after_retries(config, vision, bus):
    """화살표 UI 가 사라지지 않으면 재시도 후 실패로 끝나야 한다 (무한 대기 금지)."""
    config.rune.max_retries = 1
    frame = render_screen(rune_pos=(512, 422), arrows=["UP", "UP", "DOWN", "DOWN"])
    clock = ManualClock()
    backend = RecordingBackend()
    solver = RuneSolver(
        config=config,
        vision=vision,
        inputs=backend,
        frames=lambda: frame,
        bus=bus,
        clock=clock,
        abort=lambda: False,
    )
    attempt = solver.solve()
    assert attempt.outcome is RuneOutcome.VERIFY_FAILED
    assert attempt.retries == 1
    assert clock.now() < 1000 + 60, "실패 처리에 1분 이상 쓰면 안 된다"


def test_all_keys_released_after_solve(config, vision, bus):
    solver, world, backend, _ = build(config, vision, bus, offset=(200, 150))
    solver.solve()
    assert backend.held_keys == set()


def test_capture_failure_is_handled(config, vision, bus):
    clock = ManualClock()
    backend = RecordingBackend()
    solver = RuneSolver(
        config=config,
        vision=vision,
        inputs=backend,
        frames=lambda: None,
        bus=bus,
        clock=clock,
    )
    assert solver.solve().outcome is RuneOutcome.NO_RUNE


def test_solver_survives_broken_frames(config, vision, bus):
    """이상한 프레임이 와도 예외로 죽지 않는다."""
    clock = ManualClock()
    backend = RecordingBackend()
    frames = iter(
        [np.zeros((10, 10, 3), dtype=np.uint8), render_screen(rune_pos=(512, 422))]
    )
    solver = RuneSolver(
        config=config,
        vision=vision,
        inputs=backend,
        frames=lambda: next(frames, render_screen()),
        bus=bus,
        clock=clock,
    )
    attempt = solver.solve()
    assert attempt.outcome in tuple(RuneOutcome)


@pytest.mark.parametrize("offset", [(0, 0), (120, 0), (-200, 0), (60, 150), (-60, -150)])
def test_various_positions_all_solve(config, vision, bus, offset):
    solver, world, _, _ = build(config, vision, bus, offset=offset)
    assert solver.solve().outcome is RuneOutcome.SUCCESS
    assert world.solved == 1
