"""매크로 엔진.

스레드 구성은 일부러 단순하게 유지했다.
- 제어 스레드 1개: 키 입력 스케줄 + 룬 탐색/해제를 모두 담당한다.
- 캡처와 템플릿 매칭도 이 스레드에서 주기적으로(기본 0.6초) 수행한다.
  룬 감지 1회는 수 ms 수준이라 사냥키 주기(수십~수백 ms)에 주는 영향이 거의 없고,
  스레드 간 상태 공유가 없어져서 경합 버그가 사라진다.
- GUI 스레드는 로그 큐와 통계 스냅샷만 읽는다.

우선순위 규칙: 룬 해제 > 버프 > 보스기 > 사냥기.
룬 해제 중에는 다른 어떤 키도 입력하지 않는다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..capture.base import FrameSource
from ..config import AppConfig
from ..inputs.base import InputBackend
from ..logging_bus import EventBus
from ..platform_layer.timing import high_resolution_timer
from ..platform_layer.windows import WindowInfo, WindowLocator
from ..vision.rune import RuneVision
from .clock import Clock, RealClock
from .rune_solver import RuneAttempt, RuneOutcome, RuneSolver
from .scheduler import SkillScheduler


#: 제어 루프가 아무 할 일이 없을 때의 최소 대기 시간(초).
#: 0 으로 두면 루프가 CPU 한 코어를 그대로 태운다.
MIN_SLEEP = 0.0008


class EngineState(str, Enum):
    STOPPED = "정지"
    HUNTING = "사냥 중"
    RUNE = "룬 해제 중"
    WAITING_WINDOW = "게임 창 대기"
    WAITING_FOCUS = "게임 창 비활성"


@dataclass
class EngineStats:
    loops: int = 0
    presses: dict[str, int] = field(default_factory=dict)
    detections: int = 0
    detect_ms_total: float = 0.0
    detect_ms_max: float = 0.0
    capture_ms_total: float = 0.0
    capture_count: int = 0
    rune_attempts: int = 0
    rune_success: int = 0
    rune_last: str = "-"
    jitter_ms_max: float = 0.0
    jitter_ms_total: float = 0.0
    jitter_samples: int = 0
    started_at: float = 0.0
    uptime: float = 0.0

    @property
    def detect_ms_avg(self) -> float:
        return self.detect_ms_total / self.detections if self.detections else 0.0

    @property
    def capture_ms_avg(self) -> float:
        return self.capture_ms_total / self.capture_count if self.capture_count else 0.0

    @property
    def jitter_ms_avg(self) -> float:
        return self.jitter_ms_total / self.jitter_samples if self.jitter_samples else 0.0

    def total_presses(self) -> int:
        return sum(self.presses.values())


@dataclass
class EngineStatus:
    state: EngineState
    window: str
    stats: EngineStats


class MacroEngine:
    def __init__(
        self,
        config: AppConfig,
        inputs: InputBackend,
        capture: FrameSource,
        locator: WindowLocator,
        vision: RuneVision,
        bus: EventBus,
        clock: Clock | None = None,
        on_state: Callable[[EngineState], None] | None = None,
    ) -> None:
        self.config = config
        self.inputs = inputs
        self.capture = capture
        self.locator = locator
        self.vision = vision
        self.bus = bus
        self.clock = clock or RealClock()
        self.on_state = on_state

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = EngineState.STOPPED
        self._window: WindowInfo | None = None
        self._stats = EngineStats()
        self._scheduler = SkillScheduler()
        self._hunt_held = False
        self._rune_block_until = 0.0
        self._next_rune_check = 0.0
        self._next_window_check = 0.0
        self._next_move_at = 0.0
        self._move_dir = 1
        self._warned_no_window = False
        self._warned_focus = False
        self.last_attempt: RuneAttempt | None = None

    # --- 생명주기 -------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> EngineState:
        return self._state

    def status(self) -> EngineStatus:
        self._stats.uptime = (
            self.clock.now() - self._stats.started_at if self._stats.started_at else 0.0
        )
        return EngineStatus(
            state=self._state,
            window=self._window.describe() if self._window else "미발견",
            stats=self._stats,
        )

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._stats = EngineStats(started_at=self.clock.now())
        self._scheduler = SkillScheduler.from_configs(self.config.all_skills())
        self._scheduler.start(self.clock.now(), immediate=self.config.attack.buff_first)
        self._next_rune_check = self.clock.now()
        self._next_window_check = 0.0
        self._next_move_at = self.clock.now() + self.config.attack.movement.interval
        self._warned_no_window = self._warned_focus = False
        self._thread = threading.Thread(target=self._run, name="rune-hunter-engine", daemon=True)
        self._thread.start()
        enabled = [s.label for s in self.config.all_skills() if s.enabled]
        self.bus.ok(f"매크로 시작 — 활성 키: {', '.join(enabled) if enabled else '없음'}")
        return True

    def stop(self, timeout: float = 2.0) -> None:
        if not self.running:
            self._set_state(EngineState.STOPPED)
            return
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None
        self.inputs.release_all()
        self._hunt_held = False
        self._set_state(EngineState.STOPPED)
        stats = self._stats
        self.bus.warn(
            f"매크로 정지 — 총 입력 {stats.total_presses()}회, 룬 해제 "
            f"{stats.rune_success}/{stats.rune_attempts}"
        )

    def request_stop(self) -> None:
        self._stop.set()

    # --- 메인 루프 ------------------------------------------------------
    def _run(self) -> None:
        tick = max(0.001, self.config.general.tick_ms / 1000.0)
        with high_resolution_timer():
            try:
                while not self._stop.is_set():
                    now = self.clock.now()
                    self._stats.loops += 1

                    if not self._ensure_window(now):
                        self.clock.sleep(0.4)
                        continue

                    if self.config.general.only_when_focused and not self._is_focused():
                        self._on_focus_lost()
                        self.clock.sleep(0.15)
                        continue
                    self._on_focus_ok()

                    if self._rune_stage(now):
                        continue

                    self._skill_stage(now)
                    self._movement_stage(now)
                    self._sleep_until_next(tick)
            except Exception as exc:
                self.bus.error(f"엔진 예외로 중단: {exc!r}")
            finally:
                try:
                    self.inputs.release_all()
                except Exception:
                    pass
                self._hunt_held = False
                self._set_state(EngineState.STOPPED)

    # --- 단계별 처리 ----------------------------------------------------
    def _ensure_window(self, now: float) -> bool:
        if self._window is not None and now < self._next_window_check:
            return True
        self._next_window_check = now + 1.0
        if self._window is not None:
            refreshed = self.locator.refresh(self._window)
            if refreshed is not None:
                self._window = refreshed
                return True
            self._window = None
        found = self.locator.find(self.config.general.window_titles)
        if found is None:
            self._set_state(EngineState.WAITING_WINDOW)
            if not self._warned_no_window:
                titles = ", ".join(self.config.general.window_titles)
                self.bus.warn(f"게임 창을 찾지 못했습니다 (검색어: {titles})")
                self._warned_no_window = True
            self._release_hunt_hold()
            return False
        self._window = found
        self._warned_no_window = False
        self.bus.ok(f"게임 창 확인: {found.describe()}")
        return True

    def _is_focused(self) -> bool:
        return self._window is not None and self.locator.is_foreground(self._window)

    def _on_focus_lost(self) -> None:
        self._set_state(EngineState.WAITING_FOCUS)
        self._release_hunt_hold()
        if not self._warned_focus:
            self.bus.warn("게임 창이 비활성 상태입니다 — 입력을 잠시 멈춥니다.")
            self._warned_focus = True

    def _on_focus_ok(self) -> None:
        if self._warned_focus:
            self.bus.info("게임 창 활성화 감지 — 입력을 재개합니다.")
            self._warned_focus = False
        if self._state is not EngineState.RUNE:
            self._set_state(EngineState.HUNTING)

    def _rune_stage(self, now: float) -> bool:
        cfg = self.config.rune
        if not cfg.enabled or now < self._next_rune_check or now < self._rune_block_until:
            return False
        self._next_rune_check = now + cfg.check_interval

        frame = self._grab()
        if frame is None:
            return False
        t0 = self.clock.now()
        match = self.vision.detect_rune(frame)
        elapsed_ms = (self.clock.now() - t0) * 1000.0
        self._stats.detections += 1
        self._stats.detect_ms_total += elapsed_ms
        self._stats.detect_ms_max = max(self._stats.detect_ms_max, elapsed_ms)
        if match is None:
            return False

        self._set_state(EngineState.RUNE)
        self._release_hunt_hold()
        self.inputs.release_all()
        self._stats.rune_attempts += 1

        solver = RuneSolver(
            config=self.config,
            vision=self.vision,
            inputs=self.inputs,
            frames=self._grab,
            bus=self.bus,
            clock=self.clock,
            abort=self._stop.is_set,
        )
        attempt = solver.solve(match)
        self.last_attempt = attempt
        self._stats.rune_last = (
            f"{attempt.outcome.value}"
            + (f" [{' '.join(attempt.arrows)}]" if attempt.arrows else "")
            + f" {attempt.elapsed:.1f}초"
        )
        if attempt.success:
            self._stats.rune_success += 1
            self._rune_block_until = self.clock.now() + cfg.cooldown_success
        else:
            self.bus.warn(f"룬 해제 실패: {attempt.outcome.value} {attempt.detail}".strip())
            self._rune_block_until = self.clock.now() + (
                cfg.cooldown_fail if attempt.outcome is not RuneOutcome.NO_RUNE else 0.0
            )

        resume_at = self.clock.now()
        self._scheduler.resume_after_pause(resume_at)
        self._next_rune_check = resume_at + cfg.check_interval
        self._set_state(EngineState.HUNTING)
        return True

    def _skill_stage(self, now: float) -> None:
        due = self._scheduler.pop_due(now)
        hunt_cfg = self.config.attack.hunt

        for slot in due:
            if self._stop.is_set():
                return
            cfg = slot.config
            if cfg is hunt_cfg and cfg.hold:
                self._ensure_hunt_hold()
                continue
            self._release_hunt_hold()
            self.inputs.tap(cfg.key, cfg.press_ms, sleeper=self.clock.sleep)
            self._count_press(cfg.label)
            if self.config.general.log_key_presses and cfg.interval >= 1.0:
                self.bus.info(f"{cfg.label} 사용 ({cfg.key})")

        if hunt_cfg.enabled and hunt_cfg.hold and not due:
            self._ensure_hunt_hold()

    def _movement_stage(self, now: float) -> None:
        move = self.config.attack.movement
        if not move.enabled or now < self._next_move_at:
            return
        self._next_move_at = now + max(0.5, move.interval)
        keys = self.config.keys
        key = keys.right if self._move_dir > 0 else keys.left
        self._move_dir *= -1
        self._release_hunt_hold()
        self.inputs.hold(key, move.hold_ms, sleeper=self.clock.sleep)
        if move.jump:
            self.inputs.tap(keys.jump, 50, sleeper=self.clock.sleep)
        self._count_press("이동")

    def _sleep_until_next(self, tick: float) -> None:
        now = self.clock.now()
        deadlines = [self._scheduler.next_deadline(now + tick)]
        if self.config.rune.enabled:
            deadlines.append(max(self._next_rune_check, self._rune_block_until))
        if self.config.attack.movement.enabled:
            deadlines.append(self._next_move_at)
        deadline = min(deadlines)
        # 최소 대기를 두어 할 일이 없을 때 CPU 를 태우지 않게 한다.
        wait = min(max(deadline - now, MIN_SLEEP), tick)
        target = now + wait
        if wait > 0:
            self.clock.sleep(wait)
        drift = (self.clock.now() - target) * 1000.0
        if drift > 0:
            self._stats.jitter_ms_max = max(self._stats.jitter_ms_max, drift)
            self._stats.jitter_ms_total += drift
            self._stats.jitter_samples += 1

    # --- 보조 ----------------------------------------------------------
    def _grab(self) -> np.ndarray | None:
        if self._window is None:
            return None
        t0 = self.clock.now()
        try:
            frame = self.capture.grab(self._window.rect)
        except Exception as exc:
            self.bus.error(f"화면 캡처 실패: {exc}")
            return None
        self._stats.capture_count += 1
        self._stats.capture_ms_total += (self.clock.now() - t0) * 1000.0
        return frame.image

    def _ensure_hunt_hold(self) -> None:
        if not self._hunt_held:
            self.inputs.key_down(self.config.attack.hunt.key)
            self._hunt_held = True
            self._count_press(self.config.attack.hunt.label)

    def _release_hunt_hold(self) -> None:
        if self._hunt_held:
            try:
                self.inputs.key_up(self.config.attack.hunt.key)
            finally:
                self._hunt_held = False

    def _count_press(self, label: str) -> None:
        self._stats.presses[label] = self._stats.presses.get(label, 0) + 1

    def _set_state(self, state: EngineState) -> None:
        if state is self._state:
            return
        self._state = state
        if self.on_state is not None:
            try:
                self.on_state(state)
            except Exception:
                pass
