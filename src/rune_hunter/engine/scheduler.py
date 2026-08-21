"""스킬 주기 스케줄러.

키를 언제 눌러야 하는지만 계산하는 순수 로직이다 (입력/화면과 무관).
덕분에 가상 시계로 "10분 동안 버프가 몇 번 나가는가" 같은 검증이 쉽다.

동작 규칙
- 사냥기는 시간제한 없이 interval 마다 계속 눌린다.
- 룬 해제 등으로 멈춰 있던 동안 주기가 지난 스킬은, 재개 직후 곧바로 한 번 나간다
  (밀린 횟수만큼 몰아서 누르지는 않는다).
- 같은 시점에 여러 개가 겹치면 priority 오름차순으로 실행한다(버프 > 보스기 > 사냥기).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..config import SkillConfig


@dataclass
class Slot:
    config: SkillConfig
    next_at: float = 0.0
    fired: int = 0
    last_at: float = 0.0

    @property
    def key(self) -> str:
        return self.config.key

    @property
    def label(self) -> str:
        return self.config.label


@dataclass
class SkillScheduler:
    slots: list[Slot] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

    @classmethod
    def from_configs(cls, configs: list[SkillConfig], seed: int | None = None) -> "SkillScheduler":
        return cls(
            slots=[Slot(config=c) for c in configs if c.enabled],
            rng=random.Random(seed),
        )

    def start(self, now: float, immediate: bool = True) -> None:
        """immediate=True 면 시작 직후 한 번씩 사용(버프 선처리)."""
        for slot in self.slots:
            slot.next_at = now if immediate else now + slot.config.interval
            slot.fired = 0
            slot.last_at = 0.0

    def pop_due(self, now: float) -> list[Slot]:
        due = [s for s in self.slots if now >= s.next_at]
        if not due:
            return []
        due.sort(key=lambda s: (s.config.priority, s.next_at))
        for slot in due:
            self._reschedule(slot, now)
        return due

    def _reschedule(self, slot: Slot, now: float) -> None:
        interval = max(0.005, slot.config.interval)
        if slot.config.jitter:
            interval += self.rng.uniform(0, slot.config.jitter)
        # 원래 예정 시각을 기준으로 다음 시각을 잡아 드리프트를 없앤다.
        # (now 기준으로만 더하면 루프 지연이 매번 누적되어 실제 주기가 느려진다)
        anchored = slot.next_at + interval
        slot.next_at = anchored if anchored > now else now + interval
        slot.last_at = now
        slot.fired += 1

    def next_deadline(self, default: float) -> float:
        if not self.slots:
            return default
        return min(s.next_at for s in self.slots)

    def defer(self, seconds: float) -> None:
        """모든 슬롯을 seconds 만큼 뒤로 미룬다."""
        for slot in self.slots:
            slot.next_at += seconds

    def resume_after_pause(self, now: float, grace: float = 0.0) -> None:
        """일시정지(룬 해제 등) 후 재개.

        주기가 이미 지난 슬롯은 즉시 실행 대상이 되도록 시각을 현재로 당겨서
        '밀린 버프를 마저 사용'하게 만든다.
        """
        for slot in self.slots:
            if slot.next_at < now:
                slot.next_at = now + grace

    def counts(self) -> dict[str, int]:
        return {s.label: s.fired for s in self.slots}
