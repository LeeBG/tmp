"""데모 시뮬레이터 (게임 없이 매크로 전체 동작 검증).

RecordingBackend 가 만든 키 이벤트를 받아 "게임처럼" 반응하는 가짜 세계다.
- 일정 시간마다 룬이 등장한다.
- 방향키를 누른 시간만큼 캐릭터가 이동한다(=룬의 화면상 위치가 변한다).
- 룬 근처에서 위 방향키를 누르면 화살표 4개가 뜬다.
- 화살표를 순서대로 정확히 입력하면 해제 성공, 틀리면 실패 처리.

덕분에 접근 → 활성화 → 판독 → 입력 → 확인 전 과정을 실제 게임 없이
테스트/데모할 수 있다.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import numpy as np

from .capture.base import Frame
from .inputs.base import KeyEvent
from .keys import ARROW_KEYS
from .logging_bus import EventBus
from .vision import synth


@dataclass
class DemoSettings:
    width: int = 1024
    height: int = 768
    first_rune_after: float = 6.0
    respawn_after: float = 20.0
    activate_key: str = "UP"
    rope_key: str = "A"
    move_px_per_ms: float = 0.45
    rope_climb_px: int = 150
    jump_down_px: int = 150
    activate_radius_x: int = 45
    activate_radius_y: int = 60
    max_offset_x: int = 320
    offset_y_choices: tuple[int, ...] = (0, 0, 150)
    arrow_appear_delay: float = 0.25
    solve_delay: float = 0.3
    char_x_ratio: float = 0.5
    char_y_ratio: float = 0.55
    # --- 미니맵 시뮬레이션 --------------------------------------------
    minimap: bool = True
    minimap_scale: float = 14.0                       # 미니맵 1px = 실제 몇 px
    minimap_rect: tuple[int, int, int, int] | None = None  # None 이면 기본 위치
    minimap_rune_bgr: tuple[int, int, int] = synth.MINIMAP_RUNE_BGR
    minimap_char_bgr: tuple[int, int, int] = synth.MINIMAP_CHAR_BGR


@dataclass
class DemoWorld:
    """가짜 게임 세계. FrameSource 로 그대로 사용할 수 있다."""

    settings: DemoSettings = field(default_factory=DemoSettings)
    bus: EventBus | None = None
    seed: int = 7
    time_fn: object = time.perf_counter

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self._t0 = self._now()
        self.rune_present = False
        self.rune_offset = (0, 0)          # 캐릭터 기준 (dx, dy)
        self.arrows: list[str] | None = None
        self.expected: list[str] = []
        self.buffer: list[str] = []
        self.next_spawn = self._t0 + self.settings.first_rune_after
        self._pending_arrows_at: float | None = None
        self._pending_solve_at: float | None = None
        self._down_at: dict[str, float] = {}
        self.spawned = 0
        self.solved = 0
        self.wrong_inputs = 0
        self.activate_presses = 0
        self.frames_rendered = 0

    # --- 시간 ----------------------------------------------------------
    def _now(self) -> float:
        return float(self.time_fn())  # type: ignore[operator]

    def _log(self, message: str, level: str = "info") -> None:
        if self.bus is not None:
            self.bus.log(f"[데모] {message}", level)  # type: ignore[arg-type]

    # --- 게임 진행 ------------------------------------------------------
    def tick(self) -> None:
        now = self._now()
        if not self.rune_present and now >= self.next_spawn:
            self._spawn_rune()
        if self._pending_arrows_at is not None and now >= self._pending_arrows_at:
            self._pending_arrows_at = None
            self.expected = [self.rng.choice(ARROW_KEYS) for _ in range(4)]
            self.arrows = list(self.expected)
            self.buffer.clear()
            self._log(f"방향 입력 UI 등장: {' '.join(self.expected)}")
        if self._pending_solve_at is not None and now >= self._pending_solve_at:
            self._pending_solve_at = None
            self.arrows = None
            self.rune_present = False
            self.solved += 1
            self.next_spawn = now + self.settings.respawn_after
            self._log("룬 해제 완료 (게임 측 처리)", "ok")

    def _spawn_rune(self) -> None:
        s = self.settings
        dx = self.rng.randint(-s.max_offset_x, s.max_offset_x)
        dy = self.rng.choice(list(s.offset_y_choices))
        self.rune_present = True
        self.rune_offset = (dx, dy)
        self.arrows = None
        self.buffer.clear()
        self.spawned += 1
        self._log(f"룬 등장 (캐릭터 기준 dx={dx}, dy={dy})", "warn")

    # --- 입력 처리 ------------------------------------------------------
    def on_key(self, event: KeyEvent) -> None:
        s = self.settings
        key = event.key.upper()
        if event.action == "down":
            self._down_at[key] = self._now()
            if self.arrows is not None and key in ARROW_KEYS:
                self._arrow_input(key)
            elif key == s.activate_key.upper():
                self._try_activate()
            elif key == s.rope_key.upper():
                self._climb(+s.rope_climb_px)
            return

        pressed_at = self._down_at.pop(key, None)
        if pressed_at is None:
            return
        held_ms = max(0.0, (self._now() - pressed_at) * 1000.0)
        if key in ("LEFT", "RIGHT") and self.arrows is None:
            step = int(held_ms * s.move_px_per_ms)
            direction = 1 if key == "RIGHT" else -1
            dx, dy = self.rune_offset
            self.rune_offset = (dx - direction * step, dy)
        elif key == "ALT" and "DOWN" in self._down_at and self.arrows is None:
            self._climb(-s.jump_down_px)

    def _arrow_input(self, key: str) -> None:
        self.buffer.append(key)
        if len(self.buffer) < len(self.expected):
            return
        if self.buffer == self.expected:
            self._pending_solve_at = self._now() + self.settings.solve_delay
            self._log("입력 순서 일치 → 해제 처리 중", "ok")
        else:
            self.wrong_inputs += 1
            self._log(
                f"입력 불일치 (기대 {' '.join(self.expected)} / 입력 {' '.join(self.buffer)})",
                "error",
            )
        self.buffer.clear()

    def _try_activate(self) -> None:
        s = self.settings
        self.activate_presses += 1
        if not self.rune_present or self.arrows is not None:
            return
        dx, dy = self.rune_offset
        if abs(dx) <= s.activate_radius_x and abs(dy) <= s.activate_radius_y:
            self._pending_arrows_at = self._now() + s.arrow_appear_delay
        else:
            self._log(f"룬이 너무 멀어 활성화 실패 (dx={dx}, dy={dy})")

    def _climb(self, amount: int) -> None:
        dx, dy = self.rune_offset
        self.rune_offset = (dx, dy - amount)

    # --- 렌더링 (FrameSource 인터페이스) --------------------------------
    def render(self) -> np.ndarray:
        self.tick()
        s = self.settings
        rune_pos = None
        if self.rune_present:
            cx = int(s.width * s.char_x_ratio) + self.rune_offset[0]
            cy = int(s.height * s.char_y_ratio) - self.rune_offset[1]
            # 화면을 벗어난 룬은 그리지 않는다 (미니맵에만 보이는 상황 재현)
            if 40 <= cx <= s.width - 40 and 40 <= cy <= s.height - 40:
                rune_pos = (cx, cy)
        self.frames_rendered += 1

        char_marker = rune_marker = None
        if s.minimap:
            char_marker, rune_marker = self._minimap_markers()

        return synth.render_screen(
            width=s.width,
            height=s.height,
            rune_pos=rune_pos,
            arrows=self.arrows,
            seed=self.frames_rendered % 5,
            minimap_char=char_marker,
            minimap_rune=rune_marker,
            minimap_rect=self.minimap_rect if s.minimap else None,
            minimap_rune_bgr=s.minimap_rune_bgr,
            minimap_char_bgr=s.minimap_char_bgr,
        )

    @property
    def minimap_rect(self) -> tuple[int, int, int, int]:
        return self.settings.minimap_rect or synth.MINIMAP_RECT

    def _minimap_markers(self) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        """캐릭터는 미니맵 중앙, 룬은 상대 위치에 배치한다."""
        _, _, mw, mh = self.minimap_rect
        char = (mw // 2, mh // 2)
        if not self.rune_present:
            return char, None
        scale = max(1.0, self.settings.minimap_scale)
        dx = int(round(self.rune_offset[0] / scale))
        dy = int(round(-self.rune_offset[1] / scale))  # 미니맵 y 는 아래로 증가
        rune = (
            max(4, min(mw - 4, char[0] + dx)),
            max(4, min(mh - 4, char[1] + dy)),
        )
        return char, rune

    def grab(self, region: tuple[int, int, int, int]) -> Frame:  # noqa: ARG002
        return Frame(image=self.render())

    def close(self) -> None:
        return None
