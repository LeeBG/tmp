"""테스트/데모용 입력 백엔드.

실제 키를 보내지 않고 이벤트만 기록한다. 데모 시뮬레이터와 연결하면
"매크로가 키를 눌렀을 때 게임이 어떻게 반응하는지"까지 재현할 수 있다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .base import InputBackend, KeyEvent


class RecordingBackend(InputBackend):
    def __init__(self, sink: Callable[[KeyEvent], None] | None = None) -> None:
        super().__init__()
        self.events: list[KeyEvent] = []
        self._sink = sink
        self._lock = threading.Lock()

    def _send(self, key: str, down: bool) -> None:
        event = KeyEvent(key.upper(), "down" if down else "up", time.perf_counter())
        with self._lock:
            self.events.append(event)
        if self._sink is not None:
            self._sink(event)

    def set_sink(self, sink: Callable[[KeyEvent], None] | None) -> None:
        self._sink = sink

    # --- 테스트 편의 함수 ----------------------------------------------
    def taps(self, key: str | None = None) -> list[str]:
        """키 다운 이벤트 순서를 문자열 리스트로 반환."""
        with self._lock:
            return [
                e.key
                for e in self.events
                if e.action == "down" and (key is None or e.key == key.upper())
            ]

    def count(self, key: str) -> int:
        return len(self.taps(key))

    def clear(self) -> None:
        with self._lock:
            self.events.clear()
