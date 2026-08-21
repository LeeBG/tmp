"""실행 진입점.

  python -m rune_hunter                # GUI 실행 (Windows 에서는 관리자 권한으로 자동 재실행)
  python -m rune_hunter --demo         # 데모 모드로 GUI 실행 (게임 없이 시뮬레이션)
  python -m rune_hunter --headless 20  # GUI 없이 데모 엔진만 20초 실행 (동작 점검용)
"""

from __future__ import annotations

import argparse
import sys

from .config import DEFAULT_PROFILE_PATH, LOG_DIR, AppConfig
from .logging_bus import EventBus, setup_file_logging
from .platform_layer import IS_WINDOWS
from .platform_layer.admin import enable_dpi_awareness, is_admin, relaunch_as_admin


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rune-hunter", description="사냥 · 버프 · 룬 해제 매크로"
    )
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH), help="설정 JSON 경로")
    parser.add_argument("--demo", action="store_true", help="데모 모드로 시작")
    parser.add_argument(
        "--headless", type=float, default=0.0, metavar="초", help="GUI 없이 데모 엔진 실행"
    )
    parser.add_argument(
        "--no-admin", action="store_true", help="관리자 권한 자동 승격을 하지 않음"
    )
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def run_headless(config: AppConfig, bus: EventBus, seconds: float) -> int:
    """GUI 없이 데모 세계에서 엔진을 돌려 동작을 확인한다."""
    import time

    from .demo import DemoWorld
    from .engine import MacroEngine
    from .inputs import RecordingBackend
    from .platform_layer.windows import VirtualWindowLocator
    from .vision import RuneVision
    from .vision.matcher import template_from_array
    from .vision.synth import demo_templates

    world = DemoWorld(bus=bus)
    backend = RecordingBackend(sink=world.on_key)
    vision = RuneVision(config)
    for name, image in demo_templates().items():
        vision.register_template(name, template_from_array(image, name))

    engine = MacroEngine(
        config=config,
        inputs=backend,
        capture=world,
        locator=VirtualWindowLocator(world.settings.width, world.settings.height, "데모 창"),
        vision=vision,
        bus=bus,
    )
    engine.start()
    deadline = time.perf_counter() + seconds
    try:
        while time.perf_counter() < deadline:
            for event in bus.drain():
                print(event.formatted())
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    engine.stop()
    for event in bus.drain():
        print(event.formatted())

    status = engine.status()
    stats = status.stats
    print("\n=== 요약 ===")
    print(f"제어 루프           : {stats.loops:,}회")
    print(f"키 입력             : {stats.presses}")
    print(f"룬 감지 평균/최대   : {stats.detect_ms_avg:.2f} / {stats.detect_ms_max:.2f} ms")
    print(f"루프 지연 평균/최대 : {stats.jitter_ms_avg:.2f} / {stats.jitter_ms_max:.2f} ms")
    print(f"룬 해제             : {stats.rune_success} / {stats.rune_attempts} 성공")
    print(f"데모 세계 기록      : 등장 {world.spawned}회, 해제 {world.solved}회, 오입력 {world.wrong_inputs}회")
    return 0 if stats.rune_success > 0 or seconds < 10 else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_file_logging(LOG_DIR)
    bus = EventBus()
    config = AppConfig.load(args.profile)

    if args.headless > 0:
        return run_headless(config, bus, args.headless)

    if IS_WINDOWS and not args.no_admin and not args.elevated and not is_admin():
        if relaunch_as_admin(["--elevated"]):
            return 0
        bus.warn("관리자 권한 승격이 취소되었습니다 — 일반 권한으로 계속합니다.")

    enable_dpi_awareness()

    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("룬 헌터")
    window = MainWindow(config, bus, demo=args.demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
