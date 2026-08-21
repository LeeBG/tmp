"""실행 진입점.

  python -m rune_hunter                # GUI 실행 (Windows 에서는 관리자 권한으로 자동 재실행)
  python -m rune_hunter --demo         # 데모 모드로 GUI 실행 (게임 없이 시뮬레이션)
  python -m rune_hunter --headless 20  # GUI 없이 데모 엔진만 20초 실행 (동작 점검용)
  python -m rune_hunter --diagnose     # 실행 환경 점검 (창이 바로 닫힐 때 원인 확인)

창이 뜨지 않고 바로 닫히는 상황을 잡기 위해, 모든 예외는 logs/crash.log 에 남기고
콘솔이 있으면 Enter 를 누를 때까지 창을 붙잡아 둔다.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

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
    parser.add_argument("--diagnose", action="store_true", help="실행 환경 점검 후 종료")
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def hold_console(message: str) -> None:
    """콘솔이 붙어 있으면 사용자가 읽을 때까지 창을 붙잡는다."""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input(message)
    except Exception:
        pass


def report_crash(exc: BaseException, show_dialog: bool = True) -> Path | None:
    """예외를 logs/crash.log 에 남기고, 가능하면 메시지 창으로도 보여준다."""
    text = "".join(traceback.format_exception(exc))
    path: Path | None = LOG_DIR / "crash.log"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "crash.log").open("a", encoding="utf-8") as fp:
            fp.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n{text}")
    except Exception:
        path = None

    print("\n[룬 헌터 오류]\n" + text, file=sys.stderr)
    if not show_dialog:
        return path
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
        QMessageBox.critical(
            None,
            "룬 헌터 오류",
            "프로그램을 시작할 수 없습니다.\n\n"
            + text[-1200:]
            + (f"\n\n자세한 내용: {path}" if path else ""),
        )
    except Exception:
        pass
    return path


def diagnose(config: AppConfig) -> int:
    """창이 바로 닫힐 때 원인을 찾기 위한 환경 점검."""
    import platform

    print("=" * 72)
    print("룬 헌터 환경 점검")
    print("=" * 72)
    print(f"파이썬        : {sys.version.split()[0]} ({platform.architecture()[0]})")
    print(f"실행 파일     : {sys.executable}")
    print(f"OS            : {platform.platform()}")
    print(f"관리자 권한   : {'예' if is_admin() else '아니오'}")
    print(f"작업 폴더     : {Path.cwd()}")
    print(f"프로필        : {DEFAULT_PROFILE_PATH} (존재: {DEFAULT_PROFILE_PATH.exists()})")
    print(f"로그 폴더     : {LOG_DIR}")

    print("-" * 72)
    ok = True
    for name in ("PySide6", "cv2", "numpy", "mss"):
        try:
            module = __import__(name)
            version = getattr(module, "__version__", "?")
            print(f"[정상] {name:9s} {version}")
        except Exception as exc:
            ok = False
            print(f"[실패] {name:9s} {exc}")
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401

        print("[정상] PySide6 QtWidgets 로딩")
    except Exception as exc:
        ok = False
        print(f"[실패] PySide6 QtWidgets — {exc}")
        print("       → Microsoft Visual C++ 재배포 패키지가 필요할 수 있습니다.")

    print("-" * 72)
    from .vision import RuneVision

    ready, missing = RuneVision(config).templates_ready()
    if ready:
        print("[정상] 룬/화살표 템플릿 5장 확인")
    else:
        print("[주의] 템플릿 없음 (룬 해제만 동작하지 않음):")
        for path in missing:
            print("       -", Path(path).name)

    print("-" * 72)
    from .platform_layer.windows import create_locator

    window = create_locator().find(config.general.window_titles)
    titles = ", ".join(config.general.window_titles)
    if window is None:
        print(f"[주의] 게임 창을 찾지 못했습니다 (검색어: {titles})")
    else:
        print(f"[정상] 게임 창: {window.describe()}")

    print("=" * 72)
    print("결과:", "실행 가능" if ok else "필수 모듈이 없어 실행 불가 → run.bat 을 다시 실행하세요")
    return 0 if ok else 1


def run_headless(config: AppConfig, bus: EventBus, seconds: float) -> int:
    """GUI 없이 데모 세계에서 엔진을 돌려 동작을 확인한다."""
    import time

    from .demo import DemoSettings, DemoWorld
    from .engine import MacroEngine
    from .inputs import RecordingBackend
    from .platform_layer.windows import VirtualWindowLocator
    from .vision import RuneVision
    from .vision.matcher import template_from_array
    from .vision.synth import color_from_spec, demo_templates

    settings = DemoSettings(activate_key=config.rune.activate_key)
    if config.rune.use_minimap:
        mm = config.rune.minimap
        settings.minimap_rect = mm.roi.to_pixels(settings.width, settings.height)
        settings.minimap_rune_bgr = color_from_spec(mm.rune_color)
        settings.minimap_char_bgr = color_from_spec(mm.char_color)
        settings.max_offset_x = 420
    world = DemoWorld(bus=bus, settings=settings)
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


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_file_logging(LOG_DIR)
    bus = EventBus()
    config = AppConfig.load(args.profile)

    if args.diagnose:
        code = diagnose(config)
        hold_console("\nEnter 를 누르면 창이 닫힙니다… ")
        return code

    if args.headless > 0:
        return run_headless(config, bus, args.headless)

    if IS_WINDOWS and not args.no_admin and not args.elevated and not is_admin():
        print("관리자 권한으로 다시 실행합니다 (UAC 창에서 '예' 를 눌러주세요)…")
        if relaunch_as_admin(["--elevated"]):
            return 0
        print("관리자 권한 승격이 취소되었습니다 — 일반 권한으로 계속합니다.")
        bus.warn("관리자 권한 승격이 취소되었습니다 — 일반 권한으로 계속합니다.")

    enable_dpi_awareness()

    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("룬 헌터")
    window = MainWindow(config, bus, demo=args.demo)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except SystemExit:
        raise
    except BaseException as exc:  # 창이 조용히 닫히는 대신 원인을 남긴다
        import os

        path = report_crash(exc, show_dialog=not os.environ.get("RUNE_HUNTER_NO_DIALOG"))
        hold_console(
            f"\n오류 내용을 {path} 에 저장했습니다.\nEnter 를 누르면 창이 닫힙니다… "
            if path
            else "\nEnter 를 누르면 창이 닫힙니다… "
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
