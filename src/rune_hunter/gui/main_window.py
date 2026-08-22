"""메인 창.

왼쪽 위에서 아래로: 제목 → 상태 카드 → 탭(자동공격 / 룬 해제 / 성능·설정 / 주의사항)
→ 로그 → 시작·중지 버튼.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    DEFAULT_PROFILE_PATH,
    DEFAULT_TEMPLATE_DIR,
    LOG_DIR,
    AppConfig,
    Roi,
)
from ..demo import DemoWorld
from ..engine import EngineState, MacroEngine
from ..hotkeys import HotkeyManager
from ..inputs import RecordingBackend, create_backend
from ..keys import HOTKEY_CHOICES, SELECTABLE_KEYS
from ..logging_bus import EventBus
from ..platform_layer import IS_WINDOWS
from ..platform_layer.admin import is_admin
from ..platform_layer.windows import create_locator
from ..vision import RuneVision
from ..vision.matcher import clear_cache
from .capture_dialog import RegionSelectDialog, save_png
from .theme import STYLESHEET
from .widgets import KeySelect, LogView, SkillRow, StatusCard

ARROW_NAMES = {"UP": "위 ↑", "DOWN": "아래 ↓", "LEFT": "왼쪽 ←", "RIGHT": "오른쪽 →"}


class MainWindow(QMainWindow):
    hotkey_start = Signal()
    hotkey_stop = Signal()

    def __init__(self, config: AppConfig, bus: EventBus, demo: bool = False) -> None:
        super().__init__()
        self.config = config
        self.bus = bus
        self.engine: MacroEngine | None = None
        self._demo_world: DemoWorld | None = None
        self._preview_capture = None

        self.setWindowTitle("룬 헌터 — 사냥 / 버프 / 룬 해제 매크로")
        self.setMinimumSize(880, 900)
        self.setStyleSheet(STYLESHEET)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll(self._build_attack_tab()), "자동공격")
        self.tabs.addTab(self._scroll(self._build_rune_tab()), "룬 해제")
        self.tabs.addTab(self._scroll(self._build_settings_tab()), "성능 · 설정")
        self.tabs.addTab(self._scroll(self._build_about_tab()), "주의사항")
        layout.addWidget(self.tabs, 1)

        self.log = LogView(self.config.general.log_limit)
        self.log.setMinimumHeight(170)
        layout.addWidget(self.log)
        layout.addLayout(self._build_controls())

        self.demo_check.setChecked(demo)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(100)

        self.hotkeys = HotkeyManager(bus)
        self.hotkey_start.connect(self.start_engine)
        self.hotkey_stop.connect(self.stop_engine)
        self._rebind_hotkeys()

        self._announce()

    # ------------------------------------------------------------------
    # 화면 구성
    # ------------------------------------------------------------------
    def _scroll(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(widget)
        return area

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        left = QVBoxLayout()
        title = QLabel("룬 헌터")
        title.setObjectName("title")
        subtitle = QLabel("사냥키 무한 반복 · 버프 주기 관리 · 룬 등장 시 자동 해제")
        subtitle.setObjectName("subtitle")
        left.addWidget(title)
        left.addWidget(subtitle)
        row.addLayout(left)
        row.addStretch(1)
        self.status_card = StatusCard()
        self.status_card.setMinimumWidth(330)
        row.addWidget(self.status_card)
        return row

    def _build_attack_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        attack = self.config.attack
        hint = QLabel(
            "사냥기는 시간제한 없이 계속 반복 입력됩니다. 주기가 짧을수록 초당 입력이 늘어납니다"
            " (0.12초 ≒ 초당 8회)."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.hunt_row = SkillRow(
            attack.hunt, interval_min=0.03, interval_max=10.0, interval_step=0.01
        )
        layout.addWidget(self.hunt_row)

        hold_row = QHBoxLayout()
        self.hunt_hold = QCheckBox("사냥키를 누른 상태로 유지 (연타 대신 홀드)")
        self.hunt_hold.setChecked(attack.hunt.hold)
        hold_row.addSpacing(12)
        hold_row.addWidget(self.hunt_hold)
        hold_row.addStretch(1)
        layout.addLayout(hold_row)

        self.boss_row = SkillRow(attack.boss, interval_min=0.1, interval_max=600.0)
        layout.addWidget(self.boss_row)

        buff_box = QGroupBox("버프 (주기마다 자동 사용)")
        buff_layout = QVBoxLayout(buff_box)
        buff_layout.setSpacing(6)
        self.buff_rows = []
        for buff in attack.buffs:
            row = SkillRow(buff, interval_min=1.0, interval_max=3600.0, interval_step=5.0)
            self.buff_rows.append(row)
            buff_layout.addWidget(row)
        self.buff_first = QCheckBox("시작 직후 활성화된 버프를 한 번씩 사용")
        self.buff_first.setChecked(attack.buff_first)
        buff_layout.addWidget(self.buff_first)
        layout.addWidget(buff_box)

        move_box = QGroupBox("사냥 중 이동 (선택)")
        form = QFormLayout(move_box)
        self.move_enabled = QCheckBox("주기적으로 좌우 이동")
        self.move_enabled.setChecked(attack.movement.enabled)
        self.move_interval = self._dspin(attack.movement.interval, 1.0, 600.0, 1.0, " 초")
        self.move_hold = self._spin(attack.movement.hold_ms, 100, 5000, 50, " ms")
        self.move_jump = QCheckBox("이동 후 점프")
        self.move_jump.setChecked(attack.movement.jump)
        form.addRow(self.move_enabled)
        form.addRow("방향 전환 주기", self.move_interval)
        form.addRow("한 번에 이동 시간", self.move_hold)
        form.addRow(self.move_jump)
        layout.addWidget(move_box)

        keys_box = QGroupBox("이동 · 점프 키")
        keys_form = QFormLayout(keys_box)
        keys = self.config.keys
        self.key_jump = KeySelect(keys.jump)
        self.key_rope = KeySelect(keys.rope)
        keys_form.addRow("점프", self.key_jump)
        keys_form.addRow("로프 커넥트(수직 상승)", self.key_rope)
        note = QLabel("아래 점프는 ‘아래 방향키 + 점프키’ 조합으로 자동 처리됩니다.")
        note.setObjectName("subtitle")
        keys_form.addRow(note)
        layout.addWidget(keys_box)

        layout.addStretch(1)
        return page

    def _build_rune_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        rune = self.config.rune

        self.rune_enabled = QCheckBox("룬 해제 사용 (룬 감지 시 모든 스킬 입력을 멈추고 해제에 집중)")
        self.rune_enabled.setChecked(rune.enabled)
        layout.addWidget(self.rune_enabled)

        source_box = QGroupBox("룬 찾는 방식")
        source_layout = QVBoxLayout(source_box)
        self.source_minimap = QCheckBox("미니맵 색상으로 찾기 (룬이 화면 밖에 있어도 감지 — 권장)")
        self.source_minimap.setChecked(rune.source == "minimap")
        source_note = QLabel(
            "미니맵의 <b>보라색 룬 표식</b>과 <b>노란색 캐릭터 표식</b>이 겹치도록 이동한 뒤 활성화 키를 누릅니다.<br>"
            "끄면 화면에 보이는 룬 이미지(템플릿)로 찾습니다."
        )
        source_note.setObjectName("subtitle")
        source_note.setWordWrap(True)
        source_layout.addWidget(self.source_minimap)
        source_layout.addWidget(source_note)
        layout.addWidget(source_box)

        mm = rune.minimap
        mm_box = QGroupBox("미니맵 설정")
        mm_layout = QVBoxLayout(mm_box)

        roi_row = QHBoxLayout()
        roi_row.addWidget(QLabel("미니맵 영역"))
        self.mm_roi_label = QLabel(mm.roi.describe())
        self.mm_roi_label.setObjectName("subtitle")
        roi_row.addWidget(self.mm_roi_label, 1)
        mm_roi_button = QPushButton("영역 지정")
        mm_roi_button.clicked.connect(self._pick_minimap_roi)
        roi_row.addWidget(mm_roi_button)
        mm_layout.addLayout(roi_row)

        color_row = QHBoxLayout()
        self.mm_rune_color_label = QLabel(mm.rune_color.describe())
        self.mm_rune_color_label.setObjectName("subtitle")
        self.mm_char_color_label = QLabel(mm.char_color.describe())
        self.mm_char_color_label.setObjectName("subtitle")
        rune_color_btn = QPushButton("룬 색 추출")
        rune_color_btn.clicked.connect(lambda: self._sample_minimap_color("rune"))
        char_color_btn = QPushButton("캐릭터 색 추출")
        char_color_btn.clicked.connect(lambda: self._sample_minimap_color("char"))
        color_grid = QGridLayout()
        color_grid.addWidget(QLabel("룬 표식 색"), 0, 0)
        color_grid.addWidget(self.mm_rune_color_label, 0, 1)
        color_grid.addWidget(rune_color_btn, 0, 2)
        color_grid.addWidget(QLabel("캐릭터 표식 색"), 1, 0)
        color_grid.addWidget(self.mm_char_color_label, 1, 1)
        color_grid.addWidget(char_color_btn, 1, 2)
        color_grid.setColumnStretch(1, 1)
        mm_layout.addLayout(color_grid)
        color_row.addStretch(1)

        mm_form = QFormLayout()
        self.mm_tolerance = self._spin(mm.align_tolerance, 0, 20, 1, " px")
        self.mm_vtolerance = self._spin(mm.vertical_tolerance, 0, 20, 1, " px")
        self.mm_ms_per_px = self._dspin(mm.ms_per_px, 5.0, 400.0, 5.0, " ms/px", 1)
        self.mm_max_hold = self._spin(mm.max_hold_ms, 100, 3000, 50, " ms")
        self.mm_max_seconds = self._dspin(mm.max_seconds, 3.0, 120.0, 1.0, " 초")
        self.mm_auto = QCheckBox("이동 계수 자동 보정 (맵마다 다른 미니맵 배율에 맞춤)")
        self.mm_auto.setChecked(mm.auto_calibrate)
        self.mm_rope = QCheckBox("위로 올라갈 때 로프 커넥트 사용")
        self.mm_rope.setChecked(mm.use_rope)
        mm_form.addRow("좌우 정렬 허용 오차", self.mm_tolerance)
        mm_form.addRow("높이 허용 오차", self.mm_vtolerance)
        mm_form.addRow("이동 환산 계수", self.mm_ms_per_px)
        mm_form.addRow("1회 최대 이동", self.mm_max_hold)
        mm_form.addRow("정렬 제한 시간", self.mm_max_seconds)
        mm_form.addRow(self.mm_auto)
        mm_form.addRow(self.mm_rope)
        mm_layout.addLayout(mm_form)

        mm_test = QPushButton("미니맵 인식 테스트 (룬·캐릭터 좌표 확인)")
        mm_test.clicked.connect(self._test_minimap)
        mm_layout.addWidget(mm_test)
        layout.addWidget(mm_box)

        tpl_box = QGroupBox("템플릿 이미지")
        tpl_layout = QGridLayout(tpl_box)
        tpl_layout.setColumnStretch(1, 1)
        self.template_labels: dict[str, QLabel] = {}
        rows = [("rune", "룬 이미지", rune.rune_templates[0] if rune.rune_templates else "rune.png")]
        rows += [(d, f"화살표 {ARROW_NAMES[d]}", rune.arrow_templates.get(d, "")) for d in ARROW_NAMES]
        for i, (slot, label, filename) in enumerate(rows):
            tpl_layout.addWidget(QLabel(label), i, 0)
            state = QLabel(filename)
            state.setObjectName("subtitle")
            self.template_labels[slot] = state
            tpl_layout.addWidget(state, i, 1)
            button = QPushButton("화면에서 캡처")
            button.clicked.connect(lambda _=False, s=slot: self._capture_template(s))
            tpl_layout.addWidget(button, i, 2)

        row = len(rows)
        auto_button = QPushButton("화살표 1장으로 4방향 자동 생성 (권장)")
        auto_button.clicked.connect(self._capture_arrow_set)
        tpl_layout.addWidget(auto_button, row, 0, 1, 3)
        auto_note = QLabel(
            "게임의 화살표 4개는 같은 그림을 90도씩 돌린 것이라, 한 방향만 캡처하면 나머지는 자동으로 만듭니다."
        )
        auto_note.setObjectName("subtitle")
        auto_note.setWordWrap(True)
        tpl_layout.addWidget(auto_note, row + 1, 0, 1, 3)

        banner_row = row + 2
        self.use_banner = QCheckBox("상단 안내 문구로 룬 등장·해제 판정 (엘리트 보스의 저주 문구)")
        self.use_banner.setChecked(rune.use_banner)
        tpl_layout.addWidget(self.use_banner, banner_row, 0, 1, 2)
        banner_button = QPushButton("문구 캡처")
        banner_button.clicked.connect(lambda: self._capture_template("banner"))
        tpl_layout.addWidget(banner_button, banner_row, 2)
        self.template_labels["banner"] = QLabel(rune.banner_template)
        self.template_labels["banner"].setObjectName("subtitle")
        tpl_layout.addWidget(self.template_labels["banner"], banner_row + 1, 0, 1, 3)
        layout.addWidget(tpl_box)

        roi_box = QGroupBox("탐색 영역 (좁을수록 빠르고 오탐이 적습니다)")
        roi_layout = QGridLayout(roi_box)
        self.rune_roi_label = QLabel(rune.rune_roi.describe())
        self.arrow_roi_label = QLabel(rune.arrow_roi.describe())
        for i, (label, state, handler) in enumerate(
            [
                ("룬 탐색 영역", self.rune_roi_label, self._pick_rune_roi),
                ("화살표 탐색 영역", self.arrow_roi_label, self._pick_arrow_roi),
            ]
        ):
            roi_layout.addWidget(QLabel(label), i, 0)
            state.setObjectName("subtitle")
            roi_layout.addWidget(state, i, 1)
            button = QPushButton("영역 지정")
            button.clicked.connect(handler)
            roi_layout.addWidget(button, i, 2)
            reset = QPushButton("전체로 초기화")
            reset.clicked.connect(lambda _=False, idx=i: self._reset_roi(idx))
            roi_layout.addWidget(reset, i, 3)
        roi_layout.setColumnStretch(1, 1)
        layout.addWidget(roi_box)

        detect_box = QGroupBox("감지 설정")
        detect_form = QFormLayout(detect_box)
        self.rune_threshold = self._dspin(rune.rune_threshold, 0.3, 0.99, 0.01, "", 2)
        self.arrow_threshold = self._dspin(rune.arrow_threshold, 0.3, 0.99, 0.01, "", 2)
        self.check_interval = self._dspin(rune.check_interval, 0.1, 10.0, 0.1, " 초")
        self.arrow_count = self._spin(rune.arrow_count, 2, 8, 1, " 개")
        self.stable_frames = self._spin(rune.arrow_stable_frames, 1, 6, 1, " 프레임")
        self.detect_scale = self._dspin(rune.detect_scale, 0.3, 1.0, 0.05, " 배", 2)
        detect_form.addRow("룬 감지 임계값", self.rune_threshold)
        detect_form.addRow("화살표 감지 임계값", self.arrow_threshold)
        detect_form.addRow("룬 탐색 주기", self.check_interval)
        detect_form.addRow("화살표 개수", self.arrow_count)
        detect_form.addRow("판독 확정 프레임", self.stable_frames)
        detect_form.addRow("감지 축소 배율 (1.0=원본)", self.detect_scale)
        scale_note = QLabel("0.5 로 줄이면 룬 탐색이 3~4배 빨라집니다. 너무 낮추면 인식률이 떨어집니다.")
        scale_note.setObjectName("subtitle")
        scale_note.setWordWrap(True)
        detect_form.addRow(scale_note)
        layout.addWidget(detect_box)

        solve_box = QGroupBox("해제 동작")
        solve_form = QFormLayout(solve_box)
        self.activate_key = KeySelect(rune.activate_key)
        self.activate_taps = self._spin(rune.activate_taps, 1, 8, 1, " 회")
        self.activate_press = self._spin(rune.activate_press_ms, 20, 500, 10, " ms")
        self.activate_settle = self._dspin(rune.activate_settle, 0.0, 2.0, 0.05, " 초")
        self.activate_gap = self._dspin(rune.activate_gap, 0.1, 3.0, 0.05, " 초")
        self.nudge_ms = self._spin(rune.minimap.nudge_ms, 0, 500, 10, " ms")
        self.arrow_press = self._spin(rune.arrow_press_ms, 10, 300, 5, " ms")
        self.arrow_gap = self._dspin(rune.arrow_gap, 0.02, 1.5, 0.02, " 초")
        self.arrow_wait = self._dspin(rune.arrow_wait, 0.3, 10.0, 0.1, " 초")
        self.confirm_timeout = self._dspin(rune.confirm_timeout, 0.5, 15.0, 0.5, " 초")
        self.max_retries = self._spin(rune.max_retries, 0, 5, 1, " 회")
        self.cooldown_success = self._dspin(rune.cooldown_success, 0.0, 300.0, 1.0, " 초")
        self.cooldown_fail = self._dspin(rune.cooldown_fail, 0.0, 600.0, 5.0, " 초")
        solve_form.addRow("룬 활성화 키", self.activate_key)
        activate_note = QLabel("이 서버(나루)의 룬 활성화는 <b>SPACE</b> 입니다.")
        activate_note.setObjectName("subtitle")
        solve_form.addRow(activate_note)
        solve_form.addRow("활성화 시도 횟수", self.activate_taps)
        solve_form.addRow("활성화 키 누름 시간", self.activate_press)
        solve_form.addRow("정렬 후 안정화 대기", self.activate_settle)
        solve_form.addRow("활성화 후 UI 대기", self.activate_gap)
        solve_form.addRow("시도 사이 미세 이동", self.nudge_ms)
        activate_hint = QLabel(
            "스페이스바가 안 먹을 때: <b>누름 시간</b>을 150ms 로, <b>시도 횟수</b>를 4회로 올리세요. "
            "정렬 직후 캐릭터가 미끄러지면 <b>안정화 대기</b>를 0.4초까지 늘립니다. "
            "<b>미세 이동</b>은 시도할 때마다 좌우로 조금씩 훑는 폭입니다."
        )
        activate_hint.setObjectName("subtitle")
        activate_hint.setWordWrap(True)
        solve_form.addRow(activate_hint)
        solve_form.addRow("화살표 키 누름 시간", self.arrow_press)
        solve_form.addRow("화살표 입력 간격", self.arrow_gap)
        solve_form.addRow("화살표 UI 대기", self.arrow_wait)
        solve_form.addRow("해제 확인 대기", self.confirm_timeout)
        solve_form.addRow("재시도 횟수", self.max_retries)
        solve_form.addRow("성공 후 재탐색 대기", self.cooldown_success)
        solve_form.addRow("실패 후 재탐색 대기", self.cooldown_fail)
        layout.addWidget(solve_box)

        approach_box = QGroupBox("룬 접근 (룬이 멀리 있을 때 이동해서 붙기)")
        approach_form = QFormLayout(approach_box)
        ap = rune.approach
        self.approach_enabled = QCheckBox("접근 동작 사용")
        self.approach_enabled.setChecked(ap.enabled)
        self.deadzone = self._spin(ap.deadzone_px, 5, 200, 5, " px")
        self.ms_per_px = self._dspin(ap.ms_per_px, 0.5, 12.0, 0.1, " ms/px")
        self.max_hold = self._spin(ap.max_hold_ms, 100, 3000, 50, " ms")
        self.vertical_tol = self._spin(ap.vertical_tolerance, 10, 400, 10, " px")
        self.approach_seconds = self._dspin(ap.max_seconds, 2.0, 60.0, 1.0, " 초")
        self.use_rope = QCheckBox("위로 이동 시 로프 커넥트 사용")
        self.use_rope.setChecked(ap.use_rope)
        approach_form.addRow(self.approach_enabled)
        approach_form.addRow("좌우 허용 오차", self.deadzone)
        approach_form.addRow("이동 환산 계수", self.ms_per_px)
        approach_form.addRow("1회 최대 이동", self.max_hold)
        approach_form.addRow("높이 차 허용", self.vertical_tol)
        approach_form.addRow("접근 제한 시간", self.approach_seconds)
        approach_form.addRow(self.use_rope)
        layout.addWidget(approach_box)

        diagnose_button = QPushButton("룬 해제 진단 실행 (설정 점검 + 단계별 확인)")
        diagnose_button.setObjectName("primary")
        diagnose_button.clicked.connect(self._run_diagnostics)
        layout.addWidget(diagnose_button)
        diagnose_note = QLabel(
            "지금 화면 한 장으로 설정 실수·미니맵 인식·룬 감지·화살표 판독을 한 번에 점검해 "
            "로그로 알려주고, 화면을 <code>logs/</code> 에 저장합니다. 룬이 떠 있는 상태에서 누르면 가장 정확합니다."
        )
        diagnose_note.setObjectName("subtitle")
        diagnose_note.setWordWrap(True)
        layout.addWidget(diagnose_note)

        test_row = QHBoxLayout()
        for text, handler in [
            ("지금 화면에서 룬 감지 테스트", self._test_rune),
            ("화살표 판독 테스트", self._test_arrows),
            ("현재 화면 저장", self._save_screenshot),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            test_row.addWidget(button)
        layout.addLayout(test_row)
        layout.addStretch(1)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        general = self.config.general

        target_box = QGroupBox("게임 창")
        form = QFormLayout(target_box)
        self.window_titles = QLineEdit(", ".join(general.window_titles))
        self.only_focused = QCheckBox("게임 창이 활성화된 경우에만 키 입력 (권장)")
        self.only_focused.setChecked(general.only_when_focused)
        self.tick_ms = self._spin(general.tick_ms, 1, 50, 1, " ms")
        form.addRow("창 제목 검색어 (쉼표 구분)", self.window_titles)
        form.addRow(self.only_focused)
        form.addRow("제어 루프 주기", self.tick_ms)
        layout.addWidget(target_box)

        hotkey_box = QGroupBox("단축키")
        hk_form = QFormLayout(hotkey_box)
        self.start_hotkey = self._combo(HOTKEY_CHOICES, general.start_hotkey)
        self.stop_hotkey = self._combo(HOTKEY_CHOICES, general.stop_hotkey)
        apply_btn = QPushButton("단축키 다시 등록")
        apply_btn.clicked.connect(self._rebind_hotkeys)
        hk_form.addRow("시작키", self.start_hotkey)
        hk_form.addRow("종료키", self.stop_hotkey)
        hk_form.addRow(apply_btn)
        layout.addWidget(hotkey_box)

        demo_box = QGroupBox("데모 모드")
        demo_layout = QVBoxLayout(demo_box)
        self.demo_check = QCheckBox("게임 없이 시뮬레이션 (가짜 화면에 룬이 등장 → 실제 키 입력 없음)")
        demo_note = QLabel(
            "설정을 시험하거나 룬 해제 로직 동작을 눈으로 확인할 때 사용합니다. "
            "데모 모드에서는 키가 게임으로 전송되지 않습니다."
        )
        demo_note.setObjectName("subtitle")
        demo_note.setWordWrap(True)
        demo_layout.addWidget(self.demo_check)
        demo_layout.addWidget(demo_note)
        layout.addWidget(demo_box)

        perf_box = QGroupBox("성능 · 통계")
        perf_layout = QVBoxLayout(perf_box)
        self.stats_label = QLabel("매크로를 시작하면 통계가 표시됩니다.")
        self.stats_label.setTextFormat(Qt.RichText)
        perf_layout.addWidget(self.stats_label)
        layout.addWidget(perf_box)

        profile_row = QHBoxLayout()
        for text, handler in [
            ("설정 저장", self._save_profile),
            ("다른 이름으로 저장", self._save_profile_as),
            ("설정 불러오기", self._load_profile),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            profile_row.addWidget(button)
        layout.addLayout(profile_row)
        layout.addStretch(1)
        return page

    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        text = QLabel(
            "<b>사용 전 확인</b><br>"
            "• 이 프로그램은 사용자가 직접 운영/이용하는 사설 서버 환경에서의 개인 학습·자동화 실험용입니다.<br>"
            "• 게임 약관 위반, 계정 제재, 그로 인한 손해에 대한 책임은 전적으로 사용자에게 있습니다.<br><br>"
            "<b>동작 방식</b><br>"
            "• 키 입력은 Windows SendInput(스캔코드)으로 전송합니다. 게임이 관리자 권한으로 실행 중이면"
            " 이 프로그램도 관리자 권한이어야 입력이 전달됩니다.<br>"
            "• 창모드 기준으로 게임 창의 클라이언트 영역만 캡처해 템플릿 매칭을 수행합니다.<br>"
            "• 룬이 감지되면 사냥·버프 입력을 즉시 중단하고, 해제가 끝난 뒤 밀린 버프부터 이어서 사용합니다.<br><br>"
            "<b>권장 설정 순서</b><br>"
            "1) 게임을 창모드로 실행 → 상태 카드에 창 정보가 표시되는지 확인<br>"
            "2) ‘룬 해제’ 탭에서 룬·화살표 템플릿을 화면에서 캡처<br>"
            "3) 탐색 영역을 좁게 지정 (화살표는 화면 상단 중앙)<br>"
            "4) 데모 모드로 로직을 확인한 뒤 실제 사냥에 사용<br><br>"
            "<b>자세한 사용법</b><br>"
            "• 프로젝트 폴더의 <code>docs/USAGE.md</code> 에 설치·템플릿 제작·항목별 권장값·"
            "로그 해석·증상별 해결법이 순서대로 정리되어 있습니다.<br>"
            "• 단축키(기본 F1/F2)는 전역으로 등록되므로, 게임에서 그 키를 쓰면 F11·INSERT 등으로 바꾸세요."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch(1)
        return page

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.start_button = QPushButton("시작")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_engine)
        self.stop_button = QPushButton("중지")
        self.stop_button.setObjectName("secondary")
        self.stop_button.clicked.connect(self.stop_engine)
        self.stop_button.setEnabled(False)
        row.addWidget(self.start_button, 2)
        row.addWidget(self.stop_button, 2)
        self.state_label = QLabel("정지")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setMinimumWidth(150)
        row.addWidget(self.state_label, 1)
        return row

    # 위젯 헬퍼 --------------------------------------------------------
    def _spin(self, value: int, lo: int, hi: int, step: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(int(value))
        return spin

    def _dspin(
        self, value: float, lo: float, hi: float, step: float, suffix: str, decimals: int = 2
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setValue(float(value))
        return spin

    def _combo(self, choices, current: str) -> QComboBox:
        combo = QComboBox()
        for choice in choices:
            combo.addItem(choice, userData=choice)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
        return combo

    # ------------------------------------------------------------------
    # 설정 반영
    # ------------------------------------------------------------------
    def collect(self) -> None:
        cfg = self.config
        for row in [self.hunt_row, self.boss_row, *self.buff_rows]:
            row.apply()
        cfg.attack.hunt.hold = self.hunt_hold.isChecked()
        cfg.attack.buff_first = self.buff_first.isChecked()
        cfg.attack.movement.enabled = self.move_enabled.isChecked()
        cfg.attack.movement.interval = self.move_interval.value()
        cfg.attack.movement.hold_ms = self.move_hold.value()
        cfg.attack.movement.jump = self.move_jump.isChecked()
        cfg.keys.jump = self.key_jump.key()
        cfg.keys.rope = self.key_rope.key()

        rune = cfg.rune
        rune.enabled = self.rune_enabled.isChecked()
        rune.rune_threshold = self.rune_threshold.value()
        rune.arrow_threshold = self.arrow_threshold.value()
        rune.check_interval = self.check_interval.value()
        rune.arrow_count = self.arrow_count.value()
        rune.arrow_stable_frames = self.stable_frames.value()
        rune.detect_scale = self.detect_scale.value()
        rune.activate_key = self.activate_key.key()
        rune.activate_taps = self.activate_taps.value()
        rune.activate_press_ms = self.activate_press.value()
        rune.activate_settle = self.activate_settle.value()
        rune.activate_gap = self.activate_gap.value()
        rune.minimap.nudge_ms = self.nudge_ms.value()
        rune.arrow_press_ms = self.arrow_press.value()
        rune.arrow_gap = self.arrow_gap.value()
        rune.arrow_wait = self.arrow_wait.value()
        rune.confirm_timeout = self.confirm_timeout.value()
        rune.max_retries = self.max_retries.value()
        rune.cooldown_success = self.cooldown_success.value()
        rune.cooldown_fail = self.cooldown_fail.value()
        rune.approach.enabled = self.approach_enabled.isChecked()
        rune.approach.deadzone_px = self.deadzone.value()
        rune.approach.ms_per_px = self.ms_per_px.value()
        rune.approach.max_hold_ms = self.max_hold.value()
        rune.approach.vertical_tolerance = self.vertical_tol.value()
        rune.approach.max_seconds = self.approach_seconds.value()
        rune.approach.use_rope = self.use_rope.isChecked()
        rune.use_banner = self.use_banner.isChecked()
        rune.source = "minimap" if self.source_minimap.isChecked() else "template"
        rune.minimap.enabled = self.source_minimap.isChecked()
        rune.minimap.align_tolerance = self.mm_tolerance.value()
        rune.minimap.vertical_tolerance = self.mm_vtolerance.value()
        rune.minimap.ms_per_px = self.mm_ms_per_px.value()
        rune.minimap.max_hold_ms = self.mm_max_hold.value()
        rune.minimap.max_seconds = self.mm_max_seconds.value()
        rune.minimap.auto_calibrate = self.mm_auto.isChecked()
        rune.minimap.use_rope = self.mm_rope.isChecked()

        general = cfg.general
        titles = [t.strip() for t in self.window_titles.text().split(",") if t.strip()]
        general.window_titles = titles or ["MapleStory"]
        general.only_when_focused = self.only_focused.isChecked()
        general.tick_ms = self.tick_ms.value()
        general.start_hotkey = str(self.start_hotkey.currentData())
        general.stop_hotkey = str(self.stop_hotkey.currentData())

    def refresh_from_config(self) -> None:
        for row in [self.hunt_row, self.boss_row, *self.buff_rows]:
            row.refresh()
        cfg = self.config
        self.hunt_hold.setChecked(cfg.attack.hunt.hold)
        self.buff_first.setChecked(cfg.attack.buff_first)
        self.move_enabled.setChecked(cfg.attack.movement.enabled)
        self.move_interval.setValue(cfg.attack.movement.interval)
        self.move_hold.setValue(cfg.attack.movement.hold_ms)
        self.move_jump.setChecked(cfg.attack.movement.jump)
        self.key_jump.select(cfg.keys.jump)
        self.key_rope.select(cfg.keys.rope)
        self.rune_enabled.setChecked(cfg.rune.enabled)
        self.rune_threshold.setValue(cfg.rune.rune_threshold)
        self.arrow_threshold.setValue(cfg.rune.arrow_threshold)
        self.check_interval.setValue(cfg.rune.check_interval)
        self.arrow_count.setValue(cfg.rune.arrow_count)
        self.stable_frames.setValue(cfg.rune.arrow_stable_frames)
        self.activate_key.select(cfg.rune.activate_key)
        self.activate_taps.setValue(cfg.rune.activate_taps)
        self.activate_press.setValue(cfg.rune.activate_press_ms)
        self.activate_settle.setValue(cfg.rune.activate_settle)
        self.activate_gap.setValue(cfg.rune.activate_gap)
        self.nudge_ms.setValue(cfg.rune.minimap.nudge_ms)
        self.source_minimap.setChecked(cfg.rune.source == "minimap")
        self.use_banner.setChecked(cfg.rune.use_banner)
        self.mm_roi_label.setText(cfg.rune.minimap.roi.describe())
        self.mm_rune_color_label.setText(cfg.rune.minimap.rune_color.describe())
        self.mm_char_color_label.setText(cfg.rune.minimap.char_color.describe())
        self.mm_tolerance.setValue(cfg.rune.minimap.align_tolerance)
        self.mm_ms_per_px.setValue(cfg.rune.minimap.ms_per_px)
        self.rune_roi_label.setText(cfg.rune.rune_roi.describe())
        self.arrow_roi_label.setText(cfg.rune.arrow_roi.describe())
        self.window_titles.setText(", ".join(cfg.general.window_titles))
        self.only_focused.setChecked(cfg.general.only_when_focused)

    # ------------------------------------------------------------------
    # 엔진 제어
    # ------------------------------------------------------------------
    def _demo_settings(self):
        """데모 화면을 현재 설정(미니맵 영역·색·활성화 키)에 맞춰 만든다."""
        from ..demo import DemoSettings
        from ..vision.synth import color_from_spec

        mm = self.config.rune.minimap
        settings = DemoSettings(activate_key=self.config.rune.activate_key)
        if self.config.rune.use_minimap:
            width, height = settings.width, settings.height
            settings.minimap_rect = mm.roi.to_pixels(width, height)
            settings.minimap_rune_bgr = color_from_spec(mm.rune_color)
            settings.minimap_char_bgr = color_from_spec(mm.char_color)
            settings.max_offset_x = 420
            # 실제 게임처럼 겹치면 캐릭터 표식이 룬 표식을 가린다
            settings.minimap_occlude_px = 3
        return settings

    def _make_engine(self) -> MacroEngine:
        demo = self.demo_check.isChecked()
        vision = RuneVision(self.config)
        clear_cache()

        if demo:
            from ..vision.matcher import template_from_array
            from ..vision.synth import demo_templates

            ready, missing = vision.templates_ready()
            if not ready:
                for name, image in demo_templates().items():
                    vision.register_template(name, template_from_array(image, name))
                self.bus.info("데모 모드: 합성 템플릿을 사용합니다 (실제 이미지가 없어도 동작).")
            world = DemoWorld(bus=self.bus, settings=self._demo_settings())
            backend = RecordingBackend(sink=world.on_key)
            self._demo_world = world
            from ..platform_layer.windows import VirtualWindowLocator

            locator = VirtualWindowLocator(
                world.settings.width, world.settings.height, "데모 게임 창"
            )
            capture = world
        else:
            self._demo_world = None
            backend = create_backend()
            locator = create_locator()
            from ..capture import ScreenCapture

            capture = ScreenCapture()
            ready, missing = vision.templates_ready()
            if self.config.rune.enabled and not ready:
                self.bus.warn(
                    "룬/화살표 템플릿 이미지가 없습니다: " + ", ".join(Path(m).name for m in missing)
                )
                self.bus.warn("‘룬 해제’ 탭에서 화면 캡처로 템플릿을 만들어 주세요.")

        return MacroEngine(
            config=self.config,
            inputs=backend,
            capture=capture,
            locator=locator,
            vision=vision,
            bus=self.bus,
        )

    def start_engine(self) -> None:
        if self.engine is not None and self.engine.running:
            return
        self.collect()
        self.engine = self._make_engine()
        if self.engine.start():
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)

    def stop_engine(self) -> None:
        if self.engine is not None:
            self.engine.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    # ------------------------------------------------------------------
    # 캡처 / 테스트 도구
    # ------------------------------------------------------------------
    def _current_frame(self) -> np.ndarray | None:
        if self.demo_check.isChecked():
            world = self._demo_world or DemoWorld(bus=self.bus, settings=self._demo_settings())
            self._demo_world = world
            return world.render()
        locator = create_locator()
        window = locator.find(self.config.general.window_titles)
        if window is None:
            self.bus.warn("게임 창을 찾지 못해 화면을 가져올 수 없습니다.")
            return None
        if self._preview_capture is None:
            from ..capture import ScreenCapture

            self._preview_capture = ScreenCapture()
        try:
            return self._preview_capture.grab(window.rect).image
        except Exception as exc:
            self.bus.error(f"화면 캡처 실패: {exc}")
            return None

    def _capture_arrow_set(self) -> None:
        """화살표 한 방향만 캡처해서 4방향 템플릿을 모두 만든다."""
        from PySide6.QtWidgets import QInputDialog

        from ..vision.matcher import rotate_to_direction

        frame = self._current_frame()
        if frame is None:
            return
        dialog = RegionSelectDialog(
            frame,
            "화살표 캡처 (1장)",
            "룬 해제 화면의 화살표 <b>하나</b>만 테두리에 맞게 드래그하세요. "
            "어느 방향인지는 다음 단계에서 고릅니다.",
            self,
        )
        if not dialog.exec():
            return
        crop = dialog.cropped()
        if crop is None or crop.size == 0:
            QMessageBox.information(self, "영역 없음", "선택된 영역이 없습니다.")
            return

        options = [ARROW_NAMES[d] for d in ("UP", "DOWN", "LEFT", "RIGHT")]
        choice, ok = QInputDialog.getItem(
            self, "방향 선택", "지금 캡처한 화살표의 방향은?", options, 0, False
        )
        if not ok:
            return
        source = next(d for d, name in ARROW_NAMES.items() if name == choice)

        target_dir = (
            Path(self.config.rune.template_dir)
            if self.config.rune.template_dir
            else DEFAULT_TEMPLATE_DIR
        )
        for direction in ("UP", "DOWN", "LEFT", "RIGHT"):
            image = rotate_to_direction(crop, source, direction)
            filename = f"arrow_{direction.lower()}.png"
            save_png(image, target_dir / filename)
            self.config.rune.arrow_templates[direction] = filename
            self.template_labels[direction].setText(
                f"{filename}  ({image.shape[1]}x{image.shape[0]})"
            )
        clear_cache()
        self.bus.ok(
            f"화살표 4방향 템플릿 생성 완료 ({choice} 기준, {crop.shape[1]}x{crop.shape[0]}) → {target_dir}"
        )
        self.bus.info("‘화살표 판독 테스트’ 로 방향별 점수를 확인해 보세요.")

    def _capture_template(self, slot: str) -> None:
        frame = self._current_frame()
        if frame is None:
            return
        if slot == "banner":
            label = "상단 안내 문구"
        elif slot == "rune":
            label = "룬"
        else:
            label = f"화살표 {ARROW_NAMES.get(slot, slot)}"
        dialog = RegionSelectDialog(
            frame,
            f"{label} 템플릿 캡처",
            f"{label} 부분만 드래그해서 선택하세요. 배경이 적게 포함될수록 인식이 정확합니다.",
            self,
        )
        if not dialog.exec():
            return
        crop = dialog.cropped()
        if crop is None:
            QMessageBox.information(self, "영역 없음", "선택된 영역이 없습니다.")
            return
        filename = {
            "rune": "rune.png",
            "banner": "rune_banner.png",
        }.get(slot, f"arrow_{slot.lower()}.png")
        target_dir = (
            Path(self.config.rune.template_dir)
            if self.config.rune.template_dir
            else DEFAULT_TEMPLATE_DIR
        )
        path = target_dir / filename
        save_png(crop, path)
        clear_cache()
        if slot == "rune":
            self.config.rune.rune_templates = [filename]
        elif slot == "banner":
            self.config.rune.banner_template = filename
            self.use_banner.setChecked(True)
        else:
            self.config.rune.arrow_templates[slot] = filename
        self.template_labels[slot].setText(f"{filename}  ({crop.shape[1]}x{crop.shape[0]})")
        self.bus.ok(f"{label} 템플릿 저장: {path}")

    def _pick_roi(self, title: str, hint: str) -> Roi | None:
        frame = self._current_frame()
        if frame is None:
            return None
        dialog = RegionSelectDialog(frame, title, hint, self)
        if not dialog.exec():
            return None
        rect = dialog.normalized_rect()
        if rect is None:
            return None
        return Roi(*rect)

    def _pick_rune_roi(self) -> None:
        roi = self._pick_roi("룬 탐색 영역", "룬이 나타날 수 있는 범위를 드래그하세요 (보통 화면 대부분).")
        if roi is None:
            return
        self.config.rune.rune_roi = roi
        self.rune_roi_label.setText(roi.describe())
        self.bus.info(f"룬 탐색 영역 설정: {roi.describe()}")

    def _pick_arrow_roi(self) -> None:
        roi = self._pick_roi(
            "화살표 탐색 영역", "룬 해제 시 방향 화살표가 나타나는 영역(화면 상단 중앙)을 드래그하세요."
        )
        if roi is None:
            return
        self.config.rune.arrow_roi = roi
        self.arrow_roi_label.setText(roi.describe())
        self.bus.info(f"화살표 탐색 영역 설정: {roi.describe()}")

    def _reset_roi(self, index: int) -> None:
        if index == 0:
            self.config.rune.rune_roi = Roi()
            self.rune_roi_label.setText(self.config.rune.rune_roi.describe())
        else:
            self.config.rune.arrow_roi = Roi()
            self.arrow_roi_label.setText(self.config.rune.arrow_roi.describe())

    def _vision_for_test(self) -> RuneVision:
        vision = RuneVision(self.config)
        ready, _ = vision.templates_ready()
        if not ready and self.demo_check.isChecked():
            from ..vision.matcher import template_from_array
            from ..vision.synth import demo_templates

            for name, image in demo_templates().items():
                vision.register_template(name, template_from_array(image, name))
        return vision

    def _test_rune(self) -> None:
        self.collect()
        frame = self._current_frame()
        if frame is None:
            return
        vision = self._vision_for_test()
        ready, missing = vision.templates_ready()
        if not ready and not self.demo_check.isChecked():
            self.bus.warn("템플릿이 없습니다: " + ", ".join(Path(m).name for m in missing))
            return
        import time

        t0 = time.perf_counter()
        match = vision.detect_rune(frame)
        ms = (time.perf_counter() - t0) * 1000
        if match is None:
            self.bus.warn(f"룬을 찾지 못했습니다 (임계값 {self.config.rune.rune_threshold:.2f}, {ms:.1f}ms)")
        else:
            self.bus.ok(f"룬 감지 성공 — 점수 {match.score:.3f}, 위치 {match.center}, {ms:.1f}ms")

    def _pick_minimap_roi(self) -> None:
        roi = self._pick_roi(
            "미니맵 영역",
            "미니맵 전체를 드래그해서 선택하세요. 표식(보라·노랑)이 모두 들어가야 합니다.",
        )
        if roi is None:
            return
        self.config.rune.minimap.roi = roi
        self.mm_roi_label.setText(roi.describe())
        self.bus.info(f"미니맵 영역 설정: {roi.describe()}")

    def _sample_minimap_color(self, target: str) -> None:
        import cv2

        from ..vision.minimap import MinimapVision

        frame = self._current_frame()
        if frame is None:
            return
        label = "룬(보라색)" if target == "rune" else "캐릭터(노란색)"

        # 미니맵 표식은 2~4픽셀이라 원본 화면에서는 드래그가 거의 불가능하다.
        # 지정된 미니맵 영역만 잘라 확대해서 보여준다 (색이 변하지 않는 최근접 확대).
        mm = self.config.rune.minimap
        height, width = frame.shape[:2]
        x, y, w, h = mm.roi.to_pixels(width, height)
        if w * h > width * height * 0.25:
            self.bus.warn(
                "미니맵 영역이 너무 넓습니다 — 먼저 ‘영역 지정’ 으로 미니맵만 지정하면 색 추출이 쉬워집니다."
            )
        crop_area = frame[y : y + h, x : x + w]
        zoom = max(1, min(16, int(min(1000 / max(1, w), 700 / max(1, h)))))
        view = (
            cv2.resize(crop_area, (w * zoom, h * zoom), interpolation=cv2.INTER_NEAREST)
            if zoom > 1
            else crop_area
        )

        dialog = RegionSelectDialog(
            view,
            f"{label} 표식 색 추출 — {zoom}배 확대",
            f"확대된 미니맵입니다. <b>{label} 표식</b>만 작게 드래그하세요.<br>"
            "표식 색만 담기게 잡을수록 정확합니다. 배경이 많이 섞이면 인식이 어긋납니다.",
            self,
        )
        if not dialog.exec():
            return
        crop = dialog.cropped()
        if crop is None or crop.size == 0:
            QMessageBox.information(self, "영역 없음", "선택된 영역이 없습니다.")
            return
        spec = MinimapVision.sample_color(crop)
        other = (
            self.config.rune.minimap.char_color
            if target == "rune"
            else self.config.rune.minimap.rune_color
        )
        if target == "rune":
            self.config.rune.minimap.rune_color = spec
            self.mm_rune_color_label.setText(spec.describe())
        else:
            self.config.rune.minimap.char_color = spec
            self.mm_char_color_label.setText(spec.describe())
        self.bus.ok(f"{label} 색 범위 설정: {spec.describe()}")

        # 방금 정한 색으로 실제 표식이 잡히는지 바로 알려준다
        reading = MinimapVision(self.config).read(frame)
        found = reading.rune if target == "rune" else reading.char
        if found is not None:
            self.bus.ok(f"{label} 표식 인식 확인 — 미니맵 좌표 {found.center}, 크기 {found.area}px")
        else:
            self.bus.warn(
                f"{label} 표식을 찾지 못했습니다 — 표식만 더 정확히 드래그해서 다시 추출해 주세요."
            )

        if MinimapVision.ranges_overlap(spec, other):
            message = (
                "룬 색과 캐릭터 색 범위가 겹칩니다.\n\n"
                "이 상태면 같은 표식을 둘 다로 인식해서 좌우 차이(dx)가 항상 0 으로 나오고,\n"
                "정렬된 것으로 착각해 룬 해제가 실패합니다.\n\n"
                f"룬: {self.config.rune.minimap.rune_color.describe()}\n"
                f"캐릭터: {self.config.rune.minimap.char_color.describe()}\n\n"
                "각 표식의 색만 담기도록 더 작게 드래그해서 다시 추출해 주세요."
            )
            self.bus.error("룬 색과 캐릭터 색 범위가 겹칩니다 — 각각 다시 추출하세요.")
            QMessageBox.warning(self, "색 범위가 겹칩니다", message)

    def _test_minimap(self) -> None:
        from ..vision.minimap import MinimapVision

        self.collect()
        frame = self._current_frame()
        if frame is None:
            return
        import time

        vision = MinimapVision(self.config)
        t0 = time.perf_counter()
        reading = vision.read(frame)
        ms = (time.perf_counter() - t0) * 1000

        if reading.ambiguous:
            self.bus.error(f"미니맵 인식 오류 — {reading.describe()} ({ms:.1f}ms)")
            self.bus.error("룬 색과 캐릭터 색을 각각 다시 추출해야 합니다.")
        elif reading.found:
            self.bus.ok(f"미니맵 인식 성공 — {reading.describe()} ({ms:.1f}ms)")
            tol = max(0.5, float(self.config.rune.minimap.align_tolerance))
            if abs(reading.dx or 0) <= tol:
                self.bus.info("현재 캐릭터가 룬과 좌우로 정렬된 상태입니다.")
        else:
            self.bus.warn(f"{reading.describe()} ({ms:.1f}ms) — 미니맵 영역과 색 설정을 확인하세요.")

        # 매크로가 실제로 무엇을 보고 있는지 그림으로 남긴다
        try:
            path = LOG_DIR / "minimap_debug.png"
            save_png(vision.debug_image(frame), path)
            self.bus.info(f"미니맵 진단 이미지 저장: {path} (빨강=룬, 초록=캐릭터)")
        except Exception as exc:
            self.bus.warn(f"진단 이미지 저장 실패: {exc}")

    def _test_arrows(self) -> None:
        self.collect()
        frame = self._current_frame()
        if frame is None:
            return
        vision = self._vision_for_test()
        import time

        t0 = time.perf_counter()
        reading = vision.read_arrows(frame)
        ms = (time.perf_counter() - t0) * 1000
        if reading.ok:
            self.bus.ok(f"화살표 판독: {reading.describe()}  ({ms:.1f}ms)")
        else:
            self.bus.warn(f"판독 실패: {reading.reason} — 인식 {reading.count}개 ({ms:.1f}ms)")
        self.bus.info(
            f"방향별 최고 점수: {reading.describe_scores()} "
            f"(임계값 {self.config.rune.arrow_threshold:.2f})"
        )

    def _run_diagnostics(self) -> None:
        """설정 실수 + 현재 화면의 각 단계를 한 번에 점검해 로그로 출력한다."""
        from ..diagnostics import diagnose_frame, save_failure_snapshot
        from ..vision.minimap import MinimapVision

        self.collect()
        frame = self._current_frame()
        vision = self._vision_for_test()
        minimap = MinimapVision(self.config)

        self.bus.info("───── 룬 해제 진단 시작 ─────")
        issues = diagnose_frame(self.config, frame, vision, minimap)
        for issue in issues:
            self.bus.log(issue.formatted(), issue.level)

        problems = [i for i in issues if i.level in ("warn", "error")]
        if problems:
            self.bus.warn(f"진단 결과: 확인이 필요한 항목 {len(problems)}개 (위 ✖/▲ 줄)")
        else:
            self.bus.ok("진단 결과: 설정에서 발견된 문제 없음")

        if frame is not None:
            try:
                saved = save_failure_snapshot(frame, self.config, prefix="diagnose", minimap=minimap)
                if saved:
                    self.bus.info("진단 화면 저장: " + ", ".join(str(p) for p in saved))
            except Exception as exc:
                self.bus.warn(f"진단 화면 저장 실패: {exc}")
        self.bus.info("───── 룬 해제 진단 끝 ─────")

    def _save_screenshot(self) -> None:
        frame = self._current_frame()
        if frame is None:
            return
        import time

        path = LOG_DIR / f"screen_{int(time.time())}.png"
        save_png(frame, path)
        self.bus.info(f"현재 화면 저장: {path}")

    # ------------------------------------------------------------------
    # 프로필
    # ------------------------------------------------------------------
    def _save_profile(self) -> None:
        self.collect()
        path = self.config.save(DEFAULT_PROFILE_PATH)
        self.bus.ok(f"설정 저장 완료: {path}")

    def _save_profile_as(self) -> None:
        self.collect()
        name, _ = QFileDialog.getSaveFileName(
            self, "설정 저장", str(DEFAULT_PROFILE_PATH.parent / "profile.json"), "JSON (*.json)"
        )
        if not name:
            return
        self.config.save(name)
        self.bus.ok(f"설정 저장 완료: {name}")

    def _load_profile(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "설정 불러오기", str(DEFAULT_PROFILE_PATH.parent), "JSON (*.json)"
        )
        if not name:
            return
        loaded = AppConfig.load(name)
        self.config.general = loaded.general
        self.config.keys = loaded.keys
        self.config.attack = loaded.attack
        self.config.rune = loaded.rune
        self._rebuild_skill_rows()
        self.refresh_from_config()
        self.bus.ok(f"설정 불러오기 완료: {name}")

    def _rebuild_skill_rows(self) -> None:
        self.hunt_row.skill = self.config.attack.hunt
        self.boss_row.skill = self.config.attack.boss
        for row, buff in zip(self.buff_rows, self.config.attack.buffs):
            row.skill = buff

    # ------------------------------------------------------------------
    # 주기적 갱신
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        for event in self.bus.drain():
            self.log.append_event(event)

        engine = self.engine
        if engine is None:
            return
        status = engine.status()
        self.state_label.setText(status.state.value)
        running = engine.running
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

        if status.state is EngineState.RUNE:
            self.status_card.update_status("룬 해제 진행 중", "스킬 입력 중단 — 룬에 집중")
        elif status.window != "미발견":
            title = "프로세스 발견됨!" if running else "게임 창 확인"
            self.status_card.update_status(title, status.window)
        else:
            self.status_card.update_status("게임 창 탐색 중…", "창 제목 검색어를 확인하세요")

        s = status.stats
        presses = ", ".join(f"{k} {v}회" for k, v in s.presses.items()) or "없음"
        self.stats_label.setText(
            "<table cellpadding='3'>"
            f"<tr><td>상태</td><td><b>{status.state.value}</b></td>"
            f"<td>가동 시간</td><td><b>{s.uptime:.0f}초</b></td></tr>"
            f"<tr><td>제어 루프</td><td><b>{s.loops:,}회</b></td>"
            f"<td>루프 지연(평균/최대)</td><td><b>{s.jitter_ms_avg:.2f} / {s.jitter_ms_max:.2f} ms</b></td></tr>"
            f"<tr><td>룬 탐색</td><td><b>{s.detections:,}회</b></td>"
            f"<td>감지 시간(평균/최대)</td><td><b>{s.detect_ms_avg:.2f} / {s.detect_ms_max:.2f} ms</b></td></tr>"
            f"<tr><td>화면 캡처</td><td><b>{s.capture_count:,}회</b></td>"
            f"<td>캡처 평균</td><td><b>{s.capture_ms_avg:.2f} ms</b></td></tr>"
            f"<tr><td>룬 해제</td><td><b>{s.rune_success} / {s.rune_attempts}</b></td>"
            f"<td>최근 결과</td><td><b>{s.rune_last}</b></td></tr>"
            f"<tr><td>키 입력</td><td colspan='3'><b>{presses}</b></td></tr>"
            "</table>"
        )

    # ------------------------------------------------------------------
    def _rebind_hotkeys(self) -> None:
        self.hotkeys.stop()
        self.hotkeys.clear()
        start = str(self.start_hotkey.currentData())
        stop = str(self.stop_hotkey.currentData())
        self.hotkeys.bind(start, self.hotkey_start.emit)
        self.hotkeys.bind(stop, self.hotkey_stop.emit)
        self.hotkeys.start()

    def _announce(self) -> None:
        self.bus.info("룬 헌터 준비 완료.")
        if IS_WINDOWS:
            if is_admin():
                self.bus.ok("관리자 권한으로 실행 중 — 게임으로 키 입력이 전달됩니다.")
            else:
                self.bus.warn(
                    "관리자 권한이 아닙니다. 게임이 관리자 권한이면 키 입력이 무시될 수 있습니다."
                )
        else:
            self.bus.warn(
                f"{__import__('sys').platform} 환경입니다 — 실제 키 입력은 Windows 에서만 동작합니다. "
                "데모 모드로 로직을 확인하세요."
            )

    def closeEvent(self, event) -> None:
        try:
            self.stop_engine()
            self.hotkeys.stop()
        finally:
            super().closeEvent(event)
