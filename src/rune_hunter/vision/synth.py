"""합성 이미지 생성기 (데모 템플릿 + 테스트용 가짜 게임 화면).

실제 게임 스크린샷 없이도 룬 감지 → 화살표 판독 → 입력까지 전체 파이프라인을
검증할 수 있게 한다. 여기서 만드는 글리프와 데모 템플릿은 완전히 동일한
드로잉 코드를 쓰므로, 매칭이 실패하면 파이프라인 쪽 버그다.
"""

from __future__ import annotations

import cv2
import numpy as np

ARROW_SIZE = 44
RUNE_SIZE = (44, 52)  # (w, h)
DIRECTIONS = ("UP", "DOWN", "LEFT", "RIGHT")


def arrow_glyph(direction: str, size: int = ARROW_SIZE) -> np.ndarray:
    """방향 화살표 글리프 (BGR)."""
    img = np.full((size, size, 3), (18, 14, 26), dtype=np.uint8)
    m = size // 2
    pad = int(size * 0.18)
    tip = {
        "UP": (m, pad),
        "DOWN": (m, size - pad),
        "LEFT": (pad, m),
        "RIGHT": (size - pad, m),
    }[direction.upper()]
    if direction.upper() in ("UP", "DOWN"):
        base_y = size - pad if direction.upper() == "UP" else pad
        pts = np.array([tip, (pad, base_y), (size - pad, base_y)], dtype=np.int32)
    else:
        base_x = size - pad if direction.upper() == "LEFT" else pad
        pts = np.array([tip, (base_x, pad), (base_x, size - pad)], dtype=np.int32)
    cv2.fillConvexPoly(img, pts, (245, 240, 255))
    cv2.polylines(img, [pts], True, (120, 90, 200), 2)
    return img


