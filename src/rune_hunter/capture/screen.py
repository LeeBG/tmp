"""mss 기반 화면 캡처.

mss 객체는 스레드 안전하지 않기 때문에 threading.local 로 스레드마다
따로 만든다 (엔진 스레드 / GUI 캡처 도구가 동시에 써도 안전).
"""

from __future__ import annotations

import threading

import numpy as np

from .base import Frame


class ScreenCapture:
    def __init__(self) -> None:
        self._local = threading.local()

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss  # 지연 임포트: 헤드리스 테스트에서 불필요한 초기화 방지

            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self, region: tuple[int, int, int, int]) -> Frame:
        left, top, width, height = region
        monitor = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
        raw = self._sct().grab(monitor)
        # BGRA -> BGR (복사 한 번으로 끝내서 매칭 단계에서 추가 변환이 없게 한다)
        image = np.asarray(raw, dtype=np.uint8)[:, :, :3]
        return Frame(image=image, origin=(int(left), int(top)))

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
            self._local.sct = None
