"""OS 의존 기능 모음 (Windows 우선, 그 외 OS 는 개발/테스트용 대체 구현)."""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform.startswith("win")

__all__ = ["IS_WINDOWS"]
