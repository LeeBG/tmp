"""진단 도구: 설정 자가 점검, 실패 순간 스냅샷, 화면 변화 측정.

룬 해제가 실패했을 때 "설정이 잘못된 것인지 코드가 못 따라간 것인지" 를
사용자가 로그만 보고 판단할 수 있게 하는 것이 목적이다. GUI 에 의존하지 않아서
엔진 스레드(로그)와 GUI 버튼 양쪽에서 같은 함수를 쓴다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from .config import LOG_DIR, AppConfig
from .vision.minimap import MinimapVision

Level = Literal["info", "ok", "warn", "error"]

#: 같은 종류의 실패 스냅샷을 이 개수까지만 남긴다 (logs 폴더가 무한히 커지지 않게)
MAX_SNAPSHOTS = 20


@dataclass(frozen=True)
class Issue:
    level: Level
    message: str

    def formatted(self) -> str:
        mark = {"error": "✖", "warn": "▲", "ok": "✔", "info": "·"}[self.level]
        return f"{mark} {self.message}"


# --- 이미지 저장 --------------------------------------------------------
def save_image(image: np.ndarray, path: str | Path) -> Path:
    """PNG 저장. 한글 경로에서도 동작하도록 imencode + write_bytes 를 쓴다."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("PNG 인코딩에 실패했습니다.")
    p.write_bytes(buffer.tobytes())
    return p


