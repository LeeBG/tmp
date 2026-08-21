"""룬 감지 / 화살표 판독 정확도 검증."""

from __future__ import annotations

import time

import pytest

from rune_hunter.config import Roi
from rune_hunter.vision.synth import render_screen

SEQUENCES = [
    ["UP", "DOWN", "LEFT", "RIGHT"],
    ["LEFT", "LEFT", "UP", "DOWN"],
    ["RIGHT", "RIGHT", "RIGHT", "RIGHT"],
    ["DOWN", "UP", "RIGHT", "LEFT"],
    ["UP", "UP", "UP", "UP"],
]


def test_detects_rune_when_present(vision):
    frame = render_screen(rune_pos=(620, 380))
    match = vision.detect_rune(frame)
    assert match is not None
    assert match.score > 0.9
    assert abs(match.cx - 620) <= 4
    assert abs(match.cy - 380) <= 4


def test_no_false_positive_without_rune(vision):
    for seed in range(6):
        assert vision.detect_rune(render_screen(seed=seed)) is None


@pytest.mark.parametrize("sequence", SEQUENCES)
def test_reads_arrow_sequences(vision, sequence):
    frame = render_screen(rune_pos=(500, 400), arrows=sequence)
    reading = vision.read_arrows(frame)
    assert reading.ok, reading.reason
    assert reading.sequence == sequence


@pytest.mark.parametrize("noise", [0.0, 0.02, 0.05])
def test_robust_to_noise(vision, noise):
    sequence = ["LEFT", "UP", "RIGHT", "DOWN"]
    frame = render_screen(rune_pos=(300, 500), arrows=sequence, noise=noise)
    assert vision.detect_rune(frame) is not None
    assert vision.read_arrows(frame).sequence == sequence


def test_arrows_visible_flag(vision):
    with_arrows = render_screen(arrows=["UP", "UP", "DOWN", "DOWN"])
    without = render_screen()
    assert vision.arrows_visible(with_arrows) is True
    assert vision.arrows_visible(without) is False


def test_partial_reading_is_rejected(vision):
    frame = render_screen(arrows=["UP", "DOWN"])
    reading = vision.read_arrows(frame)
    assert reading.ok is False
    assert reading.count == 2
    assert "2개" in reading.reason


def test_roi_limits_search(vision, config):
    """화살표 ROI 밖의 화살표는 무시한다."""
    frame = render_screen(arrows=["UP", "DOWN", "LEFT", "RIGHT"], arrow_y_ratio=0.7)
    config.rune.arrow_roi = Roi(0.2, 0.02, 0.6, 0.25)
    assert vision.read_arrows(frame).ok is False
    config.rune.arrow_roi = Roi(0.0, 0.0, 1.0, 1.0)
    assert vision.read_arrows(frame).ok is True


def test_detect_scale_keeps_accuracy_and_is_faster(vision, config):
    frame = render_screen(rune_pos=(700, 420))

    config.rune.detect_scale = 1.0
    t0 = time.perf_counter()
    for _ in range(15):
        full = vision.detect_rune(frame)
    full_ms = (time.perf_counter() - t0) / 15 * 1000

    config.rune.detect_scale = 0.5
    t0 = time.perf_counter()
    for _ in range(15):
        small = vision.detect_rune(frame)
    small_ms = (time.perf_counter() - t0) / 15 * 1000

    assert full is not None and small is not None
    assert abs(small.cx - full.cx) <= 12
    assert abs(small.cy - full.cy) <= 12
    assert small_ms < full_ms


@pytest.mark.bench
def test_detection_latency_budget(vision):
    """룬 탐색 1회가 25ms 를 넘으면 사냥 루프에 영향이 생긴다."""
    frame = render_screen(rune_pos=(620, 380), arrows=["UP", "DOWN", "LEFT", "RIGHT"])
    vision.detect_rune(frame)  # 캐시 예열
    samples = []
    for _ in range(30):
        t0 = time.perf_counter()
        vision.detect_rune(frame)
        vision.read_arrows(frame)
        samples.append((time.perf_counter() - t0) * 1000)
    average = sum(samples) / len(samples)
    assert average < 60.0, f"감지 평균 {average:.1f}ms — 너무 느림"
