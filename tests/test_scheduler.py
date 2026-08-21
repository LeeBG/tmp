"""스킬 주기 로직 검증 (가상 시간이라 즉시 끝난다)."""

from __future__ import annotations

from rune_hunter.config import SkillConfig
from rune_hunter.engine.scheduler import SkillScheduler


def make(interval: float, label: str, priority: int = 50, enabled: bool = True) -> SkillConfig:
    return SkillConfig(label=label, key="A", enabled=enabled, interval=interval, priority=priority)


def test_only_enabled_slots_are_scheduled():
    sched = SkillScheduler.from_configs(
        [make(1.0, "on"), make(1.0, "off", enabled=False)]
    )
    assert [s.label for s in sched.slots] == ["on"]


def test_hunt_key_repeats_forever():
    hunt = make(0.1, "사냥기", priority=90)
    sched = SkillScheduler.from_configs([hunt])
    sched.start(0.0)
    fired = 0
    t = 0.0
    while t < 60.0:  # 1분 동안
        t += 0.01
        fired += len(sched.pop_due(t))
    assert 590 <= fired <= 610  # 0.1초 주기 → 약 600회


def test_buff_interval_respected():
    sched = SkillScheduler.from_configs([make(120.0, "버프1", priority=10)])
    sched.start(0.0)
    assert len(sched.pop_due(0.0)) == 1      # 시작 직후 1회
    assert sched.pop_due(60.0) == []         # 주기 전에는 안 나감
    assert len(sched.pop_due(120.1)) == 1    # 주기 후 1회


def test_priority_order_buff_before_hunt():
    sched = SkillScheduler.from_configs(
        [make(0.1, "사냥기", priority=90), make(5.0, "보스기", priority=40), make(60.0, "버프1", priority=10)]
    )
    sched.start(0.0)
    labels = [s.label for s in sched.pop_due(0.0)]
    assert labels == ["버프1", "보스기", "사냥기"]


def test_pending_buff_fires_right_after_pause():
    """룬 해제로 멈춘 동안 주기가 지난 버프는 재개 직후 사용된다."""
    sched = SkillScheduler.from_configs([make(10.0, "버프1", priority=10)])
    sched.start(0.0)
    sched.pop_due(0.0)                 # 시작 버프 소비 → 다음은 10초
    resume_at = 25.0                   # 룬 해제로 25초까지 정지
    sched.resume_after_pause(resume_at)
    due = sched.pop_due(resume_at)
    assert [s.label for s in due] == ["버프1"]
    assert sched.pop_due(resume_at + 0.1) == []   # 몰아서 여러 번 나가지 않는다


def test_no_backlog_burst_for_hunt_key():
    """오래 멈췄다가 재개해도 밀린 만큼 연타하지 않는다."""
    sched = SkillScheduler.from_configs([make(0.1, "사냥기", priority=90)])
    sched.start(0.0)
    sched.pop_due(0.0)
    assert len(sched.pop_due(30.0)) == 1


def test_next_deadline_and_defer():
    sched = SkillScheduler.from_configs([make(2.0, "a"), make(5.0, "b")])
    sched.start(0.0, immediate=False)
    assert sched.next_deadline(99.0) == 2.0
    sched.defer(1.0)
    assert sched.next_deadline(99.0) == 3.0


def test_jitter_stays_within_bounds():
    slot = make(1.0, "지터")
    slot.jitter = 0.5
    sched = SkillScheduler.from_configs([slot], seed=1)
    sched.start(0.0)
    sched.pop_due(0.0)
    assert 1.0 <= sched.slots[0].next_at <= 1.5


def test_counts_tracks_usage():
    sched = SkillScheduler.from_configs([make(1.0, "버프1")])
    sched.start(0.0)
    for t in (0.0, 1.0, 2.0):
        sched.pop_due(t)
    assert sched.counts() == {"버프1": 3}
