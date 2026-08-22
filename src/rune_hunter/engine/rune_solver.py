"""룬 해제 상태 머신.

호출되면 해제가 끝날 때까지(성공/실패/중단) 블로킹으로 돌기 때문에,
이 루틴이 도는 동안 사냥·버프 키는 절대 입력되지 않는다("룬 해제에 집중").

단계
1) 감지  : 화면에서 룬 템플릿을 찾는다.
2) 접근  : (선택) 룬과 캐릭터의 x/y 차이를 보고 방향키·점프·로프로 붙는다.
3) 활성화: 룬 앞에서 위 방향키를 눌러 방향 입력 UI 를 띄운다.
4) 판독  : 화살표 4개를 읽는다. 같은 결과가 N번 연속 나오면 확정한다.
5) 입력  : 읽은 순서대로 방향키를 넣는다.
6) 확인  : 화살표 UI 가 사라지면 성공, 남아 있으면 재시도.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..config import AppConfig
from ..inputs.base import InputBackend
from ..keys import ARROW_KEYS
from ..logging_bus import EventBus
from ..vision.matcher import Match
from ..vision.minimap import MinimapVision
from ..vision.rune import RuneVision
from .clock import Clock, RealClock

FrameProvider = Callable[[], np.ndarray | None]


class RuneOutcome(str, Enum):
    SUCCESS = "성공"
    NO_RUNE = "룬 없음"
    APPROACH_TIMEOUT = "접근 실패"
    ACTIVATE_TIMEOUT = "활성화 실패"
    READ_FAILED = "화살표 판독 실패"
    VERIFY_FAILED = "해제 확인 실패"
    ABORTED = "중단됨"
    ERROR = "오류"


@dataclass
class RuneAttempt:
    outcome: RuneOutcome
    arrows: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    retries: int = 0
    detail: str = ""

    @property
    def success(self) -> bool:
        return self.outcome is RuneOutcome.SUCCESS


class RuneSolver:
    def __init__(
        self,
        config: AppConfig,
        vision: RuneVision,
        inputs: InputBackend,
        frames: FrameProvider,
        bus: EventBus,
        clock: Clock | None = None,
        abort: Callable[[], bool] | None = None,
        minimap: MinimapVision | None = None,
    ) -> None:
        self.config = config
        self.vision = vision
        self.inputs = inputs
        self.frames = frames
        self.bus = bus
        self.clock = clock or RealClock()
        self._abort = abort or (lambda: False)
        self.minimap = minimap or MinimapVision(config)

    # --- 공개 API -------------------------------------------------------
    def solve(self, known_rune: Match | None = None) -> RuneAttempt:
        started = self.clock.now()
        try:
            return self._solve(started, known_rune)
        except Exception as exc:  # 매크로가 죽지 않게 항상 회수
            self.bus.error(f"룬 해제 중 오류: {exc}")
            self.inputs.release_all()
            return RuneAttempt(
                RuneOutcome.ERROR, elapsed=self.clock.now() - started, detail=str(exc)
            )

    # --- 내부 단계 -------------------------------------------------------
    def _solve(self, started: float, known_rune: Match | None) -> RuneAttempt:
        cfg = self.config.rune

        if cfg.use_minimap:
            frame = self.frames()
            reading = self.minimap.read(frame) if frame is not None else None
            if reading is None or reading.rune is None:
                # 룬 위에 서 있으면 캐릭터 표식이 룬 표식을 덮어 미니맵에서 사라진다.
                # 이때는 화면에 룬이 크게 보이므로 그것으로 확인한다.
                on_screen = (
                    cfg.minimap.screen_fallback
                    and frame is not None
                    and self.vision.detect_rune(frame) is not None
                )
                if not on_screen:
                    return self._done(RuneOutcome.NO_RUNE, started)
                self.bus.warn(
                    "미니맵 표식이 가려졌지만 화면에서 룬 확인 → 스킬 입력 중단, 룬 해제 집중"
                )
                self._fine_align_on_screen()
            else:
                self.bus.warn(
                    f"미니맵에서 룬 발견 ({reading.describe()}) → 스킬 입력 중단, 룬 해제 집중"
                )
                ok, detail = self._approach_minimap(started)
                if self._abort():
                    return self._done(RuneOutcome.ABORTED, started)
                if not ok:
                    self.bus.warn(f"룬 접근 실패: {detail}")
                    return self._done(RuneOutcome.APPROACH_TIMEOUT, started, detail=detail)
                self._fine_align_on_screen()
        elif cfg.use_banner:
            frame = self.frames()
            banner = self.vision.detect_banner(frame) if frame is not None else None
            if banner is None:
                return self._done(RuneOutcome.NO_RUNE, started)
            self.bus.warn(
                f"안내 문구 감지 (점수 {banner.score:.2f}) → 스킬 입력 중단, 룬 해제 집중"
            )
        else:
            rune = known_rune
            if rune is None:
                frame = self.frames()
                rune = self.vision.detect_rune(frame) if frame is not None else None
            if rune is None:
                return self._done(RuneOutcome.NO_RUNE, started)

            self.bus.warn(
                f"룬 감지 (점수 {rune.score:.2f}, 위치 {rune.center}) → 스킬 입력 중단, 룬 해제 집중"
            )

            if cfg.approach.enabled:
                ok, detail = self._approach(started)
                if self._abort():
                    return self._done(RuneOutcome.ABORTED, started)
                if not ok:
                    self.bus.warn(f"룬 접근 실패: {detail}")
                    return self._done(RuneOutcome.APPROACH_TIMEOUT, started, detail=detail)

        last_outcome = RuneOutcome.ACTIVATE_TIMEOUT
        last_arrows: list[str] = []
        for retries in range(max(0, cfg.max_retries) + 1):
            if retries:
                self.bus.warn(f"룬 해제 재시도 {retries}/{cfg.max_retries}")
            if self._abort():
                return self._done(RuneOutcome.ABORTED, started, retries=retries)

            reading = self._activate()
            if reading is None:
                self.bus.warn("룬 활성화 후 방향 입력 UI 를 찾지 못했습니다.")
                last_outcome = RuneOutcome.ACTIVATE_TIMEOUT
                continue
            if not reading.ok:
                self.bus.warn(f"화살표 판독 실패: {reading.reason}")
                retry_reading = self._read_arrows(cfg.arrow_wait)
                if retry_reading is None or not retry_reading.ok:
                    last_outcome = RuneOutcome.READ_FAILED
                    continue
                reading = retry_reading

            self.bus.info(f"화살표 판독: {reading.describe()}  ({reading.sequence})")
            last_arrows = list(reading.sequence)
            self._send_arrows(reading.sequence)

            verdict = self._verify()
            if verdict == "success":
                self.bus.ok(f"룬 해제 성공 ({reading.describe()}) → 사냥/버프 재개")
                return self._done(
                    RuneOutcome.SUCCESS, started, arrows=reading.sequence, retries=retries
                )
            if verdict == "arrows_remain":
                self.bus.warn("화살표 UI 가 그대로 남아 있습니다 (입력이 전달되지 않았을 수 있음)")
                last_outcome = RuneOutcome.VERIFY_FAILED
            else:  # rune_remains — 입력 순서가 틀렸을 때 게임이 이렇게 반응한다
                self.bus.warn("화살표는 사라졌지만 룬이 남아 있습니다 — 입력 순서 실패로 판단")
                last_outcome = RuneOutcome.VERIFY_FAILED

        return self._done(
            last_outcome, started, arrows=last_arrows, retries=max(0, cfg.max_retries)
        )

    def _approach(self, started: float) -> tuple[bool, str]:
        cfg = self.config.rune.approach
        keys = self.config.keys
        deadline = started + cfg.max_seconds
        aligned_x = aligned_y = False

        while self.clock.now() < deadline:
            if self._abort():
                return False, "사용자 중단"
            frame = self.frames()
            if frame is None:
                return False, "화면 캡처 실패"
            rune = self.vision.detect_rune(frame)
            if rune is None:
                return False, "접근 중 룬을 잃어버렸습니다"

            h, w = frame.shape[:2]
            char_x = int(cfg.char_x * w)
            char_y = int(cfg.char_y * h)
            dx = rune.cx - char_x
            dy = char_y - rune.cy  # 양수면 룬이 캐릭터보다 위에 있다

            aligned_x = abs(dx) <= cfg.deadzone_px
            aligned_y = abs(dy) <= cfg.vertical_tolerance
            if aligned_x and aligned_y:
                return True, "정렬 완료"

            if not aligned_x:
                key = keys.right if dx > 0 else keys.left
                hold = int(min(cfg.max_hold_ms, max(60, abs(dx) * cfg.ms_per_px)))
                self.bus.debug(f"룬 접근: {'오른쪽' if dx > 0 else '왼쪽'} {hold}ms (x차이 {dx}px)")
                self.inputs.hold(key, hold, sleeper=self.clock.sleep)
                self.clock.sleep(0.08)
                continue

            if dy > cfg.vertical_tolerance:
                if cfg.use_rope:
                    self.bus.debug(f"룬 접근: 로프 커넥트로 상승 (y차이 {dy}px)")
                    self.inputs.tap(keys.rope, 60, sleeper=self.clock.sleep)
                    self.clock.sleep(0.9)
                else:
                    self.bus.debug(f"룬 접근: 점프로 상승 (y차이 {dy}px)")
                    self.inputs.tap(keys.jump, 60, sleeper=self.clock.sleep)
                    self.clock.sleep(0.5)
            elif dy < -cfg.vertical_tolerance and cfg.jump_down:
                self.bus.debug(f"룬 접근: 아래 점프 (y차이 {dy}px)")
                self.inputs.chord([keys.down, keys.jump], 70, sleeper=self.clock.sleep)
                self.clock.sleep(0.6)
            else:
                self.clock.sleep(0.1)

        return False, f"{cfg.max_seconds:.0f}초 내 접근 실패"

    def _approach_minimap(self, started: float) -> tuple[bool, str]:
        """미니맵의 노란 캐릭터 표식이 보라색 룬 표식을 덮을 때까지 이동한다.

        미니맵 1픽셀이 실제로 몇 ms 이동인지는 맵마다 다르므로, 이동할 때마다
        '누른 시간 ÷ 실제로 줄어든 픽셀' 을 측정해 계수를 스스로 보정한다.
        """
        cfg = self.config.rune.minimap
        keys = self.config.keys
        deadline = started + cfg.max_seconds
        ms_per_px = max(1.0, cfg.ms_per_px)
        pending: tuple[int, int] | None = None  # (누른 시간, 이동 전 dx)
        stuck = 0
        last: str = "시작 전"
        damping = 1.0  # 목표를 지나쳤을 때 이동량을 줄이는 계수
        previous_sign = 0
        last_dx: float | None = None  # 표식이 가려졌을 때 판단 근거로 쓴다

        while self.clock.now() < deadline:
            if self._abort():
                return False, "사용자 중단"
            frame = self.frames()
            if frame is None:
                return False, "화면 캡처 실패"
            reading = self.minimap.read(frame)
            if reading.rune is None:
                # 캐릭터(노랑)가 룬(보라) 위에 올라가면 표식이 가려져 사라진다.
                # 직전 dx 는 '이동 전' 값이므로, 방금 이동한 거리를 빼서 현재 위치를 추정한다.
                estimate = last_dx
                if estimate is not None and pending is not None:
                    held_ms, before = pending
                    moved = held_ms / max(1.0, ms_per_px)
                    estimate = before - (moved if before > 0 else -moved)
                covered = max(1.0, float(cfg.covered_tolerance))
                if estimate is not None and abs(estimate) <= covered:
                    self.bus.debug(
                        f"룬 표식이 캐릭터에 가려짐 (추정 dx {estimate:+.1f}) → 위치 일치로 판단"
                    )
                    return True, "표식 겹침(위치 일치)"
                if cfg.screen_fallback and self.vision.detect_rune(frame) is not None:
                    self.bus.debug("표식은 가려졌지만 화면에 룬이 보임 → 위치 일치로 판단")
                    return True, "화면에서 룬 확인"
                return False, "미니맵에서 룬 표식이 사라졌습니다"
            if reading.char is None:
                return False, "미니맵에서 캐릭터 표식을 찾지 못했습니다 (캐릭터 색 설정 확인)"
            if reading.ambiguous:
                return False, (
                    f"룬 색과 캐릭터 색 범위가 {reading.overlap:.0%} 겹쳐 같은 표식을 가리킵니다 "
                    "— ‘룬 색 추출’ 과 ‘캐릭터 색 추출’ 을 각각 다시 해주세요"
                )

            dx, dy = float(reading.dx), float(reading.dy)  # type: ignore[arg-type]
            last_dx = dx
            last = f"dx {dx:+.1f}, dy {dy:+.1f}"

            if pending is not None:
                held_ms, before = pending
                pending = None
                moved = abs(before - dx)
                if moved >= 1:
                    stuck = 0
                    if cfg.auto_calibrate:
                        measured = held_ms / moved
                        ms_per_px = min(400.0, max(5.0, ms_per_px * 0.6 + measured * 0.4))
                else:
                    stuck += 1
                    if stuck >= 4:
                        return False, f"이동해도 미니맵 표식이 변하지 않습니다 ({last})"

            # 허용 오차 0 은 소수점 좌표에서 사실상 도달 불가라 최소값을 둔다
            tolerance = max(0.5, float(cfg.align_tolerance))
            v_tolerance = max(0.5, float(cfg.vertical_tolerance))

            if abs(dx) <= tolerance and abs(dy) <= v_tolerance:
                self.bus.debug(f"미니맵 정렬 완료 ({last}, 계수 {ms_per_px:.0f}ms/px)")
                return True, "정렬 완료"

            if abs(dx) > tolerance:
                sign = 1 if dx > 0 else -1
                if previous_sign and sign != previous_sign:
                    # 목표를 지나쳐 되돌아가는 중 → 이동량을 줄여 진동을 막는다
                    damping = max(0.35, damping * 0.55)
                    self.bus.debug(f"미니맵 정렬: 지나침 감지 → 이동량 {damping:.0%}")
                previous_sign = sign
                hold = int(
                    min(
                        cfg.max_hold_ms,
                        max(cfg.min_hold_ms, abs(dx) * ms_per_px * damping),
                    )
                )
                key = keys.right if dx > 0 else keys.left
                self.bus.debug(
                    f"미니맵 이동: {'오른쪽' if dx > 0 else '왼쪽'} {hold}ms ({last})"
                )
                self.inputs.hold(key, hold, sleeper=self.clock.sleep)
                pending = (hold, dx)
                self.clock.sleep(cfg.settle)
                continue

            if dy < -v_tolerance:  # 룬이 위쪽
                if cfg.use_rope:
                    self.bus.debug(f"미니맵 이동: 로프 커넥트로 상승 ({last})")
                    self.inputs.tap(keys.rope, 60, sleeper=self.clock.sleep)
                    self.clock.sleep(0.9)
                else:
                    self.bus.debug(f"미니맵 이동: 점프로 상승 ({last})")
                    self.inputs.tap(keys.jump, 60, sleeper=self.clock.sleep)
                    self.clock.sleep(0.5)
            elif dy > v_tolerance and cfg.jump_down:  # 룬이 아래쪽
                self.bus.debug(f"미니맵 이동: 아래 점프 ({last})")
                self.inputs.chord([keys.down, keys.jump], 70, sleeper=self.clock.sleep)
                self.clock.sleep(0.6)
            else:
                self.clock.sleep(0.1)

        return False, f"{cfg.max_seconds:.0f}초 내 정렬 실패 ({last})"

    def _fine_align_on_screen(self) -> None:
        """미니맵 정렬이 끝난 뒤, 룬이 화면에 보이면 템플릿으로 한 번 더 맞춘다.

        미니맵은 1픽셀이 실제 수십 픽셀이라 그것만으로는 정밀도가 부족하다.
        화면 좌표는 훨씬 촘촘하므로 마지막 정렬에 쓰면 성공률이 올라간다.
        (룬 이미지가 없거나 화면에 안 보이면 조용히 넘어간다)
        """
        cfg = self.config.rune
        if not cfg.minimap.screen_fine_align or not cfg.approach.enabled:
            return
        frame = self.frames()
        if frame is None:
            return
        rune = self.vision.detect_rune(frame)
        if rune is None:
            return
        self.bus.debug(f"화면에서 룬 확인 (점수 {rune.score:.2f}) → 템플릿으로 미세 정렬")
        ok, detail = self._approach(self.clock.now())
        if not ok:
            self.bus.debug(f"화면 미세 정렬 생략: {detail}")

    def _nudge(self, index: int) -> None:
        """활성화가 안 되면 좌우로 아주 조금 움직여 위치를 다시 맞춘다.

        룬은 정확히 겹쳐야 활성화된다. 그런데 겹치는 순간에는 캐릭터 표식이 룬 표식을
        가려서 미니맵으로 남은 오차를 알 수 없다. 그래서 오차를 알 수 있으면 그 방향으로,
        모르면 **좌우로 번갈아 폭을 늘려가며**(지그재그) 정확한 지점을 훑는다.
        """
        cfg = self.config.rune.minimap
        if not self.config.rune.use_minimap or cfg.nudge_ms <= 0:
            return
        keys = self.config.keys
        frame = self.frames()
        if frame is not None:
            reading = self.minimap.read(frame)
            if reading.usable and abs(reading.dx or 0) > 0.5:
                dx = float(reading.dx or 0)
                direction = keys.right if dx > 0 else keys.left
                step = int(min(cfg.max_hold_ms, max(cfg.nudge_ms, abs(dx) * cfg.ms_per_px)))
                self.bus.debug(f"활성화 실패 → 남은 오차 {dx:+.1f}px 만큼 이동 {step}ms")
                self.inputs.hold(direction, step, sleeper=self.clock.sleep)
                self.clock.sleep(0.15)
                return

        # 표식이 가려져 오차를 모르는 상태: +1, -2, +3, -4 … 로 훑는다
        direction = keys.right if index % 2 == 0 else keys.left
        step = int(cfg.nudge_ms * (index + 1))
        self.bus.debug(f"활성화 실패 → 지그재그 탐색 {direction} {step}ms 후 재시도")
        self.inputs.hold(direction, step, sleeper=self.clock.sleep)
        self.clock.sleep(0.15)

    def _activate(self):
        cfg = self.config.rune
        attempts = max(1, cfg.activate_taps)
        for attempt in range(attempts):
            if self._abort():
                return None
            # 화살표 UI 가 이미 떠 있는데 활성화 키를 또 누르면 그 입력이 방향 입력으로
            # 들어가 순서가 어긋난다. 그래서 매 시도 전에 UI 상태를 먼저 확인한다.
            frame = self.frames()
            if frame is not None and self.vision.arrows_visible(frame):
                self.bus.debug("방향 입력 UI 가 이미 떠 있음 — 활성화 입력 생략")
                return self._read_arrows(cfg.arrow_wait)

            self.inputs.tap(cfg.activate_key, 60, sleeper=self.clock.sleep)
            self.bus.debug(f"룬 활성화 입력 {attempt + 1}/{attempts} ({cfg.activate_key})")
            reading = self._read_arrows(cfg.activate_gap)
            if reading is not None:
                return reading
            if attempt < attempts - 1:
                self._nudge(attempt)
        return self._read_arrows(cfg.arrow_wait)

    def _read_arrows(self, timeout: float):
        """timeout 안에 안정된 판독이 나오면 반환, 화살표가 아예 없으면 None."""
        cfg = self.config.rune
        deadline = self.clock.now() + timeout
        stable_target = max(1, cfg.arrow_stable_frames)
        last: list[str] | None = None
        stable = 0
        best_bad = None
        while self.clock.now() < deadline:
            if self._abort():
                return None
            frame = self.frames()
            if frame is None:
                self.clock.sleep(0.05)
                continue
            reading = self.vision.read_arrows(frame)
            if reading.count == 0:
                last, stable = None, 0
                self.clock.sleep(0.05)
                continue
            if not reading.ok:
                best_bad = reading
                last, stable = None, 0
                self.clock.sleep(0.06)
                continue
            if reading.sequence == last:
                stable += 1
            else:
                last, stable = reading.sequence, 1
            if stable >= stable_target:
                return reading
            self.clock.sleep(0.04)
        if last is not None:
            from ..vision.rune import ArrowReading

            return ArrowReading(sequence=last, ok=True, reason="타임아웃 직전 판독 사용")
        return best_bad

    def _send_arrows(self, sequence: list[str]) -> None:
        cfg = self.config.rune
        for direction in sequence:
            key = direction.upper()
            if key not in ARROW_KEYS:
                self.bus.warn(f"방향키가 아닌 판독 결과 무시: {direction}")
                continue
            self.inputs.tap(key, cfg.arrow_press_ms, sleeper=self.clock.sleep)
            self.clock.sleep(cfg.arrow_gap)

    def _verify(self) -> str:
        """'success' | 'arrows_remain' | 'rune_remains'.

        화살표 UI 가 사라지는 것만으로는 성공을 확신할 수 없다. 순서를 틀리면
        게임도 UI 를 닫지만 룬은 그대로 남기 때문에, 룬이 사라졌는지까지 확인한다.
        """
        cfg = self.config.rune
        deadline = self.clock.now() + cfg.confirm_timeout
        arrows_gone = False
        while self.clock.now() < deadline:
            if self._abort():
                return "arrows_remain"
            frame = self.frames()
            if frame is not None and not self.vision.arrows_visible(frame):
                arrows_gone = True
                break
            self.clock.sleep(0.1)
        if not arrows_gone:
            return "arrows_remain"

        rune_deadline = self.clock.now() + max(1.0, cfg.confirm_timeout / 2)
        while self.clock.now() < rune_deadline:
            frame = self.frames()
            if frame is not None and not self._rune_visible(frame):
                return "success"
            self.clock.sleep(0.15)
        return "rune_remains"

    def _rune_visible(self, frame) -> bool:
        """룬이 아직 남아 있는지 (감지 방식에 맞춰 판단).

        안내 문구를 쓰는 경우 그것이 가장 확실한 신호다.
        해제되면 문구가 사라지기 때문이다.
        """
        cfg = self.config.rune
        if cfg.use_banner:
            return self.vision.detect_banner(frame) is not None
        if cfg.use_minimap:
            return self.minimap.read(frame).rune is not None
        return self.vision.detect_rune(frame) is not None

    def _done(
        self,
        outcome: RuneOutcome,
        started: float,
        arrows: list[str] | None = None,
        retries: int = 0,
        detail: str = "",
    ) -> RuneAttempt:
        self.inputs.release_all()
        return RuneAttempt(
            outcome=outcome,
            arrows=list(arrows or []),
            elapsed=self.clock.now() - started,
            retries=retries,
            detail=detail,
        )
