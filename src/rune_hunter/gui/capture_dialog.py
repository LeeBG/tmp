"""화면에서 영역을 드래그로 선택하는 대화상자.

용도 두 가지
1) 템플릿 만들기: 룬/화살표 부분만 잘라 PNG 로 저장
2) 탐색 영역(ROI) 지정: 룬·화살표를 찾을 범위를 좁혀 성능을 올린다
"""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

MAX_PREVIEW = 1100


def to_pixmap(image: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    qimage = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


class _Canvas(QWidget):
    def __init__(self, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.CrossCursor)
        self._start: QPoint | None = None
        self._end: QPoint | None = None

    @property
    def selection(self) -> QRect | None:
        if self._start is None or self._end is None:
            return None
        rect = QRect(self._start, self._end).normalized()
        if rect.width() < 4 or rect.height() < 4:
            return None
        return rect

    def mousePressEvent(self, event) -> None:
        self._start = event.position().toPoint()
        self._end = self._start
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        rect = self.selection
        if rect is not None:
            painter.setPen(QPen(Qt.magenta, 2, Qt.DashLine))
            painter.drawRect(rect)


class RegionSelectDialog(QDialog):
    """이미지에서 사각형 영역을 고른다. 결과는 원본 픽셀 좌표."""

    def __init__(self, image: np.ndarray, title: str, hint: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._image = image
        h, w = image.shape[:2]
        self._scale = min(1.0, MAX_PREVIEW / max(w, h))
        preview = image
        if self._scale < 1.0:
            preview = cv2.resize(
                image, (int(w * self._scale), int(h * self._scale)), interpolation=cv2.INTER_AREA
            )
        self._canvas = _Canvas(to_pixmap(preview))

        layout = QVBoxLayout(self)
        info = QLabel(hint)
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._canvas)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("선택 영역 사용")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_rect(self) -> tuple[int, int, int, int] | None:
        rect = self._canvas.selection
        if rect is None:
            return None
        s = 1.0 / self._scale
        return (
            int(rect.x() * s),
            int(rect.y() * s),
            int(rect.width() * s),
            int(rect.height() * s),
        )

    def cropped(self) -> np.ndarray | None:
        rect = self.selected_rect()
        if rect is None:
            return None
        x, y, w, h = rect
        h_img, w_img = self._image.shape[:2]
        x2, y2 = min(w_img, x + w), min(h_img, y + h)
        return self._image[y:y2, x:x2].copy()

    def normalized_rect(self) -> tuple[float, float, float, float] | None:
        rect = self.selected_rect()
        if rect is None:
            return None
        h, w = self._image.shape[:2]
        x, y, rw, rh = rect
        return (x / w, y / h, rw / w, rh / h)


def save_png(image: np.ndarray, path) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("PNG 인코딩에 실패했습니다.")
    p.write_bytes(buffer.tobytes())
