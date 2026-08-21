"""게임 창 찾기 / 좌표 계산 / 활성창 확인.

Windows 에서는 user32 를 ctypes 로 직접 호출한다 (pywin32 의존성 없음).
그 외 OS 에서는 개발·테스트를 위해 화면 전체를 하나의 창으로 취급하는
대체 구현을 사용한다.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, replace
from typing import Protocol

from . import IS_WINDOWS


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    pid: int
    process_name: str
    left: int
    top: int
    width: int
    height: int

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    def describe(self) -> str:
        name = self.process_name or "?"
        return f"{self.title} ({name}, PID {self.pid}) {self.width}x{self.height}"


class WindowLocator(Protocol):
    def find(self, titles: list[str]) -> WindowInfo | None: ...
    def refresh(self, info: WindowInfo) -> WindowInfo | None: ...
    def is_foreground(self, info: WindowInfo) -> bool: ...


# --------------------------------------------------------------------------
# Windows 구현
# --------------------------------------------------------------------------
class Win32WindowLocator:
    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

    def _titles_of_visible_windows(self):
        user32 = self._user32
        results: list[tuple[int, str]] = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            results.append((hwnd, buf.value))
            return True

        user32.EnumWindows(WNDENUMPROC(callback), None)
        return results

    def _pid_of(self, hwnd: int) -> int:
        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def _process_name(self, pid: int) -> str:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(512)
            buf = ctypes.create_unicode_buffer(size.value)
            if self._kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size)
            ):
                return buf.value.rsplit("\\", 1)[-1]
            return ""
        finally:
            self._kernel32.CloseHandle(handle)

    def _client_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        rect = RECT()
        if not self._user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        origin = POINT(0, 0)
        if not self._user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return origin.x, origin.y, width, height

    def _build(self, hwnd: int, title: str) -> WindowInfo | None:
        geom = self._client_rect(hwnd)
        if geom is None:
            return None
        pid = self._pid_of(hwnd)
        return WindowInfo(
            handle=hwnd,
            title=title,
            pid=pid,
            process_name=self._process_name(pid),
            left=geom[0],
            top=geom[1],
            width=geom[2],
            height=geom[3],
        )

    def find(self, titles: list[str]) -> WindowInfo | None:
        wanted = [t.strip().lower() for t in titles if t.strip()]
        best: WindowInfo | None = None
        for hwnd, title in self._titles_of_visible_windows():
            low = title.lower()
            if wanted and not any(w in low for w in wanted):
                continue
            info = self._build(hwnd, title)
            if info is None:
                continue
            # 여러 개가 걸리면 가장 큰 창(실제 게임 화면)을 고른다
            if best is None or info.width * info.height > best.width * best.height:
                best = info
        return best

    def refresh(self, info: WindowInfo) -> WindowInfo | None:
        if not self._user32.IsWindow(info.handle):
            return None
        geom = self._client_rect(info.handle)
        if geom is None:
            return None
        return replace(info, left=geom[0], top=geom[1], width=geom[2], height=geom[3])

    def is_foreground(self, info: WindowInfo) -> bool:
        return int(self._user32.GetForegroundWindow()) == int(info.handle)


# --------------------------------------------------------------------------
# 비 Windows(개발/테스트) 구현
# --------------------------------------------------------------------------
class VirtualWindowLocator:
    """개발용: 화면 전체(혹은 지정 크기)를 게임 창처럼 취급한다."""

    def __init__(self, width: int = 1366, height: int = 768, title: str = "가상 게임 창") -> None:
        self._info = WindowInfo(
            handle=1,
            title=title,
            pid=0,
            process_name="virtual",
            left=0,
            top=0,
            width=width,
            height=height,
        )

    def find(self, titles: list[str]) -> WindowInfo | None:  # noqa: ARG002
        return self._info

    def refresh(self, info: WindowInfo) -> WindowInfo | None:  # noqa: ARG002
        return self._info

    def is_foreground(self, info: WindowInfo) -> bool:  # noqa: ARG002
        return True


def create_locator(**kwargs) -> WindowLocator:
    if IS_WINDOWS:
        return Win32WindowLocator()
    return VirtualWindowLocator(**kwargs)
