from __future__ import annotations

import pytest

from rune_hunter.keys import (
    ARROW_KEYS,
    HOTKEY_CHOICES,
    KEY_TABLE,
    SELECTABLE_KEYS,
    is_valid,
    resolve,
)


def test_arrow_keys_are_extended():
    """방향키는 확장 스캔코드(E0 프리픽스)여야 게임이 정상 인식한다."""
    for name in ARROW_KEYS:
        assert resolve(name).extended is True


def test_known_scan_codes():
    assert resolve("U").scan == 0x16
    assert resolve("Q").scan == 0x10
    assert resolve("W").scan == 0x11
    assert resolve("ALT").scan == 0x38
    assert resolve("A").scan == 0x1E
    assert resolve("F1").scan == 0x3B
    assert resolve("UP").scan == 0x48


def test_case_insensitive_and_invalid():
    assert resolve("u").name == "U"
    assert is_valid("alt")
    assert not is_valid("존재하지않는키")
    with pytest.raises(ValueError):
        resolve("없는키")


def test_every_selectable_key_resolves():
    for name in SELECTABLE_KEYS:
        assert name in KEY_TABLE


def test_hotkeys_have_virtual_keys():
    """RegisterHotKey 는 가상키 코드를 요구한다."""
    for name in HOTKEY_CHOICES:
        assert resolve(name).vk is not None
