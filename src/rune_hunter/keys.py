"""키 이름 <-> 스캔코드/가상키 매핑.

메이플스토리 계열 클라이언트는 DirectInput/RawInput 으로 키를 읽기 때문에
가상키(VK) 기반 keybd_event 대신 **스캔코드 기반 SendInput** 을 사용해야 입력이 먹는다.
그래서 모든 키는 (scan_code, extended) 쌍으로 관리한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyDef:
    name: str
    scan: int
    extended: bool = False
    vk: int | None = None
    label: str | None = None

    @property
    def display(self) -> str:
        return self.label or self.name


def _letters() -> list[KeyDef]:
    table = {
        "A": 0x1E, "B": 0x30, "C": 0x2E, "D": 0x20, "E": 0x12, "F": 0x21,
        "G": 0x22, "H": 0x23, "I": 0x17, "J": 0x24, "K": 0x25, "L": 0x26,
        "M": 0x32, "N": 0x31, "O": 0x18, "P": 0x19, "Q": 0x10, "R": 0x13,
        "S": 0x1F, "T": 0x14, "U": 0x16, "V": 0x2F, "W": 0x11, "X": 0x2D,
        "Y": 0x15, "Z": 0x2C,
    }
    return [KeyDef(name, scan, vk=ord(name)) for name, scan in table.items()]


def _digits() -> list[KeyDef]:
    scans = [0x0B, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A]
    return [KeyDef(str(d), scans[d], vk=0x30 + d) for d in range(10)]


def _functions() -> list[KeyDef]:
    scans = [0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x57, 0x58]
    return [KeyDef(f"F{i + 1}", scans[i], vk=0x70 + i) for i in range(12)]


_ALL: list[KeyDef] = [
    *_letters(),
    *_digits(),
    *_functions(),
    KeyDef("LEFT", 0x4B, extended=True, vk=0x25, label="← 왼쪽"),
    KeyDef("RIGHT", 0x4D, extended=True, vk=0x27, label="→ 오른쪽"),
    KeyDef("UP", 0x48, extended=True, vk=0x26, label="↑ 위"),
    KeyDef("DOWN", 0x50, extended=True, vk=0x28, label="↓ 아래"),
    KeyDef("ALT", 0x38, vk=0x12, label="ALT (점프)"),
    KeyDef("CTRL", 0x1D, vk=0x11, label="CTRL"),
    KeyDef("SHIFT", 0x2A, vk=0x10, label="SHIFT"),
    KeyDef("SPACE", 0x39, vk=0x20, label="SPACE"),
    KeyDef("ENTER", 0x1C, vk=0x0D, label="ENTER"),
    KeyDef("ESC", 0x01, vk=0x1B, label="ESC"),
    KeyDef("TAB", 0x0F, vk=0x09, label="TAB"),
    KeyDef("INSERT", 0x52, extended=True, vk=0x2D),
    KeyDef("DELETE", 0x53, extended=True, vk=0x2E),
    KeyDef("HOME", 0x47, extended=True, vk=0x24),
    KeyDef("END", 0x4F, extended=True, vk=0x23),
    KeyDef("PAGEUP", 0x49, extended=True, vk=0x21),
    KeyDef("PAGEDOWN", 0x51, extended=True, vk=0x22),
    KeyDef("GRAVE", 0x29, vk=0xC0, label="` (백틱)"),
    KeyDef("MINUS", 0x0C, vk=0xBD, label="- (마이너스)"),
    KeyDef("EQUAL", 0x0D, vk=0xBB, label="= (이퀄)"),
    KeyDef("LBRACKET", 0x1A, vk=0xDB, label="[ "),
    KeyDef("RBRACKET", 0x1B, vk=0xDD, label="] "),
    KeyDef("SEMICOLON", 0x27, vk=0xBA, label="; "),
    KeyDef("QUOTE", 0x28, vk=0xDE, label="' "),
    KeyDef("COMMA", 0x33, vk=0xBC, label=", "),
    KeyDef("PERIOD", 0x34, vk=0xBE, label=". "),
    KeyDef("SLASH", 0x35, vk=0xBF, label="/ "),
    KeyDef("BACKSLASH", 0x2B, vk=0xDC, label="\\ "),
    KeyDef("NUM0", 0x52, vk=0x60, label="숫자패드 0"),
    KeyDef("NUM1", 0x4F, vk=0x61, label="숫자패드 1"),
    KeyDef("NUM2", 0x50, vk=0x62, label="숫자패드 2"),
    KeyDef("NUM3", 0x51, vk=0x63, label="숫자패드 3"),
    KeyDef("NUM4", 0x4B, vk=0x64, label="숫자패드 4"),
    KeyDef("NUM5", 0x4C, vk=0x65, label="숫자패드 5"),
    KeyDef("NUM6", 0x4D, vk=0x66, label="숫자패드 6"),
    KeyDef("NUM7", 0x47, vk=0x67, label="숫자패드 7"),
    KeyDef("NUM8", 0x48, vk=0x68, label="숫자패드 8"),
    KeyDef("NUM9", 0x49, vk=0x69, label="숫자패드 9"),
    KeyDef("NUMDOT", 0x53, vk=0x6E, label="숫자패드 ."),
    KeyDef("NUMPLUS", 0x4E, vk=0x6B, label="숫자패드 +"),
    KeyDef("NUMMINUS", 0x4A, vk=0x6D, label="숫자패드 -"),
    KeyDef("NUMMUL", 0x37, vk=0x6A, label="숫자패드 *"),
    KeyDef("NUMDIV", 0x35, extended=True, vk=0x6F, label="숫자패드 /"),
]

KEY_TABLE: dict[str, KeyDef] = {k.name: k for k in _ALL}

ARROW_KEYS = ("UP", "DOWN", "LEFT", "RIGHT")

#: GUI 콤보박스에서 사용할, 사람이 고르기 쉬운 순서의 키 목록
SELECTABLE_KEYS: tuple[str, ...] = (
    *[f"F{i}" for i in range(1, 13)],
    *[chr(c) for c in range(ord("A"), ord("Z") + 1)],
    *[str(d) for d in range(10)],
    "CTRL", "SHIFT", "ALT", "SPACE", "ENTER", "TAB",
    "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN",
    "UP", "DOWN", "LEFT", "RIGHT",
    "GRAVE", "MINUS", "EQUAL", "LBRACKET", "RBRACKET",
    "SEMICOLON", "QUOTE", "COMMA", "PERIOD", "SLASH", "BACKSLASH",
    *[f"NUM{d}" for d in range(10)],
    "NUMDOT", "NUMPLUS", "NUMMINUS", "NUMMUL", "NUMDIV",
)

#: 전역 단축키(시작/종료)로 쓸 수 있는 키
HOTKEY_CHOICES: tuple[str, ...] = tuple(f"F{i}" for i in range(1, 13)) + (
    "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN",
)


def resolve(name: str) -> KeyDef:
    """키 이름을 KeyDef 로 변환한다. 알 수 없는 키는 ValueError."""
    key = KEY_TABLE.get(name.strip().upper())
    if key is None:
        raise ValueError(f"지원하지 않는 키 이름입니다: {name!r}")
    return key


def is_valid(name: str) -> bool:
    return name.strip().upper() in KEY_TABLE


def display_name(name: str) -> str:
    try:
        return resolve(name).display
    except ValueError:
        return name
