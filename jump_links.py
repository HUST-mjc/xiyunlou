# -*- coding: utf-8 -*-
"""跳转功能（PyQt6 版）"""

import os
import shutil
import subprocess
import webbrowser

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QComboBox, QDialogButtonBox, QLabel,
)
from PyQt6.QtCore import Qt


BILI_HOME = "https://www.bilibili.com"
NETEASE_HOME = "https://music.163.com"
NETEASE_EXE_CANDIDATES = [
    r"C:\Program Files (x86)\Netease\CloudMusic\cloudmusic.exe",
    r"C:\Program Files\Netease\CloudMusic\cloudmusic.exe",
]


class UrlJumpDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义跳转")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(440, 200)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("例如：https://www.example.com")
        form.addRow("网址：", self.url_edit)

        self.history_combo = QComboBox()
        self.history_combo.addItem("-- 选择历史记录 --")
        for url in cfg.get("url_history", []):
            self.history_combo.addItem(url)
        self.history_combo.currentIndexChanged.connect(self._on_history_selected)
        form.addRow("历史记录：", self.history_combo)

        layout.addLayout(form)
        tip = QLabel("提示：不带 http(s):// 时会自动补全为 https://")
        tip.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(tip)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_history_selected(self, idx):
        if idx > 0:
            self.url_edit.setText(self.history_combo.currentText())

    def get_url(self):
        return self.url_edit.text().strip()


class JumpHelper:
    def __init__(self, cfg, save_config_fn, play_voice_fn=None):
        self.cfg = cfg
        self.save_config = save_config_fn
        self.play_voice = play_voice_fn

    def _voice(self):
        if self.play_voice:
            try:
                self.play_voice()
            except Exception:
                pass

    def open_url(self, url):
        self._voice()
        try:
            os.startfile(url)
        except Exception:
            try:
                webbrowser.open(url)
            except Exception as e:
                print(f"[跳转] 打开失败：{url} -> {e}")

    def open_bili(self):
        self.open_url(BILI_HOME)

    def open_live_room(self, room_id):
        self.open_url(f"https://live.bilibili.com/{room_id}")

    def open_dynamic_page(self, uid):
        self.open_url(f"https://space.bilibili.com/{uid}/dynamic")

    def open_netease(self):
        self._voice()
        for p in NETEASE_EXE_CANDIDATES:
            if os.path.exists(p):
                try:
                    subprocess.Popen([p])
                    return
                except Exception:
                    pass
        exe = shutil.which("cloudmusic")
        if exe:
            try:
                subprocess.Popen([exe])
                return
            except Exception:
                pass
        try:
            os.startfile(NETEASE_HOME)
        except Exception:
            webbrowser.open(NETEASE_HOME)

    def open_custom(self, parent=None):
        dlg = UrlJumpDialog(self.cfg, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        url = dlg.get_url()
        if not url:
            return False
        if not url.startswith(("http://", "https://", "ftp://", "file://")):
            url = "https://" + url
        history = self.cfg.get("url_history", [])
        if url in history:
            history.remove(url)
        history.insert(0, url)
        self.cfg["url_history"] = history[:10]
        try:
            self.save_config(self.cfg)
        except Exception:
            pass
        self.open_url(url)
        return True