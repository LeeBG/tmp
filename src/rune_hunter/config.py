"""설정 모델과 JSON 저장/불러오기.

모든 값은 dataclass 로 관리하고, 알 수 없는/누락된 키는 기본값으로 채운다
(프로필 파일을 나중에 확장해도 예전 파일이 그대로 열린다).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_args, get_origin

CONFIG_VERSION = 1


def _project_root() -> Path:
    """설정·템플릿·로그를 둘 폴더.

    소스 체크아웃(또는 editable 설치)이면 저장소 루트를 쓰고, 그 외에는
    site-packages 안에 파일을 쓰지 않도록 현재 작업 폴더를 쓴다.
    """
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


PROJECT_ROOT = _project_root()
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "profiles"
DEFAULT_PROFILE_PATH = DEFAULT_PROFILE_DIR / "default.json"
DEFAULT_TEMPLATE_DIR = PROJECT_ROOT / "templates"
LOG_DIR = PROJECT_ROOT / "logs"


@dataclass
class Roi:
    """화면 영역. 0~1 비율로 저장해서 해상도가 바뀌어도 그대로 쓸 수 있다."""

    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x = max(0, min(width - 1, int(round(self.x * width))))
        y = max(0, min(height - 1, int(round(self.y * height))))
        w = max(1, min(width - x, int(round(self.w * width))))
        h = max(1, min(height - y, int(round(self.h * height))))
        return x, y, w, h

    def describe(self) -> str:
        return f"x{self.x:.2f} y{self.y:.2f} w{self.w:.2f} h{self.h:.2f}"


@dataclass
class SkillConfig:
    """주기적으로 눌러줄 키 하나."""

    label: str = "스킬"
    key: str = "A"
    enabled: bool = False
    interval: float = 5.0          # 초 단위 사용 주기
    press_ms: int = 40             # 키를 누르고 있는 시간(ms)
    hold: bool = False             # True 면 계속 누른 상태 유지(사냥기 전용)
    jitter: float = 0.0            # 주기에 더할 랜덤 흔들림(초). 0 이면 정확한 주기
    priority: int = 50             # 낮을수록 먼저 실행


@dataclass
class MovementConfig:
    """사냥 중 좌우 이동/점프 (선택 기능)."""

    enabled: bool = False
    interval: float = 6.0          # 방향 전환 주기(초)
    hold_ms: int = 700             # 한 번에 이동 유지 시간(ms)
    jump: bool = False             # 이동 후 점프 여부


@dataclass
class KeyBindings:
    """이동/점프 관련 고정 키."""

    left: str = "LEFT"
    right: str = "RIGHT"
    up: str = "UP"
    down: str = "DOWN"
    jump: str = "ALT"              # 점프
    rope: str = "A"                # 로프 커넥트(수직 상승)


@dataclass
class ApproachConfig:
    """룬 위치까지 접근 동작 설정."""

    enabled: bool = True
    char_x: float = 0.5            # 캐릭터의 화면상 위치(비율)
    char_y: float = 0.55
    deadzone_px: int = 30          # 이 정도 x 오차는 정렬된 것으로 본다
    ms_per_px: float = 2.2         # 1픽셀 이동에 필요한 키 유지 시간
    max_hold_ms: int = 700         # 한 번에 방향키를 누를 최대 시간
    max_seconds: float = 12.0      # 접근 포기 시간
    vertical_tolerance: int = 60   # 이 이상 높이 차이가 나면 로프/점프 사용
    use_rope: bool = True          # 위로 갈 때 로프 커넥트 사용
    jump_down: bool = True         # 아래로 갈 때 아래+점프 사용


@dataclass
class ColorSpec:
    """HSV 색 범위 (OpenCV 기준: H 0~179, S/V 0~255)."""

    lower: list[int] = field(default_factory=lambda: [0, 0, 0])
    upper: list[int] = field(default_factory=lambda: [179, 255, 255])
    min_area: int = 2                      # 이보다 작은 덩어리는 무시(노이즈)

    def describe(self) -> str:
        return f"H {self.lower[0]}~{self.upper[0]}, S {self.lower[1]}~{self.upper[1]}, V {self.lower[2]}~{self.upper[2]}"


def _purple() -> ColorSpec:
    """미니맵의 룬 표식(보라/자주).

    상한을 158 로 둔 이유: 배경 그라디언트에 노이즈가 끼면 H 160~175 대의
    자주빛 픽셀이 몇 개씩 생겨 오탐이 난다. 채도/명도 하한도 함께 올려 걸러낸다.
    """
    return ColorSpec(lower=[125, 90, 80], upper=[158, 255, 255], min_area=3)


def _yellow() -> ColorSpec:
    """미니맵의 내 캐릭터 표식(노랑)."""
    return ColorSpec(lower=[18, 110, 130], upper=[35, 255, 255], min_area=2)


@dataclass
class MinimapConfig:
    """미니맵 색상으로 룬 위치를 찾는 방식 설정.

    룬이 화면 밖에 있어도 미니맵에는 표시되므로, 미니맵의 룬 표식(보라)과
    캐릭터 표식(노랑)의 좌표 차이를 보고 이동한다.
    """

    enabled: bool = False
    roi: Roi = field(default_factory=lambda: Roi(0.0, 0.0, 0.22, 0.20))
    rune_color: ColorSpec = field(default_factory=_purple)
    char_color: ColorSpec = field(default_factory=_yellow)
    align_tolerance: int = 2               # 좌우 정렬 허용 오차(미니맵 px)
    vertical_tolerance: int = 2            # 높이 허용 오차(미니맵 px)
    ms_per_px: float = 45.0                # 미니맵 1px 이동에 필요한 방향키 유지 시간
    min_hold_ms: int = 60
    max_hold_ms: int = 800
    max_seconds: float = 25.0              # 정렬 포기 시간
    settle: float = 0.12                   # 이동 후 표식이 갱신될 때까지 대기
    auto_calibrate: bool = True            # 실제 이동량으로 ms_per_px 자동 보정
    use_rope: bool = True                  # 위로 올라갈 때 로프 커넥트 사용
    jump_down: bool = True                 # 아래로 내려갈 때 아래+점프 사용
    nudge_ms: int = 80                     # 활성화 실패 시 미세 이동 시간
    screen_fine_align: bool = True         # 룬이 화면에 보이면 템플릿으로 최종 미세 정렬


@dataclass
class RuneConfig:
    enabled: bool = True
    source: str = "template"               # "template" = 화면의 룬 이미지, "minimap" = 미니맵 색상
    check_interval: float = 0.6            # 룬 탐색 주기(초)
    rune_templates: list[str] = field(default_factory=lambda: ["rune.png"])
    rune_threshold: float = 0.72
    rune_roi: Roi = field(default_factory=lambda: Roi(0.0, 0.0, 1.0, 0.9))
    arrow_templates: dict[str, str] = field(
        default_factory=lambda: {
            "UP": "arrow_up.png",
            "DOWN": "arrow_down.png",
            "LEFT": "arrow_left.png",
            "RIGHT": "arrow_right.png",
        }
    )
    arrow_threshold: float = 0.70
    arrow_roi: Roi = field(default_factory=lambda: Roi(0.20, 0.02, 0.60, 0.35))
    arrow_count: int = 4
    # 상단 안내 문구("엘리트 보스의 저주…") — 룬이 남아 있는 동안 계속 떠 있다
    use_banner: bool = False
    banner_template: str = "rune_banner.png"
    banner_threshold: float = 0.75
    banner_roi: Roi = field(default_factory=lambda: Roi(0.15, 0.05, 0.70, 0.35))
    activate_key: str = "UP"               # 룬 앞에서 누르는 키
    activate_taps: int = 2
    activate_gap: float = 0.45
    arrow_wait: float = 2.5                # 화살표 UI 대기 시간
    arrow_stable_frames: int = 2           # 같은 판독이 N번 나오면 확정
    arrow_press_ms: int = 45
    arrow_gap: float = 0.16                # 화살표 입력 간격
    confirm_timeout: float = 3.0           # 해제 성공 확인 대기
    max_retries: int = 2
    cooldown_success: float = 8.0          # 성공 후 재탐색까지 쉬는 시간
    cooldown_fail: float = 20.0
    template_dir: str = ""                 # 비우면 프로젝트의 templates/
    scales: list[float] = field(default_factory=lambda: [1.0])
    detect_scale: float = 1.0              # 1.0=원본. 0.5 로 줄이면 룬 탐색이 3~4배 빨라진다
    approach: ApproachConfig = field(default_factory=ApproachConfig)
    minimap: MinimapConfig = field(default_factory=MinimapConfig)

    @property
    def use_minimap(self) -> bool:
        return self.source == "minimap" and self.minimap.enabled


@dataclass
class AttackConfig:
    hunt: SkillConfig = field(
        default_factory=lambda: SkillConfig(
            label="사냥기", key="U", enabled=True, interval=0.12, press_ms=30, priority=90
        )
    )
    boss: SkillConfig = field(
        default_factory=lambda: SkillConfig(
            label="보스기", key="W", enabled=False, interval=8.0, press_ms=40, priority=40
        )
    )
    buffs: list[SkillConfig] = field(
        default_factory=lambda: [
            SkillConfig(label="버프1", key="Q", enabled=True, interval=120.0, priority=10),
            SkillConfig(label="버프2", key="W", enabled=True, interval=180.0, priority=11),
            SkillConfig(label="버프3", key="E", enabled=False, interval=200.0, priority=12),
            SkillConfig(label="버프4", key="R", enabled=False, interval=240.0, priority=13),
            SkillConfig(label="버프5", key="T", enabled=False, interval=300.0, priority=14),
            SkillConfig(label="버프6", key="Y", enabled=False, interval=600.0, priority=15),
        ]
    )
    movement: MovementConfig = field(default_factory=MovementConfig)
    buff_first: bool = True        # 시작 직후 활성화된 버프를 한 번씩 사용


@dataclass
class GeneralConfig:
    window_titles: list[str] = field(
        default_factory=lambda: ["MapleStory", "메이플스토리", "나루"]
    )
    only_when_focused: bool = True  # 게임 창이 활성화된 경우에만 키 입력
    start_hotkey: str = "F1"
    stop_hotkey: str = "F2"
    tick_ms: int = 4                # 제어 루프 주기(ms)
    log_key_presses: bool = True
    log_limit: int = 500


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    general: GeneralConfig = field(default_factory=GeneralConfig)
    keys: KeyBindings = field(default_factory=KeyBindings)
    attack: AttackConfig = field(default_factory=AttackConfig)
    rune: RuneConfig = field(default_factory=RuneConfig)

    # --- 저장/불러오기 -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path = DEFAULT_PROFILE_PATH) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return p

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PROFILE_PATH) -> "AppConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return _build(cls, data)

    def template_path(self, name: str) -> Path:
        base = Path(self.rune.template_dir) if self.rune.template_dir else DEFAULT_TEMPLATE_DIR
        candidate = Path(name)
        return candidate if candidate.is_absolute() else base / name

    def all_skills(self) -> list[SkillConfig]:
        return [self.attack.hunt, self.attack.boss, *self.attack.buffs]


def _build(cls: type, data: Any, base: Any = None) -> Any:
    """dataclass 를 dict 에서 재구성한다.

    기본값 인스턴스(base)에 dict 값을 덮어쓰는 방식이라, 예전 프로필처럼 일부
    필드가 빠져 있어도 라벨·우선순위 같은 기본값이 그대로 남는다.
    """
    result = base if base is not None else cls()
    if not isinstance(data, dict):
        return result
    for f in fields(cls):
        if f.name not in data:
            continue
        ftype = f.type
        if isinstance(ftype, str):  # from __future__ import annotations 대응
            ftype = _RESOLVED_TYPES.get((cls.__name__, f.name), ftype)
        setattr(result, f.name, _coerce(ftype, data[f.name], getattr(result, f.name, None)))
    return result


def _coerce(ftype: Any, value: Any, current: Any = None) -> Any:
    if is_dataclass(ftype) and isinstance(ftype, type):
        return _build(ftype, value, base=current if isinstance(current, ftype) else None)
    origin = get_origin(ftype)
    if origin is list:
        (inner,) = get_args(ftype) or (Any,)
        if is_dataclass(inner) and isinstance(inner, type):
            defaults = list(current or [])
            items = []
            for i, entry in enumerate(value or []):
                base = defaults[i] if i < len(defaults) else None
                items.append(_build(inner, entry, base=base))
            return items
        return list(value or [])
    if origin is dict:
        merged = dict(current or {})
        merged.update(value or {})
        return merged
    return value


# from __future__ 로 문자열이 된 어노테이션 중 dataclass 인 것만 수동 매핑
_RESOLVED_TYPES: dict[tuple[str, str], Any] = {
    ("AppConfig", "general"): GeneralConfig,
    ("AppConfig", "keys"): KeyBindings,
    ("AppConfig", "attack"): AttackConfig,
    ("AppConfig", "rune"): RuneConfig,
    ("AttackConfig", "hunt"): SkillConfig,
    ("AttackConfig", "boss"): SkillConfig,
    ("AttackConfig", "buffs"): list[SkillConfig],
    ("AttackConfig", "movement"): MovementConfig,
    ("RuneConfig", "rune_roi"): Roi,
    ("RuneConfig", "arrow_roi"): Roi,
    ("RuneConfig", "banner_roi"): Roi,
    ("RuneConfig", "approach"): ApproachConfig,
    ("RuneConfig", "minimap"): MinimapConfig,
    ("MinimapConfig", "roi"): Roi,
    ("MinimapConfig", "rune_color"): ColorSpec,
    ("MinimapConfig", "char_color"): ColorSpec,
    ("ColorSpec", "lower"): list[int],
    ("ColorSpec", "upper"): list[int],
    ("RuneConfig", "rune_templates"): list[str],
    ("RuneConfig", "scales"): list[float],
    ("GeneralConfig", "window_titles"): list[str],
}
