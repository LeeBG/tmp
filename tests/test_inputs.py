"""입력 백엔드 동작 검증.

실제 SendInput 호출은 Windows 에서만 가능하므로, 여기서는
(1) 키 조합/해제 같은 순서 로직과 (2) SendInput 에 넘길 플래그 계산을 검증한다.
"""

from __future__ import annotations

from rune_hunter.inputs.recorder import RecordingBackend
from rune_hunter.inputs.win_sendinput import (
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    KEYEVENTF_SCANCODE,
    key_flags,
)


def _pairs(backend: RecordingBackend) -> list[tuple[str, str]]:
    return [(e.key, e.action) for e in backend.events]


def test_tap_emits_down_then_up():
    backend = RecordingBackend()
    backend.tap("U", press_ms=1, sleeper=lambda s: None)
    assert _pairs(backend) == [("U", "down"), ("U", "up")]
    assert backend.held_keys == set()


def test_chord_presses_together_and_releases_in_reverse():
    """아래 점프 = 아래 방향키 + ALT 를 동시에 눌러야 한다."""
    backend = RecordingBackend()
    backend.chord(["DOWN", "ALT"], press_ms=1, sleeper=lambda s: None)
    assert _pairs(backend) == [
        ("DOWN", "down"),
        ("ALT", "down"),
        ("ALT", "up"),
        ("DOWN", "up"),
    ]


def test_release_all_clears_held_keys():
    backend = RecordingBackend()
    backend.key_down("U")
    backend.key_down("LEFT")
    assert backend.held_keys == {"U", "LEFT"}
    backend.release_all()
    assert backend.held_keys == set()
    assert _pairs(backend)[-2:] in (
        [("U", "up"), ("LEFT", "up")],
        [("LEFT", "up"), ("U", "up")],
    )


def test_sink_receives_events_in_order():
    seen = []
    backend = RecordingBackend(sink=lambda e: seen.append((e.key, e.action)))
    backend.tap("Q", press_ms=1, sleeper=lambda s: None)
    assert seen == [("Q", "down"), ("Q", "up")]


def test_scancode_flags_for_letter():
    scan, flags = key_flags("U", down=True)
    assert scan == 0x16
    assert flags == KEYEVENTF_SCANCODE  # 확장 아님, 키다운


def test_scancode_flags_for_arrow_key():
    """방향키는 확장 플래그가 있어야 게임이 좌우/상하로 인식한다."""
    scan, flags = key_flags("LEFT", down=True)
    assert scan == 0x4B
    assert flags & KEYEVENTF_EXTENDEDKEY
    assert flags & KEYEVENTF_SCANCODE
    assert not flags & KEYEVENTF_KEYUP


def test_keyup_flag():
    _, flags = key_flags("ALT", down=False)
    assert flags & KEYEVENTF_KEYUP
    assert not flags & KEYEVENTF_EXTENDEDKEY


def test_virtual_key_is_not_used():
    """가상키(VK) 대신 스캔코드를 쓰는지 확인 — DirectInput 클라이언트 대응."""
    for name in ("U", "ALT", "LEFT", "F1", "NUM5"):
        _, flags = key_flags(name, down=True)
        assert flags & KEYEVENTF_SCANCODE


def test_create_backend_falls_back_to_recorder_off_windows():
    from rune_hunter.inputs import create_backend
    from rune_hunter.platform_layer import IS_WINDOWS

    backend = create_backend()
    if IS_WINDOWS:
        from rune_hunter.inputs.win_sendinput import SendInputBackend

        assert isinstance(backend, SendInputBackend)
    else:
        assert isinstance(backend, RecordingBackend)
