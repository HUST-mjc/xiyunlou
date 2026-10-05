# -*- coding: utf-8 -*-
"""圆环菜单：右键桌宠 → 围绕底图展开的圆形菜单
=========================================================
· 底图限制最大 400×400
· 弹出时先显示中心底图（only丸），短暂延迟后再显现周围按钮
=========================================================
"""
import os
import math

from PyQt6.QtWidgets import QWidget, QPushButton
from PyQt6.QtGui import QPainter, QPixmap, QColor
from PyQt6.QtCore import Qt, pyqtSignal, QTimer


class RingMenu(QWidget):
    """围绕底图展开的圆环菜单"""

    action_triggered = pyqtSignal(str)

    BTN_SIZE = 46
    RADIUS_EXTRA = 30
    BG_ALPHA = 210
    MAX_IMG_SIZE = 400
    BTN_DELAY_MS = 120

    def __init__(self, image_path, actions, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # ---------- 底图（限制最大 400×400） ----------
        pix = QPixmap(image_path) \
            if (image_path and os.path.exists(image_path)) else QPixmap()

        if pix.isNull():
            pix = QPixmap(180, 180)
            pix.fill(Qt.GlobalColor.transparent)
        elif (pix.width() > self.MAX_IMG_SIZE
              or pix.height() > self.MAX_IMG_SIZE):
            pix = pix.scaled(
                self.MAX_IMG_SIZE, self.MAX_IMG_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._pix = pix

        # ---------- 尺寸 & 半径 ----------
        img_w = max(self._pix.width(), 160)
        img_h = max(self._pix.height(), 160)
        self._radius = min(img_w, img_h) // 2 + self.RADIUS_EXTRA
        size = self._radius * 2 + self.BTN_SIZE
        self.setFixedSize(size, size)
        self._cx = size // 2
        self._cy = size // 2

        # ---------- 按钮 ----------
        self._buttons = []
        n = max(1, len(actions))
        for i, item in enumerate(actions):
            key = item[0]
            text = item[1] if len(item) > 1 else key
            tip = item[2] if len(item) > 2 else ""

            btn = QPushButton(text, self)
            btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton {"
                "  background: rgba(255,255,255,235);"
                "  border: 2px solid #7aa8d8;"
                "  border-radius: 23px;"
                "  font-size: 18px;"
                "  color: #2b4a80;"
                "}"
                "QPushButton:hover {"
                "  background: #d9ecff;"
                "  border-color: #4a8ad4;"
                "}"
                "QPushButton:pressed {"
                "  background: #a8ccee;"
                "}"
            )

            angle = -math.pi / 2 + i * (2 * math.pi / n)
            bx = int(self._cx + math.cos(angle) * self._radius
                     - self.BTN_SIZE / 2)
            by = int(self._cy + math.sin(angle) * self._radius
                     - self.BTN_SIZE / 2)
            btn.move(bx, by)
            btn.clicked.connect(lambda _, k=key: self._emit(k))
            btn.hide()
            self._buttons.append(btn)

        self._btns_visible = False

        self._show_btn_timer = QTimer(self)
        self._show_btn_timer.setSingleShot(True)
        self._show_btn_timer.timeout.connect(self._reveal_buttons)

    def _emit(self, key):
        self.action_triggered.emit(key)
        self.close()

    def popup_at(self, global_x, global_y):
        self.move(global_x - self._cx, global_y - self._cy)
        self.show()
        self.raise_()
        self.activateWindow()
        self._show_btn_timer.start(self.BTN_DELAY_MS)

    def _reveal_buttons(self):
        self._btns_visible = True
        for btn in self._buttons:
            btn.show()
            btn.raise_()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if self._btns_visible:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, self.BG_ALPHA))
            p.drawEllipse(
                self._cx - self._radius,
                self._cy - self._radius,
                self._radius * 2,
                self._radius * 2,
            )

        if not self._pix.isNull():
            px = self._cx - self._pix.width() // 2
            py = self._cy - self._pix.height() // 2
            p.drawPixmap(px, py, self._pix)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            self._show_btn_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)