def rune_glyph(size: tuple[int, int] = RUNE_SIZE) -> np.ndarray:
    """맵에 떠 있는 룬 글리프 (BGR)."""
    w, h = size
    img = np.full((h, w, 3), (12, 10, 18), dtype=np.uint8)
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 2 - 2, (190, 110, 235), -1)
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 2 - 2, (255, 220, 255), 2)
    cv2.line(img, (w // 2, 6), (w // 2, h - 6), (40, 20, 60), 3)
    cv2.line(img, (w // 2, h // 3), (w - 8, 8), (40, 20, 60), 3)
    cv2.line(img, (w // 2, 2 * h // 3), (8, h - 8), (40, 20, 60), 3)
    return img


def demo_templates() -> dict[str, np.ndarray]:
    """데모/테스트에서 쓰는 템플릿 묶음 (파일명 -> 이미지)."""
    out = {"rune.png": rune_glyph()}
    for d in DIRECTIONS:
        out[f"arrow_{d.lower()}.png"] = arrow_glyph(d)
    return out


def write_demo_templates(directory) -> list[str]:
    from pathlib import Path

    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, image in demo_templates().items():
        ok, buf = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError(f"PNG 인코딩 실패: {name}")
        (path / name).write_bytes(buf.tobytes())
        written.append(str(path / name))
    return written


def _background(width: int, height: int, seed: int = 0) -> np.ndarray:
    """게임 화면처럼 밋밋하지 않은 배경 (그라디언트 + 지형 + 노이즈)."""
    rng = np.random.default_rng(seed)
    grad_y = np.linspace(30, 90, height, dtype=np.float32)[:, None]
    grad_x = np.linspace(20, 70, width, dtype=np.float32)[None, :]
    base = (grad_y + grad_x) / 2.0
    img = np.dstack([base * 0.9, base * 0.8, base]).astype(np.uint8)
    for i in range(6):
        y = int(height * (0.35 + 0.1 * i))
        cv2.line(img, (0, y), (width, y), (60, 70, 90), 3)
    noise = rng.integers(0, 12, size=img.shape, dtype=np.uint8)
    return cv2.add(img, noise)


MINIMAP_RECT = (12, 12, 180, 110)  # (x, y, w, h) 화면 좌상단
MINIMAP_RUNE_BGR = (200, 40, 190)  # 보라색 룬 표식
MINIMAP_CHAR_BGR = (40, 230, 250)  # 노란색 캐릭터 표식


def color_from_spec(spec) -> tuple[int, int, int]:
    """설정된 HSV 범위의 중앙값을 BGR 색으로 바꾼다.

    데모 화면의 표식을 사용자가 설정한 색 범위에 맞춰 그리기 위한 것.
    (사용자가 실제 게임 화면에서 색을 추출해 두었어도 데모가 그대로 동작한다)
    """
    h = int((spec.lower[0] + spec.upper[0]) / 2)
    s = int(min(255, max(spec.lower[1] + 60, (spec.lower[1] + spec.upper[1]) / 2)))
    v = int(min(255, max(spec.lower[2] + 60, (spec.lower[2] + spec.upper[2]) / 2)))
    bgr = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0][0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def draw_minimap(
    canvas: np.ndarray,
    char: tuple[int, int] | None = None,
    rune: tuple[int, int] | None = None,
    rect: tuple[int, int, int, int] = MINIMAP_RECT,
    rune_bgr: tuple[int, int, int] = MINIMAP_RUNE_BGR,
    char_bgr: tuple[int, int, int] = MINIMAP_CHAR_BGR,
) -> None:
    """미니맵 패널과 표식을 그린다. char/rune 좌표는 미니맵 내부 좌표."""
    x, y, w, h = rect
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (48, 42, 40), -1)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (110, 100, 95), 1)
    for i in range(3):  # 지형처럼 보이는 선
        line_y = y + int(h * (0.35 + 0.2 * i))
        cv2.line(canvas, (x + 6, line_y), (x + w - 6, line_y), (90, 84, 80), 1)
    if rune is not None:
        cx, cy = x + rune[0], y + rune[1]
        cv2.rectangle(canvas, (cx - 2, cy - 2), (cx + 2, cy + 2), rune_bgr, -1)
    if char is not None:
        cx, cy = x + char[0], y + char[1]
        cv2.rectangle(canvas, (cx - 1, cy - 1), (cx + 1, cy + 1), char_bgr, -1)


def render_screen(
    width: int = 1024,
    height: int = 768,
    rune_pos: tuple[int, int] | None = None,
    arrows: list[str] | None = None,
    seed: int = 0,
    arrow_y_ratio: float = 0.12,
    arrow_spacing: int = 66,
    noise: float = 0.0,
    minimap_char: tuple[int, int] | None = None,
    minimap_rune: tuple[int, int] | None = None,
    minimap_rect: tuple[int, int, int, int] | None = None,
    minimap_rune_bgr: tuple[int, int, int] = MINIMAP_RUNE_BGR,
    minimap_char_bgr: tuple[int, int, int] = MINIMAP_CHAR_BGR,
) -> np.ndarray:
    """가짜 게임 화면 한 장을 만든다.

    rune_pos: 룬 중심 좌표 (없으면 룬 없음)
    arrows: 상단에 표시할 방향 순서 (없으면 화살표 UI 없음)
    """
    img = _background(width, height, seed)

    if rune_pos is not None:
        glyph = rune_glyph()
        _paste(img, glyph, rune_pos)

    if arrows:
        glyphs = [arrow_glyph(d) for d in arrows]
        total = arrow_spacing * (len(glyphs) - 1)
        start_x = width // 2 - total // 2
        y = int(height * arrow_y_ratio)
        for i, glyph in enumerate(glyphs):
            _paste(img, glyph, (start_x + i * arrow_spacing, y))

    if noise > 0:
        rng = np.random.default_rng(seed + 7)
        extra = rng.normal(0, noise * 255, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + extra, 0, 255).astype(np.uint8)

    # 미니맵은 노이즈 뒤에 그린다 (실제 게임에서도 UI 는 선명하다)
    if minimap_char is not None or minimap_rune is not None or minimap_rect is not None:
        draw_minimap(
            img,
            char=minimap_char,
            rune=minimap_rune,
            rect=minimap_rect or MINIMAP_RECT,
            rune_bgr=minimap_rune_bgr,
            char_bgr=minimap_char_bgr,
        )
    return img


def _paste(canvas: np.ndarray, glyph: np.ndarray, center: tuple[int, int]) -> None:
    gh, gw = glyph.shape[:2]
    cx, cy = center
    x0, y0 = cx - gw // 2, cy - gh // 2
    x1, y1 = x0 + gw, y0 + gh
    if x0 < 0 or y0 < 0 or x1 > canvas.shape[1] or y1 > canvas.shape[0]:
        return
    canvas[y0:y1, x0:x1] = glyph
