"""템플릿 매칭 유틸.

성능을 위해 지킨 규칙:
- 템플릿은 (경로, mtime) 기준으로 캐시해서 매번 디코딩하지 않는다.
- 매칭은 항상 그레이스케일 + 지정된 ROI 안에서만 수행한다.
- 알파 채널이 있으면 마스크 매칭(TM_CCORR_NORMED), 없으면 TM_CCOEFF_NORMED.
- 한글 경로 대응을 위해 cv2.imread 대신 np.fromfile + imdecode 를 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Match:
    score: float
    x: int
    y: int
    w: int
    h: int
    label: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass(frozen=True)
class Template:
    name: str
    gray: np.ndarray
    mask: np.ndarray | None

    @property
    def size(self) -> tuple[int, int]:
        return int(self.gray.shape[1]), int(self.gray.shape[0])


_CACHE: dict[tuple[str, float, float], Template] = {}


def load_template(path: str | Path, scale: float = 1.0) -> Template:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"템플릿 이미지를 찾을 수 없습니다: {p}")
    key = (str(p.resolve()), p.stat().st_mtime, round(scale, 4))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    buffer = np.fromfile(str(p), dtype=np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise ValueError(f"이미지를 해석할 수 없습니다: {p}")
    template = _from_array(decoded, name=p.stem, scale=scale)
    _CACHE[key] = template
    return template


def template_from_array(image: np.ndarray, name: str = "mem", scale: float = 1.0) -> Template:
    """메모리 이미지에서 템플릿을 만든다 (테스트/데모용, 캐시하지 않음)."""
    return _from_array(image, name=name, scale=scale)


def _from_array(decoded: np.ndarray, name: str, scale: float) -> Template:
    mask: np.ndarray | None = None
    if decoded.ndim == 3 and decoded.shape[2] == 4:
        alpha = decoded[:, :, 3]
        bgr = decoded[:, :, :3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if alpha.min() < 250:  # 실제로 투명한 부분이 있을 때만 마스크 사용
            mask = alpha
    elif decoded.ndim == 3:
        gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    else:
        gray = decoded

    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if mask is not None:
            mask = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return Template(name=name, gray=np.ascontiguousarray(gray), mask=mask)


def clear_cache() -> None:
    _CACHE.clear()


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    channels = image.shape[2]
    if channels == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


class TemplateMatcher:
    """ROI 안에서 템플릿을 찾는다. 결과 좌표는 항상 원본 프레임 기준."""

    def find_best(
        self,
        frame: np.ndarray,
        template: Template,
        roi: tuple[int, int, int, int] | None = None,
        threshold: float = 0.7,
    ) -> Match | None:
        matches = self.find_all(frame, template, roi, threshold, max_results=1)
        return matches[0] if matches else None

    def find_all(
        self,
        frame: np.ndarray,
        template: Template,
        roi: tuple[int, int, int, int] | None = None,
        threshold: float = 0.7,
        max_results: int = 10,
    ) -> list[Match]:
        gray = to_gray(frame)
        if roi is None:
            ox, oy = 0, 0
            region = gray
        else:
            rx, ry, rw, rh = roi
            rx = max(0, min(rx, gray.shape[1] - 1))
            ry = max(0, min(ry, gray.shape[0] - 1))
            rw = max(1, min(rw, gray.shape[1] - rx))
            rh = max(1, min(rh, gray.shape[0] - ry))
            ox, oy = rx, ry
            region = gray[ry : ry + rh, rx : rx + rw]

        tw, th = template.size
        if region.shape[0] < th or region.shape[1] < tw:
            return []

        if template.mask is not None:
            heat = cv2.matchTemplate(
                region, template.gray, cv2.TM_CCORR_NORMED, mask=template.mask
            )
        else:
            heat = cv2.matchTemplate(region, template.gray, cv2.TM_CCOEFF_NORMED)
        heat = np.nan_to_num(heat, nan=0.0, posinf=0.0, neginf=0.0)

        results: list[Match] = []
        work = heat.copy()
        for _ in range(max_results):
            _, max_val, _, max_loc = cv2.minMaxLoc(work)
            if max_val < threshold:
                break
            results.append(
                Match(
                    score=float(max_val),
                    x=int(max_loc[0]) + ox,
                    y=int(max_loc[1]) + oy,
                    w=tw,
                    h=th,
                    label=template.name,
                )
            )
            # 이미 찾은 위치 주변을 억제 (겹치는 중복 검출 제거)
            x0 = max(0, max_loc[0] - tw // 2)
            y0 = max(0, max_loc[1] - th // 2)
            x1 = min(work.shape[1], max_loc[0] + tw // 2 + 1)
            y1 = min(work.shape[0], max_loc[1] + th // 2 + 1)
            work[y0:y1, x0:x1] = -1.0
        return results
