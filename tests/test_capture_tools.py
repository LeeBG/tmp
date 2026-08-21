"""템플릿 캡처 도구(영역 선택 → 저장 → 재로딩) 검증.

미리보기 축소 배율을 잘못 되돌리면 잘라낸 템플릿이 어긋나 인식이 통째로
깨지기 때문에 좌표 환산을 직접 확인한다. 한글 경로도 함께 검증한다.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rune_hunter.gui.capture_dialog import RegionSelectDialog, save_png  # noqa: E402
from rune_hunter.vision.matcher import TemplateMatcher, load_template  # noqa: E402
from rune_hunter.vision.synth import render_screen, rune_glyph  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _select(dialog: RegionSelectDialog, x0: int, y0: int, x1: int, y1: int) -> None:
    canvas = dialog._canvas
    canvas._start = QPoint(x0, y0)
    canvas._end = QPoint(x1, y1)


def test_selected_rect_maps_back_to_original_pixels(app):
    image = render_screen(width=1920, height=1200)
    dialog = RegionSelectDialog(image, "테스트", "힌트")
    scale = dialog._scale
    assert scale < 1.0, "1920 폭이면 미리보기가 축소되어야 한다"

    _select(dialog, 100, 200, 200, 260)
    x, y, w, h = dialog.selected_rect()
    assert x == pytest.approx(100 / scale, abs=3)
    assert y == pytest.approx(200 / scale, abs=3)
    assert w == pytest.approx(100 / scale, abs=3)
    assert h == pytest.approx(60 / scale, abs=3)


def test_normalized_rect_is_within_unit_range(app):
    image = render_screen(width=1024, height=768)
    dialog = RegionSelectDialog(image, "테스트", "힌트")
    _select(dialog, 200, 20, 800, 250)
    x, y, w, h = dialog.normalized_rect()
    assert 0 <= x < 1 and 0 <= y < 1
    assert 0 < w <= 1 and 0 < h <= 1
    assert x + w <= 1.001 and y + h <= 1.001


def test_tiny_selection_is_ignored(app):
    dialog = RegionSelectDialog(render_screen(width=800, height=600), "테스트", "힌트")
    _select(dialog, 10, 10, 12, 12)
    assert dialog.selected_rect() is None
    assert dialog.cropped() is None


def test_cropped_template_matches_source_image(app, tmp_path):
    """잘라낸 조각으로 원본을 다시 찾을 수 있어야 한다."""
    image = render_screen(width=1024, height=768, rune_pos=(500, 400))
    dialog = RegionSelectDialog(image, "테스트", "힌트")
    glyph_h, glyph_w = rune_glyph().shape[:2]
    x0, y0 = 500 - glyph_w // 2, 400 - glyph_h // 2
    _select(dialog, x0, y0, x0 + glyph_w, y0 + glyph_h)

    crop = dialog.cropped()
    assert crop is not None
    path = tmp_path / "한글 폴더" / "룬.png"
    save_png(crop, path)
    assert path.exists()

    template = load_template(path)
    match = TemplateMatcher().find_best(image, template, None, 0.8)
    assert match is not None
    assert abs(match.cx - 500) <= 3
    assert abs(match.cy - 400) <= 3


def test_save_png_handles_grayscale_and_color(tmp_path):
    color = np.full((10, 12, 3), 128, dtype=np.uint8)
    save_png(color, tmp_path / "색.png")
    assert (tmp_path / "색.png").exists()
    assert load_template(tmp_path / "색.png").size == (12, 10)
