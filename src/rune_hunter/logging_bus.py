"""스레드 안전 로그 버스.

엔진 스레드는 큐에 넣기만 하고(락 경쟁 없음), GUI 는 타이머로 큐를 비운다.
동시에 파일 로그도 남겨서 나중에 원인 추적이 가능하게 한다.
"""

from __future__ import annotations

import logging
import queue
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

Level = Literal["debug", "info", "ok", "warn", "error"]

_LEVEL_TO_LOGGING = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "ok": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


@dataclass(frozen=True)
class LogEvent:
    ts: float
    level: Level
    message: str

    def formatted(self) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(self.ts))
        return f"[{stamp}] {self.message}"


class EventBus:
    def __init__(self, maxsize: int = 4096, logger_name: str = "rune_hunter") -> None:
        self._q: queue.Queue[LogEvent] = queue.Queue(maxsize=maxsize)
        self._logger = logging.getLogger(logger_name)
        self._dropped = 0

    def log(self, message: str, level: Level = "info") -> None:
        event = LogEvent(time.time(), level, message)
        self._logger.log(_LEVEL_TO_LOGGING[level], message)
        try:
            self._q.put_nowait(event)
        except queue.Full:
            self._dropped += 1

    def info(self, message: str) -> None:
        self.log(message, "info")

    def ok(self, message: str) -> None:
        self.log(message, "ok")

    def warn(self, message: str) -> None:
        self.log(message, "warn")

    def error(self, message: str) -> None:
        self.log(message, "error")

    def debug(self, message: str) -> None:
        self.log(message, "debug")

    def drain(self, limit: int = 200) -> list[LogEvent]:
        out: list[LogEvent] = []
        for _ in range(limit):
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out

    @property
    def dropped(self) -> int:
        return self._dropped


def setup_file_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "rune_hunter.log"
    logger = logging.getLogger("rune_hunter")
    logger.setLevel(logging.DEBUG)
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
    return path
