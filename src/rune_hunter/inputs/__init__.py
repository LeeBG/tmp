from __future__ import annotations

from ..platform_layer import IS_WINDOWS
from .base import InputBackend, KeyEvent
from .recorder import RecordingBackend

__all__ = ["InputBackend", "KeyEvent", "RecordingBackend", "create_backend"]


def create_backend(record: bool = False) -> InputBackend:
    """실행 환경에 맞는 입력 백엔드를 만든다."""
    if record or not IS_WINDOWS:
        return RecordingBackend()
    from .win_sendinput import SendInputBackend

    return SendInputBackend()