def _prune(directory: Path, prefix: str, keep: int | None = None) -> None:
    keep = MAX_SNAPSHOTS if keep is None else keep
    files = sorted(directory.glob(f"{prefix}_*.png"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep] if len(files) > keep else []:
        try:
            old.unlink()
        except OSError:
            pass


def save_failure_snapshot(
    frame: np.ndarray | None,
    config: AppConfig,
    prefix: str = "activate_fail",
    log_dir: str | Path | None = None,
    minimap: MinimapVision | None = None,
) -> list[Path]:
    """실패 시점의 화면과 미니맵 진단 이미지를 저장하고 저장된 경로를 돌려준다.

    사용자가 이 파일만 보내면 어느 단계가 왜 실패했는지 눈으로 확인할 수 있다.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    directory = Path(log_dir) if log_dir is not None else LOG_DIR
    stamp = time.strftime("%Y%m%d_%H%M%S_") + f"{int(time.time() * 1000) % 1000:03d}"
    saved = [save_image(frame, directory / f"{prefix}_{stamp}.png")]
    if config.rune.use_minimap:
        try:
            vision = minimap or MinimapVision(config)
            saved.append(
                save_image(vision.debug_image(frame), directory / f"{prefix}_{stamp}_minimap.png")
            )
        except Exception:  # 진단 이미지 실패로 본 화면 저장까지 잃지 않는다
            pass
    _prune(directory, prefix)
    return saved


# --- 화면 변화 측정 -----------------------------------------------------
def region_change_ratio(before: np.ndarray | None, after: np.ndarray | None, level: int = 25) -> float:
    """두 이미지에서 밝기가 level 이상 달라진 픽셀의 비율.

    활성화 키를 누른 뒤 화살표 영역이 '변하기는 했는데' 화살표가 인식되지
    않았다면, 스페이스바는 먹었고 **화살표 템플릿이 안 맞는 것**이다.
    이 둘을 구분해야 사용자가 엉뚱한 설정을 만지지 않는다.
    """
    if before is None or after is None:
        return 0.0
    if before.shape != after.shape or before.size == 0:
        return 0.0
    a = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY) if before.ndim == 3 else before
    b = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY) if after.ndim == 3 else after
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff >= level)) / float(diff.size)


# --- 설정 자가 점검 -----------------------------------------------------
def check_config(config: AppConfig, vision=None) -> list[Issue]:
    """룬 해제에 실패하게 만드는 흔한 설정 실수를 찾는다.

    실제 게임 없이도 판단할 수 있는 것만 본다(화면이 필요한 검사는 diagnose_frame).
    """
    issues: list[Issue] = []
    cfg = config.rune
    if not cfg.enabled:
        return [Issue("info", "룬 해제 기능이 꺼져 있습니다.")]

    if cfg.activate_key.upper() != "SPACE":
        issues.append(
            Issue(
                "warn",
                f"룬 활성화 키가 {cfg.activate_key} 입니다 — 이 서버(나루)의 룬 해제는 "
                "스페이스바입니다. ‘해제 동작 → 룬 활성화 키’ 를 SPACE 로 바꾸세요.",
            )
        )
    if cfg.activate_taps <= 1:
        issues.append(
            Issue(
                "warn",
                "활성화 시도 횟수가 1회입니다 — 한 번 빗나가면 바로 포기합니다. 3~4회를 권장합니다.",
            )
        )
    if cfg.activate_press_ms < 60:
        issues.append(
            Issue(
                "warn",
                f"활성화 키 누름 시간이 {cfg.activate_press_ms}ms 로 짧습니다 — "
                "게임이 입력을 놓칠 수 있습니다 (100~150ms 권장).",
            )
        )
    if cfg.activate_gap < 0.35:
        issues.append(
            Issue(
                "warn",
                f"활성화 후 UI 대기가 {cfg.activate_gap:.2f}초로 짧습니다 — "
                "화살표 패널이 뜨기 전에 실패로 판단할 수 있습니다 (0.6초 이상 권장).",
            )
        )
    if cfg.max_retries <= 0:
        issues.append(Issue("info", "재시도 횟수가 0회입니다 — 한 번 실패하면 다음 룬까지 기다립니다."))

    if cfg.use_minimap:
        issues.extend(_check_minimap(config))
    elif cfg.source == "minimap":
        issues.append(
            Issue("warn", "룬 찾는 방식이 미니맵인데 미니맵 설정이 꺼져 있어 화면 템플릿으로 동작합니다.")
        )

    if vision is not None:
        ready, missing = vision.templates_ready()
        if not ready:
            names = ", ".join(Path(m).name for m in missing)
            issues.append(
                Issue(
                    "error",
                    f"필요한 템플릿 이미지가 없습니다: {names} — 화살표가 없으면 UI 가 떠도 "
                    "‘활성화 실패’ 로 보고됩니다. ‘화살표 1장으로 4방향 자동 생성’ 을 먼저 하세요.",
                )
            )
    return issues


def _check_minimap(config: AppConfig) -> list[Issue]:
    issues: list[Issue] = []
    mm = config.rune.minimap
    if MinimapVision.ranges_overlap(mm.rune_color, mm.char_color):
        issues.append(
            Issue(
                "error",
                f"룬 색({mm.rune_color.describe()})과 캐릭터 색({mm.char_color.describe()}) "
                "범위가 겹칩니다 — 같은 표식을 둘 다로 인식해 dx 가 항상 0 이 되고, "
                "정렬된 것으로 착각해 활성화가 계속 빗나갑니다. 두 색을 각각 다시 추출하세요.",
            )
        )
    if mm.align_tolerance <= 0:
        issues.append(
            Issue(
                "warn",
                "좌우 정렬 허용 오차가 0px 입니다 — 소수점 좌표에서는 도달할 수 없어 "
                "내부적으로 0.5px 로 처리됩니다. 1~2px 을 권장합니다.",
            )
        )
    if mm.nudge_ms <= 0:
        issues.append(
            Issue(
                "warn",
                "미세 이동 시간이 0ms 라 활성화가 빗나가도 위치를 다시 잡지 않습니다 (60~100ms 권장).",
            )
        )
    area = mm.roi.w * mm.roi.h
    if area > 0.25:
        issues.append(
            Issue(
                "warn",
                f"미니맵 영역이 화면의 {area:.0%} 입니다 — 미니맵만 정확히 지정하세요. "
                "넓으면 다른 UI 색을 표식으로 오인합니다.",
            )
        )
    elif area < 0.002:
        issues.append(
            Issue(
                "warn",
                f"미니맵 영역이 화면의 {area:.1%} 로 너무 작습니다 — 표식이 영역 밖으로 나갈 수 있습니다.",
            )
        )
    return issues


# --- 현재 화면으로 단계별 점검 -------------------------------------------
def diagnose_frame(config: AppConfig, frame: np.ndarray | None, vision, minimap=None) -> list[Issue]:
    """지금 화면 한 장으로 감지 → 정렬 → 판독 각 단계를 한 번씩 점검한다."""
    issues = check_config(config, vision)
    if frame is None:
        issues.append(Issue("error", "화면을 가져오지 못했습니다 — 게임 창을 찾을 수 없습니다."))
        return issues

    cfg = config.rune
    if cfg.use_minimap:
        reading = (minimap or MinimapVision(config)).read(frame)
        if reading.ambiguous:
            issues.append(Issue("error", f"미니맵 판독: {reading.describe()}"))
        elif reading.found:
            tolerance = max(0.5, float(cfg.minimap.align_tolerance))
            issues.append(Issue("ok", f"미니맵 판독: {reading.describe()}"))
            if abs(reading.dx or 0) <= tolerance:
                issues.append(
                    Issue("ok", "지금 캐릭터가 룬과 좌우로 정렬된 상태입니다 — 이 자리에서 활성화가 됩니다.")
                )
        elif reading.char is None and reading.rune is None:
            issues.append(
                Issue("warn", "미니맵에서 두 표식 모두 찾지 못했습니다 — 미니맵 영역과 색 설정을 확인하세요.")
            )
        elif reading.rune is None:
            issues.append(
                Issue(
                    "info",
                    "미니맵에 룬 표식이 없습니다 — 지금 룬이 없거나, 캐릭터가 룬 위에 서서 가린 상태입니다.",
                )
            )
        else:
            issues.append(Issue("warn", "미니맵에서 캐릭터 표식을 찾지 못했습니다 — 캐릭터 색을 다시 추출하세요."))

    rune = vision.detect_rune(frame)
    if rune is not None:
        issues.append(Issue("ok", f"화면에서 룬 이미지 확인 (점수 {rune.score:.2f}, 위치 {rune.center})"))
    else:
        issues.append(Issue("info", f"화면에서 룬 이미지를 찾지 못했습니다 (임계값 {cfg.rune_threshold:.2f})"))

    if cfg.use_banner and cfg.banner_template:
        banner = vision.detect_banner(frame)
        issues.append(
            Issue("ok", f"상단 안내 문구 감지 (점수 {banner.score:.2f})")
            if banner is not None
            else Issue("info", "상단 안내 문구가 보이지 않습니다 (룬이 없으면 정상입니다).")
        )

    arrows = vision.read_arrows(frame)
    if arrows.ok:
        issues.append(Issue("ok", f"화살표 판독: {arrows.describe()} ({arrows.sequence})"))
    elif arrows.count:
        issues.append(Issue("warn", f"화살표 판독 실패: {arrows.reason}"))
    else:
        issues.append(Issue("info", "화살표 UI 가 화면에 없습니다 (해제 중이 아니면 정상입니다)."))
    issues.append(
        Issue("info", f"방향별 최고 점수: {arrows.describe_scores()} (임계값 {cfg.arrow_threshold:.2f})")
    )
    return issues
