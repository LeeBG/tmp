"""미니맵 색상 인식.

룬이 화면 밖에 있어도 미니맵에는 표시되므로, 미니맵에서
- 룬 표식(보라/자주)
- 내 캐릭터 표식(노랑)
의 좌표를 각각 찾아 차이를 계산한다. 템플릿 매칭이 아니라 **HSV 색 범위 마스킹**을
쓰는 이유는, 미니맵 표식이 몇 픽셀짜리 단색 점이라 모양보다 색이 훨씬 안정적이기 때문이다.

좌표는 미니맵 픽셀 기준이며, 미니맵 1픽셀은 실제 맵에서 수십 픽셀에 해당한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..config import AppConfig, ColorSpec


@dataclass(frozen=True)
class Marker:
    cx: int
    cy: int
    area: int

    @property
    def center(self) -> tuple[int, int]:
        return self.cx, self.cy


@dataclass(frozen=True)
class MinimapReading:
    rune: Marker | None
    char: Marker | None
    roi: tuple[int, int, int, int]

    @property
    def found(self) -> bool:
        return self.rune is not None and self.char is not None

    @property
    def dx(self) -> int | None:
        """룬이 캐릭터보다 오른쪽이면 양수."""
        if not self.found:
            return None
        return self.rune.cx - self.char.cx  # type: ignore[union-attr]

    @property
    def dy(self) -> int | None:
        """룬이 캐릭터보다 아래면 양수 (미니맵은 y 가 아래로 증가)."""
        if not self.found:
            return None
        return self.rune.cy - self.char.cy  # type: ignore[union-attr]

    def describe(self) -> str:
        if not self.found:
            missing = []
            if self.rune is None:
                missing.append("룬")
            if self.char is None:
                missing.append("캐릭터")
            return f"미니맵 표식 없음: {', '.join(missing)}"
        return f"룬 {self.rune.center} / 캐릭터 {self.char.center} → dx {self.dx}, dy {self.dy}"


class MinimapVision:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    # --- 내부 ----------------------------------------------------------
    def _roi(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        h, w = frame.shape[:2]
        return self.config.rune.minimap.roi.to_pixels(w, h)

    def crop(self, frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        x, y, cw, ch = self._roi(frame)
        return frame[y : y + ch, x : x + cw], (x, y, cw, ch)

    @staticmethod
    def _largest(mask: np.ndarray, min_area: int) -> tuple[int, int, int] | None:
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best: tuple[int, int, int] | None = None
        for index in range(1, count):  # 0 은 배경
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < max(1, min_area):
                continue
            if best is None or area > best[2]:
                cx, cy = centroids[index]
                best = (int(round(cx)), int(round(cy)), area)
        return best

    def find_marker(
        self, frame: np.ndarray, color: ColorSpec, roi: tuple[int, int, int, int] | None = None
    ) -> Marker | None:
        """지정한 색 범위에서 가장 큰 덩어리를 찾는다. 좌표는 미니맵(ROI) 기준."""
        if roi is None:
            crop, roi = self.crop(frame)
        else:
            x, y, w, h = roi
            crop = frame[y : y + h, x : x + w]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array(color.lower, dtype=np.uint8),
            np.array(color.upper, dtype=np.uint8),
        )
        found = self._largest(mask, color.min_area)
        if found is None:
            return None
        return Marker(cx=found[0], cy=found[1], area=found[2])

    # --- 공개 API -------------------------------------------------------
    def read(self, frame: np.ndarray) -> MinimapReading:
        cfg = self.config.rune.minimap
        crop, roi = self.crop(frame)
        rune = self.find_marker(frame, cfg.rune_color, roi)
        char = self.find_marker(frame, cfg.char_color, roi)
        return MinimapReading(rune=rune, char=char, roi=roi)

    def rune_present(self, frame: np.ndarray) -> bool:
        cfg = self.config.rune.minimap
        return self.find_marker(frame, cfg.rune_color) is not None

    # --- 색 추출 (GUI 에서 사용) ----------------------------------------
    @staticmethod
    def sample_color(
        crop: np.ndarray,
        hue_tolerance: int = 12,
        sat_tolerance: int = 70,
        val_tolerance: int = 70,
        min_area: int = 2,
    ) -> ColorSpec:
        """드래그로 고른 작은 영역에서 대표 색을 뽑아 HSV 범위를 만든다.

        선택 영역에 배경이 섞여 있어도 되도록, 채도가 높은 픽셀만 골라 중앙값을 쓴다.
        """
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int32)
        if hsv.size == 0:
            return ColorSpec()
        saturation = hsv[:, 1]
        threshold = max(40, int(np.percentile(saturation, 70)))
        picked = hsv[saturation >= threshold]
        if picked.size == 0:
            picked = hsv
        h, s, v = (int(np.median(picked[:, i])) for i in range(3))
        lower = [
            max(0, h - hue_tolerance),
            max(30, s - sat_tolerance),
            max(30, v - val_tolerance),
        ]
        upper = [
            min(179, h + hue_tolerance),
            min(255, s + sat_tolerance),
            min(255, v + val_tolerance),
        ]
        return ColorSpec(lower=lower, upper=upper, min_area=min_area)
