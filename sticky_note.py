# -*- coding: utf-8 -*-
"""便利贴（PyQt6 版）—— 集成 floral-notepaper 功能"""

import os

from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QTextEdit, QMessageBox,
    QApplication, QDialog, QVBoxLayout, QListWidget,
    QListWidgetItem, QDialogButtonBox, QTextBrowser, QMenu,
    QFileDialog,
)
from PyQt6.QtGui import QPixmap, QPainter, QKeySequence, QColor, QShortcut
from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF

try:
    import markdown2
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


NOTE_BG_SCALE = 0.25
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
EDITOR_BOX_COLOR = QColor(255, 255, 255, 170)
EDITOR_BOX_RADIUS = 8

# 编辑区起点占窗口高度的比例（越小编辑区越大）
EDITOR_TOP_RATIO = 0.42


def _project_root():
    return os.path.dirname(os.path.abspath(__file__))


def note_dir_abs():
    return os.path.join(_project_root(), "note")


def list_note_bg_files():
    folder = note_dir_abs()
    if not os.path.isdir(folder):
        return []
    return sorted(
        n for n in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, n))
        and os.path.splitext(n)[1].lower() in IMAGE_EXTS
    )


def find_note_bg(filename):
    if not filename:
        return None
    folder = note_dir_abs()
    full = os.path.join(folder, filename)
    if os.path.isfile(full):
        return full
    if os.path.isdir(folder):
        low = filename.lower()
        for name in os.listdir(folder):
            if name.lower() == low:
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    return p
    return None


def load_scaled_bg(filename):
    full = find_note_bg(filename)
    if not full:
        return None
    pix = QPixmap(full)
    if pix.isNull():
        return None
    w = max(1, int(pix.width() * NOTE_BG_SCALE))
    h = max(1, int(pix.height() * NOTE_BG_SCALE))
    return pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


