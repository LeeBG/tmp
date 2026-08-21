from __future__ import annotations

__all__ = ["MainWindow"]


def __getattr__(name: str):  # PySide6 를 실제로 필요할 때만 임포트
    if name == "MainWindow":
        from .main_window import MainWindow

        return MainWindow
    raise AttributeError(name)
