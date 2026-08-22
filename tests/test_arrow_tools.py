"""화살표 템플릿 회전 생성 · 판독 진단 · 안내 문구 감지 검증.

실제 게임의 룬 화살표 4개는 같은 스프라이트를 90도씩 돌린 것이므로,
한 장만 캡처해도 나머지 세 방향을 정확히 만들어낼 수 있어야 한다.
"""

from __future__ import annotations

import numpy as np
import pytest

from rune_hunter.config import Roi
from rune_hunter.vision.matcher import (
    TemplateMatcher,
    rotate_clockwise,
    rotate_to_direction,
    template_from_array,
)
from rune_hunter.vision.rune import RuneVision
from rune_hunter.vision.synth import arrow_glyph, render_screen

DIRECTIONS = ("UP", "RIGHT", "DOWN", "LEFT")


def test_rotate_clockwise_cycles_back():
    image = arrow_glyph("UP")
    assert np.array_equal(rotate_clockwise(image, 360), image)
    assert np.array_equal(
        rotate_clockwise(rotate_clockwise(image, 90), 270), image
    )


@pytest.mark.parametrize("target", DIRECTIONS)
def test_rotated_arrow_matches_real_glyph(target):
    """↑ 한 장을 돌려 만든 템플릿이 실제 해당 방향 글리프와 일치해야 한다."""
    generated = rotate_to_direction(arrow_glyph("UP"), "UP", target)
    expected = arrow_glyph(target)

    matcher = TemplateMatcher()
    match = matcher.find_best(
        expected, template_from_array(generated, target), None, threshold=0.9
    )
    assert match is not None, f"{target} 회전 템플릿이 실제 글리프와 맞지 않음"
    assert match.score > 0.99


def test_generated_set_reads_full_sequence(config):
    """회전으로 만든 4장으로 실제 화면의 순서를 그대로 읽어야 한다."""
    vision = RuneVision(config)
    base = arrow_glyph("UP")
    for direction in DIRECTIONS:
        image = rotate_to_direction(base, "UP", direction)
        vision.register_template(
            f"arrow_{direction.lower()}.png", template_from_array(image, direction)
        )

    sequence = ["LEFT", "DOWN", "RIGHT", "UP"]
    reading = vision.read_arrows(render_screen(arrows=sequence))
    assert reading.ok, reading.reason
    assert reading.sequence == sequence


def test_reading_reports_per_direction_scores(vision):
    reading = vision.read_arrows(render_screen(arrows=["UP", "UP", "DOWN", "LEFT"]))
    assert reading.ok
    assert set(reading.scores) == set(DIRECTIONS)
    assert all(0.0 <= v <= 1.0 for v in reading.scores.values())
    assert "UP" in reading.describe_scores()


def test_scores_available_even_when_reading_fails(vision):
    """판독이 실패해도 점수를 보여줘야 임계값을 조정할 수 있다."""
    reading = vision.read_arrows(render_screen())  # 화살표 없음
    assert reading.ok is False
    assert reading.scores, "실패할 때도 방향별 점수는 있어야 한다"
    assert max(reading.scores.values()) < 0.7


# --- 안내 문구(저주 배너) ------------------------------------------------
def _banner_image() -> np.ndarray:
    import cv2

    banner = np.full((46, 260, 3), (60, 20, 70), dtype=np.uint8)
    cv2.rectangle(banner, (2, 2), (257, 43), (150, 60, 170), 2)
    cv2.putText(banner, "ELITE CURSE", (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 200, 255), 2)
    return banner


def _screen_with_banner(banner: np.ndarray | None) -> np.ndarray:
    frame = render_screen(seed=2)
    if banner is not None:
        h, w = banner.shape[:2]
        x = frame.shape[1] // 2 - w // 2
        y = int(frame.shape[0] * 0.15)
        frame[y : y + h, x : x + w] = banner
    return frame


def test_detects_curse_banner(config):
    config.rune.use_banner = True
    config.rune.banner_roi = Roi(0.15, 0.05, 0.7, 0.35)
    vision = RuneVision(config)
    banner = _banner_image()
    vision.register_template("rune_banner.png", template_from_array(banner, "banner"))

    assert vision.detect_banner(_screen_with_banner(banner)) is not None
    assert vision.detect_banner(_screen_with_banner(None)) is None


def test_banner_mode_requires_banner_template(config):
    config.rune.use_banner = True
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    vision = RuneVision(config)

    ready, missing = vision.templates_ready()
    assert ready is False
    assert any("rune_banner" in name for name in missing)
    assert not any("rune.png" in name for name in missing), "미니맵 모드는 룬 이미지가 필요 없다"


def test_minimap_mode_does_not_require_rune_template(config):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    vision = RuneVision(config)
    for direction in DIRECTIONS:
        vision.register_template(
            f"arrow_{direction.lower()}.png",
            template_from_array(arrow_glyph(direction), direction),
        )
    ready, missing = vision.templates_ready()
    assert ready is True, missing


def test_banner_disappearance_counts_as_success(config, bus):
    """안내 문구가 사라지면 해제 성공으로 판정해야 한다."""
    from rune_hunter.engine.clock import ManualClock
    from rune_hunter.engine.rune_solver import RuneSolver
    from rune_hunter.inputs.recorder import RecordingBackend

    config.rune.use_banner = True
    config.rune.source = "template"
    vision = RuneVision(config)
    banner = _banner_image()
    vision.register_template("rune_banner.png", template_from_array(banner, "banner"))

    state = {"banner": True}

    def frames():
        return _screen_with_banner(banner if state["banner"] else None)

    solver = RuneSolver(
        config=config,
        vision=vision,
        inputs=RecordingBackend(),
        frames=frames,
        bus=bus,
        clock=ManualClock(),
    )
    assert solver._rune_visible(frames()) is True
    state["banner"] = False
    assert solver._rune_visible(frames()) is False
