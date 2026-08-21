"""공용 위젯 (키 선택, 스킬 행, 로그 뷰, 상태 카드)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import SkillConfig
from ..keys import SELECTABLE_KEYS, display_name
from ..logging_bus import LogEvent
from .theme import LEVEL_COLORS


class KeySelect(QComboBox):
    """스킬/버프에 쓸 키를 고르는 콤보박스."""

    def __init__(self, current: str = "A", choices=SELECTABLE_KEYS, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(150)
        for name in choices:
            self.addItem(display_name(name), userData=name)
        self.select(current)

    def select(self, key: str) -> None:
        index = self.findData(key.upper())
        if index >= 0:
            self.setCurrentIndex(index)

    def key(self) -> str:
        return str(self.currentData())


class SkillRow(QWidget):
    """[체크박스] 라벨 | 입력 키 [선택] | 주기 [숫자] 초  형태의 한 줄."""

    def __init__(
        self,
        skill: SkillConfig,
        show_interval: bool = True,
        interval_suffix: str = " 초",
        interval_min: float = 0.03,
        interval_max: float = 3600.0,
        interval_step: float = 0.5,
        interval_decimals: int = 2,
        on_change: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.skill = skill
        self._on_change = on_change

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        self.enabled = QCheckBox(skill.label)
        self.enabled.setChecked(skill.enabled)
        self.enabled.setMinimumWidth(90)
        layout.addWidget(self.enabled)
        layout.addStretch(1)

        layout.addWidget(QLabel("입력 키"))
        self.key = KeySelect(skill.key)
        layout.addWidget(self.key)

        self.interval: QDoubleSpinBox | None = None
        if show_interval:
            layout.addSpacing(8)
            layout.addWidget(QLabel("주기"))
            spin = QDoubleSpinBox()
            spin.setDecimals(interval_decimals)
            spin.setRange(interval_min, interval_max)
            spin.setSingleStep(interval_step)
            spin.setSuffix(interval_suffix)
            spin.setValue(skill.interval)
            spin.setMinimumWidth(110)
            self.interval = spin
            layout.addWidget(spin)

        for widget in (self.enabled, self.key, self.interval):
            if widget is None:
                continue
            signal = getattr(widget, "toggled", None) or getattr(widget, "currentIndexChanged", None)
            if signal is None:
                signal = getattr(widget, "valueChanged")
            signal.connect(self._changed)

        self.setObjectName("card")
        self.setProperty("class", "row")

    def _changed(self, *_args) -> None:
        self.apply()
        if self._on_change is not None:
            self._on_change()

    def apply(self) -> None:
        """화면 값을 설정 객체에 반영."""
        self.skill.enabled = self.enabled.isChecked()
        self.skill.key = self.key.key()
        if self.interval is not None:
            self.skill.interval = float(self.interval.value())

    def refresh(self) -> None:
        self.enabled.setChecked(self.skill.enabled)
        self.key.select(self.skill.key)
        if self.interval is not None:
            self.interval.setValue(self.skill.interval)


class LogView(QPlainTextEdit):
    def __init__(self, limit: int = 500, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(limit)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def append_event(self, event: LogEvent) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(Qt.white)
        color = LEVEL_COLORS.get(event.level)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        if color:
            from PySide6.QtGui import QColor

            fmt.setForeground(QColor(color))
        cursor.insertText(event.formatted() + "\n", fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class StatusCard(QFrame):
    """예전 프로그램의 '프로세스 발견됨!' 카드와 같은 역할."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.title = QLabel("게임 창 탐색 중…")
        self.title.setObjectName("statusTitle")
        self.detail = QLabel("창 제목 검색어를 확인하세요")
        self.detail.setObjectName("statusDetail")
        layout.addWidget(self.title)
        layout.addWidget(self.detail)

    def update_status(self, title: str, detail: str) -> None:
        self.title.setText(title)
        self.detail.setText(detail)


def card(widget: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    return frame
