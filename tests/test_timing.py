"""정밀 대기의 정확도와 CPU 비용 검증.

사냥키 주기는 이 대기 함수의 정확도에 달려 있고, CPU 비용은 게임 프레임에
영향을 준다. 둘 다 회귀하면 바로 티가 나야 한다.
"""

from __future__ import annotations

import time

import pytest

from rune_hunter.platform_layer.timing import high_resolution_timer, precise_sleep, sleep_until


@pytest.mark.parametrize("target", [0.002, 0.02, 0.1])
def test_sleep_is_accurate_enough(target):
    with high_resolution_timer():
        errors = []
        for _ in range(5):
            start = time.perf_counter()
            precise_sleep(target)
            errors.append((time.perf_counter() - start) - target)
    assert min(errors) >= -0.0005, "목표보다 빨리 깨어나면 안 된다"
    assert max(errors) < 0.02, f"오차가 너무 큼: {max(errors) * 1000:.1f}ms"


def test_sleep_does_not_burn_cpu():
    """예전에는 모든 대기의 마지막 1.5ms 를 스핀으로 채워 CPU 를 35% 썼다."""
    duration, count = 0.005, 60
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    with high_resolution_timer():
        for _ in range(count):
            precise_sleep(duration)
    wall = time.perf_counter() - wall_start
    cpu = time.process_time() - cpu_start
    assert wall >= duration * count * 0.9
    assert cpu / wall < 0.15, f"대기 중 CPU 사용률 {cpu / wall:.0%} — 스핀 대기 회귀"


def test_zero_and_negative_durations_return_immediately():
    start = time.perf_counter()
    precise_sleep(0)
    precise_sleep(-1.0)
    assert time.perf_counter() - start < 0.01


def test_sleep_until_past_deadline_returns_immediately():
    start = time.perf_counter()
    sleep_until(start - 1.0)
    assert time.perf_counter() - start < 0.01


def test_high_resolution_timer_is_reentrant():
    with high_resolution_timer():
        with high_resolution_timer():
            precise_sleep(0.001)
