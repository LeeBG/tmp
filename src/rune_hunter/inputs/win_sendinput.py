"""Windows SendInput(스캔코드) 기반 키 입력.

- 가상키가 아니라 **스캔코드**(KEYEVENTF_SCANCODE)를 보낸다.
  메이플 계열 클라이언트는 DirectInput/RawInput 으로 키를 읽어서
  keybd_event 의 가상키 입력을 무시하는 경우가 많다.
- 방향키/일부 키는 확장 플래그(KEYEVENTF_EXTENDEDKEY)가 필요하다.
- PostMessage/SendMessage 방식은 이 계열 클라이언트에서 대체로 동작하지 않아
  사용하지 않는다 (창이 활성화되어 있어야 입력이 들어간다).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..keys import resolve
from .base import InputBackend

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def key_flags(name: str, down: bool) -> tuple[int, int]:
    """키 이름 -> (스캔코드, SendInput 플래그). 순수 함수라 테스트가 쉽다."""
    keydef = resolve(name)
    flags = KEYEVENTF_SCANCODE
    if keydef.extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if not down:
        flags |= KEYEVENTF_KEYUP
    return keydef.scan, flags


class SendInputBackend(InputBackend):
    def __init__(self) -> None:
        super().__init__()
        self._user32 = ctypes.windll.user32
        self._user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        )
        self._user32.SendInput.restype = wintypes.UINT
        self.failures = 0

    def _send(self, key: str, down: bool) -> None:
        scan, flags = key_flags(key, down)
        payload = _INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUTUNION(
                ki=_KEYBDINPUT(
                    wVk=0,
                    wScan=scan,
                    dwFlags=flags,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        sent = self._user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(_INPUT))
        if sent != 1:
            self.failures += 1
            raise OSError(
                f"SendInput 실패 (key={key}, GetLastError={ctypes.GetLastError()}). "
                "게임이 관리자 권한으로 실행 중이면 매크로도 관리자 권한이 필요합니다."
            )
