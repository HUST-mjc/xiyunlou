# -*- coding: utf-8 -*-
"""
DD_Monitor 多平台直播监控播放器（WebView2 版）
================================================
· 支持 B站 / 抖音 / 虎牙 / 斗鱼 / 小红书 / YouTube 六大平台
· 支持关注直播间，开播时弹窗提醒
· 支持 15 种预设布局，滑动/滚轮切换布局
· 画面编号 + 一键聚焦切换
· 拖拽交换画面（纯鼠标事件，无 QDrag 阻塞）
· 支持画质切换、切片录制、缓存设置等 DD监控室功能
· 支持命令行 --room 预填直播间
· 每个画面独立左右声道调节
· 底栏「当前路数」随布局自动更新，「最大路数」可随时修改（增删窗口）
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QUrl, QMimeData
from PyQt6.QtGui import QAction, QColor, QFont, QPalette, QBrush, QCursor, QIntValidator
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QFrame, QSizePolicy,
    QComboBox, QDialog, QInputDialog, QMenu,
    QSystemTrayIcon, QStyle, QListWidget, QListWidgetItem,
    QMessageBox, QSplitter, QSlider, QSpinBox, QCheckBox,
    QFileDialog,
)

try:
    from qtwebview2 import QtWebView2Widget
    HAS_WEBVIEW2 = True
except ImportError:
    HAS_WEBVIEW2 = False
    print("[警告] 请先安装 qtwebview2: pip install qtwebview2")


# =========================================================================== #
#  常量
# =========================================================================== #
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
BILI_LIVE_API = "https://api.live.bilibili.com/room/v1/Room/get_info"
BILI_PLAY_API = "https://api.live.bilibili.com/room/v1/Room/playUrl"
BILIBILI_SESSDATA = ""
DOUYIN_ENTER_API = (
    "https://live.douyin.com/webcast/room/web/enter/"
    "?aid=6383&app_name=douyin_web&live_id=1&device_platform=web"
    "&language=zh-CN&cookie_enabled=true&browser_language=zh-CN"
    "&browser_platform=Win32&browser_name=Chrome&browser_version=131.0.0.0"
)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(APP_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
SLICE_MAX_MINUTES = 5

# 支持的平台定义
PLATFORMS = {
    "bilibili":    {"name": "B站",     "url": "https://live.bilibili.com/{id}"},
    "douyin":      {"name": "抖音",    "url": "https://live.douyin.com/{id}"},
    "huya":        {"name": "虎牙",    "url": "https://www.huya.com/{id}"},
    "douyu":       {"name": "斗鱼",    "url": "https://www.douyu.com/{id}"},
    "xiaohongshu": {"name": "小红书",  "url": "https://www.xiaohongshu.com/user/profile/{id}"},
    "youtube":     {"name": "YouTube", "url": "https://www.youtube.com/@{id}/live"},
}
PLATFORM_URL_PATTERNS = {
    "bilibili":    [r'live\.bilibili\.com/(?:blanc/)?(\d+)'],
    "douyin":      [r'live\.douyin\.com/(?:user/)?(\d+)'],
    "huya":        [r'huya\.com/(\d+)'],
    "douyu":       [r'douyu\.com/(\d+)'],
    "xiaohongshu": [r'xiaohongshu\.com/user/profile/([^/?]+)'],
    "youtube":     [r'youtube\.com/@([^/?]+)', r'youtube\.com/channel/([^/?]+)'],
}


def parse_room_url(raw: str, platform: str):
    """返回 (room_id, full_url)"""
    raw = raw.strip()
    for p in PLATFORM_URL_PATTERNS.get(platform, []):
        m = re.search(p, raw)
        if m:
            rid = m.group(1)
            return rid, PLATFORMS[platform]["url"].format(id=rid)
    if raw.startswith("http"):
        return raw, raw
    return raw, PLATFORMS[platform]["url"].format(id=raw)


def sanitize_filename(name: str, max_len: int = 60) -> str:
    if not name:
        return ""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    return re.sub(r'\s+', ' ', s).strip()[:max_len]


# =========================================================================== #
#  布局系统
# =========================================================================== #
LAYOUTS: dict[str, dict] = {}


def _reg(key, name, orient, family, cells, mirror="",
         row_stretch=None, col_stretch=None):
    tile_count = sum(1 for c in cells if c[4] in ("tile", "main"))
    LAYOUTS[key] = {
        "key": key, "name": name, "orientation": orient,
        "family": family, "cells": cells, "mirror": mirror,
        "row_stretch": row_stretch, "col_stretch": col_stretch,
        "_tile_count": tile_count,
    }


# ---------- 平分布局 ---------- #
_reg("split_1", "单画面", "h", "split",
     [(0, 0, 1, 1, "tile")], mirror="split_1")
_reg("split_2ud", "上下两分", "h", "split",
     [(0, 0, 1, 1, "tile"), (1, 0, 1, 1, "tile")], mirror="split_2lr")
_reg("split_2lr", "左右两分", "h", "split",
     [(0, 0, 1, 1, "tile"), (0, 1, 1, 1, "tile")], mirror="split_2ud")
_reg("split_4", "四分 2×2", "h", "split",
     [(r, c, 1, 1, "tile") for r in range(2) for c in range(2)],
     mirror="split_4")
_reg("split_6", "六分 2×3", "h", "split",
     [(r, c, 1, 1, "tile") for r in range(2) for c in range(3)],
     mirror="split_6")
_reg("split_9", "九分 3×3", "h", "split",
     [(r, c, 1, 1, "tile") for r in range(3) for c in range(3)],
     mirror="split_9")

# ---------- 大带小（横屏） ---------- #
_reg("bs_m2r", "主画面 + 2 小", "h", "big_small",
     [(0, 0, 2, 2, "main"),
      (0, 2, 1, 1, "tile"), (1, 2, 1, 1, "tile")],
     mirror="v_m2s")
_reg("bs_2lm", "2 小 + 主画面", "h", "big_small",
     [(0, 0, 1, 1, "tile"), (1, 0, 1, 1, "tile"),
      (0, 1, 2, 2, "main")],
     mirror="v_m2s")
_reg("bs_m3r", "主画面 + 3 小", "h", "big_small",
     [(0, 0, 3, 2, "main"),
      (0, 2, 1, 1, "tile"), (1, 2, 1, 1, "tile"), (2, 2, 1, 1, "tile")],
     mirror="v_m4s")
_reg("bs_m4r", "主画面 + 4 小", "h", "big_small",
     [(0, 0, 2, 2, "main"),
      (0, 2, 1, 1, "tile"), (0, 3, 1, 1, "tile"),
      (1, 2, 1, 1, "tile"), (1, 3, 1, 1, "tile")],
     mirror="v_m4s")
_reg("bs_tm2b", "上主画面 + 下 2 小", "h", "big_small",
     [(0, 0, 1, 2, "main"),
      (1, 0, 1, 1, "tile"), (1, 1, 1, 1, "tile")],
     mirror="v_m2s",
     row_stretch=[2, 1])
_reg("bs_m5around", "主画面 + 5 小环绕", "h", "big_small",
     [(0, 0, 1, 1, "tile"), (0, 1, 1, 1, "tile"), (0, 2, 1, 1, "tile"),
      (1, 0, 1, 1, "tile"), (1, 1, 1, 1, "main"), (1, 2, 1, 1, "tile"),
      (2, 1, 1, 1, "tile")],
     mirror="v_m6s",
     row_stretch=[1, 2, 1], col_stretch=[1, 2, 1])
_reg("bs_2m4s", "双主画面 + 4 小", "h", "big_small",
     [(0, 0, 1, 2, "main"), (0, 2, 1, 2, "main"),
      (1, 0, 1, 1, "tile"), (1, 1, 1, 1, "tile"),
      (1, 2, 1, 1, "tile"), (1, 3, 1, 1, "tile")],
     mirror="v_m6s",
     row_stretch=[2, 1])

# ---------- 竖屏布局 ---------- #
_reg("v_m2s", "主 + 2 小", "v", "v",
     [(0, 0, 1, 2, "main"),
      (1, 0, 1, 1, "tile"), (1, 1, 1, 1, "tile")],
     mirror="bs_m2r",
     row_stretch=[3, 1])
_reg("v_m4s", "主 + 4 小", "v", "v",
     [(0, 0, 1, 2, "main"),
      (1, 0, 1, 1, "tile"), (1, 1, 1, 1, "tile"),
      (2, 0, 1, 1, "tile"), (2, 1, 1, 1, "tile")],
     mirror="bs_m3r",
     row_stretch=[3, 1, 1])
_reg("v_m6s", "主 + 6 小", "v", "v",
     [(0, 0, 1, 3, "main"),
      (1, 0, 1, 1, "tile"), (1, 1, 1, 1, "tile"), (1, 2, 1, 1, "tile"),
      (2, 0, 1, 1, "tile"), (2, 1, 1, 1, "tile"), (2, 2, 1, 1, "tile")],
     mirror="bs_m5around",
     row_stretch=[3, 1, 1])


LAYOUT_KEYS = sorted(LAYOUTS.keys())

LAYOUT_NAV_ORDER = [
    "split_1",
    "split_2lr", "split_2ud",
    "split_4",
    "split_6",
    "split_9",
    "bs_m2r", "bs_2lm", "bs_m3r", "bs_m4r",
    "bs_tm2b", "bs_m5around", "bs_2m4s",
    "v_m2s", "v_m4s", "v_m6s",
]


class LayoutManager:
    """布局应用器"""

    def __init__(self, host: QWidget):
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(2)
        self._tiles = []
        self._current_key = ""
        self._empty_ph: Optional[QLabel] = None

    def register_tiles(self, tiles):
        self._tiles = tiles

    @property
    def current_key(self) -> str:
        return self._current_key

    def _clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 0)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 0)

    def _get_empty_placeholder(self) -> QLabel:
        if self._empty_ph is None:
            lbl = QLabel("空")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "background:#0d0d0d;color:#333;font-size:11px;")
        else:
            lbl = self._empty_ph
        self._empty_ph = lbl
        return lbl

    def apply(self, key: str):
        spec = LAYOUTS.get(key)
        if not spec:
            return
        self._clear()
        self._current_key = key

        tile_idx = 0
        used_tiles = []
        for (r, c, rs, cs, role) in spec["cells"]:
            if tile_idx < len(self._tiles):
                widget = self._tiles[tile_idx]
                used_tiles.append(widget)
                tile_idx += 1
            else:
                widget = self._get_empty_placeholder()
            self.grid.addWidget(widget, r, c, rs, cs)

        for t in self._tiles:
            if t in used_tiles:
                t.show()
            else:
                t.hide()

        max_r = max(c[0] + c[2] for c in spec["cells"])
        max_c = max(c[1] + c[3] for c in spec["cells"])

        rs = spec.get("row_stretch")
        if rs:
            for i in range(max_r):
                self.grid.setRowStretch(i, rs[i] if i < len(rs) else 1)
        else:
            for i in range(max_r):
                self.grid.setRowStretch(i, 1)

        cs = spec.get("col_stretch")
        if cs:
            for i in range(max_c):
                self.grid.setColumnStretch(i, cs[i] if i < len(cs) else 1)
        else:
            for i in range(max_c):
                self.grid.setColumnStretch(i, 1)

    def used_count(self) -> int:
        """返回当前布局实际使用的 tile 数量"""
        spec = LAYOUTS.get(self._current_key)
        if not spec:
            return 0
        return min(spec.get("_tile_count", 0), len(self._tiles))


# =========================================================================== #
#  滑动切换控件
# =========================================================================== #
class SwipeToast(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QLabel{background:rgba(30,30,30,230);color:#fff;"
            "font-size:15px;font-weight:bold;padding:10px 24px;"
            "border:1px solid #4a90e2;border-radius:6px;}")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text, duration=1200):
        self.setText(text)
        self.adjustSize()
        if self.parent():
            x = (self.parent().width() - self.width()) // 2
            y = int(self.parent().height() * 0.35)
            self.move(max(0, x), max(0, y))
        self.raise_()
        self.show()
        self._timer.start(duration)


class SwipeGridHost(QWidget):
    swipe_left = pyqtSignal()
    swipe_right = pyqtSignal()
    SWIPE_THRESHOLD = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.pos()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton
                and self._press_pos is not None):
            delta = e.pos() - self._press_pos
            dx, dy = delta.x(), delta.y()
            if abs(dx) >= self.SWIPE_THRESHOLD and abs(dx) > abs(dy) * 1.5:
                if dx < 0:
                    self.swipe_left.emit()
                else:
                    self.swipe_right.emit()
        self._press_pos = None
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        dx = e.angleDelta().x()
        dy = e.angleDelta().y()
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl or dx != 0:
            delta = dx if dx != 0 else dy
            if delta < 0:
                self.swipe_left.emit()
            elif delta > 0:
                self.swipe_right.emit()
            e.accept()
        else:
            super().wheelEvent(e)


# =========================================================================== #
#  状态监控
# =========================================================================== #
@dataclass
class RoomInfo:
    platform: str
    room_id: str
    title: str = ""
    anchor_name: str = ""
    live_status: int = 0
    cover_url: str = ""
    online: int = 0
    last_check: float = 0.0
    followed: bool = False
    url: str = ""


class BilibiliStatusChecker:
    @staticmethod
    def check(room_id: str) -> Optional[RoomInfo]:
        try:
            headers = {"User-Agent": USER_AGENT}
            if BILIBILI_SESSDATA:
                headers["Cookie"] = f"SESSDATA={BILIBILI_SESSDATA}"
            r = requests.get(BILI_LIVE_API, params={"room_id": room_id},
                             headers=headers, timeout=10).json()
            if r.get("code") != 0:
                return None
            d = r["data"]
            return RoomInfo("bilibili", str(d.get("room_id", room_id)),
                            d.get("title", ""), d.get("uname", ""),
                            d.get("live_status", 0), d.get("user_cover", ""),
                            d.get("online", 0), time.time())
        except Exception:
            return None


class DouyinStatusChecker:
    _ttwid: Optional[str] = None
    MANUAL_TTWID = ""

    @classmethod
    def _get_ttwid(cls) -> str:
        if cls.MANUAL_TTWID:
            return cls.MANUAL_TTWID
        if cls._ttwid:
            return cls._ttwid
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT,
                          "Referer": "https://live.douyin.com/"})
        for url in ("https://live.douyin.com/", "https://www.douyin.com/"):
            try:
                r = s.get(url, timeout=10, allow_redirects=True)
                for c in r.cookies:
                    if c.name == "ttwid":
                        cls._ttwid = c.value
                        return cls._ttwid
                m = re.search(r'ttwid=([^;]+)',
                              r.headers.get("Set-Cookie", ""))
                if m:
                    cls._ttwid = m.group(1)
                    return cls._ttwid
            except Exception:
                continue
        return ""

    @classmethod
    def check(cls, room_id: str) -> Optional[RoomInfo]:
        ttwid = cls._get_ttwid()
        if not ttwid:
            return None
        try:
            r = requests.get(
                DOUYIN_ENTER_API, params={"web_rid": room_id},
                headers={"User-Agent": USER_AGENT,
                         "Cookie": f"ttwid={ttwid}",
                         "Referer": "https://live.douyin.com/"},
                timeout=10).json()
            rd = r.get("data", {}).get("data", [{}])[0]
            return RoomInfo(
                "douyin", room_id, rd.get("title", ""),
                rd.get("owner", {}).get("nickname", ""),
                1 if rd.get("status") == 2 else 0,
                (rd.get("cover", {}) or {}).get("url_list", [""])[0],
                rd.get("stats", {}).get("total_user", 0), time.time())
        except Exception:
            return None


class HuyaStatusChecker:
    @staticmethod
    def check(room_id: str) -> Optional[RoomInfo]:
        try:
            url = (f"https://mp.huya.com/cache.php?"
                   f"m=Live&do=profileRoom&roomid={room_id}")
            r = requests.get(url, headers={"User-Agent": USER_AGENT},
                             timeout=10).json()
            if r.get("status") != 200:
                return None
            d = r.get("data", {}) or {}
            pi = d.get("profileInfo", {}) or {}
            live = (d.get("liveStatus") == "ON"
                    or d.get("liveData", {}).get("liveStatus") == "ON")
            return RoomInfo(
                "huya", str(pi.get("roomId", room_id)),
                (d.get("liveData", {}) or {}).get("introduction", "")
                or pi.get("sIntroduction", ""),
                pi.get("nick", ""),
                1 if live else 0, "", 0, time.time())
        except Exception:
            return None


class DouyuStatusChecker:
    @staticmethod
    def check(room_id: str) -> Optional[RoomInfo]:
        try:
            url = f"https://www.douyu.com/betard/{room_id}"
            r = requests.get(url, headers={"User-Agent": USER_AGENT},
                             timeout=10).json()
            d = r.get("room", {}) or {}
            if not d:
                return None
            return RoomInfo(
                "douyu", str(d.get("room_id", room_id)),
                d.get("room_name", ""),
                d.get("nickname", ""),
                1 if d.get("show_status") == 1 else 0,
                d.get("room_pic", ""),
                int(d.get("hot_num", 0) or 0),
                time.time())
        except Exception:
            return None


class StatusMonitorWorker(QObject):
    status_updated = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._rooms = []
        self._running = False
        self._interval = 15

    def set_rooms(self, rooms):
        self._rooms = rooms

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            for room in list(self._rooms):
                if not self._running:
                    return
                try:
                    p = room.platform
                    if p == "bilibili":
                        info = BilibiliStatusChecker.check(room.room_id)
                    elif p == "douyin":
                        info = DouyinStatusChecker.check(room.room_id)
                    elif p == "huya":
                        info = HuyaStatusChecker.check(room.room_id)
                    elif p == "douyu":
                        info = DouyuStatusChecker.check(room.room_id)
                    else:
                        info = None
                    if info:
                        info.followed = room.followed
                        info.url = room.url
                        self.status_updated.emit(info)
                except Exception:
                    pass
                time.sleep(2)
            for _ in range(self._interval):
                if not self._running:
                    return
                time.sleep(1)


class StatusPanel(QWidget):
    room_double_clicked = pyqtSignal(object)
    follow_toggled = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setStyleSheet("background:#1a1a1a;border-right:1px solid #333;")
        self._rooms = {}

        title = QLabel("直播间监控")
        title.setStyleSheet(
            "color:#ddd;font-size:14px;font-weight:bold;padding:10px 8px 4px;")
        self.btn_add = QPushButton("+ 添加直播间")
        self.btn_add.setStyleSheet(
            "QPushButton{background:#2d5a8e;color:#fff;border:none;"
            "border-radius:4px;padding:6px 10px;font-size:12px;margin:4px 8px;}"
            "QPushButton:hover{background:#3a6ea5;}")
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget{background:#1a1a1a;border:none;}"
            "QListWidget::item{border-bottom:1px solid #2a2a2a;"
            "padding:4px;color:#ddd;}")
        self.list_widget.itemDoubleClicked.connect(self._on_dc)
        self.list_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(
            self._show_context_menu)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(title)
        lay.addWidget(self.btn_add)
        lay.addWidget(self.list_widget, 1)

    def update_room_status(self, info: RoomInfo):
        self._rooms[f"{info.platform}:{info.room_id}"] = info
        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        items = sorted(self._rooms.values(),
                       key=lambda x: (not x.followed, x.platform, x.room_id))
        for info in items:
            icon = "ON" if info.live_status == 1 else "OFF"
            star = "★ " if info.followed else "  "
            pname = PLATFORMS.get(info.platform, {}).get("name", info.platform)
            title = (info.title[:16] + "...") if len(info.title) > 16 else (info.title or "——")
            item = QListWidgetItem(
                f"{star}{icon} [{pname}] {info.anchor_name or info.room_id}\n"
                f"     {title}")
            item.setData(Qt.ItemDataRole.UserRole, info)
            f = QFont()
            f.setPointSize(9)
            item.setFont(f)
            if info.followed:
                item.setForeground(QColor("#FFD700"))
            self.list_widget.addItem(item)

    def _on_dc(self, item):
        info = item.data(Qt.ItemDataRole.UserRole)
        if info:
            self.room_double_clicked.emit(info)

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        info = item.data(Qt.ItemDataRole.UserRole)
        if not info:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#2d2d2d;color:#ddd;border:1px solid #555;}"
            "QMenu::item{padding:4px 20px;}"
            "QMenu::item:selected{background:#3a6ea5;}")
        act = menu.addAction("取消关注" if info.followed else "★ 关注此直播间")
        act.triggered.connect(lambda: self.follow_toggled.emit(info))
        menu.exec(self.list_widget.mapToGlobal(pos))


# =========================================================================== #
#  流提取（切片）
# =========================================================================== #
class BilibiliStreamExtractor:
    @staticmethod
    def get_stream_info(room_id):
        headers = {"User-Agent": USER_AGENT}
        if BILIBILI_SESSDATA:
            headers["Cookie"] = f"SESSDATA={BILIBILI_SESSDATA}"
        try:
            info = requests.get(BILI_LIVE_API, params={"room_id": room_id},
                                headers=headers, timeout=10).json()
            if info.get("code") != 0:
                return None
            d = info["data"]
            play = requests.get(
                BILI_PLAY_API,
                params={"cid": d["room_id"], "platform": "web", "qn": 10000},
                headers=headers, timeout=10).json()
            if play.get("code") != 0:
                return None
            durl = play["data"].get("durl", [])
            if durl:
                return {"url": durl[0].get("url", ""),
                        "anchor_name": d.get("uname", ""),
                        "title": d.get("title", "")}
        except Exception:
            pass
        return None


class DouyinStreamExtractor:
    @staticmethod
    def get_stream_info(web_rid):
        ttwid = DouyinStatusChecker._get_ttwid()
        if not ttwid:
            return None
        try:
            data = requests.get(
                DOUYIN_ENTER_API, params={"web_rid": web_rid},
                headers={"User-Agent": USER_AGENT,
                         "Cookie": f"ttwid={ttwid}",
                         "Referer": "https://live.douyin.com/"},
                timeout=10).json()
            rd = data.get("data", {}).get("data", [{}])[0]
            if rd.get("status") != 2:
                return None
            su = rd.get("stream_url", {}) or {}
            flvs = su.get("flv_pull_url", {}) or {}
            hlss = su.get("hls_pull_url_map", {}) or {}
            flv = next((flvs[k] for k in ["FULL_HD1", "HD1", "SD1", "SD2"]
                        if k in flvs), next(iter(flvs.values()), None))
            hls = next((hlss[k] for k in ["FULL_HD1", "HD1", "SD1", "SD2"]
                        if k in hlss), next(iter(hlss.values()), None))
            url = flv or hls
            if url:
                return {"url": url,
                        "anchor_name": rd.get("owner", {}).get("nickname", ""),
                        "title": rd.get("title", "")}
        except Exception:
            pass
        return None


# =========================================================================== #
#  切片录制
# =========================================================================== #
class ClipRecorder:
    _hw_encoder = None
    _hw_checked = False
    _hw_lock = threading.Lock()
    _pool = None
    _pool_lock = threading.Lock()

    def __init__(self, output_dir="./clips"):
        self.output_dir = output_dir
        self.export_dir = os.path.join(output_dir, "ready_to_upload")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.export_dir, exist_ok=True)
        self._process = None
        self._stdin = None
        self._log_fp = None
        self._start_time = 0.0
        self._output_file = None
        self._base_name = ""
        self.ffmpeg_path = self._find_ffmpeg()

    @classmethod
    def _get_pool(cls):
        if cls._pool is None:
            with cls._pool_lock:
                if cls._pool is None:
                    cls._pool = ThreadPoolExecutor(max_workers=2,
                                                   thread_name_prefix="clip")
        return cls._pool

    @staticmethod
    def _find_ffmpeg():
        p = shutil.which("ffmpeg")
        if p:
            return p
        base = os.path.dirname(os.path.abspath(__file__))
        for n in ("ffmpeg.exe", "ffmpeg"):
            c = os.path.join(base, n)
            if os.path.exists(c):
                return c
        for c in [r"C:\\ffmpeg\\bin\\ffmpeg.exe",
                  r"C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe"]:
            if os.path.exists(c):
                return c
        return None

    def start(self, url, platform="", room_id="", anchor="",
              referer="", user_agent="") -> bool:
        if self._process is not None or not self.ffmpeg_path:
            return False
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [sanitize_filename(x, 40) for x in (platform, room_id, anchor)
                 if x]
        parts.append(ts)
        self._base_name = "_".join(parts) or "clip"
        self._output_file = os.path.join(self.output_dir,
                                         f"{self._base_name}.ts")

        cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "warning",
               "-thread_queue_size", "512", "-fflags", "+genpts",
               "-rw_timeout", "15000000"]
        hdrs = []
        if referer:
            hdrs.append(f"Referer: {referer}\r\n")
        if user_agent:
            hdrs.append(f"User-Agent: {user_agent}\r\n")
        if hdrs:
            cmd += ["-headers", "".join(hdrs)]
        cmd += ["-rtbufsize", "256M", "-i", url,
                "-c", "copy", "-flush_packets", "0",
                "-f", "mpegts", "-y", self._output_file]
        try:
            self._log_fp = open(self._output_file + ".log", "wb")
        except Exception:
            self._log_fp = None
        try:
            self._process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._log_fp if self._log_fp else subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self._stdin = self._process.stdin
            self._start_time = time.time()
            print(f"[切片] 开始录制: {self._output_file}")
            return True
        except Exception as e:
            print(f"[切片] 启动失败: {e}")
            self._process = None
            return False

    def stop(self, on_done=None):
        called = {"flag": False}

        def safe_done(ok, d):
            if called["flag"]:
                return
            called["flag"] = True
            if on_done:
                try:
                    on_done(ok, d)
                except Exception:
                    pass

        try:
            if self._process is None:
                safe_done(False, self.export_dir)
                return
            proc = self._process
            stdin = self._stdin
            self._process = None
            self._stdin = None
            try:
                if stdin:
                    stdin.write(b"q")
                    stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                if stdin:
                    stdin.close()
            except Exception:
                pass
            if self._log_fp:
                try:
                    self._log_fp.close()
                except Exception:
                    pass
                self._log_fp = None
            if not self._output_file or not os.path.exists(self._output_file):
                safe_done(False, self.export_dir)
                return
            if os.path.getsize(self._output_file) < 1024:
                safe_done(False, self.export_dir)
                return
            src = self._output_file
            out = os.path.join(self.export_dir, f"{self._base_name}.mp4")

            def _export():
                ok = self._convert(src, out, "copy") or \
                     self._convert(src, out, "encode")
                safe_done(ok, self.export_dir)

            self._get_pool().submit(_export)
        except Exception as e:
            print(f"[切片] 异常: {e}")
            safe_done(False, self.export_dir)

    def _convert(self, src, out, mode) -> bool:
        cmd = [self.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "warning",
               "-i", src]
        if mode == "copy":
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero",
                    "-movflags", "+faststart", out]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-threads", "2", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out]
        try:
            r = subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, timeout=1800)
            if r.returncode == 0 and os.path.exists(out) and \
                    os.path.getsize(out) > 1024:
                print(f"[切片] 已导出: {out}")
                return True
        except Exception:
            pass
        return False

    def shutdown(self):
        if self._process:
            try:
                if self._stdin:
                    self._stdin.write(b"q")
                    self._stdin.flush()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            self._process = None


# =========================================================================== #
#  音频控制（音量 + 左右声道）
# =========================================================================== #
class JsVideoController:
    def __init__(self, wv):
        self._wv = wv
        self._vol = 1.0
        self._muted = False
        self._balance = 0.0   # -1.0 左  ~  +1.0 右

    def _run(self, js):
        if self._wv is None:
            return
        fn = getattr(self._wv, "evaluate_js", None)
        if callable(fn):
            try:
                fn(js)
            except Exception:
                pass

    def set_volume(self, v):
        self._vol = max(0.0, min(1.0, v))
        self._apply()

    def set_mute(self, m):
        self._muted = m
        self._apply()

    def set_balance(self, b):
        """b: -1.0(全左) 到 +1.0(全右)，0 居中"""
        self._balance = max(-1.0, min(1.0, b))
        self._apply_balance()

    def _apply(self):
        vol = 0.0 if self._muted else self._vol
        self._run(f"document.querySelectorAll('video').forEach(v=>{{"
                  f"v.volume={vol:.3f};"
                  f"v.muted={'true' if self._muted else 'false'};}});")

    def _apply_balance(self):
        """通过 Web Audio API 的 StereoPannerNode 设置声道平衡"""
        b = self._balance
        # 同时更新 window.__balance_value，让注入脚本在检测到新 video 时也应用
        js = (
            f"window.__balance_value={b:.3f};"
            "document.querySelectorAll('video').forEach(function(v){"
            "  if(v.__balance_pan){try{v.__balance_pan.pan.value="
            f"{b:.3f};"
            "  }catch(e){}}"
            "});"
        )
        self._run(js)


# =========================================================================== #
#  ChromeTile
# =========================================================================== #
class ChromeTile(QFrame):
    sig_export_done = pyqtSignal(bool, str)

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self._web_view = None
        self._recorder = None
        self._audio = None
        self._url = ""
        self._wv_ready = False
        self._pending_url = ""
        self._is_paused = False
        self._clip_state = "idle"
        self._auto_timer = None
        self._quality = 10000
        self._room_id = ""
        self._room_history = []
        # 拖拽交换相关
        self._drag_start_pos = None
        self._drag_has_started = False
        self._is_dragging = False
        self._anchor_name = ""

        self.sig_export_done.connect(
            self._on_export_done_ui, Qt.ConnectionType.QueuedConnection)

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "ChromeTile{background:#111;border:1px solid #333;border-radius:4px;}")

        # ============ 顶部栏 ============ #
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("直播间地址")
        self.url_input.setStyleSheet(
            "QLineEdit{background:#1e1e1e;color:#ddd;border:1px solid #444;"
            "border-radius:3px;padding:3px 6px;font-size:12px;}")

        self.num_label = QLabel(f"#{index + 1}")
        self.num_label.setFixedWidth(28)
        self.num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num_label.setStyleSheet(
            "QLabel{color:#4a90e2;font-weight:bold;font-size:11px;"
            "background:#1a2a3a;border-radius:3px;padding:1px;}")

        self.btn_load = QPushButton("加载")
        self.btn_clip = QPushButton("切片")
        self.btn_close = QPushButton("关闭")
        self.cmb_quality = QComboBox()
        self.cmb_quality.addItems(["原画", "蓝光", "超清", "流畅"])
        self.cmb_quality.setCurrentIndex(0)

        for b in (self.btn_load, self.btn_clip, self.btn_close):
            b.setFixedHeight(24)
            b.setStyleSheet(
                "QPushButton{padding:2px 6px;border:1px solid #555;"
                "border-radius:3px;background:#2d2d2d;color:#ddd;"
                "font-size:11px;}"
                "QPushButton:hover{background:#3d3d3d;}")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(3)
        top.addWidget(self.num_label)
        top.addWidget(self.url_input, 1)
        top.addWidget(self.btn_load)
        top.addWidget(self.btn_clip)

        self.room_selector = QComboBox()
        self.room_selector.setFixedWidth(120)
        self.room_selector.addItem("选择直播间查看")
        self.room_selector.currentIndexChanged.connect(self._on_room_select)
        top.addWidget(self.room_selector)
        top.addWidget(self.cmb_quality)
        top.addWidget(self.btn_close)

        # ============ 控制栏 ============ #
        self.btn_pause = QPushButton("暂停")
        self.btn_reload = QPushButton("重载")
        self.btn_snapshot = QPushButton("截图")
        self.btn_fullscreen = QPushButton("全屏")
        for b in (self.btn_pause, self.btn_reload, self.btn_snapshot,
                   self.btn_fullscreen):
            b.setFixedSize(30, 28)
            b.setStyleSheet(
                "QPushButton{border:1px solid #555;border-radius:3px;"
                "background:#2d2d2d;color:#ddd;font-size:11px;padding:0;}"
                "QPushButton:hover{background:#3d3d3d;}")

        # 音量滑块
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setMinimumWidth(40)
        self.vol.setMaximumWidth(100)
        self.vol.setStyleSheet(
            "QSlider::groove:horizontal{height:3px;background:#333;}"
            "QSlider::handle:horizontal{background:#4a90e2;width:8px;"
            "margin:-3px 0;border-radius:4px;}"
            "QSlider::sub-page:horizontal{background:#4a90e2;}")
        self.btn_mute = QPushButton("静音")
        self.btn_mute.setFixedSize(30, 24)
        self.btn_mute.setCheckable(True)
        self.btn_mute.setStyleSheet(
            "QPushButton{border:1px solid #555;border-radius:3px;"
            "background:#2d2d2d;color:#ddd;font-size:11px;padding:0;}"
            "QPushButton:checked{background:#a33;}")

        # ★ 左右声道滑块（-100 ~ 100，0 居中）
        self.balance = QSlider(Qt.Orientation.Horizontal)
        self.balance.setRange(-100, 100)
        self.balance.setValue(0)
        self.balance.setMinimumWidth(60)
        self.balance.setMaximumWidth(110)
        self.balance.setToolTip("左右声道平衡\n-100 = 全左   0 = 居中   100 = 全右")
        self.balance.setStyleSheet(
            "QSlider::groove:horizontal{height:3px;background:#333;}"
            "QSlider::handle:horizontal{background:#e0a04a;width:8px;"
            "margin:-3px 0;border-radius:4px;}"
            "QSlider::sub-page:horizontal{background:#a07030;}")
        self.balance_label = QLabel("0")
        self.balance_label.setFixedWidth(26)
        self.balance_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.balance_label.setStyleSheet(
            "QLabel{color:#e0a04a;font-size:10px;font-weight:bold;}")
        self.btn_balance_reset = QPushButton("C")
        self.btn_balance_reset.setFixedSize(20, 24)
        self.btn_balance_reset.setToolTip("重置声道为居中")
        self.btn_balance_reset.setStyleSheet(
            "QPushButton{border:1px solid #555;border-radius:3px;"
            "background:#2d2d2d;color:#e0a04a;font-size:10px;padding:0;}"
            "QPushButton:hover{background:#3d3d3d;}")

        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(3, 3, 3, 3)
        ctrl.setSpacing(6)
        ctrl.addWidget(self.btn_pause)
        ctrl.addWidget(self.btn_reload)
        ctrl.addWidget(self.btn_snapshot)
        ctrl.addWidget(self.btn_fullscreen)
        ctrl.addSpacing(6)
        ctrl.addWidget(QLabel("音量"))
        ctrl.addWidget(self.vol, 1)
        ctrl.addWidget(self.btn_mute)
        ctrl.addSpacing(6)
        ctrl.addWidget(QLabel("声道"))
        ctrl.addWidget(self.balance, 1)
        ctrl.addWidget(self.balance_label)
        ctrl.addWidget(self.btn_balance_reset)

        # ============ WebView2 ============ #
        if HAS_WEBVIEW2:
            try:
                self._web_view = QtWebView2Widget()
                self._web_view.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
                self._audio = JsVideoController(self._web_view)
                self._ready_timer = QTimer(self)
                self._ready_timer.timeout.connect(self._check_ready)
                self._ready_timer.start(200)
            except Exception as e:
                print(f"[WebView2] 创建失败: {e}")
                self._web_view = None
        if self._web_view is None:
            self._web_view = QLabel(f"画面 {index + 1}\n未加载")
            self._web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._web_view.setStyleSheet(
                "color:#555;background:#0d0d0d;font-size:12px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        lay.addLayout(top)
        lay.addLayout(ctrl)
        lay.addWidget(self._web_view, 1)

        # ============ 信号 ============ #
        self.btn_load.clicked.connect(self.load_url)
        self.btn_close.clicked.connect(self.close_view)
        self.btn_clip.clicked.connect(self._on_clip_clicked)
        self.url_input.returnPressed.connect(self.load_url)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_reload.clicked.connect(self._on_reload)
        self.btn_snapshot.clicked.connect(self._on_snapshot)
        self.btn_fullscreen.clicked.connect(self._on_fullscreen)
        self.vol.valueChanged.connect(self._on_vol)
        self.btn_mute.toggled.connect(self._on_mute)
        self.cmb_quality.currentIndexChanged.connect(self._change_quality)
        # ★ 左右声道
        self.balance.valueChanged.connect(self._on_balance_changed)
        self.btn_balance_reset.clicked.connect(
            lambda: self.balance.setValue(0))

    def _change_quality(self, index):
        quality_map = {0: 10000, 1: 400, 2: 250, 3: 80}
        self._quality = quality_map.get(index, 10000)
        self._wv_js(f"window.__bili_quality={self._quality};")

    def _wv_load(self, url):
        if self._web_view is None:
            return
        fn = getattr(self._web_view, "load_url", None)
        if callable(fn):
            try:
                fn(url)
            except Exception:
                pass

    def _wv_js(self, js):
        if self._web_view is None:
            return
        fn = getattr(self._web_view, "evaluate_js", None)
        if callable(fn):
            try:
                fn(js)
            except Exception:
                pass

    def _wv_reload(self):
        if self._web_view is None:
            return
        fn = getattr(self._web_view, "reload", None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:
                pass
        if self._url:
            self._wv_load(self._url)

    def _check_ready(self):
        if self._web_view is None:
            return
        ready = False
        attr = getattr(self._web_view, "is_ready", None)
        if callable(attr):
            try:
                ready = bool(attr())
            except Exception:
                ready = False
        elif attr is not None:
            ready = bool(attr)
        if ready:
            self._wv_ready = True
            self._ready_timer.stop()
            if self._pending_url:
                u = self._pending_url
                self._pending_url = ""
                self._wv_load(u)
                QTimer.singleShot(2000, self._inject)
                QTimer.singleShot(5000, self._inject)

    def _load_when_ready(self, url):
        if self._wv_ready:
            self._wv_load(url)
            QTimer.singleShot(2000, self._inject)
            QTimer.singleShot(5000, self._inject)
        else:
            self._pending_url = url

    def load_url(self):
        url = self.url_input.text().strip()
        if not url:
            return
        if not url.startswith("http"):
            if re.fullmatch(r"\d+", url):
                url = f"https://live.bilibili.com/{url}"
            else:
                url = "https://" + url
        self._url = url
        room_name = url.split("/")[-1] if "/" in url else url
        if room_name not in self._room_history:
            self._room_history.append(room_name)
            self.room_selector.addItem(room_name)
        self._load_when_ready(url)

    def _on_room_select(self, index):
        if index == 0:
            return
        selected = self.room_selector.itemText(index)
        if selected and selected != "选择直播间查看":
            self.url_input.setText(selected)
            self.load_url()

    def _inject(self):
        """注入自动播放 + 声道平衡处理脚本"""
        bal = self.balance.value() / 100.0
        self._wv_js(r"""
        (function(){
            if(window.__ddm_injected) return;
            window.__ddm_injected=true;
            window.__balance_value = 0;

            function ensureAudioGraph(v){
                if(v.__balance_pan || v.__balance_failed) return;
                try{
                    var ctx = new (window.AudioContext||window.webkitAudioContext)();
                    if(ctx.state === 'suspended'){
                        try{ ctx.resume(); }catch(e){}
                    }
                    var src = ctx.createMediaElementSource(v);
                    if(ctx.createStereoPanner){
                        var pan = ctx.createStereoPanner();
                        src.connect(pan);
                        pan.connect(ctx.destination);
                        v.__balance_ctx = ctx;
                        v.__balance_pan = pan;
                    } else {
                        // 老浏览器无 StereoPanner，只连直通
                        src.connect(ctx.destination);
                        v.__balance_ctx = ctx;
                    }
                }catch(e){
                    v.__balance_failed = true;
                }
            }

            function autoPlayAndBalance(){
                document.querySelectorAll('video').forEach(function(v){
                    // 自动播放
                    if(v.paused){
                        try{
                            v.muted = true;
                            var p = v.play();
                            if(p && p.then){
                                p.then(function(){
                                    setTimeout(function(){ v.muted = false; }, 800);
                                }).catch(function(){});
                            }
                        }catch(e){}
                    }
                    // 声道
                    if(!v.__balance_failed){
                        ensureAudioGraph(v);
                        if(v.__balance_pan){
                            try{
                                v.__balance_pan.pan.value = window.__balance_value;
                            }catch(e){}
                        }
                    }
                });
            }
            setInterval(autoPlayAndBalance, 1000);
            window.__bili_quality = 10000;
        })();
        """)
        # 立即应用当前声道值
        QTimer.singleShot(200, lambda: self._wv_js(
            f"window.__balance_value={bal:.3f};"
            "document.querySelectorAll('video').forEach(function(v){"
            f"  if(v.__balance_pan){{try{{v.__balance_pan.pan.value={bal:.3f};}}catch(e){{}}}}"
            "});"))

    def _on_pause(self):
        if self._is_paused:
            self._wv_js(
                "document.querySelectorAll('video').forEach(v=>v.play());")
            self._is_paused = False
            self.btn_pause.setText("暂停")
        else:
            self._wv_js(
                "document.querySelectorAll('video').forEach(v=>v.pause());")
            self._is_paused = True
            self.btn_pause.setText("播放")

    def _on_reload(self):
        self._is_paused = False
        self.btn_pause.setText("暂停")
        self._wv_reload()
        QTimer.singleShot(2000, self._inject)

    def _on_snapshot(self):
        try:
            pm = self._web_view.grab()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = os.path.join(SCREENSHOT_DIR, f"tile{self.index}_{ts}.png")
            pm.save(out, "PNG")
            QMessageBox.information(self, "截图", f"已保存:\n{out}")
        except Exception as e:
            print(f"[截图] 失败: {e}")

    def _on_fullscreen(self):
        self._wv_js(
            "var v=document.querySelector('video');"
            "if(v){if(v.requestFullscreen)v.requestFullscreen();"
            "else if(v.webkitRequestFullscreen)v.webkitRequestFullscreen();}")

    def _on_vol(self, v):
        if self._audio:
            self._audio.set_volume(v / 100.0)
        if v > 0 and self.btn_mute.isChecked():
            self.btn_mute.setChecked(False)

    def _on_mute(self, m):
        if self._audio:
            self._audio.set_mute(m)
        self.btn_mute.setText("静音" if m else "音量")

    def _on_balance_changed(self, v):
        """左右声道改变"""
        self.balance_label.setText(str(v))
        if self._audio:
            self._audio.set_balance(v / 100.0)
        # 如果还没注入，延迟再试
        self._wv_js(
            f"window.__balance_value={(v/100.0):.3f};"
            "document.querySelectorAll('video').forEach(function(vv){"
            f"  if(vv.__balance_pan){{try{{vv.__balance_pan.pan.value={(v/100.0):.3f};}}catch(e){{}}}}"
            "});")

    def set_mute(self, m):
        self.btn_mute.setChecked(m)

    # ---------- 切片 ---------- #
    def _on_clip_clicked(self):
        if self._clip_state == "exporting":
            return
        if self._clip_state == "idle":
            self._start_clip()
        elif self._clip_state == "recording":
            self._stop_clip()

    def _start_clip(self):
        url = self.url_input.text()
        bili = re.search(r'live\.bilibili\.com/(?:blanc/)?(\d+)', url)
        douyin = re.search(r'live\.douyin\.com/(?:user/)?(\d+)', url)
        if bili:
            info = BilibiliStreamExtractor.get_stream_info(bili.group(1))
            if not info:
                QMessageBox.warning(self, "切片", "无法获取B站流")
                return
            self._recorder = ClipRecorder()
            ok = self._recorder.start(
                info["url"], platform="bilibili", room_id=bili.group(1),
                anchor=info.get("anchor_name", ""),
                referer="https://live.bilibili.com/", user_agent=USER_AGENT)
        elif douyin:
            info = DouyinStreamExtractor.get_stream_info(douyin.group(1))
            if not info:
                QMessageBox.warning(self, "切片", "无法获取抖音流")
                return
            self._recorder = ClipRecorder()
            ok = self._recorder.start(
                info["url"], platform="douyin", room_id=douyin.group(1),
                anchor=info.get("anchor_name", ""),
                referer="https://live.douyin.com/", user_agent=USER_AGENT)
        else:
            QMessageBox.warning(self, "切片", "切片功能目前仅支持 B站/抖音")
            return
        if not ok:
            QMessageBox.warning(self, "切片", "录制启动失败")
            self._recorder = None
            return
        self._clip_state = "recording"
        self.btn_clip.setText("停止")
        self.btn_clip.setStyleSheet(
            "QPushButton{padding:2px 6px;border:1px solid #e74c3c;"
            "border-radius:3px;background:#c0392b;color:#fff;"
            "font-weight:bold;font-size:11px;}")
        if SLICE_MAX_MINUTES > 0:
            self._auto_timer = QTimer(self)
            self._auto_timer.setSingleShot(True)
            self._auto_timer.timeout.connect(self._auto_stop)
            self._auto_timer.start(SLICE_MAX_MINUTES * 60 * 1000)

    def _auto_stop(self):
        if self._clip_state == "recording":
            self._stop_clip()

    def _stop_clip(self):
        if self._clip_state != "recording":
            return
        if self._auto_timer:
            self._auto_timer.stop()
            self._auto_timer = None
        self._clip_state = "exporting"
        self.btn_clip.setText("导出中...")
        self.btn_clip.setStyleSheet(
            "QPushButton{padding:2px 6px;border:1px solid #f0ad4e;"
            "border-radius:3px;background:#8a6d3b;color:#fff;font-size:11px;}")
        if self._recorder:
            rec = self._recorder
            self._recorder = None
            rec.stop(on_done=self._on_export_done)

    def _on_export_done(self, ok, d):
        self.sig_export_done.emit(ok, d)

    def _on_export_done_ui(self, ok, d):
        self._clip_state = "idle"
        self.btn_clip.setText("切片")
        self.btn_clip.setStyleSheet(
            "QPushButton{padding:2px 6px;border:1px solid #555;"
            "border-radius:3px;background:#2d2d2d;color:#ddd;font-size:11px;}"
            "QPushButton:hover{background:#3d3d3d;}")

    def close_view(self):
        if self._auto_timer:
            self._auto_timer.stop()
            self._auto_timer = None
        if self._recorder:
            rec = self._recorder
            self._recorder = None
            rec.stop(on_done=self._on_export_done)
        self._url = ""
        self._pending_url = ""
        self._is_paused = False
        self._clip_state = "idle"
        self.btn_pause.setText("暂停")
        self.btn_clip.setText("切片")

    def shutdown(self):
        try:
            self.close_view()
        except Exception:
            pass

    # =========================================================== #
    #  拖拽交换（纯鼠标事件，不用 QDrag）
    # =========================================================== #
    DRAG_ZONE_HEIGHT = 30
    DRAG_THRESHOLD = 10

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and event.position().y() < self.DRAG_ZONE_HEIGHT):
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_has_started = False
            self._is_dragging = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None:
            super().mouseMoveEvent(event)
            return

        cur = event.globalPosition().toPoint()
        delta = cur - self._drag_start_pos

        if not self._drag_has_started and delta.manhattanLength() > self.DRAG_THRESHOLD:
            self._drag_has_started = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.setStyleSheet(
                "ChromeTile{background:#1a3a5c;border:2px solid #4a90e2;"
                "border-radius:4px;}")

        if self._drag_has_started:
            hover = self._find_tile_at(cur)
            for t in self._all_tiles():
                if t is self:
                    continue
                if t is hover:
                    t.setStyleSheet(
                        "ChromeTile{background:#1a3a5c;border:2px solid "
                        "#4a90e2;border-radius:4px;}")
                else:
                    t.setStyleSheet(
                        "ChromeTile{background:#111;border:1px solid #333;"
                        "border-radius:4px;}")
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_has_started:
            cur = event.globalPosition().toPoint()
            target = self._find_tile_at(cur)
            if target is not None:
                self._swap_with(target)
            for t in self._all_tiles():
                t.setStyleSheet(
                    "ChromeTile{background:#111;border:1px solid #333;"
                    "border-radius:4px;}")
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._reset_drag_state()
            event.accept()
            return

        self._reset_drag_state()
        super().mouseReleaseEvent(event)

    def _reset_drag_state(self):
        self._drag_start_pos = None
        self._drag_has_started = False
        self._is_dragging = False

    def _all_tiles(self):
        p = self.parentWidget()
        while p is not None:
            tiles = getattr(p, "tiles", None)
            if isinstance(tiles, list) and tiles:
                return tiles
            p = p.parentWidget()
        return [self]

    def _find_tile_at(self, global_pos):
        widget = QApplication.widgetAt(global_pos)
        if widget is None:
            return None
        target = widget
        while target is not None:
            if isinstance(target, ChromeTile) and target is not self:
                return target
            target = target.parentWidget()
        return None

    def _swap_with(self, other):
        self._url, other._url = other._url, self._url
        self.url_input.setText(self._url)
        other.url_input.setText(other._url)

        self._room_id, other._room_id = other._room_id, self._room_id
        self._anchor_name, other._anchor_name = other._anchor_name, self._anchor_name

        self._quality, other._quality = other._quality, self._quality

        self_p = self._is_paused
        other_p = other._is_paused
        self._is_paused = other_p
        other._is_paused = self_p
        self.btn_pause.setText("暂停" if not self._is_paused else "播放")
        other.btn_pause.setText("暂停" if not other._is_paused else "播放")

        self._room_history, other._room_history = \
            other._room_history, self._room_history
        self.room_selector.blockSignals(True)
        other.room_selector.blockSignals(True)
        self.room_selector.clear()
        self.room_selector.addItem("选择直播间查看")
        self.room_selector.addItems(self._room_history)
        other.room_selector.clear()
        other.room_selector.addItem("选择直播间查看")
        other.room_selector.addItems(other._room_history)
        self.room_selector.blockSignals(False)
        other.room_selector.blockSignals(False)

        if self._url:
            self._load_when_ready(self._url)
        else:
            self._wv_load("about:blank")
        if other._url:
            other._load_when_ready(other._url)
        else:
            other._wv_load("about:blank")

        print(f"[交换] 画面 {self.index + 1} <-> 画面 {other.index + 1}")


# =========================================================================== #
#  对话框
# =========================================================================== #
class AddRoomDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加直播间")
        self.setFixedSize(420, 260)
        self.setStyleSheet(
            "QDialog{background:#1e1e1e;color:#ddd;}"
            "QLabel{font-size:12px;}"
            "QLineEdit{background:#2d2d2d;color:#ddd;border:1px solid #555;"
            "border-radius:3px;padding:5px 8px;}"
            "QComboBox{background:#2d2d2d;color:#ddd;border:1px solid #555;"
            "border-radius:3px;padding:5px 8px;}"
            "QCheckBox{font-size:12px;}"
            "QPushButton{padding:6px 18px;border:1px solid #555;"
            "border-radius:3px;background:#2d2d2d;color:#ddd;}"
            "QPushButton:hover{background:#3d3d3d;}")
        self.result_data = None
        self.cmb = QComboBox()
        for key, cfg in PLATFORMS.items():
            self.cmb.addItem(cfg["name"], key)
        self.input = QLineEdit()
        self.input.setPlaceholderText("直播间 URL 或房间号（留空则仅关注）")
        self.chk_follow = QCheckBox("★ 关注此直播间（开播时弹窗提醒）")
        self.chk_follow.setChecked(True)
        ok = QPushButton("添加")
        cancel = QPushButton("取消")
        ok.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("平台："))
        lay.addWidget(self.cmb)
        lay.addWidget(QLabel("地址或房间号："))
        lay.addWidget(self.input)
        lay.addWidget(self.chk_follow)
        lay.addLayout(row)

    def _ok(self):
        key = self.cmb.currentData()
        raw = self.input.text().strip()
        if not raw:
            return
        room_id, url = parse_room_url(raw, key)
        self.result_data = RoomInfo(
            key, room_id, title="待检查",
            followed=self.chk_follow.isChecked(), url=url)
        self.accept()


class StartupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("启动设置")
        self.setFixedSize(360, 200)
        self.setStyleSheet(
            "QDialog{background:#1e1e1e;color:#ddd;}"
            "QLabel{font-size:13px;}"
            "QComboBox{background:#2d2d2d;color:#ddd;border:1px solid #555;"
            "border-radius:3px;padding:4px 8px;}"
            "QPushButton{padding:6px 18px;border:1px solid #555;"
            "border-radius:3px;background:#2d2d2d;color:#ddd;}"
            "QPushButton:hover{background:#3d3d3d;}")
        self.rows = self.cols = 0
        self.cmb = QComboBox()
        for t, _ in [("4 路", (2, 2)), ("6 路", (2, 3)),
                     ("9 路", (3, 3)), ("16 路", (4, 4))]:
            self.cmb.addItem(t)
        # ★ 默认 9 路
        self.cmb.setCurrentIndex(2)
        ok = QPushButton("开始")
        cancel = QPushButton("退出")
        ok.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("播放内核：WebView2\n选择最大路数："))
        lay.addWidget(self.cmb)
        lay.addLayout(row)

    def _ok(self):
        idx = self.cmb.currentIndex()
        opts = [(2, 2), (2, 3), (3, 3), (4, 4)]
        self.rows, self.cols = opts[idx]
        self.accept()


class StartLiveWindow(QWidget):
    def __init__(self):
        super(StartLiveWindow, self).__init__()
        self.setWindowTitle('开播提醒')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(320, 80)
        self.tipLabel = QLabel()
        self.tipLabel.setStyleSheet(
            'color:#293038;background-color:#ffeeba;padding:8px;'
            'border-radius:4px;')
        self.tipLabel.setFont(QFont('微软雅黑', 13, QFont.Weight.Bold))
        self.tipLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QGridLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.addWidget(self.tipLabel)

        self.hideTimer = QTimer(self)
        self.hideTimer.setInterval(10000)
        self.hideTimer.timeout.connect(self.hide)

    def mousePressEvent(self, QMouseEvent):
        self.hideTimer.stop()

    def show_message(self, text):
        self.tipLabel.setText(text)
        self.show()
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2,
                  int(screen.height() * 0.78))
        self.hideTimer.start()


class CacheSetting(QWidget):
    setting = pyqtSignal(list)

    def __init__(self):
        super(CacheSetting, self).__init__()
        self.resize(420, 220)
        self.setWindowTitle('缓存设置')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        cache_row = QHBoxLayout()
        cache_row.addWidget(QLabel('最大缓存(GB)'))
        self.maxCacheEdit = QLineEdit()
        self.maxCacheEdit.setValidator(QIntValidator(1, 9))
        cache_row.addWidget(self.maxCacheEdit)
        cache_row.addStretch(1)
        layout.addLayout(cache_row)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel('备份路径'))
        selectButton = QPushButton('选择路径')
        selectButton.setStyleSheet(
            'background-color:#31363b;border-width:1px;color:#ddd')
        selectButton.clicked.connect(self.selectCopyPath)
        path_row.addWidget(selectButton)
        self.savePathEdit = QLineEdit()
        path_row.addWidget(self.savePathEdit)
        layout.addLayout(path_row)

        hint_label = QLabel('缓存自动备份至以上路径 (若不填则默认删除)')
        hint_label.setStyleSheet('color:#888;font-size:10px;')
        layout.addWidget(hint_label)

        layout.addStretch(1)
        okButton = QPushButton('OK')
        okButton.setStyleSheet(
            'background-color:#3daee9;border-width:1px;color:#fff;'
            'font-size:12px;padding:6px')
        okButton.clicked.connect(self.sendSetting)
        layout.addWidget(okButton)

    def selectCopyPath(self):
        savePath = QFileDialog.getExistingDirectory(
            self, "选择备份缓存路径", None, QFileDialog.ShowDirsOnly)
        if savePath:
            self.savePathEdit.setText(savePath)

    def sendSetting(self):
        self.setting.emit([self.maxCacheEdit.text(),
                           self.savePathEdit.text()])
        self.hide()


# =========================================================================== #
#  主窗口
# =========================================================================== #
class MainWindow(QWidget):
    def __init__(self, rows, cols, preload_rooms=None):
        super().__init__()
        self.rows = rows
        self.cols = cols
        # ★ 最大路数（可修改）—— 初始值 = 启动时选的路数
        self._max_channels = rows * cols
        self.tiles = []
        self._all_rooms = []
        self._orientation = "h"
        self._room_states = {}
        self.config_startlive = True
        self._focused = False
        self._saved_layout_key = ""
        self._saved_tiles_order = []
        self._preload_rooms_list = list(preload_rooms or [])
        self._updating_channel_spin = False   # 防止信号循环

        self.setWindowTitle("DD_Monitor（WebView2 多平台版）")
        self.resize(1400, 880)
        self.setStyleSheet("QWidget{background:#1e1e1e;color:#ddd;}")

        # ============ 侧栏 ============ #
        self.status_panel = StatusPanel()
        self.status_panel.btn_add.clicked.connect(self._open_add)
        self.status_panel.room_double_clicked.connect(self._on_room_dc)
        self.status_panel.follow_toggled.connect(self._on_follow_toggle)

        # ============ 画面区 ============ #
        self.grid_host = SwipeGridHost()
        self.grid_host.swipe_left.connect(lambda: self._navigate_layout(+1))
        self.grid_host.swipe_right.connect(lambda: self._navigate_layout(-1))
        self.layout_mgr = LayoutManager(self.grid_host)

        # ★ 按最大路数创建 tile
        for i in range(self._max_channels):
            self.tiles.append(ChromeTile(i))
        self.layout_mgr.register_tiles(self.tiles)
        # 默认九分 3×3
        self.layout_mgr.apply("split_9")

        self._toast = SwipeToast(self.grid_host)

        # ============ 底栏 ============ #
        self.btn_layout = self._mk_tool("布局")
        self.btn_switch = self._mk_tool("画面切换")
        self.btn_pause_all = self._mk_tool("全部暂停", checkable=True)
        self.btn_close_all = self._mk_tool("全部关闭")
        self.btn_mute_all = self._mk_tool("全部静音", checkable=True)
        self.btn_quality = self._mk_tool("画质")
        self.btn_ttwid = self._mk_tool("抖音ttwid")
        self.btn_sessdata = self._mk_tool("B站SESSDATA")
        self.btn_open_clips = self._mk_tool("切片目录")
        self.btn_startlive = self._mk_tool("开播提醒", checkable=True)
        self.btn_startlive.setChecked(True)
        self.btn_cache = self._mk_tool("缓存设置")

        # ★ 当前路数（只读，自动随布局更新）
        self.current_channel_label = QLabel("当前路数: 9")
        self.current_channel_label.setStyleSheet(
            "color:#7ed957;font-size:12px;font-weight:bold;"
            "padding:4px 10px;background:#1a2a1a;border-radius:3px;")
        self.current_channel_label.setMinimumWidth(96)

        # ★ 最大路数（可编辑）
        max_label = QLabel("最大路数:")
        max_label.setStyleSheet(
            "color:#4a90e2;font-size:12px;font-weight:bold;padding:4px 4px;")
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 16)
        self.channel_spin.setValue(self._max_channels)
        self.channel_spin.setFixedHeight(28)
        self.channel_spin.setFixedWidth(64)
        self.channel_spin.setStyleSheet(
            "QSpinBox{background:#2d2d2d;color:#4a90e2;border:1px solid #555;"
            "border-radius:3px;padding:3px 6px;font-size:12px;"
            "font-weight:bold;}")
        self.channel_spin.valueChanged.connect(self._on_channel_count_changed)

        self.slice_spin = QSpinBox()
        self.slice_spin.setRange(0, 5)
        self.slice_spin.setValue(SLICE_MAX_MINUTES)
        self.slice_spin.setSuffix(" 分钟")
        self.slice_spin.setFixedHeight(28)
        self.slice_spin.setStyleSheet(
            "QSpinBox{background:#2d2d2d;color:#ddd;border:1px solid #555;"
            "border-radius:3px;padding:3px 6px;font-size:12px;}")
        self.slice_spin.valueChanged.connect(self._on_slice_changed)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(6, 0, 6, 6)
        bottom.setSpacing(6)
        bottom.addWidget(self.btn_layout)
        bottom.addWidget(self.btn_switch)
        bottom.addWidget(self.btn_pause_all)
        bottom.addWidget(self.btn_close_all)
        bottom.addWidget(self.btn_mute_all)
        bottom.addWidget(self.btn_quality)
        bottom.addSpacing(12)
        bottom.addWidget(self.btn_ttwid)
        bottom.addWidget(self.btn_sessdata)
        bottom.addWidget(self.btn_open_clips)
        bottom.addWidget(self.btn_startlive)
        bottom.addWidget(self.btn_cache)
        bottom.addSpacing(12)
        bottom.addWidget(self.current_channel_label)
        bottom.addWidget(max_label)
        bottom.addWidget(self.channel_spin)
        bottom.addWidget(QLabel("最长切片："))
        bottom.addWidget(self.slice_spin)
        bottom.addStretch(1)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addWidget(self.grid_host, 1)
        rl.addLayout(bottom)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.status_panel)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        self.startLiveWindow = StartLiveWindow()
        self.cacheSetting = CacheSetting()

        # 画质菜单
        self.qualityMenu = QMenu(self)
        quality_actions = [
            ("原画 (蓝光)", 10000),
            ("蓝光 (4K)", 4000),
            ("超清 (1080P)", 2500),
            ("高清 (720P)", 1500),
            ("流畅 (480P)", 800),
        ]
        for name, qn in quality_actions:
            act = QAction(name, self)
            act.triggered.connect(
                lambda checked=False, q=qn: self._set_global_quality(q))
            self.qualityMenu.addAction(act)

        # 信号连接
        self.btn_layout.clicked.connect(self._show_layout_menu)
        self.btn_switch.clicked.connect(self._show_tile_switcher)
        self.btn_pause_all.toggled.connect(self._toggle_pause_all)
        self.btn_close_all.clicked.connect(self._close_all)
        self.btn_mute_all.toggled.connect(self._toggle_mute_all)
        self.btn_quality.clicked.connect(self._show_quality_menu)
        self.btn_ttwid.clicked.connect(self._set_ttwid)
        self.btn_sessdata.clicked.connect(self._set_sessdata)
        self.btn_open_clips.clicked.connect(self._open_clips)
        self.btn_startlive.toggled.connect(self._on_startlive_toggled)
        self.btn_cache.clicked.connect(self._open_cache_setting)

        # 状态监控
        self.worker = StatusMonitorWorker()
        self.worker.status_updated.connect(self._on_status)
        self.worker.start()

        self._init_tray()
        QTimer.singleShot(500, self._detect_orientation)

        # 预填直播间
        if self._preload_rooms_list:
            QTimer.singleShot(
                800, lambda: self._preload_rooms(self._preload_rooms_list))

        # 初始化「当前路数」显示
        self._update_current_channel_label()

    @staticmethod
    def _mk_tool(text, checkable=False):
        b = QPushButton(text)
        b.setCheckable(checkable)
        b.setFixedHeight(28)
        b.setStyleSheet(
            "QPushButton{padding:3px 10px;border:1px solid #555;"
            "border-radius:3px;background:#2d2d2d;color:#ddd;font-size:12px;}"
            "QPushButton:hover{background:#3d3d3d;}"
            "QPushButton:checked{background:#a33;border-color:#c55;}")
        return b

    # ---------- 当前路数标签 ---------- #
    def _update_current_channel_label(self):
        """根据当前布局，更新「当前路数」标签"""
        used = self.layout_mgr.used_count()
        name = LAYOUTS.get(self.layout_mgr.current_key, {}).get("name", "-")
        self.current_channel_label.setText(
            f"当前路数: {used} ({name})")

    # ---------- 最大路数动态修改 ---------- #
    def _on_channel_count_changed(self, new_count: int):
        """根据新的最大路数，增删 tile"""
        if self._updating_channel_spin:
            return
        old_count = len(self.tiles)
        if new_count == old_count:
            self._max_channels = new_count
            return

        if new_count > old_count:
            for i in range(old_count, new_count):
                t = ChromeTile(i)
                self.tiles.append(t)
            print(f"[路数] 增加到 {new_count}")
        else:
            # 关闭多余 tile 并释放资源
            for t in self.tiles[new_count:]:
                try:
                    t.shutdown()
                except Exception:
                    pass
                t.setParent(None)
                t.deleteLater()
            self.tiles = self.tiles[:new_count]
            print(f"[路数] 减少到 {new_count}")

        self._max_channels = new_count
        self.layout_mgr.register_tiles(self.tiles)

        # 退出聚焦模式
        if self._focused:
            self._focused = False
            self._saved_tiles_order = []
            self._saved_layout_key = ""

        # 挑选合适的布局：优先刚好容纳，其次稍大一点的
        layout_key = self._pick_layout_for(new_count)
        if layout_key:
            self.layout_mgr.apply(layout_key)
            self._toast.show_text(
                f"路数: {new_count} · {LAYOUTS[layout_key]['name']}")
        else:
            # 实在没有合适的布局，退回默认 9 路
            self.layout_mgr.apply("split_9")
        self._update_current_channel_label()

    @staticmethod
    def _pick_layout_for(n: int) -> Optional[str]:
        """为 n 路选择最合适的布局 key：
        - 优先恰好 n 路的布局
        - 否则返回第一个能容纳 n 路的布局
        """
        exact = {
            1: "split_1",
            2: "split_2lr",
            4: "split_4",
            6: "split_6",
            9: "split_9",
        }
        if n in exact:
            return exact[n]
        # 找能容纳 n 的最小布局
        for key in LAYOUT_NAV_ORDER:
            spec = LAYOUTS.get(key)
            if spec and spec.get("_tile_count", 0) >= n:
                return key
        return None

    # ---------- 预填直播间 ---------- #
    def _preload_rooms(self, room_ids):
        print(f"[启动] 预填 {len(room_ids)} 个直播间: {room_ids}")
        for i, rid in enumerate(room_ids):
            if i >= len(self.tiles):
                break
            rid_str = str(rid).strip()
            if rid_str.startswith("http"):
                url = rid_str
            elif rid_str.isdigit():
                url = f"https://live.bilibili.com/{rid_str}"
            else:
                url = rid_str
            t = self.tiles[i]
            t.url_input.setText(url)
            QTimer.singleShot(i * 400, lambda _t=t: _t.load_url())

    # ---------- 画面编号切换 ---------- #
    def _show_tile_switcher(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#2d2d2d;color:#ddd;border:1px solid #555;}"
            "QMenu::item{padding:5px 24px;}"
            "QMenu::item:selected{background:#3a6ea5;}"
            "QMenu::separator{height:1px;background:#444;margin:4px 8px;}")

        if self._focused:
            act = menu.addAction("◆ 恢复总览布局")
            act.triggered.connect(self._unfocus_tile)
            menu.addSeparator()

        for i, t in enumerate(self.tiles):
            has_stream = " ●" if t._url else ""
            act = menu.addAction(f"画面 {i + 1}{has_stream}")
            act.triggered.connect(
                lambda checked=False, idx=i: self._focus_tile(idx))

        menu.exec(self.btn_switch.mapToGlobal(
            self.btn_switch.rect().bottomLeft()))

    def _focus_tile(self, idx):
        if not self._focused:
            self._saved_layout_key = self.layout_mgr.current_key
            self._saved_tiles_order = list(self.tiles)
            self._focused = True
        target = self.tiles[idx]
        reordered = [target] + [t for t in self.tiles if t is not target]
        self.layout_mgr.register_tiles(reordered)
        self.layout_mgr.apply("split_1")
        self._toast.show_text(f"聚焦画面 {idx + 1}")
        self._update_current_channel_label()

    def _unfocus_tile(self):
        if not self._focused:
            return
        self.layout_mgr.register_tiles(self._saved_tiles_order)
        self.layout_mgr.apply(self._saved_layout_key or "split_4")
        self._toast.show_text("已恢复总览布局")
        self._focused = False
        self._saved_tiles_order = []
        self._saved_layout_key = ""
        self._update_current_channel_label()

    # ---------- 布局菜单 ---------- #
    def _show_layout_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#2d2d2d;color:#ddd;border:1px solid #555;}"
            "QMenu::item{padding:4px 20px;}"
            "QMenu::item:selected{background:#3a6ea5;}"
            "QMenu::separator{height:1px;background:#444;margin:4px 8px;}")

        sub = menu.addMenu("平分布局")
        for k in ("split_1", "split_2ud", "split_2lr",
                  "split_4", "split_6", "split_9"):
            spec = LAYOUTS.get(k)
            if spec:
                act = sub.addAction(spec["name"])
                act.triggered.connect(
                    lambda checked=False, key=k: self._apply_layout(key))

        sub = menu.addMenu("大带小")
        for k in ("bs_m2r", "bs_2lm", "bs_m3r", "bs_m4r",
                  "bs_tm2b", "bs_m5around", "bs_2m4s"):
            spec = LAYOUTS.get(k)
            if spec:
                act = sub.addAction(spec["name"])
                act.triggered.connect(
                    lambda checked=False, key=k: self._apply_layout(key))

        sub = menu.addMenu("竖屏布局")
        for k in ("v_m2s", "v_m4s", "v_m6s"):
            spec = LAYOUTS.get(k)
            if spec:
                act = sub.addAction(spec["name"])
                act.triggered.connect(
                    lambda checked=False, key=k: self._apply_layout(key))

        cur = self.layout_mgr.current_key
        for act in menu.findChildren(QAction):
            if act.text() and LAYOUTS.get(cur, {}).get("name") == act.text():
                act.setCheckable(True)
                act.setChecked(True)

        menu.exec(self.btn_layout.mapToGlobal(
            self.btn_layout.rect().bottomLeft()))

    def _apply_layout(self, key):
        spec = LAYOUTS.get(key)
        if not spec:
            return
        if self._focused:
            self._focused = False
            self._saved_tiles_order = []
            self._saved_layout_key = ""
        self.layout_mgr.apply(key)
        # ★ 更新当前路数显示
        self._update_current_channel_label()

    def _navigate_layout(self, direction: int):
        if self._focused:
            self._unfocus_tile()
            return
        cur = self.layout_mgr.current_key
        order = LAYOUT_NAV_ORDER
        if cur in order:
            idx = order.index(cur)
            new_idx = (idx + direction) % len(order)
        else:
            new_idx = 0 if direction > 0 else len(order) - 1
        new_key = order[new_idx]
        if new_key == cur:
            return
        self._apply_layout(new_key)
        name = LAYOUTS.get(new_key, {}).get("name", new_key)
        self._toast.show_text(f"◀  {name}  ▶")

    # ---------- 方向自适应 ---------- #
    def _detect_orientation(self):
        w, h = self.width(), self.height()
        new = "v" if h > w * 1.15 else "h"
        if new == self._orientation:
            return
        self._orientation = new
        if self._focused:
            return
        cur = self.layout_mgr.current_key
        spec = LAYOUTS.get(cur)
        if spec:
            mir = spec.get("mirror", "")
            mspec = LAYOUTS.get(mir)
            if mspec and mspec["orientation"] == new:
                self._apply_layout(mir)
                return
            if new == "v":
                self._apply_layout("v_m2s")
            else:
                self._apply_layout("split_9")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._detect_orientation)

    # ---------- 关注 & 开播提醒 ---------- #
    def _on_follow_toggle(self, info: RoomInfo):
        key = (info.platform, info.room_id)
        for r in self._all_rooms:
            if (r.platform, r.room_id) == key:
                r.followed = not r.followed
                info.followed = r.followed
                break
        self.worker.set_rooms(self._all_rooms)
        self.status_panel.update_room_status(info)

    def _on_startlive_toggled(self, checked):
        self.config_startlive = checked
        print(f"[开播提醒] {'开启' if checked else '关闭'}")

    def _on_status(self, info: RoomInfo):
        key = (info.platform, info.room_id)
        prev_status = self._room_states.get(key)
        self._room_states[key] = info.live_status
        self.status_panel.update_room_status(info)

        if (info.followed and self.config_startlive
                and info.live_status == 1 and prev_status != 1):
            name = info.anchor_name or info.room_id
            pname = PLATFORMS.get(info.platform, {}).get("name", info.platform)
            self.startLiveWindow.show_message(
                f"🎉 [{pname}] {name} 开播了！")
            try:
                self._tray.showMessage(
                    "开播提醒", f"[{pname}] {name} 开播了！",
                    QSystemTrayIcon.MessageIcon.Information, 4000)
            except Exception:
                pass

    # ---------- 其他功能 ---------- #
    def _on_slice_changed(self, v):
        global SLICE_MAX_MINUTES
        SLICE_MAX_MINUTES = int(v)

    def _open_add(self):
        dlg = AddRoomDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_data:
            key = (dlg.result_data.platform, dlg.result_data.room_id)
            for r in self._all_rooms:
                if (r.platform, r.room_id) == key:
                    QMessageBox.information(self, "添加直播间", "该直播间已存在")
                    return
            self._all_rooms.append(dlg.result_data)
            self.worker.set_rooms(self._all_rooms)
            self.status_panel.update_room_status(dlg.result_data)

    def _on_room_dc(self, info: RoomInfo):
        for t in self.tiles:
            if not t._url:
                url = info.url or PLATFORMS.get(
                    info.platform, {}).get("url", "").format(id=info.room_id)
                if url:
                    t.url_input.setText(url)
                    t.load_url()
                return

    def _toggle_pause_all(self, checked):
        for t in self.tiles:
            if checked and not t._is_paused:
                t._on_pause()
            elif not checked and t._is_paused:
                t._on_pause()

    def _close_all(self):
        for t in self.tiles:
            t.close_view()

    def _toggle_mute_all(self, checked):
        for t in self.tiles:
            t.set_mute(checked)

    def _show_quality_menu(self):
        self.qualityMenu.exec(QCursor.pos())

    def _set_global_quality(self, quality):
        quality_names = {10000: "原画", 4000: "蓝光",
                         2500: "超清", 1500: "高清", 800: "流畅"}
        for t in self.tiles:
            t._quality = quality
            idx = (list(quality_names.keys()).index(quality)
                   if quality in quality_names else 0)
            t.cmb_quality.setCurrentIndex(idx)
            t._wv_js(f"window.__bili_quality={quality};")

    def _set_ttwid(self):
        txt, ok = QInputDialog.getText(
            self, "抖音 ttwid", "从浏览器复制 ttwid：",
            text=DouyinStatusChecker.MANUAL_TTWID)
        if ok and txt.strip():
            DouyinStatusChecker.MANUAL_TTWID = txt.strip()
            DouyinStatusChecker._ttwid = None

    def _set_sessdata(self):
        global BILIBILI_SESSDATA
        txt, ok = QInputDialog.getText(
            self, "B站 SESSDATA", "从浏览器 Cookie 复制 SESSDATA：",
            text=BILIBILI_SESSDATA)
        if ok:
            BILIBILI_SESSDATA = txt.strip()

    def _open_clips(self):
        d = os.path.join(APP_DIR, "clips")
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def _open_cache_setting(self):
        self.cacheSetting.show()

    # ---------- 托盘 ---------- #
    def _init_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ComputerIcon))
        menu = QMenu()
        a = QAction("显示", self)
        a.triggered.connect(lambda: (self.showNormal(), self.activateWindow()))
        q = QAction("退出", self)
        q.triggered.connect(self._quit)
        menu.addAction(a)
        menu.addSeparator()
        menu.addAction(q)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _quit(self):
        self.worker.stop()
        for t in self.tiles:
            t.shutdown()
        QApplication.instance().quit()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self._tray.showMessage("DD_Monitor", "已最小化到托盘",
                               QSystemTrayIcon.MessageIcon.Information, 2000)


# =========================================================================== #
#  入口
# =========================================================================== #
def main():
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--room", action="append", default=[],
                        help="预填直播间房间号（可重复）")
    parser.add_argument("--rows", type=int, default=0)
    parser.add_argument("--cols", type=int, default=0)
    parser.add_argument("--skip-dialog", action="store_true",
                        help="跳过启动对话框，直接进入主界面")
    args, _ = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not HAS_WEBVIEW2:
        QMessageBox.critical(None, "缺少依赖", "pip install qtwebview2")
        sys.exit(1)

    # 决定行列数
    if args.rows > 0 and args.cols > 0:
        rows, cols = args.rows, args.cols
    elif args.skip_dialog and args.room:
        n = len(args.room)
        if n <= 1:
            rows, cols = 1, 1
        elif n <= 2:
            rows, cols = 1, 2
        elif n <= 4:
            rows, cols = 2, 2
        elif n <= 6:
            rows, cols = 2, 3
        else:
            rows, cols = 3, 3
    elif args.skip_dialog:
        # ★ 默认 9 路
        rows, cols = 3, 3
    else:
        dlg = StartupDialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        rows, cols = dlg.rows, dlg.cols

    w = MainWindow(rows, cols, preload_rooms=args.room)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()