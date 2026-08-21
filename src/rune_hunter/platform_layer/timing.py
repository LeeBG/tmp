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

#: 이 시간 이상 기다릴 때는 스핀 없이 그냥 sleep 한다.
#: 타이머 해상도가 1ms 면 오차가 1ms 내외라 사냥 주기(수십~수백 ms)에 영향이 없다.
LONG_WAIT = 0.004

#: 아주 짧은 대기에서만 마지막 이만큼을 스핀으로 채운다.
#: (스핀은 정확하지만 CPU 를 100% 쓰기 때문에 최소로만 사용한다)
SPIN_THRESHOLD = 0.0003

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
    """duration 초 동안 대기한다.

    긴 대기는 그냥 sleep 하고(CPU 0%), 1ms 미만의 짧은 대기만 스핀으로 채운다.
    예전에는 모든 대기의 마지막 1.5ms 를 스핀으로 채웠는데, 4ms 주기 루프에서
    CPU 를 35% 나 먹었다.
    """
    if duration <= 0:
        return
    if duration >= LONG_WAIT:
        time.sleep(duration)
        return
    deadline = now() + duration
    coarse = duration - SPIN_THRESHOLD
    if coarse > 0:
        time.sleep(coarse)
    while now() < deadline:
        pass


def sleep_until(deadline: float) -> None:
    precise_sleep(deadline - now())
