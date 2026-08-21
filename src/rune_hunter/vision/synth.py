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


def render_screen(
    width: int = 1024,
    height: int = 768,
    rune_pos: tuple[int, int] | None = None,
    arrows: list[str] | None = None,
    seed: int = 0,
    arrow_y_ratio: float = 0.12,
    arrow_spacing: int = 66,
    noise: float = 0.0,
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
    return img


def _paste(canvas: np.ndarray, glyph: np.ndarray, center: tuple[int, int]) -> None:
    gh, gw = glyph.shape[:2]
    cx, cy = center
    x0, y0 = cx - gw // 2, cy - gh // 2
    x1, y1 = x0 + gw, y0 + gh
    if x0 < 0 or y0 < 0 or x1 > canvas.shape[1] or y1 > canvas.shape[0]:
        return
    canvas[y0:y1, x0:x1] = glyph
