"""화면 캡처 인터페이스."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Frame:
    """BGR 이미지 한 장 + 캡처 시각 + 원본 창 좌표."""

    image: np.ndarray
    ts: float = field(default_factory=time.perf_counter)
    origin: tuple[int, int] = (0, 0)

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


class FrameSource(Protocol):
    def grab(self, region: tuple[int, int, int, int]) -> Frame:
        """region = (left, top, width, height) 화면 좌표."""
        ...

    def close(self) -> None: ...
