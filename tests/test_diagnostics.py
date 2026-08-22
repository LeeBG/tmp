"""설정 자가 점검 · 실패 스냅샷 · 화면 변화 감지 검증.

사용자가 "왜 안 되는지" 를 로그만 보고 알 수 있어야 하므로,
경고 문구가 실제로 나오는지까지 확인한다.
"""

from __future__ import annotations

import numpy as np
import pytest

from rune_hunter import diagnostics
from rune_hunter.config import AppConfig, ColorSpec, Roi
from rune_hunter.diagnostics import (
    check_config,
    diagnose_frame,
    region_change_ratio,
    save_failure_snapshot,
    save_image,
)
from rune_hunter.vision.synth import render_screen


def levels(issues, *wanted):
    return [i for i in issues if i.level in wanted]


def joined(issues) -> str:
    return "\n".join(i.message for i in issues)


# --- 설정 점검 ----------------------------------------------------------
def test_default_config_has_no_blocking_warning(config: AppConfig):
    """기본값은 이 서버 기준으로 곧바로 쓸 수 있어야 한다."""
    text = joined(check_config(config))
    assert "SPACE" not in text, text
    assert levels(check_config(config), "error") == []


def test_warns_when_activate_key_is_not_space(config: AppConfig):
    config.rune.activate_key = "UP"
    assert "스페이스바" in joined(check_config(config))


def test_warns_about_single_activation_attempt_and_short_press(config: AppConfig):
    config.rune.activate_taps = 1
    config.rune.activate_press_ms = 40
    text = joined(check_config(config))
    assert "활성화 시도 횟수" in text
    assert "누름 시간" in text


def test_warns_when_ui_wait_is_too_short(config: AppConfig):
    config.rune.activate_gap = 0.2
    assert "UI 대기" in joined(check_config(config))


def test_detects_overlapping_marker_colors(config: AppConfig):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.rune_color = config.rune.minimap.char_color
    issues = check_config(config)
    assert levels(issues, "error"), joined(issues)
    assert "겹칩니다" in joined(issues)


def test_warns_about_zero_tolerance_and_no_nudge(config: AppConfig):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.align_tolerance = 0
    config.rune.minimap.nudge_ms = 0
    text = joined(check_config(config))
    assert "0px" in text
    assert "미세 이동" in text


@pytest.mark.parametrize("roi,expect", [(Roi(0, 0, 0.9, 0.9), "넓"), (Roi(0, 0, 0.01, 0.01), "작")])
def test_warns_about_bad_minimap_area(config: AppConfig, roi, expect):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.roi = roi
    assert expect in joined(check_config(config))


def test_missing_arrow_templates_is_an_error(config: AppConfig, tmp_path):
    from rune_hunter.vision import RuneVision

    config.rune.template_dir = str(tmp_path)  # 빈 폴더 → 템플릿 없음
    issues = check_config(config, RuneVision(config))
    assert levels(issues, "error"), joined(issues)
    assert "활성화 실패" in joined(issues), "템플릿이 없으면 활성화 실패로 보인다는 설명이 있어야 한다"


# --- 화면 변화 감지 ------------------------------------------------------
def arrow_region(config: AppConfig, frame):
    """솔버와 같은 방식으로 화살표 탐색 영역만 자른다."""
    h, w = frame.shape[:2]
    x, y, rw, rh = config.rune.arrow_roi.to_pixels(w, h)
    return frame[y : y + rh, x : x + rw]


def test_region_change_ratio_is_zero_for_similar_frames(config: AppConfig):
    a = arrow_region(config, render_screen(seed=1))
    b = arrow_region(config, render_screen(seed=2))  # 노이즈만 다른 같은 화면
    assert region_change_ratio(a, b) < 0.01


def test_region_change_ratio_detects_arrow_panel(config: AppConfig):
    before = arrow_region(config, render_screen(seed=1))
    after = arrow_region(config, render_screen(seed=1, arrows=["UP", "DOWN", "LEFT", "RIGHT"]))
    assert region_change_ratio(before, after) > 0.01


def test_region_change_ratio_handles_none_and_mismatched_shapes():
    assert region_change_ratio(None, render_screen()) == 0.0
    assert region_change_ratio(render_screen(width=200, height=200), render_screen()) == 0.0


# --- 스냅샷 -------------------------------------------------------------
def test_save_failure_snapshot_writes_screen_and_minimap(config: AppConfig, tmp_path):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    frame = render_screen(minimap_char=(90, 55), minimap_rune=(70, 55))
    saved = save_failure_snapshot(frame, config, prefix="activate_fail", log_dir=tmp_path)

    assert len(saved) == 2
    assert all(p.exists() and p.stat().st_size > 0 for p in saved)
    assert any("minimap" in p.name for p in saved)
    assert all(p.name.startswith("activate_fail_") for p in saved)


def test_save_failure_snapshot_prunes_old_files(config: AppConfig, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_SNAPSHOTS", 3)
    for i in range(6):
        path = tmp_path / f"activate_fail_old{i}.png"
        save_image(np.zeros((4, 4, 3), dtype=np.uint8), path)
    save_failure_snapshot(render_screen(), config, prefix="activate_fail", log_dir=tmp_path)
    assert len(list(tmp_path.glob("activate_fail_*.png"))) <= 4


def test_snapshot_of_missing_frame_is_ignored(config: AppConfig, tmp_path):
    assert save_failure_snapshot(None, config, log_dir=tmp_path) == []
    assert list(tmp_path.glob("*.png")) == []


# --- 현재 화면 진단 ------------------------------------------------------
def test_diagnose_frame_reports_each_stage(config: AppConfig, vision):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.roi = Roi(12 / 1024, 12 / 768, 180 / 1024, 110 / 768)
    frame = render_screen(
        minimap_char=(90, 55), minimap_rune=(70, 55), arrows=["UP", "DOWN", "LEFT", "RIGHT"]
    )
    text = joined(diagnose_frame(config, frame, vision))

    assert "미니맵 판독" in text
    assert "화살표 판독" in text
    assert "방향별 최고 점수" in text


def test_diagnose_frame_without_screen_reports_capture_failure(config: AppConfig, vision):
    issues = diagnose_frame(config, None, vision)
    assert any("화면을 가져오지 못했습니다" in i.message for i in issues)


def test_diagnose_frame_flags_overlapping_colors(config: AppConfig, vision):
    config.rune.source = "minimap"
    config.rune.minimap.enabled = True
    config.rune.minimap.roi = Roi(12 / 1024, 12 / 768, 180 / 1024, 110 / 768)
    config.rune.minimap.rune_color = ColorSpec(lower=[18, 110, 130], upper=[35, 255, 255])
    frame = render_screen(minimap_char=(90, 55), minimap_rune=(70, 55))
    assert levels(diagnose_frame(config, frame, vision), "error")
