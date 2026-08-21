"""입력 백엔드 인터페이스.

엔진은 이 인터페이스만 사용하므로, 실제 키 입력(Windows SendInput)과
테스트용 기록 백엔드를 자유롭게 교체할 수 있다.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KeyEvent:
    key: str
    action: str  # "down" | "up"
    ts: float = field(default_factory=time.perf_counter)


class InputBackend(ABC):
    """키 다운/업만 제공하고, 조합 동작은 상위에서 만든다."""

    def __init__(self) -> None:
        self._held: set[str] = set()

    @abstractmethod
    def _send(self, key: str, down: bool) -> None: ...

    # --- 기본 동작 -----------------------------------------------------
    def key_down(self, key: str) -> None:
        self._send(key, True)
        self._held.add(key.upper())

    def key_up(self, key: str) -> None:
        self._send(key, False)
        self._held.discard(key.upper())

    def tap(self, key: str, press_ms: int = 40, sleeper=None) -> None:
        sleep = sleeper or _default_sleep
        self.key_down(key)
        sleep(max(press_ms, 1) / 1000.0)
        self.key_up(key)

    def hold(self, key: str, duration_ms: int, sleeper=None) -> None:
        self.tap(key, duration_ms, sleeper)

    def chord(self, keys: list[str], press_ms: int = 40, sleeper=None) -> None:
        """여러 키를 동시에 누른다 (예: 아래 방향키 + ALT = 아래 점프)."""
        sleep = sleeper or _default_sleep
        for key in keys:
            self.key_down(key)
            sleep(0.012)
        sleep(max(press_ms, 1) / 1000.0)
        for key in reversed(keys):
            self.key_up(key)
            sleep(0.008)

    def release_all(self) -> None:
        for key in list(self._held):
            try:
                self.key_up(key)
            except Exception:
                self._held.discard(key)

    @property
    def held_keys(self) -> set[str]:
        return set(self._held)


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)
