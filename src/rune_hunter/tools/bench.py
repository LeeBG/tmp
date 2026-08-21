"""성능 측정 도구.

  python -m rune_hunter.tools.bench                 # 합성 화면으로 측정
  python -m rune_hunter.tools.bench --live          # 실제 게임 창을 캡처해 측정
  python -m rune_hunter.tools.bench --iters 300

측정 항목
- 화면 캡처 1회 시간
- 룬 감지 1회 시간 (전체 영역 / 좁힌 영역 비교)
- 화살표 판독 1회 시간
- 키 입력 스케줄러의 이론상 최대 처리량
- 정밀 sleep 오차 (사냥키 주기 정확도의 근거)
"""

from __future__ import annotations

import argparse
import statistics
import time

from ..config import AppConfig, Roi
from ..platform_layer.timing import high_resolution_timer, precise_sleep
from ..vision import RuneVision
from ..vision.matcher import template_from_array
from ..vision.synth import demo_templates, render_screen


def _stats(samples: list[float]) -> str:
    if not samples:
        return "샘플 없음"
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return (
        f"평균 {statistics.fmean(samples):6.2f} ms | "
        f"중앙 {statistics.median(samples):6.2f} ms | "
        f"p95 {p95:6.2f} ms | 최대 {max(samples):6.2f} ms"
    )


def bench_vision(iters: int, live: bool) -> None:
    config = AppConfig()
    vision = RuneVision(config)
    for name, image in demo_templates().items():
        vision.register_template(name, template_from_array(image, name))

    frames = []
    if live:
        from ..capture import ScreenCapture
        from ..platform_layer.windows import create_locator

        locator = create_locator()
        window = locator.find(config.general.window_titles)
        if window is None:
            print("게임 창을 찾지 못했습니다 — 합성 화면으로 측정합니다.")
            live = False
        else:
            capture = ScreenCapture()
            grab_samples = []
            for _ in range(min(iters, 60)):
                t0 = time.perf_counter()
                frame = capture.grab(window.rect)
                grab_samples.append((time.perf_counter() - t0) * 1000)
                frames.append(frame.image)
            print(f"[캡처   ] {window.width}x{window.height}  {_stats(grab_samples)}")

    if not frames:
        frames = [
            render_screen(
                rune_pos=(400 + i * 7 % 400, 400),
                arrows=["UP", "LEFT", "DOWN", "RIGHT"],
                seed=i % 5,
            )
            for i in range(10)
        ]
        print(f"[캡처   ] 합성 화면 {frames[0].shape[1]}x{frames[0].shape[0]} (캡처 시간 측정 제외)")

    samples = []
    for i in range(iters):
        frame = frames[i % len(frames)]
        t0 = time.perf_counter()
        vision.detect_rune(frame)
        samples.append((time.perf_counter() - t0) * 1000)
    print(f"[룬 감지] 전체 영역   {_stats(samples)}")

    config.rune.detect_scale = 0.5
    samples = []
    for i in range(iters):
        frame = frames[i % len(frames)]
        t0 = time.perf_counter()
        vision.detect_rune(frame)
        samples.append((time.perf_counter() - t0) * 1000)
    print(f"[룬 감지] 축소 0.5배  {_stats(samples)}")
    config.rune.detect_scale = 1.0

    config.rune.rune_roi = Roi(0.15, 0.25, 0.7, 0.5)
    samples = []
    for i in range(iters):
        frame = frames[i % len(frames)]
        t0 = time.perf_counter()
        vision.detect_rune(frame)
        samples.append((time.perf_counter() - t0) * 1000)
    print(f"[룬 감지] 좁힌 영역   {_stats(samples)}")

    samples = []
    for i in range(iters):
        frame = frames[i % len(frames)]
        t0 = time.perf_counter()
        vision.read_arrows(frame)
        samples.append((time.perf_counter() - t0) * 1000)
    print(f"[화살표 ] 상단 영역   {_stats(samples)}")


def bench_timing(iters: int = 200) -> None:
    with high_resolution_timer():
        for target_ms in (5, 20, 120):
            errors = []
            for _ in range(max(20, iters // 10)):
                t0 = time.perf_counter()
                precise_sleep(target_ms / 1000.0)
                errors.append(abs((time.perf_counter() - t0) * 1000 - target_ms))
            print(f"[타이머 ] {target_ms:3d} ms 목표 오차  {_stats(errors)}")


def bench_scheduler(seconds: float = 1.0) -> None:
    from ..config import SkillConfig
    from ..engine.scheduler import SkillScheduler

    slots = [
        SkillConfig(label="사냥기", key="U", enabled=True, interval=0.1),
        SkillConfig(label="버프1", key="Q", enabled=True, interval=120.0),
        SkillConfig(label="버프2", key="W", enabled=True, interval=180.0),
    ]
    scheduler = SkillScheduler.from_configs(slots)
    now = 0.0
    scheduler.start(now)
    count = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        now += 0.001
        count += len(scheduler.pop_due(now))
    ops = count / (time.perf_counter() - t0)
    print(f"[스케줄 ] 1초당 처리 가능한 스킬 결정 수 ≈ {ops:,.0f}회 (실사용은 초당 수십 회)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="룬 헌터 성능 측정")
    parser.add_argument("--iters", type=int, default=200, help="반복 횟수")
    parser.add_argument("--live", action="store_true", help="실제 게임 창 캡처 포함")
    args = parser.parse_args(argv)

    print("=" * 78)
    print("룬 헌터 성능 측정")
    print("=" * 78)
    bench_vision(args.iters, args.live)
    bench_timing(args.iters)
    bench_scheduler()
    print("-" * 78)
    print("기준: 룬 탐색은 기본 0.6초에 1회만 수행하므로 감지 시간 10ms 는 CPU 점유 약 1.7% 수준.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
