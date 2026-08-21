"""전역 단축키 (F1 시작 / F2 정지 등).

Windows 는 RegisterHotKey + 메시지 루프를 전용 스레드에서 돌린다.
게임 창이 활성화된 상태에서도 매크로를 시작/정지할 수 있어야 하므로 전역 등록이 필요하다.
콜백은 이 스레드에서 호출되므로, GUI 쪽에서는 시그널로 넘겨서 처리한다.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable

from .keys import resolve
from .logging_bus import EventBus
from .platform_layer import IS_WINDOWS

if IS_WINDOWS:  # wintypes 는 Windows 에서만 안전하게 임포트된다
    from ctypes import wintypes

WM_HOTKEY = 0x0312


class HotkeyManager:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._bindings: dict[str, Callable[[], None]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.active = False

    def bind(self, key_name: str, callback: Callable[[], None]) -> None:
        self._bindings[key_name.upper()] = callback

    def clear(self) -> None:
        self._bindings.clear()

    def start(self) -> bool:
        if not IS_WINDOWS:
            if self._bindings:
                keys = ", ".join(self._bindings)
                self.bus.warn(
                    f"이 OS 에서는 전역 단축키({keys})를 지원하지 않습니다 — 화면의 버튼을 사용하세요."
                )
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rune-hunter-hotkeys", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(1.0)
        self._thread = None
        self.active = False

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        registered: dict[int, Callable[[], None]] = {}
        for index, (key_name, callback) in enumerate(self._bindings.items(), start=1):
            try:
                vk = resolve(key_name).vk
            except ValueError:
                self.bus.warn(f"단축키로 쓸 수 없는 키: {key_name}")
                continue
            if vk is None:
                continue
            if user32.RegisterHotKey(None, index, 0, vk):
                registered[index] = callback
                self.bus.info(f"전역 단축키 등록: {key_name}")
            else:
                self.bus.warn(f"단축키 {key_name} 등록 실패 (다른 프로그램이 사용 중일 수 있습니다)")

        self.active = bool(registered)
        try:
            msg = wintypes.MSG()
            while not self._stop.is_set():
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == WM_HOTKEY:
                        callback = registered.get(int(msg.wParam))
                        if callback is not None:
                            try:
                                callback()
                            except Exception as exc:
                                self.bus.error(f"단축키 처리 중 오류: {exc}")
                else:
                    self._stop.wait(0.02)
        finally:
            for index in registered:
                try:
                    user32.UnregisterHotKey(None, index)
                except Exception:
                    pass
