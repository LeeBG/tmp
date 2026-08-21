"""정밀 타이밍 도구.

time.sleep() 은 Windows 기본 타이머 해상도(약 15.6ms)에 묶여 있어서 사냥키를
100ms 주기로 누르려면 오차가 심하다. timeBeginPeriod(1) 로 해상도를 1ms 로 낮추고,
남은 시간이 아주 짧을 때는 스핀 대기로 마무리한다.
"""

from __future__ import annotations

import ctypes
import time
from contextlib import contextmanager

from . import IS_WINDOWS

#: 남은 시간이 이 값보다 작으면 sleep 대신 스핀(바쁜 대기)으로 기다린다.
SPIN_THRESHOLD = 0.0015

now = time.perf_counter


@contextmanager
def high_resolution_timer():
    """with 블록 동안 1ms 타이머 해상도를 요청한다 (Windows 전용)."""
    acquired = False
    if IS_WINDOWS:
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
            acquired = True
        except Exception:
            acquired = False
    try:
        yield
    finally:
        if acquired:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass


def precise_sleep(duration: float) -> None:
    """duration 초 동안 대기한다 (짧은 구간은 스핀으로 오차 최소화)."""
    if duration <= 0:
        return
    deadline = now() + duration
    coarse = duration - SPIN_THRESHOLD
    if coarse > 0:
        time.sleep(coarse)
    while now() < deadline:
        pass


def sleep_until(deadline: float) -> None:
    precise_sleep(deadline - now())
