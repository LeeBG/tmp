"""시간 추상화.

실제 실행은 perf_counter + 정밀 sleep 을 쓰고, 테스트는 ManualClock 으로
시간을 직접 흘려보내 초 단위 대기 없이 로직 전체를 검증한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..platform_layer.timing import now as _perf_now
from ..platform_layer.timing import precise_sleep


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class RealClock:
    def now(self) -> float:
        return _perf_now()

    def sleep(self, seconds: float) -> None:
        precise_sleep(seconds)


class ManualClock:
    """테스트용 가상 시계. sleep 은 즉시 시간만 앞으로 감는다."""

    def __init__(self, start: float = 1000.0) -> None:
        self._t = start
        self.on_advance: Callable[[float], None] | None = None
        self.slept: list[float] = []

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.slept.append(seconds)
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self._t += seconds
        if self.on_advance is not None:
            self.on_advance(self._t)
