"""관리자 권한 확인 및 승격 재실행.

게임 클라이언트가 관리자 권한으로 떠 있으면, 같은 권한이 아닌 프로세스의
키 입력은 UIPI(User Interface Privilege Isolation)에 막혀 아무 반응이 없다.
그래서 매크로도 관리자 권한으로 실행되어야 한다.
"""

from __future__ import annotations

import ctypes
import os
import sys

from . import IS_WINDOWS


def is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args: list[str] | None = None) -> bool:
    """UAC 승격으로 자신을 다시 실행한다. 성공하면 True (호출자는 종료해야 함)."""
    if not IS_WINDOWS or is_admin():
        return False
    args = [*sys.argv[1:], *(extra_args or [])]
    params = " ".join(f'"{a}"' for a in [os.path.abspath(sys.argv[0]), *args])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
    except Exception:
        return False
    return rc > 32


def enable_dpi_awareness() -> None:
    """DPI 배율 100% 가 아닐 때 창 좌표가 어긋나는 문제를 막는다."""
    if not IS_WINDOWS:
        return
    try:  # Windows 10 1703+
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