class NoteBgPickerDialog(QDialog):
    def __init__(self, current_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择便利贴底图")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(360, 420)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        names = list_note_bg_files()
        if not names:
            item = QListWidgetItem("(note 里没有图片)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        else:
            for name in names:
                self.list.addItem(name)
            idx = self.list.findItems(
                current_name, Qt.MatchFlag.MatchExactly)
            if idx:
                self.list.setCurrentItem(idx[0])
            else:
                self.list.setCurrentRow(0)

        self.list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_name(self):
        item = self.list.currentItem()
        if item is None:
            return ""
        if not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return ""
        return item.text()


class StickyNote(QWidget):
    MIN_FONT = 10
    MAX_FONT = 24

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._dragging = False
        self._drag_pos = QPoint()
        self._font_size = cfg.get("sticky_font_size", 14)
        self._bg_filename = cfg.get("note_bg_file", "")
        self._bg_pix = QPixmap()
        self._pinned = cfg.get("sticky_pinned", False)
        self._preview_visible = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("便利贴")

        self._apply_background(self._bg_filename)
        self._layout_widgets()

        QShortcut(QKeySequence("Esc"), self,
                  activated=self._on_close)
        QShortcut(QKeySequence("Ctrl+S"), self,
                  activated=self._save_explicit)
        QShortcut(QKeySequence("Ctrl+L"), self,
                  activated=self._on_clear)
        QShortcut(QKeySequence("Ctrl+P"), self,
                  activated=self._toggle_preview)

        saved_pos = cfg.get("sticky_pos")
        if saved_pos and isinstance(saved_pos, list) \
                and len(saved_pos) == 2:
            self.move(saved_pos[0], saved_pos[1])

    # ------------------------------------------------------
    #  背景
    # ------------------------------------------------------
    def _apply_background(self, filename):
        files = list_note_bg_files()
        pix = load_scaled_bg(filename) if filename else None
        if pix is None and files:
            filename = files[0]
            pix = load_scaled_bg(filename)
        if pix is None:
            pix = QPixmap(320, 448)
            pix.fill(Qt.GlobalColor.yellow)
            filename = ""
        self._bg_filename = filename
        self._bg_pix = pix
        self.cfg["note_bg_file"] = filename
        self.setFixedSize(pix.width(), pix.height())

    def set_background(self, filename, persist=True):
        self._apply_background(filename)
        if persist:
            self.cfg["note_bg_file"] = self._bg_filename
            self._save_config_safe()
        self._layout_widgets()
        self.update()

    def current_background(self):
        return self._bg_filename

    # ------------------------------------------------------
    #  布局
    # ------------------------------------------------------
    def _layout_widgets(self):
        w, h = self.width(), self.height()

        close_size = 26
        if getattr(self, "close_btn", None) is None:
            self.close_btn = QPushButton("×", self)
            self.close_btn.setStyleSheet(
                "QPushButton { background: transparent;"
                " border: none;"
                "  font-size: 20px; font-weight: bold;"
                " color: #cc7a7a; }"
                "QPushButton:hover { color: #e04040; }"
            )
            self.close_btn.clicked.connect(self._on_close)
        self.close_btn.setGeometry(
            w - close_size - int(w * 0.06), int(h * 0.025),
            close_size, close_size
        )

        margin_x = int(w * 0.13)
        # 编辑区顶部上移，编辑区变大
        edit_top = int(h * EDITOR_TOP_RATIO)
        status_h = 20
        toolbar_h = 34
        bottom_pad = int(h * 0.04)
        edit_h = h - edit_top - bottom_pad - status_h - toolbar_h - 8

        self._editor_rect = QRectF(
            margin_x - 6, edit_top - 6,
            (w - 2 * margin_x) + 12, edit_h + 12
        )

        # 编辑器
        if getattr(self, "editor", None) is None:
            self.editor = QTextEdit(self)
            self.editor.setPlaceholderText(
                "在这里输入要记住的事情...\n"
                "支持 Markdown 语法，Ctrl+P 切换预览")
            self.editor.setText(self.cfg.get("sticky_note", ""))
            self.editor.textChanged.connect(self._on_text_changed)
            self.editor.viewport().setAutoFillBackground(False)

        self.editor.setGeometry(
            margin_x, edit_top, w - 2 * margin_x, edit_h)
        self._refresh_editor_style()

        # Markdown 预览浏览器
        if getattr(self, "preview_browser", None) is None:
            self.preview_browser = QTextBrowser(self)
            self.preview_browser.setStyleSheet(
                "QTextBrowser { background: transparent;"
                " border: none; }"
            )
            self.preview_browser.setOpenExternalLinks(True)
            self.preview_browser.hide()

        self.preview_browser.setGeometry(
            margin_x, edit_top, w - 2 * margin_x, edit_h)

        # 状态栏
        status_y = edit_top + edit_h + 2
        if getattr(self, "status_label", None) is None:
            self.status_label = QLabel(self)
            self.status_label.setAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )
        self.status_label.setGeometry(
            margin_x, status_y, w - 2 * margin_x, status_h
        )
        self._update_status()

        # 工具栏
        toolbar_y = status_y + status_h + 4
        inner_w = w - 2 * margin_x
        gap = 4
        btn_count = 8
        btn_w = max(30, (inner_w - gap * (btn_count - 1)) // btn_count)

        btn_style = (
            "QPushButton { background: rgba(255,255,255,150);"
            "  border: 1px solid #d8b898; border-radius: 6px;"
            "  font-size: 11px; color: #6a4a2a; padding: 2px; }"
            "QPushButton:hover { background: rgba(255,255,255,230); }"
        )
        close_style = (
            "QPushButton { background: rgba(230,150,150,200);"
            "  border: 1px solid #a05050; border-radius: 6px;"
            "  font-size: 11px; color: white; padding: 2px; }"
        )
        change_style = (
            "QPushButton { background: rgba(200,225,255,210);"
            "  border: 1px solid #7aa0d0; border-radius: 6px;"
            "  font-size: 11px; color: #2b4a80; padding: 2px; }"
        )

        if getattr(self, "btn_change_bg", None) is None:
            self.btn_change_bg = QPushButton("换图", self)
            self.btn_preview = QPushButton("预览", self)
            self.btn_io = QPushButton("导入/导出", self)
            self.btn_pin = QPushButton("钉住", self)
            self.btn_clear = QPushButton("清空", self)
            self.btn_copy = QPushButton("复制", self)
            self.btn_minus = QPushButton("A-", self)
            self.btn_plus = QPushButton("A+", self)

            self.btn_change_bg.clicked.connect(self._on_change_bg)
            self.btn_preview.clicked.connect(self._toggle_preview)
            self.btn_io.clicked.connect(self._show_io_menu)
            self.btn_pin.clicked.connect(self._toggle_pin)
            self.btn_clear.clicked.connect(self._on_clear)
            self.btn_copy.clicked.connect(self._on_copy)
            self.btn_minus.clicked.connect(
                lambda: self._change_font(-1))
            self.btn_plus.clicked.connect(
                lambda: self._change_font(+1))

        buttons = [
            self.btn_change_bg, self.btn_preview, self.btn_io,
            self.btn_pin, self.btn_clear, self.btn_copy,
            self.btn_minus, self.btn_plus,
        ]
        for i, b in enumerate(buttons):
            b.setGeometry(
                margin_x + i * (btn_w + gap),
                toolbar_y, btn_w, toolbar_h
            )
            if b is self.btn_change_bg:
                b.setStyleSheet(change_style)
            else:
                b.setStyleSheet(btn_style)

        self.close_btn.setStyleSheet(close_style)

        self._apply_pin_state()

    def _refresh_editor_style(self):
        text_color = self.cfg.get("note_text_color", "#5A4A3A")
        self.editor.setStyleSheet(
            "QTextEdit { background: transparent; border: none;"
            f"  font-size: {self._font_size}px;"
            f"  color: {text_color}; }}"
        )

    # ------------------------------------------------------
    #  Markdown 预览
    # ------------------------------------------------------
    def _toggle_preview(self):
        if not HAS_MARKDOWN:
            QMessageBox.information(
                self, "提示",
                "需要安装 markdown2：\npip install markdown2")
            return

        if self._preview_visible:
            self._preview_visible = False
            self.preview_browser.hide()
            self.editor.show()
            self.btn_preview.setText("预览")
        else:
            md_text = self.editor.toPlainText()
            html = markdown2.markdown(
                md_text,
                extras=[
                    "fenced-code-blocks", "tables",
                    "strike", "task_list", "break-on-newline",
                ]
            )
            self.preview_browser.setHtml(self._wrap_html(html))
            self.editor.hide()
            self.preview_browser.show()
            self._preview_visible = True
            self.btn_preview.setText("编辑")

    def _wrap_html(self, html):
        text_color = self.cfg.get("note_text_color", "#5A4A3A")
        return f"""
        <style>
        body {{
            font-size: {self._font_size}px;
            color: {text_color};
            background: transparent;
            word-wrap: break-word;
            font-family: "Microsoft YaHei", sans-serif;
        }}
        code {{
            background: rgba(0,0,0,0.08);
            padding: 2px 4px;
            border-radius: 3px;
            font-family: Consolas, monospace;
        }}
        pre {{
            background: rgba(0,0,0,0.06);
            padding: 8px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        table {{ border-collapse: collapse; }}
        td, th {{
            border: 1px solid #ccc;
            padding: 4px 8px;
        }}
        blockquote {{
            border-left: 3px solid #d8b898;
            margin: 4px 0;
            padding-left: 8px;
            color: #8a7a6a;
        }}
        a {{ color: #4a7ab5; }}
        </style>
        {html}
        """

    # ------------------------------------------------------
    #  导入 / 导出 Markdown
    # ------------------------------------------------------
    def _show_io_menu(self):
        menu = QMenu(self)
        menu.addAction("导入 Markdown", self._import_md)
        menu.addAction("导出 Markdown", self._export_md)
        menu.exec(
            self.btn_io.mapToGlobal(
                self.btn_io.rect().bottomLeft()))

    def _export_md(self):
        text = self.editor.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "便利贴是空的")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出为 Markdown", "note.md",
            "Markdown 文件 (*.md)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.status_label.setText("已导出")
                QTimer.singleShot(1200, self._update_status)
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _import_md(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Markdown", "",
            "Markdown 文件 (*.md *.markdown *.txt)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        if self.editor.toPlainText().strip():
            reply = QMessageBox.question(
                self, "确认导入",
                "当前内容将被覆盖，确定继续吗？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.editor.setPlainText(content)

    # ------------------------------------------------------
    #  磁贴模式（钉住）
    # ------------------------------------------------------
    def _toggle_pin(self):
        self._pinned = not self._pinned
        self.cfg["sticky_pinned"] = self._pinned
        self._apply_pin_state()
        self._save_config_safe()

    def _apply_pin_state(self):
        if self._pinned:
            self.editor.setReadOnly(True)
            self.btn_change_bg.hide()
            self.btn_io.hide()
            self.btn_clear.hide()
            self.btn_minus.hide()
            self.btn_plus.hide()
            self.btn_copy.hide()
            self.btn_preview.hide()
            self.btn_pin.setText("编辑")
            if not self._preview_visible and HAS_MARKDOWN:
                self._toggle_preview()
        else:
            self.editor.setReadOnly(False)
            self.btn_change_bg.show()
            self.btn_io.show()
            self.btn_clear.show()
            self.btn_minus.show()
            self.btn_plus.show()
            self.btn_copy.show()
            self.btn_preview.show()
            self.btn_pin.setText("钉住")
            if self._preview_visible:
                self._toggle_preview()

    # ------------------------------------------------------
    #  状态栏 / 配置保存
    # ------------------------------------------------------
    def _update_status(self):
        text = self.editor.toPlainText()
        chars = len(text)
        lines = text.count("\n") + 1 if text else 0
        self.status_label.setText(f"{chars} 字 / {lines} 行")
        self.status_label.setStyleSheet(
            "color: #b08a6a; font-size: 11px;"
            " background: transparent;"
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing, True)

        if not self._bg_pix.isNull():
            painter.drawPixmap(0, 0, self._bg_pix)

        bg_color = QColor(
            self.cfg.get("note_bg_color", "#00FFFFFF"))
        if bg_color.isValid() and bg_color.alpha() > 0:
            painter.fillRect(self.rect(), bg_color)

        if getattr(self, "_editor_rect", None) is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(EDITOR_BOX_COLOR)
            painter.drawRoundedRect(
                self._editor_rect,
                EDITOR_BOX_RADIUS, EDITOR_BOX_RADIUS
            )

    def set_save_config(self, fn):
        self._save_config_fn = fn

    def _save_config_safe(self):
        saver = getattr(self, "_save_config_fn", None)
        if saver:
            try:
                saver(self.cfg)
            except Exception:
                pass

    def _on_text_changed(self):
        self.cfg["sticky_note"] = self.editor.toPlainText()
        self._save_config_safe()
        self._update_status()

    def _on_change_bg(self):
        dlg = NoteBgPickerDialog(self._bg_filename, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.selected_name()
        if not name or name == self._bg_filename:
            return
        self.set_background(name, persist=True)

    def _on_clear(self):
        if not self.editor.toPlainText():
            return
        reply = QMessageBox.question(
            self, "确认清空",
            "确定要清空便利贴内容吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.editor.clear()

    def _on_copy(self):
        text = self.editor.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "便利贴是空的")
            return
        QApplication.clipboard().setText(text)
        self.status_label.setText("已复制到剪贴板")
        QTimer.singleShot(1500, self._update_status)

    def _change_font(self, delta):
        new_size = self._font_size + delta
        if new_size < self.MIN_FONT or new_size > self.MAX_FONT:
            return
        self._font_size = new_size
        self.cfg["sticky_font_size"] = new_size
        self._refresh_editor_style()
        self._save_config_safe()

    def _save_explicit(self):
        self.cfg["sticky_note"] = self.editor.toPlainText()
        self.cfg["sticky_pos"] = [self.x(), self.y()]
        self._save_config_safe()
        self.status_label.setText("已保存")
        QTimer.singleShot(1200, self._update_status)

    def _on_close(self):
        self.cfg["sticky_pos"] = [self.x(), self.y()]
        self.cfg["sticky_note"] = self.editor.toPlainText()
        self._save_config_safe()
        self.hide()

    # ------------------------------------------------------
    #  拖拽
    # ------------------------------------------------------
    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and event.position().y()
                < int(self.height() * (EDITOR_TOP_RATIO - 0.02))):
            self._dragging = True
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() \
                & Qt.MouseButton.LeftButton:
            self.move(
                event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.cfg["sticky_pos"] = [self.x(), self.y()]
            self._save_config_safe()