"""룬 감지 + 방향 화살표 판독.

두 단계로 나뉜다.
1) 룬 감지: 맵에 떠 있는 룬(또는 사용자가 지정한 표식)을 템플릿으로 찾는다.
2) 화살표 판독: 룬을 활성화하면 화면 상단에 방향 화살표 4개가 나온다.
   4개 템플릿을 각각 매칭한 뒤 x 좌표로 묶고(클러스터링), 클러스터마다
   점수가 가장 높은 방향을 골라 왼쪽→오른쪽 순서로 정렬한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..config import AppConfig, Roi
from .matcher import Match, Template, TemplateMatcher, load_template, template_from_array


@dataclass
class ArrowReading:
    sequence: list[str] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    ok: bool = False
    reason: str = ""
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.sequence)

    def describe(self) -> str:
        arrows = {"UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→"}
        return " ".join(arrows.get(d, d) for d in self.sequence)

    def describe_scores(self) -> str:
        """방향별 최고 점수 — 임계값을 정할 때 참고한다."""
        if not self.scores:
            return "점수 없음"
        return ", ".join(f"{k} {v:.2f}" for k, v in sorted(self.scores.items()))


class RuneVision:
    def __init__(self, config: AppConfig, matcher: TemplateMatcher | None = None) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher()
        self.missing_templates: list[str] = []
        self._mem_templates: dict[str, Template] = {}

    # --- 템플릿 관리 ---------------------------------------------------
    def register_template(self, name: str, template: Template) -> None:
        """파일 없이 메모리 템플릿을 등록 (테스트/데모)."""
        self._mem_templates[name] = template

    def _templates(self, names: list[str], scale_mult: float = 1.0) -> list[Template]:
        out: list[Template] = []
        missing: list[str] = []
        scales = self.config.rune.scales or [1.0]
        for name in names:
            mem = self._mem_templates.get(name)
            if mem is not None:
                out.append(
                    mem
                    if scale_mult == 1.0
                    else template_from_array(mem.gray, mem.name, scale=scale_mult)
                )
                continue
            path: Path = self.config.template_path(name)
            for scale in scales:
                try:
                    out.append(load_template(path, scale=scale * scale_mult))
                except (FileNotFoundError, ValueError):
                    missing.append(str(path))
                    break
        self.missing_templates = missing
        return out

    def _roi_pixels(self, roi: Roi, frame: np.ndarray) -> tuple[int, int, int, int]:
        h, w = frame.shape[:2]
        return roi.to_pixels(w, h)

    def templates_ready(self) -> tuple[bool, list[str]]:
        """현재 설정에서 실제로 필요한 템플릿만 확인한다.

        미니맵 모드에서는 룬 이미지가 필요 없고, 안내 문구 모드에서는 문구 이미지가 필요하다.
        """
        cfg = self.config.rune
        names = list(cfg.arrow_templates.values())
        if not cfg.use_minimap:
            names.extend(cfg.rune_templates)
        if cfg.use_banner and cfg.banner_template:
            names.append(cfg.banner_template)
        missing = [
            str(self.config.template_path(n))
            for n in names
            if n not in self._mem_templates and not self.config.template_path(n).exists()
        ]
        return (not missing), missing

    # --- 1단계: 룬 감지 -------------------------------------------------
    def detect_rune(self, frame: np.ndarray) -> Match | None:
        cfg = self.config.rune
        roi = self._roi_pixels(cfg.rune_roi, frame)
        scale = cfg.detect_scale if 0.2 <= cfg.detect_scale < 1.0 else 1.0

        if scale == 1.0:
            search = frame
            search_roi: tuple[int, int, int, int] | None = roi
        else:
            # ROI 만 잘라 축소해서 매칭한다 (탐색 픽셀 수가 scale^2 로 줄어든다)
            x, y, w, h = roi
            search = cv2.resize(
                frame[y : y + h, x : x + w], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
            search_roi = None

        best: Match | None = None
        for template in self._templates(list(cfg.rune_templates), scale_mult=scale):
            match = self.matcher.find_best(search, template, search_roi, cfg.rune_threshold)
            if match is not None and (best is None or match.score > best.score):
                best = match
        if best is None or scale == 1.0:
            return best
        inv = 1.0 / scale
        return Match(
            score=best.score,
            x=roi[0] + int(best.x * inv),
            y=roi[1] + int(best.y * inv),
            w=int(best.w * inv),
            h=int(best.h * inv),
            label=best.label,
        )

    # --- 2단계: 화살표 판독 ---------------------------------------------
    def read_arrows(self, frame: np.ndarray) -> ArrowReading:
        cfg = self.config.rune
        roi = self._roi_pixels(cfg.arrow_roi, frame)
        candidates: list[Match] = []
        scores: dict[str, float] = {}
        for direction, name in cfg.arrow_templates.items():
            for template in self._templates([name]):
                # 진단용으로 임계값과 무관한 최고 점수도 같이 구한다
                best = self.matcher.find_best(frame, template, roi, threshold=-1.0)
                if best is not None:
                    scores[direction] = max(scores.get(direction, 0.0), best.score)
                found = self.matcher.find_all(
                    frame,
                    template,
                    roi,
                    cfg.arrow_threshold,
                    max_results=max(cfg.arrow_count + 2, 4),
                )
                for m in found:
                    candidates.append(
                        Match(m.score, m.x, m.y, m.w, m.h, label=direction)
                    )

        if not candidates:
            return ArrowReading(ok=False, reason="화살표를 찾지 못함", scores=scores)

        clusters = _cluster_by_x(candidates)
        picked = [max(group, key=lambda m: m.score) for group in clusters]
        picked.sort(key=lambda m: m.cx)

        sequence = [m.label for m in picked]
        if len(sequence) != cfg.arrow_count:
            return ArrowReading(
                sequence=sequence,
                matches=picked,
                ok=False,
                reason=f"화살표 {cfg.arrow_count}개 필요, {len(sequence)}개 인식",
                scores=scores,
            )
        return ArrowReading(sequence=sequence, matches=picked, ok=True, scores=scores)

    # --- 상단 안내 문구(저주 배너) ---------------------------------------
    def detect_banner(self, frame: np.ndarray) -> Match | None:
        """`엘리트 보스의 저주…` 안내 문구가 떠 있는지 확인한다.

        이 문구는 룬이 남아 있는 동안 계속 표시되고 해제되면 사라지므로,
        룬 등장 감지와 해제 성공 판정 모두에 쓸 수 있다.
        """
        cfg = self.config.rune
        if not cfg.banner_template:
            return None
        roi = self._roi_pixels(cfg.banner_roi, frame)
        for template in self._templates([cfg.banner_template]):
            match = self.matcher.find_best(frame, template, roi, cfg.banner_threshold)
            if match is not None:
                return match
        return None

    def arrows_visible(self, frame: np.ndarray) -> bool:
        """화살표 UI 가 아직 떠 있는지 (해제 성공 판정용)."""
        cfg = self.config.rune
        roi = self._roi_pixels(cfg.arrow_roi, frame)
        for direction, name in cfg.arrow_templates.items():  # noqa: B007
            for template in self._templates([name]):
                if self.matcher.find_best(frame, template, roi, cfg.arrow_threshold):
                    return True
        return False


def _cluster_by_x(matches: list[Match], gap_ratio: float = 0.6) -> list[list[Match]]:
    """x 좌표가 가까운 검출들을 하나의 화살표로 묶는다."""
    if not matches:
        return []
    ordered = sorted(matches, key=lambda m: m.cx)
    width = max(m.w for m in ordered)
    gap = max(4, int(width * gap_ratio))
    clusters: list[list[Match]] = [[ordered[0]]]
    for m in ordered[1:]:
        if m.cx - clusters[-1][-1].cx <= gap:
            clusters[-1].append(m)
        else:
            clusters.append([m])
    return clusters
