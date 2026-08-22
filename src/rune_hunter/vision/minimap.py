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
    """표식 위치. 좌표는 소수점까지 유지한다.

    미니맵은 작아서 1픽셀이 실제 수십 픽셀에 해당한다. 정수로 반올림하면
    그 오차가 그대로 이동 오차가 되므로, 무게중심을 소수점으로 쓴다.
    """

    cx: float
    cy: float
    area: int

    @property
    def center(self) -> tuple[float, float]:
        return round(self.cx, 1), round(self.cy, 1)


@dataclass(frozen=True)
class MinimapReading:
    rune: Marker | None
    char: Marker | None
    roi: tuple[int, int, int, int]
    ambiguous: bool = False       # 룬 색과 캐릭터 색이 같은 대상을 가리킴
    overlap: float = 0.0          # 두 색 마스크가 겹치는 비율

    @property
    def found(self) -> bool:
        return self.rune is not None and self.char is not None

    @property
    def usable(self) -> bool:
        return self.found and not self.ambiguous

    @property
    def dx(self) -> float | None:
        """룬이 캐릭터보다 오른쪽이면 양수."""
        if not self.found:
            return None
        return self.rune.cx - self.char.cx  # type: ignore[union-attr]

    @property
    def dy(self) -> float | None:
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
        text = (
            f"룬 {self.rune.center} / 캐릭터 {self.char.center} "
            f"→ dx {self.dx:+.1f}, dy {self.dy:+.1f}"
        )
        if self.ambiguous:
            text += f"  ⚠ 두 색 범위가 {self.overlap:.0%} 겹칩니다 (같은 표식을 가리킴)"
        return text


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
    def _largest(mask: np.ndarray, min_area: int) -> Marker | None:
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best: Marker | None = None
        for index in range(1, count):  # 0 은 배경
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < max(1, min_area):
                continue
            if best is None or area > best.area:
                cx, cy = centroids[index]
                best = Marker(cx=float(cx), cy=float(cy), area=area)
        return best

    def _mask(self, crop: np.ndarray, color: ColorSpec) -> np.ndarray:
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        return cv2.inRange(
            hsv,
            np.array(color.lower, dtype=np.uint8),
            np.array(color.upper, dtype=np.uint8),
        )

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
        return self._largest(self._mask(crop, color), color.min_area)

    # --- 공개 API -------------------------------------------------------
    def read(self, frame: np.ndarray) -> MinimapReading:
        cfg = self.config.rune.minimap
        crop, roi = self.crop(frame)
        if crop.size == 0:
            return MinimapReading(rune=None, char=None, roi=roi)

        rune_mask = self._mask(crop, cfg.rune_color)
        char_mask = self._mask(crop, cfg.char_color)
        rune = self._largest(rune_mask, cfg.rune_color.min_area)
        char = self._largest(char_mask, cfg.char_color.min_area)

        # 두 색 범위가 겹치면 같은 표식을 룬으로도 캐릭터로도 인식해 dx 가 0 이 된다.
        # 이 상태를 정렬 완료로 착각하면 절대 해제되지 않으므로 명시적으로 걸러낸다.
        overlap = 0.0
        ambiguous = False
        if rune is not None and char is not None:
            intersection = int(cv2.countNonZero(cv2.bitwise_and(rune_mask, char_mask)))
            smaller = max(1, min(rune.area, char.area))
            overlap = intersection / smaller
            distance = ((rune.cx - char.cx) ** 2 + (rune.cy - char.cy) ** 2) ** 0.5
            ambiguous = overlap > 0.5 and distance < 2.0

        return MinimapReading(
            rune=rune, char=char, roi=roi, ambiguous=ambiguous, overlap=overlap
        )

    def rune_present(self, frame: np.ndarray) -> bool:
        reading = self.read(frame)
        return reading.rune is not None and not reading.ambiguous

    # --- 진단 -----------------------------------------------------------
    def debug_image(self, frame: np.ndarray, scale: int = 5) -> np.ndarray:
        """미니맵 영역을 확대하고 인식된 표식을 표시한 진단 이미지."""
        crop, roi = self.crop(frame)
        reading = self.read(frame)
        canvas = cv2.resize(
            crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST
        )
        if reading.rune is not None:
            center = (int(reading.rune.cx * scale), int(reading.rune.cy * scale))
            cv2.circle(canvas, center, scale * 3, (0, 0, 255), 2)
            cv2.putText(
                canvas, "RUNE", (center[0] + 8, center[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1,
            )
        if reading.char is not None:
            center = (int(reading.char.cx * scale), int(reading.char.cy * scale))
            cv2.circle(canvas, center, scale * 3, (0, 255, 0), 2)
            cv2.putText(
                canvas, "ME", (center[0] + 8, center[1] + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1,
            )
        return canvas

    @staticmethod
    def ranges_overlap(a: ColorSpec, b: ColorSpec) -> bool:
        """두 색 범위가 서로 겹치는지 (설정 실수 감지용)."""
        return all(
            a.lower[i] <= b.upper[i] and b.lower[i] <= a.upper[i] for i in range(3)
        )

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

        선택 영역에 미니맵 배경(어둡고 탁한 색)이 섞여 있어도 표식 색을 잡도록,
        **채도와 명도가 모두 높은 픽셀**만 골라 중앙값을 쓴다. 배경을 뽑아버리면
        룬과 캐릭터의 색 범위가 서로 겹쳐 인식이 망가진다.
        """
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int32)
        if hsv.size == 0:
            return ColorSpec()
        saturation, value = hsv[:, 1], hsv[:, 2]
        s_threshold = max(40, int(np.percentile(saturation, 65)))
        v_threshold = max(50, int(np.percentile(value, 65)))
        picked = hsv[(saturation >= s_threshold) & (value >= v_threshold)]
        if picked.size == 0:  # 전부 어두운 영역이면 채도만으로 다시 시도
            picked = hsv[saturation >= s_threshold]
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
