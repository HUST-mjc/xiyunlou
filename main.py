import sys
import json
import os
import time
import threading
import subprocess 
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from music_player import MusicPlayer, MusicPlayerDialog
from PyQt6.QtWidgets import (
    QApplication, QLabel, QMenu, QDialog, QMessageBox,
    QDialogButtonBox, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QGraphicsOpacityEffect, QWidget, QInputDialog,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, QDate, QRectF
from PyQt6.QtGui import (
    QPainter, QAction, QIcon, QSurfaceFormat, QPixmap, QCursor, QFontMetrics, QColor
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from pynput import mouse

# 假设这些模块存在于同一目录或已安装
from settings import GlobalSettings, SettingsDialog
from update_checker import UpdateChecker
from character_manager import CharacterManager
from input_handler import InputHandler, MouseTracker
from tray_manager import TrayManager
from window_manager import WindowManager
from custom_layer_manager import (
    CustomLayerManager, CustomLayer, DefaultLayer, build_all_layers,
)
from custom_layer_dialog import CustomLayerDialog
from path_manager import path_manager
from key_lines_manager import KeyLineManager

from pomodoro import PomodoroTimer
from character_stats import CharacterDailyStats
from sticky_note import StickyNote
from jump_links import JumpHelper
from games_launcher import launch_game
from weather_op import (
    WeatherService, WeatherAnimWidget, WMO_CODE_MAP,
)

# ============================================================
#  默认直播间号
# ============================================================
DEFAULT_LIVE_ROOMS = {
    "梨安": 23770996,
    "又一": 23771092,
    "沐霂": 23771139,
    "恬豆": 23771189,
    "明前奶绿": 25034104,
}

LIVE_ROOM_ALIASES = {
    "梨安不迷路": "梨安",
    "又一充电中": "又一",
    "沐霂是mumu呀": "沐霂",
    "恬豆发芽了": "恬豆",
}

# ============================================================
#  顶部额外空间高度（用于显示天气/直播状态等标签，图片不受影响）
#  想预留更高/更低时改这个值即可
# ============================================================
TOP_HEADER_HEIGHT = 70

# ============================================================
#  番茄钟默认向下偏移量（像素）
#  数值越大，番茄钟越靠下；负数则上移
#  也可以在角色设置中通过 "pomodoro_offset_y" 键覆盖
# ============================================================
DEFAULT_POMODORO_OFFSET_Y = 30


def resolve_default_room(character_name):
    if not character_name:
        return 0
    if character_name in DEFAULT_LIVE_ROOMS:
        return DEFAULT_LIVE_ROOMS[character_name]
    alias = LIVE_ROOM_ALIASES.get(character_name)
    if alias and alias in DEFAULT_LIVE_ROOMS:
        return DEFAULT_LIVE_ROOMS[alias]
    for k, v in DEFAULT_LIVE_ROOMS.items():
        if k in character_name:
            return v
    return 0


# ============================================================
#  自定义滚动标签 (实现跑马灯效果)
# ============================================================
class ScrollingLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._offset = 0
        self._speed = 1.0  # 像素/帧
        self._pause_time = 2000  # 滚动完暂停毫秒数
        self._last_move_time = 0

        # 定时器用于动画
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._update_scroll)
        self._anim_timer.start(16)  # ~60 FPS

    def set_scrolling_text(self, text):
        self._full_text = text
        self._offset = 0
        self._last_move_time = time.time() * 1000
        self.update()

    def _update_scroll(self):
        if not self._full_text:
            return

        now = time.time() * 1000
        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(self._full_text)
        label_width = self.width()

        # 如果文字比标签短，不需要滚动，居中显示即可（由父类处理）
        if text_width <= label_width:
            self.setText(self._full_text)
            return

        # 如果需要滚动
        self.setText("")  # 清空默认文本，由 paintEvent 绘制

        # 检查是否处于暂停期
        if now - self._last_move_time < self._pause_time:
            return

        self._offset -= self._speed
        # 如果完全滚出视野，重置
        if abs(self._offset) > text_width + 20:
            self._offset = label_width
            self._last_move_time = now

        self.update()

    def paintEvent(self, event):
        if not self._full_text:
            super().paintEvent(event)
            return

        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(self._full_text)
        label_width = self.width()

        # 如果文字较短，直接调用父类绘制（居中/左对齐）
        if text_width <= label_width:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 设置画笔颜色
        painter.setPen(self.palette().text().color())

        # 计算绘制位置
        y_pos = (self.height() - fm.height()) // 2 + fm.ascent()

        # 绘制滚动文字
        painter.drawText(int(self._offset), int(y_pos), self._full_text)

        painter.end()


# ============================================================
#  Settings → dict 适配器
# ============================================================
class SettingsProxy(dict):
    _KNOWN_KEYS = (
        "pomodoro", "char_stats", "special_days", "special_day_notified",
        "sticky_note", "sticky_pos", "sticky_font_size",
        "note_bg_file", "note_text_color", "note_bg_color",
        "url_history", "game_launcher", "game_launcher_path",
        "weather_city", "weather_lat", "weather_lon",
        "weather_check_interval", "show_weather",
        "external_player", "external_player_path",
        "show_subtitle", "lyrics_text_color", "lyrics_bg_color",
        "idle_seconds", "dynamic_check_interval",
        "play_op_on_start", "dynamic_notify_voice",
        "show_key_display", "key_display_anchor",
        "key_display_text_color", "key_display_bg_color",
        "key_display_map",
        "live_room_id", "live_check_interval",
        # 番茄钟
        "pomodoro_focus_minutes", "pomodoro_break_minutes",
        "pomodoro_offset_y",
    )

    def __init__(self, settings):
        super().__init__()
        self._settings = settings
        for k in self._KNOWN_KEYS:
            try:
                v = settings.get(k)
                if v is not None:
                    super().__setitem__(k, v)
            except Exception:
                pass

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        try:
            self._settings.set(key, value)
        except Exception as e:
            print(f"[SettingsProxy] set '{key}' 失败: {e}")

    def setdefault(self, key, default):
        if key not in self:
            try:
                v = self._settings.get(key)
                if v is not None:
                    super().__setitem__(key, v)
                    return super().__getitem__(key)
            except Exception:
                pass
            self[key] = default
        return super().__getitem__(key)

    def save(self):
        for k, v in list(self.items()):
            try:
                self._settings.set(k, v)
            except Exception:
                pass
        try:
            self._settings.save()
        except Exception as e:
            print(f"[SettingsProxy] save 失败: {e}")

    def refresh_from_settings(self):
        for k in self._KNOWN_KEYS:
            try:
                v = self._settings.get(k)
                if v is not None:
                    dict.__setitem__(self, k, v)
            except Exception:
                pass


# ============================================================
#  特殊日子对话框
# ============================================================
class SpecialDayDialog(QDialog):
    def __init__(self, cfg, save_fn, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._save = save_fn
        self.setWindowTitle("特殊日子")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(620, 460)

        layout = QVBoxLayout(self)
        tip = QLabel("特殊日子当天会自动提醒。可导出 .ics 到系统日历。")
        tip.setStyleSheet("color: #666; font-size: 11px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["日期", "名称"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        add_row = QHBoxLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：ComiDay / 生日")
        btn_add = QPushButton("添加 / 更新")
        btn_add.clicked.connect(self._on_add)
        add_row.addWidget(QLabel("日期："))
        add_row.addWidget(self.date_edit)
        add_row.addWidget(QLabel("名称："))
        add_row.addWidget(self.name_edit)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        op_row = QHBoxLayout()
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._on_delete)
        btn_clear = QPushButton("清空全部")
        btn_clear.clicked.connect(self._on_clear)
        btn_export = QPushButton("导出 .ics")
        btn_export.clicked.connect(self._on_export)
        op_row.addWidget(btn_del)
        op_row.addWidget(btn_clear)
        op_row.addStretch()
        op_row.addWidget(btn_export)
        layout.addLayout(op_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_table()

    def _refresh_table(self):
        sd = self.cfg.get("special_days", {}) or {}
        self.table.setRowCount(0)
        for d in sorted(sd.keys()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(d))
            self.table.setItem(r, 1, QTableWidgetItem(sd[d]))

    def _on_add(self):
        d = self.date_edit.date().toString("yyyy-MM-dd")
        n = self.name_edit.text().strip()
        if not n:
            return
        self.cfg.setdefault("special_days", {})[d] = n
        self._save(self.cfg)
        self.name_edit.clear()
        self._refresh_table()

    def _on_delete(self):
        rows = {i.row() for i in self.table.selectedItems()}
        sd = self.cfg.setdefault("special_days", {})
        for r in rows:
            it = self.table.item(r, 0)
            if it:
                sd.pop(it.text(), None)
        self._save(self.cfg)
        self._refresh_table()

    def _on_clear(self):
        if not self.cfg.get("special_days"):
            return
        if QMessageBox.question(self, "确认", "清空所有？") \
                == QMessageBox.StandardButton.Yes:
            self.cfg["special_days"] = {}
            self._save(self.cfg)
            self._refresh_table()

    def _on_export(self):
        sd = self.cfg.get("special_days", {}) or {}
        if not sd:
            return
        try:
            ics = os.path.join(os.getcwd(), "special_days.ics")
            lines = [
                "BEGIN:VCALENDAR", "VERSION:2.0",
                "PRODID:-//DeskPet//SpecialDays//CN",
                "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
            ]
            now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            for ds, nm in sorted(sd.items()):
                try:
                    d = datetime.strptime(ds, "%Y-%m-%d").date()
                except Exception:
                    continue
                de = d + timedelta(days=1)
                lines += [
                    "BEGIN:VEVENT", f"UID:{ds}@deskpet",
                    f"DTSTAMP:{now}",
                    f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                    f"DTEND;VALUE=DATE:{de.strftime('%Y%m%d')}",
                    f"SUMMARY:{nm}", "END:VEVENT",
                ]
            lines.append("END:VCALENDAR")
            with open(ics, "w", encoding="utf-8", newline="\r\n") as f:
                f.write("\n".join(lines))
            os.startfile(ics)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))


# ============================================================
#  DesktopPet 主类
# ============================================================
class DesktopPet(QOpenGLWidget):
    key_press_signal = pyqtSignal(object)
    key_release_signal = pyqtSignal()
    live_update_signal = pyqtSignal(str, int, str)

    LIVE_API = ("https://api.live.bilibili.com/room/v1/Room/get_info"
                "?room_id={room_id}")
    LIVE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/120.0.0.0 Safari/537.36")

    def __init__(self):
        super().__init__()
        self.key_press_signal.connect(self._on_key_press_signal)
        self.key_release_signal.connect(self._on_key_release_signal)
        self.live_update_signal.connect(self._on_live_ui_update)

        # 全局设置
        self.global_settings = GlobalSettings()

        # 窗口管理
        self.window_manager = WindowManager(self, self.global_settings)
        self.always_on_top = self.window_manager.always_on_top
        self.mouse_passthrough = self.window_manager.mouse_passthrough
        self.hide_taskbar = self.window_manager.hide_taskbar
        self.mouse_locked = self.window_manager.mouse_locked
        self.keyboard_horizontal_offset = \
            self.window_manager.keyboard_horizontal_offset
        self.keypress_display_enabled = \
            self.window_manager.keypress_display_enabled
        self.keypress_display_background = \
            self.window_manager.keypress_display_background

        # 角色管理
        self.character_manager = CharacterManager()
        self.character_manager.initialize_from_global_settings(
            self.global_settings)
        self.key_lines_manager = KeyLineManager(base_dir="img")

        # 自定义图层
        self.custom_layer_manager = CustomLayerManager(
            self.character_manager.current_character)
        self.custom_layers = []

        self.settings = self.character_manager.settings
        self.window_width = self.settings.get('window_width')
        self.window_height = self.settings.get('window_height')

        # 顶部额外空间：窗口向上扩展，图片屏幕位置不变
        self.top_header_height = TOP_HEADER_HEIGHT
        self._actual_window_height = (
            self.window_height + self.top_header_height)

        self._settings_proxy = SettingsProxy(self.settings)

        # 运行时长
        self._load_runtime_stats()
        self.start_time = time.time()

        # 托盘
        self.tray_manager = TrayManager(self)
        self.tray_manager.init_tray()

        # 番茄钟
        self._pomodoro = PomodoroTimer(
            self._settings_proxy, self._save_settings)
        self._pomodoro.tick.connect(self._on_pomodoro_tick)
        self._pomodoro.finished.connect(self._on_pomodoro_finished)
        self._pomodoro_text = ""

        # 角色统计
        self._char_stats = CharacterDailyStats(
            self._settings_proxy, self._save_settings)

        # 便利贴
        self.sticky_note = None

        # 跳转
        self.jump_helper = JumpHelper(
            self._settings_proxy, self._save_settings)

        # 天气
        self._weather_text = ""
        self._weather_temp = None
        self._weather_code = None
        self._weather_service = None
        self._weather_started = False
        self._last_weather_city = self.settings.get('weather_city', '北京')

        # 特殊日子
        self._special_day_notified = ""

        # 直播间
        self._live_monitor_running = True
        self._live_monitor_enabled = True
        self._live_monitor_thread = None
        self._live_status_map = {}
        self._live_prev_status = {}
        self._live_last_text = ""
        self._last_live_debug_key = ""
        # ★ 立即重检信号
        self._live_recheck_now = threading.Event()

        # UI
        self.init_ui()
        # ===== 音乐播放器初始化（B站纯音频 + 悬浮歌词） =====
        # pet_window=self：歌词窗口会自动悬浮在桌宠上方
        self.music_player = MusicPlayer(pet_window=self)
        self._music_dlg = None
        # ====================================================
        # 输入处理器
        self.input_handler = InputHandler(
            self.settings,
            self._handle_key_press,
            self._handle_key_release,
            self._handle_mouse_click,
            self.keyboard_horizontal_offset,
        )
        self.mouse_tracker = MouseTracker(self.settings, self.mouse_locked)
        self.input_handler.start_listeners()

        # 鼠标定时器
        self.mouse_timer = QTimer()
        self.mouse_timer.timeout.connect(self._update_mouse_position)
        self.mouse_timer.start(16)

        # 自定义图层位置
        self.custom_layer_timer = QTimer()
        self.custom_layer_timer.timeout.connect(
            self.update_custom_layers_position)
        self.custom_layer_timer.start(16)

        # 陪伴时间
        self._companion_action = None
        self.companion_timer = QTimer()
        self.companion_timer.timeout.connect(self._update_companion_display)
        self.companion_timer.start(1000)

        # 特殊日子
        self.special_timer = QTimer()
        self.special_timer.timeout.connect(self._check_special_day_notify)
        self.special_timer.start(60000)

        # 信息栏
        self.info_timer = QTimer()
        self.info_timer.timeout.connect(self._update_info_display)
        self.info_timer.start(1000)

        # 启动服务
        QTimer.singleShot(1000, self._start_live_monitor)
        QTimer.singleShot(2000, self._start_weather_service)
        QTimer.singleShot(3000, self._check_special_day_notify)
        QTimer.singleShot(1500, self._refresh_live_ui)
        QTimer.singleShot(2500, self._refresh_weather_ui)

        app.aboutToQuit.connect(self._save_runtime_stats)

        self._is_keypress_preview_active = False
        self._keypress_preview_text = "Ctrl"

    # ============================================================
    #  运行时长
    # ============================================================
    def _load_runtime_stats(self):
        stats_file = path_manager.get_stats_file()
        try:
            if os.path.exists(stats_file):
                with open(stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.total_runtime = data.get('total_runtime', 0)
            else:
                self.total_runtime = 0
        except Exception as e:
            print(f"加载运行时长失败: {e}")
            self.total_runtime = 0

    def _save_runtime_stats(self):
        if hasattr(self, 'start_time') and hasattr(self, 'total_runtime'):
            self.total_runtime += time.time() - self.start_time
        stats_file = path_manager.get_stats_file()
        try:
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {'total_runtime': getattr(self, 'total_runtime', 0)},
                    f, ensure_ascii=False,
                )
        except Exception as e:
            print(f"保存运行时长失败: {e}")

    def get_companion_time_text(self):
        if not hasattr(self, 'total_runtime'):
            return "陪伴：0秒"
        elapsed = self.total_runtime + (time.time() - self.start_time)
        if elapsed < 60:
            return f"陪伴：{int(elapsed)}秒"
        if elapsed < 3600:
            return f"陪伴：{int(elapsed // 60)}分{int(elapsed % 60)}秒"
        return f"陪伴：{int(elapsed // 3600)}时{int((elapsed % 3600) // 60)}分"

    def _update_companion_display(self):
        if self._companion_action:
            self._companion_action.setText(self.get_companion_time_text())

    def add_companion_action_to_menu(self, menu):
        companion_label = QAction(self.get_companion_time_text(), self)
        companion_label.setEnabled(False)
        menu.addAction(companion_label)
        self._companion_action = companion_label
        return companion_label

    # ============================================================
    #  设置保存
    # ============================================================
    def _save_settings(self, cfg=None):
        try:
            if isinstance(cfg, SettingsProxy):
                cfg.save()
            elif hasattr(self, "_settings_proxy"):
                self._settings_proxy.save()
            else:
                self.settings.save()
        except Exception as e:
            print(f"保存设置失败: {e}")

    # ============================================================
    #  直播间检测
    # ============================================================
    def _start_live_monitor(self):
        if self._live_monitor_thread is not None:
            return
        self._live_monitor_thread = threading.Thread(
            target=self._live_monitor_loop, daemon=True)
        self._live_monitor_thread.start()
        print("[直播] 检测线程已启动")

    def _get_live_rooms_to_check(self):
        """返回 {角色名: 房间号}"""
        if not getattr(self, "_live_monitor_enabled", True):
            return {}
        cur = self.character_manager.current_character
        if not cur:
            return {}

        room_id = 0
        source = "未知"

        # 1. 尝试直接从默认字典获取
        if cur in DEFAULT_LIVE_ROOMS:
            room_id = DEFAULT_LIVE_ROOMS[cur]
            source = "默认映射(精确)"

        # 2. 尝试通过别名解析
        elif cur in LIVE_ROOM_ALIASES:
            alias_name = LIVE_ROOM_ALIASES[cur]
            if alias_name in DEFAULT_LIVE_ROOMS:
                room_id = DEFAULT_LIVE_ROOMS[alias_name]
                source = f"默认映射(别名:{alias_name})"

        # 3. 尝试模糊匹配
        else:
            for name, rid in DEFAULT_LIVE_ROOMS.items():
                if name in cur or cur in name:
                    room_id = rid
                    source = f"默认映射(模糊:{name})"
                    break

        if room_id > 0:
            key = f"{cur}/{room_id}"
            if getattr(self, "_last_live_debug_key", None) != key:
                self._last_live_debug_key = key
                print(f"[直播] 使用{source}的房间号：角色={cur!r} 房间号={room_id}")
            return {cur: room_id}

        key = f"{cur}/NONE"
        if getattr(self, "_last_live_debug_key", None) != key:
            self._last_live_debug_key = key
            print(f"[直播] 警告: 无法在默认列表中确定角色 '{cur}' 的房间号")
        return {}

    def _check_live_status(self, room_id):
        try:
            url = self.LIVE_API.format(room_id=room_id)
            req = Request(url, headers={
                "User-Agent": self.LIVE_UA,
                "Referer": f"https://live.bilibili.com/{room_id}",
                "Origin": "https://live.bilibili.com",
                "Accept": "application/json, text/plain, */*",
            })
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0:
                d = data.get("data", {}) or {}
                return (int(d.get("live_status", 0)),
                        d.get("title", "") or "")
            else:
                print(f"[直播] room={room_id} API code="
                      f"{data.get('code')} msg={data.get('message')}")
        except Exception as e:
            print(f"[直播] room={room_id} 检测异常：{e}")
        return -1, ""

    def _live_monitor_loop(self):
        for _ in range(2):
            if not self._live_monitor_running:
                return
            time.sleep(1)

        while self._live_monitor_running:
            try:
                if not getattr(self, "_live_monitor_enabled", True):
                    self._wait_for_recheck_or_timeout(5)
                    continue

                rooms = self._get_live_rooms_to_check()
                if not rooms:
                    self._live_last_text = ""
                    self._wait_for_recheck_or_timeout(10)
                    continue

                for char, room_id in rooms.items():
                    if not self._live_monitor_running:
                        return
                    status, title = self._check_live_status(room_id)
                    self._live_status_map[room_id] = (status, title)

                    prev = self._live_prev_status.get(room_id)
                    if prev is None:
                        self._live_prev_status[room_id] = status
                    elif status != prev:
                        self._live_prev_status[room_id] = status
                        if status == 1 and prev == 0:
                            self._notify_live_start(char, title)
                        elif status == 0 and prev == 1:
                            self._notify_live_end(char)

                    cur = self.character_manager.current_character
                    if char == cur:
                        self._live_last_text = self._format_live_text(
                            char, status, title)

                    # 通知 UI 线程
                    self.live_update_signal.emit(char, status, title)

                self._update_info_display()

            except Exception as e:
                print(f"[直播] 循环异常：{e}")

            interval = int(
                self.settings.get("live_check_interval", 60) or 60)
            interval = max(10, interval)
            self._wait_for_recheck_or_timeout(interval)

    def _wait_for_recheck_or_timeout(self, seconds):
        """等待 seconds 秒，或被 _live_recheck_now 唤醒"""
        end = time.time() + seconds
        while time.time() < end:
            if not self._live_monitor_running:
                return
            if self._live_recheck_now.is_set():
                self._live_recheck_now.clear()
                return
            time.sleep(0.3)

    def _sleep_interruptible(self, seconds):
        self._wait_for_recheck_or_timeout(seconds)

    @staticmethod
    def _format_live_text(char, status, title):
        if status == 1:
            return f"📺 {char} 直播中"
        if status == 2:
            return f"📺 {char} 轮播中"
        if status == 0:
            return f"📺 {char} 未开播"
        return ""

    def _notify_live_start(self, char, title):
        msg = f"{char} 开播啦！"
        if title:
            msg += f"\n{title}"
        try:
            self.tray_manager.tray.showMessage(
                "B站直播通知", msg, 5000)
        except Exception:
            pass
        print(f"[直播] {char} 开播：{title}")

        # ★ 梨安/又一/沐霂/恬豆 中有人开播 → 自动拉起监控室
        auto_targets = {"梨安", "又一", "沐霂", "恬豆"}
        if char in auto_targets:
            now = time.time()
            last = getattr(self, "_last_monitor_launch", 0)
            if now - last > 300:   # 5 分钟内只自动启动一次
                self._last_monitor_launch = now
                print(f"[监控室] 检测到 {char} 开播，自动启动监控室")
                QTimer.singleShot(
                    800, lambda c=char: self._launch_monitor_room(c))
    def _notify_live_end(self, char):
        try:
            self.tray_manager.tray.showMessage(
                "B站直播通知", f"{char} 已下播", 5000)
        except Exception:
            pass
        print(f"[直播] {char} 已下播")

    def _show_live_status(self):
        cur = self.character_manager.current_character
        try:
            room_id = int(self.settings.get("live_room_id", 0) or 0)
        except (TypeError, ValueError):
            room_id = 0
        if room_id <= 0:
            room_id = resolve_default_room(cur)
        if room_id <= 0:
            QMessageBox.information(
                self, "直播状态",
                f"当前角色「{cur}」没有配置直播间，也没有默认房间号。")
            return
        status, title = self._live_status_map.get(room_id, (-1, ""))
        tag = {1: "🔴 直播中", 2: "🟠 轮播中",
               0: "⚫ 未开播", -1: "❓ 未知"}.get(status, "❓")
        text = f"{cur}（房间 {room_id}）：{tag}"
        if title and status in (1, 2):
            text += f"\n\n标题：{title}"
        QMessageBox.information(self, "直播状态", text)

    def _refresh_live_ui(self):
        """立即根据缓存刷新左上角直播状态标签"""
        cur = self.character_manager.current_character
        try:
            room_id = int(self.settings.get("live_room_id", 0) or 0)
        except (TypeError, ValueError):
            room_id = 0
        if room_id <= 0:
            room_id = resolve_default_room(cur)
        status, title = self._live_status_map.get(room_id, (-1, ""))
        self._on_live_ui_update(cur, status, title)

    def _on_live_ui_update(self, char, status, title):
        """主线程更新左上角直播状态标签 (使用滚动标签)"""
        cur = self.character_manager.current_character
        if char != cur:
            return

        if status == 1:
            text = f"🔴 {char} 直播中"
            bg_color = QColor(200, 40, 40, 220)
        elif status == 2:
            text = f"🟠 {char} 轮播中"
            bg_color = QColor(230, 130, 40, 220)
        elif status == 0:
            text = f"⚫ {char} 未开播"
            bg_color = QColor(80, 80, 80, 200)
        else:
            text = f"⏳ {char} 检测中…"
            bg_color = QColor(80, 80, 80, 200)

        if title and status in (1, 2):
            text += f" · {title}"

        if not hasattr(self, "info_live_label"):
            return

        # 设置滚动文本
        self.info_live_label.set_scrolling_text(text)

        # 更新背景色样式
        style = (
            "QLabel {"
            "  color: white;"
            f"  background: rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, {bg_color.alpha()});"
            "  border-radius: 8px;"
            "  font-size: 12px;"
            "  font-weight: bold;"
            "  padding: 2px 8px;"
            "}"
        )
        self.info_live_label.setStyleSheet(style)
        self.info_live_label.show()
        self.info_live_label.raise_()

    # ============================================================
    #  UI 初始化
    # ============================================================
    def init_ui(self):
        flags = Qt.WindowType.FramelessWindowHint
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(
            Qt.WidgetAttribute.WA_AlwaysStackOnTop, self.always_on_top)
        self.setWindowTitle("Xiyunlou")

        if self.character_manager.current_character:
            icon_path = os.path.join(
                "img", self.character_manager.current_character,
                "bgImage.png")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))

        # 窗口向上扩展：实际高度 = 图片高度 + 顶部预留
        self.resize(self.window_width, self._actual_window_height)
        self._set_window_position()

        # ============================================================
        # 图片容器：整体下移 top_header_height，
        # 让图片在屏幕上的位置保持不变；
        # 顶部空出的区域专门用来显示天气/直播状态等标签。
        # ============================================================
        self.image_container = QWidget(self)
        self.image_container.setGeometry(
            0, self.top_header_height,
            self.window_width, self.window_height)
        self.image_container.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground)

        # 天气动画（放在图片容器里，坐标与原来一致）
        self.weather_anim = WeatherAnimWidget(self.image_container)
        self.weather_anim.setGeometry(0, 0,
                                      self.window_width,
                                      self.window_height)
        self.weather_anim.lower()
        self.weather_anim.show()

        # 图层（父级为图片容器，坐标与原来一致）
        self.bg_label = QLabel(self.image_container)
        self.keyboard_label = QLabel(self.image_container)
        self.mouse_label = QLabel(self.image_container)
        self.left_click_label = QLabel(self.image_container)
        self.right_click_label = QLabel(self.image_container)

        # 按键显示（父级为图片容器，跟着图片走）
        self.keypress_display_label = QLabel(self.image_container)
        self._update_keypress_display_style()
        self.keypress_display_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self.keypress_display_label.hide()
        self.keypress_display_label.setGeometry(
            self.settings.get('keypress_display_x', 10),
            self.settings.get('keypress_display_y', 10),
            100, 40,
        )

        self.keypress_display_timer = QTimer()
        self.keypress_display_timer.timeout.connect(
            self._hide_keypress_display)
        self.keypress_display_timer.setSingleShot(True)

        # 番茄钟标签（父级为主窗口，底部定位，通过 offset 下移）
        self.pomodoro_display_label = QLabel(self)
        self.pomodoro_display_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self.pomodoro_display_label.hide()

        # --- 天气 / 直播标签：父级为主窗口，位于顶部预留区 ---
        info_style_base = (
            "QLabel {"
            "  color: white;"
            "  border-radius: 8px;"
            "  font-size: 12px;"
            "  font-weight: bold;"
            "  padding: 2px 8px;"
            "}"
        )

        # 天气标签（左上 - 上方）
        self.info_weather_label = ScrollingLabel(self)
        self.info_weather_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_weather_label.setStyleSheet(
            info_style_base +
            "  background: rgba(40, 100, 180, 200);"
        )
        self.info_weather_label.set_scrolling_text("🌤 加载中…")
        self.info_weather_label.show()

        # 直播状态标签（左上 - 下方，紧邻天气）
        self.info_live_label = ScrollingLabel(self)
        self.info_live_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_live_label.setStyleSheet(
            info_style_base +
            "  background: rgba(80, 80, 80, 200);"
        )
        cur = self.character_manager.current_character or ""
        self.info_live_label.set_scrolling_text(f"⏳ {cur} 检测中…")
        self.info_live_label.show()

        # 加载
        self.load_character_images()
        self.create_custom_layers()
        self.window_manager.apply_mouse_passthrough()

        self.dragging = False
        self.drag_position = QPoint()

        self.show()

        self._layout_overlay_labels()

        if self.hide_taskbar:
            self.window_manager.apply_hide_taskbar()

        self.window_manager.show_first_launch_tip()
        QTimer.singleShot(1000, self.check_for_updates)

    def _set_window_position(self):
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        window_x = self.global_settings.get('window_x')
        window_y = self.global_settings.get('window_y')
        if window_x is None or window_y is None:
            center_x = (screen_geometry.width() - self.window_width) // 2
            center_y = (screen_geometry.height()
                        - self._actual_window_height) // 2
            self.move(center_x, center_y)
        else:
            # window_y 保存的是“图片区域顶部”的位置；
            # 窗口为了顶部标签额外向上扩展，因此实际 y 要减去偏移
            new_y = window_y - self.top_header_height
            if new_y < 0:
                new_y = 0
            self.move(window_x, new_y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_overlay_labels()

    # ============================================================
    #  覆盖标签布局
    # ============================================================
    def _layout_overlay_labels(self):
        w = max(self.window_width, 100)
        h = max(self._actual_window_height, 60)

        top_margin = 6
        label_height = 24
        label_width = min(w - 2 * top_margin, 250)

        # 1. 天气标签（顶部上方）
        if hasattr(self, 'info_weather_label'):
            self.info_weather_label.setGeometry(
                top_margin, top_margin,
                label_width, label_height)

        # 2. 直播标签（紧贴天气下方）
        if hasattr(self, 'info_live_label'):
            self.info_live_label.setGeometry(
                top_margin, top_margin + label_height + 4,
                label_width, label_height)

        # 番茄钟标签（底部居中）
        #   pomodoro_offset_y > 0  → 向下移动（可部分超出窗口底部）
        #   pomodoro_offset_y = 0  → 底部保留 6px 内边距
        #   pomodoro_offset_y < 0  → 向上移动
        if hasattr(self, 'pomodoro_display_label'):
            font_size = max(24, min(64, w // 6))
            ph = int(font_size * 1.6)
            try:
                offset_y = int(self.settings.get(
                    'pomodoro_offset_y', DEFAULT_POMODORO_OFFSET_Y) or 0)
            except (TypeError, ValueError):
                offset_y = DEFAULT_POMODORO_OFFSET_Y
            py = h - ph - 6 + offset_y
            self.pomodoro_display_label.setStyleSheet(
                "QLabel {"
                "  color: white;"
                "  background: rgba(200, 40, 40, 210);"
                "  border-radius: 12px;"
                f"  font-size: {font_size}px;"
                "  font-weight: bold;"
                "  padding: 4px 12px;"
                "}"
            )
            self.pomodoro_display_label.setGeometry(0, py, w, ph)

        # 层级提升
        if hasattr(self, 'info_weather_label'):
            self.info_weather_label.raise_()
        if hasattr(self, 'info_live_label'):
            self.info_live_label.raise_()
        if (hasattr(self, 'pomodoro_display_label')
                and self.pomodoro_display_label.isVisible()):
            self.pomodoro_display_label.raise_()

    def _layout_pomodoro_display(self):
        self._layout_overlay_labels()

    # ============================================================
    #  图片 / 图层
    # ============================================================
    def load_character_images(self):
        labels_dict = {
            'bg': self.bg_label,
            'keyboard': self.keyboard_label,
            'mouse': self.mouse_label,
            'left_click': self.left_click_label,
            'right_click': self.right_click_label,
        }
        self.character_manager.load_character_images(labels_dict)

    def create_custom_layers(self):
        all_layers = build_all_layers(
            self.character_manager.current_character,
            self.custom_layer_manager)
        self._rebuild_custom_layer_labels(all_layers)
        self._apply_default_layers_from_list(all_layers)
        self._restack_all_layers(all_layers)

    def _rebuild_custom_layer_labels(self, all_layers):
        for label in self.custom_layers:
            label.deleteLater()
        self.custom_layers.clear()

        for layer in all_layers:
            if isinstance(layer, CustomLayer):
                if os.path.exists(layer.image_path):
                    label = QLabel(self.image_container)
                    label.setPixmap(QPixmap(layer.image_path))
                    label.setScaledContents(True)
                    if layer.opacity < 1.0:
                        effect = QGraphicsOpacityEffect()
                        effect.setOpacity(layer.opacity)
                        label.setGraphicsEffect(effect)
                    x, y = self.calculate_layer_position(layer)
                    label.setGeometry(x, y, layer.width, layer.height)
                    label.show() if layer.visible else label.hide()
                    self.custom_layers.append(label)
                else:
                    label = QLabel(self.image_container)
                    label.hide()
                    self.custom_layers.append(label)

    def calculate_layer_position(self, layer):
        base_x, base_y = layer.x, layer.y
        if layer.follow_type == "keyboard":
            kb_geometry = self.keyboard_label.geometry()
            return base_x + kb_geometry.x(), base_y + kb_geometry.y()
        if layer.follow_type == "mouse":
            m_geometry = self.mouse_label.geometry()
            return base_x + m_geometry.x(), base_y + m_geometry.y()
        return base_x, base_y

    def update_custom_layers_position(self):
        if not hasattr(self, 'custom_layers') or not self.custom_layers:
            return
        custom_layers = sorted(
            [l for l in self.custom_layer_manager.layers if l.visible],
            key=lambda x: x.z_index,
        )
        for i, layer in enumerate(custom_layers):
            if i < len(self.custom_layers):
                label = self.custom_layers[i]
                x, y = self.calculate_layer_position(layer)
                cur = label.geometry()
                if cur.x() != x or cur.y() != y:
                    label.setGeometry(x, y, layer.width, layer.height)

    def open_custom_layer_manager(self):
        self.pause_input_monitoring()
        try:
            dialog = CustomLayerDialog(
                self.custom_layer_manager, self,
                character_name=self.character_manager.current_character,
                settings=self.settings,
            )
            dialog.layers_changed.connect(
                lambda: self.on_custom_layers_preview(dialog))
            dialog.layers_applied.connect(self.on_custom_layers_applied)
            dialog.keypress_preview_requested.connect(
                self._on_keypress_preview_requested)
            dialog.exec()
        finally:
            self.resume_input_monitoring()

    def on_custom_layers_preview(self, dialog):
        if not dialog.realtime_preview_check.isChecked():
            return
        if self.settings and dialog.temp_settings:
            orig = {k: self.settings.get(k) for k in dialog.temp_settings}
            for k, v in dialog.temp_settings.items():
                self.settings.set(k, v)
            self._apply_geometry_from_settings()
            self._rebuild_custom_layer_labels(dialog.all_layers)
            self._apply_default_layers_from_list(dialog.all_layers)
            self._restack_all_layers(dialog.all_layers)
            if self._is_keypress_preview_active:
                self.keypress_display_label.setText(
                    self._keypress_preview_text)
                self._auto_fit_keypress_font(self._keypress_preview_text)
                self.keypress_display_label.show()
            for k, v in orig.items():
                self.settings.set(k, v)
        else:
            self._rebuild_custom_layer_labels(dialog.all_layers)
            self._apply_default_layers_from_list(dialog.all_layers)
            self._restack_all_layers(dialog.all_layers)
            if self._is_keypress_preview_active:
                self.keypress_display_label.setText(
                    self._keypress_preview_text)
                self._auto_fit_keypress_font(self._keypress_preview_text)
                self.keypress_display_label.show()

    def on_custom_layers_applied(self, ordered_layers):
        if ordered_layers is None:
            self.create_custom_layers()
            self._apply_default_layers_config()
        else:
            self.apply_settings()

    def _apply_default_layers_config(self):
        all_layers = build_all_layers(
            self.character_manager.current_character,
            self.custom_layer_manager)
        self._apply_default_layers_from_list(all_layers)
        self._restack_all_layers(all_layers)

    def _apply_default_layers_from_list(self, all_layers):
        label_map = {
            'bg': self.bg_label,
            'keyboard': self.keyboard_label,
            'mouse_click': self.mouse_label,
        }
        for layer in all_layers:
            if not isinstance(layer, DefaultLayer):
                continue
            label = label_map.get(layer.layer_key)
            if label is None:
                continue
            if layer.opacity < 1.0:
                effect = QGraphicsOpacityEffect()
                effect.setOpacity(layer.opacity)
                label.setGraphicsEffect(effect)
            else:
                label.setGraphicsEffect(None)
            if layer.layer_key != 'mouse_click':
                label.show() if layer.visible else label.hide()

    def _restack_all_layers(self, all_layers):
        label_map = {
            'bg': self.bg_label,
            'keyboard': self.keyboard_label,
            'mouse_click': self.mouse_label,
        }
        custom_idx = 0
        mouse_click_processed = False
        for layer in all_layers:
            if isinstance(layer, DefaultLayer):
                label = label_map.get(layer.layer_key)
                if label:
                    label.raise_()
                if layer.layer_key == 'mouse_click':
                    self.left_click_label.raise_()
                    self.right_click_label.raise_()
                    mouse_click_processed = True
            elif isinstance(layer, CustomLayer):
                if custom_idx < len(self.custom_layers):
                    self.custom_layers[custom_idx].raise_()
                    custom_idx += 1
        if not mouse_click_processed:
            self.left_click_label.raise_()
            self.right_click_label.raise_()
        if hasattr(self, 'keypress_display_label'):
            self.keypress_display_label.raise_()
        if hasattr(self, 'info_weather_label'):
            self.info_weather_label.raise_()
        if hasattr(self, 'info_live_label'):
            self.info_live_label.raise_()
        if (hasattr(self, 'pomodoro_display_label')
                and self.pomodoro_display_label.isVisible()):
            self.pomodoro_display_label.raise_()

    def pause_input_monitoring(self):
        if hasattr(self, 'input_handler'):
            self.input_handler.stop_listeners()
        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.stop()
        if hasattr(self, 'custom_layer_timer'):
            self.custom_layer_timer.stop()

    def resume_input_monitoring(self):
        if hasattr(self, 'input_handler'):
            self.input_handler.start_listeners()
        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.start(16)
        if hasattr(self, 'custom_layer_timer'):
            self.custom_layer_timer.start(16)

    def switch_to_character(self, character_name):
        if self.character_manager.set_character(
                character_name, self.global_settings):
            self.settings = self.character_manager.settings
            self._settings_proxy = SettingsProxy(self.settings)

            self.custom_layer_manager = CustomLayerManager(character_name)
            self.key_lines_manager.clear(character_name)
            self.apply_settings()
            self.tray_manager.create_tray_menu()

            # 重置直播显示
            self._live_last_text = ""
            self._last_live_debug_key = ""
            self._last_weather_city = self.settings.get(
                'weather_city', '北京')

            if hasattr(self, "info_live_label"):
                self.info_live_label.set_scrolling_text(
                    f"⏳ {character_name} 检测中…")
                self.info_live_label.setStyleSheet(
                    "QLabel {"
                    "  color: white;"
                    "  background: rgba(80, 80, 80, 200);"
                    "  border-radius: 8px;"
                    "  font-size: 12px;"
                    "  font-weight: bold;"
                    "  padding: 2px 8px;"
                    "}"
                )

            # ★ 立即触发直播重检
            self._live_recheck_now.set()

            self._restart_weather_service()
            self._update_info_display()

    # ============================================================
    #  输入回调
    # ============================================================
    def _handle_key_press(self, key_identifier):
        self.key_press_signal.emit(key_identifier)

    def _handle_key_release(self):
        self.key_release_signal.emit()

    def _handle_mouse_click(self, button, pressed):
        if pressed:
            if button == mouse.Button.left:
                self.show_left_click()
            elif button == mouse.Button.right:
                self.show_right_click()
        else:
            self.hide_click_images()

    def _on_key_press_signal(self, key_identifier):
        self.input_handler.animate_key_press(
            self.keyboard_label, key_identifier)
        if self.keypress_display_enabled:
            self._show_keypress_display(key_identifier)
        self.update_custom_layers_position()

    def _on_key_release_signal(self):
        self.input_handler.animate_key_release(self.keyboard_label)
        self.update_custom_layers_position()

    # ============================================================
    #  按键显示
    # ============================================================
    def _show_keypress_display(self, key_identifier):
        if not key_identifier:
            return
        display_text = self._get_key_line(key_identifier)
        if not display_text:
            return
        self.keypress_display_label.setText(display_text)
        self._auto_fit_keypress_font(display_text)
        self.keypress_display_label.show()
        self.keypress_display_label.raise_()
        self.keypress_display_timer.start(1000)

    def _get_key_line(self, key_identifier):
        if '+' in key_identifier:
            return self._format_key_display(key_identifier)
        line = self.key_lines_manager.get(
            self.character_manager.current_character, key_identifier)
        if line is not None:
            return line
        return self._format_key_display(key_identifier)

    def _auto_fit_keypress_font(self, text):
        from PyQt6.QtGui import QFontMetrics

        try:
            base_font_size = int(
                self.settings.get('keypress_display_font_size', 16) or 16)
        except (TypeError, ValueError):
            base_font_size = 16
        try:
            user_height = int(
                self.settings.get('keypress_display_height', 40) or 40)
        except (TypeError, ValueError):
            user_height = 40
        try:
            user_max_width = self.settings.get(
                'keypress_display_max_width', None)
            user_max_width = int(user_max_width) if user_max_width else None
        except (TypeError, ValueError):
            user_max_width = None

        if user_max_width and user_max_width > 0:
            max_width = user_max_width
        else:
            try:
                kx = int(self.settings.get('keypress_display_x', 10) or 10)
            except (TypeError, ValueError):
                kx = 10
            max_width = self.window_width - kx - 10
            max_width = min(max_width, int(self.window_width * 0.85))

        min_width = 80
        font_size = base_font_size
        min_font_size = 8
        label = self.keypress_display_label
        font = label.font()
        font.setPointSize(base_font_size)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)

        if text_width > max_width:
            while font_size >= min_font_size:
                font.setPointSize(font_size)
                fm = QFontMetrics(font)
                text_width = fm.horizontalAdvance(text)
                if text_width <= max_width:
                    break
                font_size -= 1

        if self.keypress_display_background:
            style = (
                f"color: white; background-color: rgba(0, 0, 0, 150); "
                f"border-radius: 5px; font-size: {font_size}px; "
                f"font-weight: bold;")
        else:
            style = (
                f"color: white; font-size: {font_size}px; "
                f"font-weight: bold;")
        label.setStyleSheet(style)

        font.setPointSize(font_size)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        actual_width = max(min_width, text_width)
        label.setFixedSize(actual_width, user_height)

    def _hide_keypress_display(self):
        self.keypress_display_label.hide()

    def _on_keypress_preview_requested(self, show):
        self._is_keypress_preview_active = show
        if show:
            self.keypress_display_timer.stop()
            self.keypress_display_label.setText(self._keypress_preview_text)
            self._auto_fit_keypress_font(self._keypress_preview_text)
            self.keypress_display_label.show()
            self.keypress_display_label.raise_()
        else:
            self.keypress_display_label.hide()

    def _update_keypress_display_style(self):
        if self.keypress_display_background:
            style = (
                f"color: white; background-color: rgba(0, 0, 0, 150); "
                f"padding: 5px; border-radius: 5px; "
                f"font-size: {self.settings.get('keypress_display_font_size', 16)}px; "
                f"font-weight: bold;")
        else:
            style = (
                f"color: white; padding: 5px; "
                f"font-size: {self.settings.get('keypress_display_font_size', 16)}px; "
                f"font-weight: bold;")
        self.keypress_display_label.setStyleSheet(style)

    def _format_key_display(self, key_identifier):
        key_map = {
            'space': 'Space', 'enter': 'Enter', 'backspace': 'Backspace',
            'delete': 'Delete', 'tab': 'Tab', 'esc': 'Esc',
            'caps_lock': 'Caps', 'shift': 'Shift', 'shift_l': 'L-Shift',
            'shift_r': 'R-Shift', 'ctrl': 'Ctrl', 'ctrl_l': 'L-Ctrl',
            'ctrl_r': 'R-Ctrl', 'alt': 'Alt', 'alt_l': 'L-Alt',
            'alt_r': 'R-Alt', 'alt_gr': 'AltGr', 'cmd': 'Win',
            'cmd_l': 'L-Win', 'cmd_r': 'R-Win', 'super': 'Win',
            'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
            'page_up': 'PgUp', 'page_down': 'PgDn',
            'home': 'Home', 'end': 'End', 'insert': 'Insert',
            'f1': 'F1', 'f2': 'F2', 'f3': 'F3', 'f4': 'F4',
            'f5': 'F5', 'f6': 'F6', 'f7': 'F7', 'f8': 'F8',
            'f9': 'F9', 'f10': 'F10', 'f11': 'F11', 'f12': 'F12',
        }
        if '+' in key_identifier:
            parts = key_identifier.split('+')
            formatted_parts = []
            for part in parts:
                if part in ('Ctrl', 'Shift', 'Alt', 'AltGr', 'Win',
                            'L-Ctrl', 'R-Ctrl', 'L-Shift', 'R-Shift',
                            'L-Alt', 'R-Alt', 'L-Win', 'R-Win'):
                    formatted_parts.append(part)
                else:
                    mapped = key_map.get(part.lower())
                    if mapped:
                        formatted_parts.append(mapped)
                    elif len(part) == 1:
                        formatted_parts.append(part.upper())
                    else:
                        formatted_parts.append(part.title())
            return '+'.join(formatted_parts)
        return key_map.get(
            key_identifier,
            key_identifier.upper() if len(key_identifier) == 1
            else key_identifier.title())

    # ============================================================
    #  点击显示
    # ============================================================
    def show_left_click(self):
        self.hide_click_images()
        if (self.left_click_label.pixmap()
                and not self.left_click_label.pixmap().isNull()):
            self.left_click_label.show()

    def show_right_click(self):
        self.hide_click_images()
        if (self.right_click_label.pixmap()
                and not self.right_click_label.pixmap().isNull()):
            self.right_click_label.show()

    def hide_click_images(self):
        self.left_click_label.hide()
        self.right_click_label.hide()

    def _update_mouse_position(self):
        self.mouse_tracker.update_mouse_position(
            self.mouse_label, self.left_click_label,
            self.right_click_label)

    # ============================================================
    #  窗口管理
    # ============================================================
    def toggle_always_on_top(self):
        self.window_manager.toggle_always_on_top()
        self.always_on_top = self.window_manager.always_on_top
        self.tray_manager.create_tray_menu()

    def toggle_mouse_passthrough(self):
        self.window_manager.toggle_mouse_passthrough()
        self.mouse_passthrough = self.window_manager.mouse_passthrough
        self.tray_manager.create_tray_menu()

    def toggle_hide_taskbar(self):
        self.window_manager.toggle_hide_taskbar()
        self.hide_taskbar = self.window_manager.hide_taskbar
        self.tray_manager.create_tray_menu()

    def toggle_mouse_locked(self):
        self.window_manager.toggle_mouse_locked()
        self.mouse_locked = self.window_manager.mouse_locked
        self.mouse_tracker.set_locked(self.mouse_locked)
        if self.mouse_locked:
            base_x = self.settings.get('mouse_x')
            base_y = self.settings.get('mouse_y')
            mw = self.settings.get('mouse_width')
            mh = self.settings.get('mouse_height')
            self.mouse_label.setGeometry(base_x, base_y, mw, mh)
            self.left_click_label.setGeometry(base_x, base_y, mw, mh)
            self.right_click_label.setGeometry(base_x, base_y, mw, mh)
        self.tray_manager.create_tray_menu()

    def toggle_keyboard_horizontal_offset(self):
        self.window_manager.toggle_keyboard_horizontal_offset()
        self.keyboard_horizontal_offset = \
            self.window_manager.keyboard_horizontal_offset
        self.input_handler.keyboard_horizontal_offset = \
            self.keyboard_horizontal_offset
        self.tray_manager.create_tray_menu()

    def toggle_keypress_display(self):
        self.window_manager.toggle_keypress_display()
        self.keypress_display_enabled = \
            self.window_manager.keypress_display_enabled
        if not self.keypress_display_enabled:
            self.keypress_display_label.hide()
        self.tray_manager.create_tray_menu()

    def toggle_keypress_display_background(self):
        self.window_manager.toggle_keypress_display_background()
        self.keypress_display_background = \
            self.window_manager.keypress_display_background
        self._update_keypress_display_style()
        self.tray_manager.create_tray_menu()

    def toggle_window_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def quit_application(self):
        self.close()

    # ============================================================
    #  番茄钟
    # ============================================================
    def _on_pomodoro_tick(self, text, remain):
        self._pomodoro_text = text

        real_remain = 0
        try:
            p = self._pomodoro
            if p.is_running():
                real_remain = max(0, int(p._end_ts - time.time()))
            elif p.is_paused():
                real_remain = max(0, int(p._remain))
        except Exception:
            try:
                real_remain = int(remain) if remain else 0
            except (TypeError, ValueError):
                real_remain = 0

        try:
            if real_remain > 0:
                m, s = divmod(real_remain, 60)
                self.pomodoro_display_label.setText(f"{m:02d}:{s:02d}")
                self.pomodoro_display_label.show()
                self.pomodoro_display_label.raise_()
            else:
                self.pomodoro_display_label.hide()
        except Exception as e:
            print(f"[番茄钟] 显示失败：{e}")

        self._update_info_display()

    def _on_pomodoro_finished(self, mode):
        label = PomodoroTimer.MODE_LABELS.get(mode, mode)
        QMessageBox.information(
            self, f"{label}结束", f"{label}已完成，休息一下～")
        try:
            self.pomodoro_display_label.hide()
        except Exception:
            pass
        self._update_info_display()

    def start_pomodoro(self, mode=PomodoroTimer.MODE_FOCUS):
        print(f"[番茄钟] 开始 {mode}")
        self._pomodoro.start(mode)
        self._update_info_display()

    def start_pomodoro_with_minutes(self, minutes):
        """以自定义分钟数启动番茄钟。

        兼容多种 PomodoroTimer 实现：
        1) 若 start() 支持第二个参数 duration(minutes)，直接传入；
        2) 否则写入 pomodoro_focus_minutes / pomodoro 设置，再调 start(mode)。
        """
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            QMessageBox.warning(self, "番茄钟", "时长必须是整数分钟。")
            return
        if minutes <= 0:
            QMessageBox.warning(self, "番茄钟", "时长必须大于 0 分钟。")
            return

        # 1) 写入设置（供 PomodoroTimer 内部读取）
        try:
            self._settings_proxy["pomodoro_focus_minutes"] = minutes
            cfg = self.settings.get("pomodoro")
            if isinstance(cfg, dict):
                cfg = dict(cfg)
                cfg["focus_minutes"] = minutes
                cfg["focus_duration"] = minutes * 60
                self.settings.set("pomodoro", cfg)
            self._settings_proxy.save()
        except Exception as e:
            print(f"[番茄钟] 写入自定义时长失败：{e}")

        # 2) 尝试 start(mode, minutes)
        started = False
        try:
            self._pomodoro.start(PomodoroTimer.MODE_FOCUS, minutes)
            started = True
        except TypeError:
            # 参数不匹配，回退到 start(mode)
            pass
        except Exception as e:
            print(f"[番茄钟] start(mode, minutes) 失败：{e}")

        # 3) 回退
        if not started:
            try:
                self._pomodoro.start(PomodoroTimer.MODE_FOCUS)
            except Exception as e:
                print(f"[番茄钟] start(mode) 失败：{e}")

        print(f"[番茄钟] 以自定义 {minutes} 分钟启动")
        self._update_info_display()

    def _start_pomodoro_custom_dialog(self):
        """弹出对话框，让用户输入自定义番茄钟分钟数"""
        # 读取上次使用的值作为默认
        try:
            default_min = int(self._settings_proxy.get(
                "pomodoro_focus_minutes", 25) or 25)
        except (TypeError, ValueError):
            default_min = 25

        minutes, ok = QInputDialog.getInt(
            self, "自定义番茄钟", "专注时长（分钟）：",
            default_min, 1, 180, 1)
        if ok:
            self.start_pomodoro_with_minutes(minutes)

    def pause_pomodoro(self):
        if self._pomodoro.is_paused():
            self._pomodoro.resume()
        else:
            self._pomodoro.pause()

    def stop_pomodoro(self):
        self._pomodoro.stop()
        self._pomodoro_text = ""
        try:
            self.pomodoro_display_label.hide()
        except Exception:
            pass
        self._update_info_display()

    # ============================================================
    #  角色专属统计
    # ============================================================
    def _current_character(self):
        return self.character_manager.current_character or "梨安"

    def _show_char_stats(self):
        char = self._current_character()
        QMessageBox.information(
            self, f"{char} · 今日统计",
            self._char_stats.summary_text(char) + "\n\n"
            + self._char_stats.weekly_text(char),
        )

    def _add_char_stat(self, n=None):
        char = self._current_character()
        cfg = self._char_stats.config_for(char)
        if n is None:
            n = cfg.get("step", 1)
        self._char_stats.add(char, n)
        self._update_info_display()
        QMessageBox.information(self, char,
                                self._char_stats.summary_text(char))

    def _undo_char_stat(self):
        char = self._current_character()
        self._char_stats.undo(char)
        self._update_info_display()

    def _reset_char_stat(self):
        char = self._current_character()
        self._char_stats.reset_today(char)
        self._update_info_display()

    def _mark_meal(self):
        self._char_stats.mark_meal()
        self._update_info_display()
        QMessageBox.information(self, "🍚", "已记录用餐时间")

    def _on_charstat_clicked(self):
        char = self._current_character()
        cfg = self._char_stats.config_for(char)
        menu = QMenu(self)
        if cfg["mode"] == "timer":
            menu.addAction("🍚 刚吃完饭（记录时间）").triggered.connect(
                self._mark_meal)
            menu.addAction("⏱ 查看距上顿时长").triggered.connect(
                self._show_char_stats)
            menu.addSeparator()
            menu.addAction("重置今日").triggered.connect(
                self._reset_char_stat)
        else:
            menu.addAction(
                f"{cfg['icon']} {cfg['label']} +{cfg['step']}"
            ).triggered.connect(lambda: self._add_char_stat(None))
            menu.addAction("— 撤销一次").triggered.connect(
                self._undo_char_stat)
            menu.addSeparator()
            menu.addAction("📊 查看统计").triggered.connect(
                self._show_char_stats)
            menu.addAction("清零今日").triggered.connect(
                self._reset_char_stat)
        menu.exec(QCursor.pos())

    # ============================================================
    #  特殊日子
    # ============================================================
    def open_special_day_manager(self):
        dlg = SpecialDayDialog(
            self._settings_proxy, self._save_settings, self)
        dlg.exec()
        self._check_special_day_notify()

    def _check_special_day_notify(self):
        today = time.strftime("%Y-%m-%d")
        special_days = self.settings.get("special_days", {}) or {}
        if today not in special_days:
            return
        if self._special_day_notified == today:
            return
        name = special_days[today]
        QMessageBox.information(self, "特殊日子提醒",
                                f"今天是「{name}」！\n别忘了安排哦~")
        self._special_day_notified = today
        try:
            self._settings_proxy["special_day_notified"] = today
            self._settings_proxy.save()
        except Exception:
            pass
    # ============================================================
    #  音乐播放器
    # ============================================================
    def _open_music_player(self):
        """打开 B站音乐播放器窗口。关闭窗口不会停止音乐。"""
        if self._music_dlg is None:
            self._music_dlg = MusicPlayerDialog(self.music_player, self)
        self._music_dlg.show()
        self._music_dlg.raise_()
        self._music_dlg.activateWindow()
    # ============================================================
    #  便利贴
    # ============================================================
    def open_sticky_note(self):
        if self.sticky_note is None:
            self.sticky_note = StickyNote(self._settings_proxy)
            self.sticky_note.set_save_config(self._save_settings)
        else:
            try:
                new_bg = self.settings.get('note_bg_file', '') or ''
                if self.sticky_note.current_background() != new_bg:
                    self.sticky_note.set_background(new_bg, persist=False)
            except Exception as e:
                print(f"[便利贴] 同步背景失败：{e}")

        if not self.settings.get("sticky_pos"):
            screen = QApplication.primaryScreen().geometry()
            self.sticky_note.move(
                screen.x() + screen.width()
                - self.sticky_note.width() - 40,
                screen.y() + 80,
            )
        self.sticky_note.show()
        self.sticky_note.raise_()
        self.sticky_note.activateWindow()

    # ============================================================
    #  跳转 / 游戏
    # ============================================================
    def _open_bili(self):
        self.jump_helper.open_bili()

    def _open_netease(self):
        self.jump_helper.open_netease()

    def _open_custom_url(self):
        self.jump_helper.open_custom(self)

    def _open_game_with(self, key):
        custom = self.settings.get("game_launcher_path", "")
        ok, info, mode = launch_game(key, custom)
        if ok:
            print(f"[游戏] 已启动（{mode}）：{info}")
        else:
            QMessageBox.warning(self, "启动失败", f"未找到 {key}。")

    def _open_custom_game(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "选择游戏 EXE", "",
            "可执行文件 (*.exe);;所有文件 (*.*)")
        if not file:
            return
        self.settings.set("game_launcher", "custom")
        self.settings.set("game_launcher_path", file)
        self._save_settings()
        self._open_game_with("custom")

    # ============================================================
    #  天气
    # ============================================================
    def _start_weather_service(self):
        if self._weather_started:
            return
        self._weather_started = True
        self._weather_service = WeatherService(
            self._settings_proxy, self._save_settings,
            self._on_weather_update)
        self._weather_service.start()

    def _restart_weather_service(self):
        if self._weather_service:
            try:
                self._weather_service.stop()
            except Exception:
                pass
        self._weather_service = None
        self._weather_started = False
        try:
            self.settings.set('weather_lat', None)
            self.settings.set('weather_lon', None)
        except Exception:
            pass
        self._settings_proxy.refresh_from_settings()
        QTimer.singleShot(500, self._start_weather_service)

    def _on_weather_update(self, temp, code):
        if code is None:
            self._weather_text = ""
            self.weather_anim.set_weather("none")
        else:
            try:
                code_i = int(code)
            except Exception:
                code_i = -1
            desc, kind = WMO_CODE_MAP.get(code_i, ("未知", "none"))
            if temp is None:
                self._weather_text = desc
            else:
                try:
                    self._weather_text = f"{desc} {round(float(temp))}°"
                except Exception:
                    self._weather_text = desc
            self._weather_code = code_i
            if self.settings.get("show_weather", True):
                self.weather_anim.set_weather(kind)
            else:
                self.weather_anim.set_weather("none")
        self._refresh_weather_ui()
        self._update_info_display()

    def _refresh_weather_ui(self):
        if not hasattr(self, "info_weather_label"):
            return
        city = self.settings.get("weather_city", "北京") or "北京"
        if self._weather_text:
            text = f"🌤 {city} · {self._weather_text}"
        else:
            text = f"🌤 {city} · 加载中…"

        # 使用滚动标签的方法
        self.info_weather_label.set_scrolling_text(text)
        self.info_weather_label.show()
        self.info_weather_label.raise_()

    def _toggle_weather(self):
        cur = bool(self.settings.get("show_weather", True))
        new_val = not cur
        self.settings.set("show_weather", new_val)
        self.settings.save()

        if new_val:
            if self._weather_code is not None:
                _, kind = WMO_CODE_MAP.get(
                    int(self._weather_code), ("未知", "none"))
                self.weather_anim.set_weather(kind)
        else:
            self.weather_anim.set_weather("none")

        self._refresh_weather_ui()
        self._update_info_display()

    # ============================================================
    #  直播间监听开关
    # ============================================================
    def _toggle_live_monitor(self):
        self._live_monitor_enabled = not getattr(
            self, "_live_monitor_enabled", True)
        if not self._live_monitor_enabled:
            self._live_last_text = ""
            if hasattr(self, "info_live_label"):
                self.info_live_label.set_scrolling_text("📴 监听已关闭")
                self.info_live_label.setStyleSheet(
                    "QLabel {"
                    "  color: white;"
                    "  background: rgba(60, 60, 60, 200);"
                    "  border-radius: 8px;"
                    "  font-size: 12px;"
                    "  font-weight: bold;"
                    "  padding: 2px 8px;"
                    "}"
                )
            self._update_info_display()
        else:
            self._last_live_debug_key = ""
            self._live_recheck_now.set()
            QTimer.singleShot(300, self._refresh_live_ui)
        print(f"[直播] 监听 "
              f"{'开启' if self._live_monitor_enabled else '关闭'}")

    # ============================================================
    #  信息栏
    # ============================================================
    def _update_info_display(self):
        parts = [self.get_companion_time_text()]
        if self._weather_text:
            city = self.settings.get("weather_city", "")
            parts.append(f"{city} {self._weather_text}")
        if self._pomodoro_text:
            parts.append(self._pomodoro_text)
        try:
            char = self._current_character()
            parts.append(self._char_stats.tray_text(char))
        except Exception:
            pass
        if self._live_last_text:
            parts.append(self._live_last_text)
        try:
            if hasattr(self.tray_manager, "tray"):
                self.tray_manager.tray.setToolTip(" | ".join(parts))
        except Exception:
            pass
    def _get_char_stat_menu_text(self):
        """返回一级菜单中显示的角色状态文本。

        例如：'📊 ☕ 奶茶 今天 3 杯'
        会尽量尝试从 CharacterDailyStats 中读取今日计数，
        取不到时回退到 tray_text。
        """
        try:
            char = self._current_character()
            cfg = self._char_stats.config_for(char)
            icon = cfg.get("icon", "📊")
            label = cfg.get("label", "角色状态")
            unit = cfg.get("unit", "次")

            # 计时模式（如用餐）：显示距上顿时长
            if cfg.get("mode") == "timer":
                try:
                    t = self._char_stats.tray_text(char)
                    if t:
                        return f"{icon} {t}"
                except Exception:
                    pass
                return f"{icon} {label}"

            # 计数模式：优先直接取今日计数
            count = None
            for attr in ("today_count", "count_today", "get_today",
                         "get_count", "today_value"):
                fn = getattr(self._char_stats, attr, None)
                if callable(fn):
                    try:
                        count = fn(char)
                        break
                    except Exception:
                        pass

            if count is not None:
                return f"{icon} {label}：今天 {count} {unit}"

            # 回退：用 tray_text（通常形如 '☕ 奶茶 3 杯'）
            try:
                t = self._char_stats.tray_text(char)
                if t:
                    return f"📊 {t}"
            except Exception:
                pass

            return f"{icon} {label}"
        except Exception:
            return "📊 角色状态"
    # ============================================================
    #  一级右键菜单
    # ============================================================
    def _show_main_menu(self, global_pos):
        menu = QMenu(self)

        self.add_companion_action_to_menu(menu)
        menu.addSeparator()

        settings_action = QAction("⚙ 设置", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        # ---------- 番茄钟子菜单（含自定义时长） ----------
        pomodoro_menu = menu.addMenu("🍅 番茄钟")
        pomodoro_menu.addAction("专注 15 分钟").triggered.connect(
            lambda: self.start_pomodoro_with_minutes(15))
        pomodoro_menu.addAction("专注 25 分钟").triggered.connect(
            lambda: self.start_pomodoro_with_minutes(25))
        pomodoro_menu.addAction("专注 45 分钟").triggered.connect(
            lambda: self.start_pomodoro_with_minutes(45))
        pomodoro_menu.addAction("专注 60 分钟").triggered.connect(
            lambda: self.start_pomodoro_with_minutes(60))
        pomodoro_menu.addSeparator()
        pomodoro_menu.addAction("✏️ 自定义时长…").triggered.connect(
            self._start_pomodoro_custom_dialog)
        pomodoro_menu.addSeparator()
        pomodoro_menu.addAction("⏸ 暂停 / 继续").triggered.connect(
            self.pause_pomodoro)
        pomodoro_menu.addAction("⏹ 停止").triggered.connect(
            self.stop_pomodoro)
        # --------------------------------------------------
        monitor_action = QAction("📺 启动监控室", self)
        monitor_action.triggered.connect(
            lambda: self._launch_monitor_room())
        menu.addAction(monitor_action)

        # ★ 新增：音乐播放器入口
        music_action = QAction("🎵 音乐播放器", self)
        music_action.triggered.connect(self._open_music_player)
        menu.addAction(music_action)

        sticky_action = QAction("📝 便利贴", self)
        sticky_action.triggered.connect(self.open_sticky_note)
        menu.addAction(sticky_action)

        special_action = QAction("📅 特殊日子", self)
        special_action.triggered.connect(self.open_special_day_manager)
        menu.addAction(special_action)

        menu.addSeparator()

        typing_action = QAction("⌨️ 打字显示", self)
        typing_action.setCheckable(True)
        typing_action.setChecked(self.keypress_display_enabled)
        typing_action.triggered.connect(self.toggle_keypress_display)
        menu.addAction(typing_action)

        weather_action = QAction("🌤 天气动画", self)
        weather_action.setCheckable(True)
        weather_action.setChecked(
            bool(self.settings.get("show_weather", True)))
        weather_action.triggered.connect(self._toggle_weather)
        menu.addAction(weather_action)

        live_action = QAction("📺 直播间监听", self)
        live_action.setCheckable(True)
        live_action.setChecked(
            getattr(self, "_live_monitor_enabled", True))
        live_action.triggered.connect(self._toggle_live_monitor)
        menu.addAction(live_action)

        menu.addSeparator()

        cur = self._current_character()
        pet_menu = menu.addMenu(f"🐾 桌面宠物（当前：{cur}）")
        self._fill_character_menu(pet_menu)

        layers_action = QAction("🎨 自定义图层", self)
        layers_action.triggered.connect(self.open_custom_layer_manager)
        menu.addAction(layers_action)

        game_menu = menu.addMenu("🎮 打开游戏")
        game_menu.addAction("Steam").triggered.connect(
            lambda: self._open_game_with("steam"))
        game_menu.addAction("Epic Games").triggered.connect(
            lambda: self._open_game_with("epic"))
        game_menu.addSeparator()
        game_menu.addAction("自定义 EXE...").triggered.connect(
            self._open_custom_game)

        jump_menu = menu.addMenu("🔗 跳转")
        jump_menu.addAction("打开 B 站").triggered.connect(self._open_bili)
        jump_menu.addAction("打开网易云音乐").triggered.connect(
            self._open_netease)
        jump_menu.addAction("自定义 URL...").triggered.connect(
            self._open_custom_url)

        menu.addSeparator()

        menu.addSeparator()

        cur_cfg = self._char_stats.config_for(self._current_character())
        char_stat_action = QAction(self._get_char_stat_menu_text(), self)
        char_stat_action.triggered.connect(self._on_charstat_clicked)
        menu.addAction(char_stat_action)

        refresh_live_action = QAction("🔄 立即刷新直播状态", self)
        refresh_live_action.triggered.connect(self._force_refresh_live)
        menu.addAction(refresh_live_action)

        menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

        menu.exec(global_pos)

    def _force_refresh_live(self):
        """右键手动触发：立即重检"""
        self._last_live_debug_key = ""
        self._live_recheck_now.set()
        cur = self.character_manager.current_character
        if hasattr(self, "info_live_label"):
            self.info_live_label.set_scrolling_text(f"⏳ {cur} 检测中…")
            self.info_live_label.setStyleSheet(
                "QLabel {"
                "  color: white;"
                "  background: rgba(80, 80, 80, 200);"
                "  border-radius: 8px;"
                "  font-size: 12px;"
                "  font-weight: bold;"
                "  padding: 2px 8px;"
                "}"
            )
        print("[直播] 手动触发重检")

    # ============================================================
    #  监控室启动
    # ============================================================
    # ============================================================
    #  监控室启动
    # ============================================================
    def _launch_monitor_room(self, character=None):
        """启动监控室（默认无条件启动）：
        - character 为空：检查主要四位，有直播的自动填入，无直播则启动空监控室
        - character 指定：只检查指定角色（如自动触发时已知道是谁开播）
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        launcher = os.path.join(script_dir, "launch_monitor.py")
        video_path = os.path.join(script_dir, "video.py")

        if not os.path.exists(video_path):
            QMessageBox.warning(
                self, "监控室", f"找不到 video.py:\n{video_path}")
            return

        if os.path.exists(launcher):
            args = [sys.executable, launcher]
            if character:
                args += ["--character", character]
            # 注意：不加 --only-if-live，因此无论是否直播都会启动
            try:
                print(f"[监控室] 启动: {' '.join(args)}")
                subprocess.Popen(args, cwd=script_dir)
                return
            except Exception as e:
                print(f"[监控室] 启动器失败: {e}")

        # 回退：直接打开 video.py（无预填）
        try:
            print("[监控室] 回退：直接启动 video.py")
            subprocess.Popen(
                [sys.executable, video_path, "--skip-dialog"],
                cwd=script_dir,
            )
        except Exception as e:
            QMessageBox.warning(self, "监控室", f"启动失败:\n{e}")
    def _fill_character_menu(self, parent_menu):
        if self.character_manager.characters:
            chars = list(self.character_manager.characters.keys())
        else:
            chars = list(DEFAULT_LIVE_ROOMS.keys())

        current = self.character_manager.current_character

        for name in chars:
            icon = self._char_stats.config_for(name).get("icon", "👤")
            act = QAction(f"{icon} {name}", self)
            act.setCheckable(True)
            act.setChecked(name == current)
            act.triggered.connect(
                lambda checked, c=name: self.switch_to_character(c))
            parent_menu.addAction(act)

        parent_menu.addSeparator()


    def contextMenuEvent(self, event):
        self._show_main_menu(event.globalPos())

    # ============================================================
    #  设置 / 关于
    # ============================================================
    def open_settings(self):
        self.pause_input_monitoring()
        try:
            dialog = SettingsDialog(self.settings, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    print(f"[设置] 保存后 "
                          f"城市={self.settings.get('weather_city')!r} "
                          f"房间号={self.settings.get('live_room_id')!r} "
                          f"背景={self.settings.get('note_bg_file')!r}")
                except Exception:
                    pass
                self._settings_proxy.refresh_from_settings()
                self.apply_settings()
                self._refresh_weather_ui()

                # ★ 立即触发直播重检
                self._last_live_debug_key = ""
                self._live_recheck_now.set()

                cur = self.character_manager.current_character
                if hasattr(self, "info_live_label"):
                    self.info_live_label.set_scrolling_text(f"⏳ {cur} 检测中…")
                    self.info_live_label.setStyleSheet(
                        "QLabel {"
                        "  color: white;"
                        "  background: rgba(80, 80, 80, 200);"
                        "  border-radius: 8px;"
                        "  font-size: 12px;"
                        "  font-weight: bold;"
                        "  padding: 2px 8px;"
                        "}"
                    )
        finally:
            self.resume_input_monitoring()

    def show_about(self):
        version = self.get_version()
        about_text = f"""
<h2>Xiyunlou v{version}</h2>
<p>轻量级桌面宠物，支持键盘敲击动画、鼠标跟随、自定义图层、番茄钟、角色统计、直播间检测等。</p>
<br>
<p><b>使用说明：</b></p>
<p>· 右键点击窗口 → 菜单</p>
<p>· "桌面宠物" 子菜单 → 切换五位 liver</p>
<p>· "番茄钟" 子菜单 → 选择预设时长 / 自定义时长</p>
<p>· 天气、直播状态直接显示在桌宠上方</p>
<p>· 将角色素材放入 <code>img/&lt;角色名&gt;/</code> 目录</p>
<p>· 在角色目录下放置 <code>lines.json</code> 定义按键台词</p>
"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("关于")
        msg_box.setText(about_text)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setMinimumWidth(400)
        msg_box.exec()

    def apply_settings(self):
        old_city = getattr(self, '_last_weather_city', None)

        self.window_width = self.settings.get('window_width')
        self.window_height = self.settings.get('window_height')
        self._actual_window_height = (
            self.window_height + self.top_header_height)
        self.resize(self.window_width, self._actual_window_height)
        if hasattr(self, 'image_container'):
            self.image_container.setGeometry(
                0, self.top_header_height,
                self.window_width, self.window_height)

        self.mouse_tracker.update_settings(self.settings)
        self._update_keypress_display_style()
        self.keypress_display_label.setGeometry(
            self.settings.get('keypress_display_x', 10),
            self.settings.get('keypress_display_y', 10),
            100, 40,
        )
        if hasattr(self, 'weather_anim'):
            self.weather_anim.setGeometry(
                0, 0, self.window_width, self.window_height)
        self.load_character_images()
        self.create_custom_layers()

        self._layout_overlay_labels()

        new_city = self.settings.get('weather_city', '北京')
        if old_city is not None and old_city != new_city:
            print(f"[天气] 城市变化 {old_city} → {new_city}，重启服务")
            self._restart_weather_service()
        self._last_weather_city = new_city

        if hasattr(self, "_settings_proxy"):
            self._settings_proxy.refresh_from_settings()

        self._refresh_weather_ui()

    def _apply_geometry_from_settings(self):
        s = self.settings
        w = s.get('window_width')
        h = s.get('window_height')
        self.window_width = w
        self.window_height = h
        self._actual_window_height = h + self.top_header_height
        self.resize(w, self._actual_window_height)
        if hasattr(self, 'image_container'):
            self.image_container.setGeometry(
                0, self.top_header_height, w, h)
        self.bg_label.setGeometry(0, 0,
                                  s.get('bg_width'), s.get('bg_height'))
        self.keyboard_label.setGeometry(
            s.get('keyboard_x'), s.get('keyboard_y'),
            s.get('keyboard_width'), s.get('keyboard_height'))
        mx, my = s.get('mouse_x'), s.get('mouse_y')
        mw, mh = s.get('mouse_width'), s.get('mouse_height')
        self.mouse_label.setGeometry(mx, my, mw, mh)
        self.left_click_label.setGeometry(mx, my, mw, mh)
        self.right_click_label.setGeometry(mx, my, mw, mh)
        self.keypress_display_label.setGeometry(
            s.get('keypress_display_x', 10),
            s.get('keypress_display_y', 10),
            100, 40)
        self._layout_overlay_labels()

    def get_version(self):
        try:
            version_file = path_manager.get_version_file()
            with open(version_file, 'r', encoding='utf-8') as f:
                return json.load(f).get('version', '1.0.0')
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return '1.0.0'

    def check_for_updates(self):
        try:
            checker = UpdateChecker()
            checker.check_for_updates(self, self.global_settings)
        except Exception as e:
            print(f"检查更新失败: {e}")

    # ============================================================
    #  鼠标事件
    # ============================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False

    # ============================================================
    #  关闭
    # ============================================================
    def closeEvent(self, event):
        pos = self.pos()
        self.global_settings.set('window_x', pos.x())
        # 保存基准位置（图片区域顶部），恢复成窗口未扩展时的坐标
        self.global_settings.set(
            'window_y', pos.y() + self.top_header_height)
        self.global_settings.set(
            'last_character', self.character_manager.current_character)
        self.global_settings.save()

        self._live_monitor_running = False
        self._live_recheck_now.set()  # 唤醒等待中的线程

        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.stop()
        if hasattr(self, 'custom_layer_timer'):
            self.custom_layer_timer.stop()
        if hasattr(self, 'special_timer'):
            self.special_timer.stop()
        if hasattr(self, 'info_timer'):
            self.info_timer.stop()

        # 停止滚动动画定时器
        if hasattr(self, 'info_weather_label'):
            self.info_weather_label._anim_timer.stop()
        if hasattr(self, 'info_live_label'):
            self.info_live_label._anim_timer.stop()

        if self._weather_service:
            self._weather_service.stop()

        self.input_handler.stop_listeners()
        self.input_handler.stop_animation()
        self.tray_manager.hide()
        if hasattr(self, "music_player"):
            try:
                self.music_player.shutdown()
            except Exception as e:
                print(f"[音乐] 关闭播放器失败：{e}")
        event.accept()
        QApplication.quit()


# ============================================================
#  入口
# ============================================================
if __name__ == '__main__':
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_UseDesktopOpenGL)

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    pet = DesktopPet()
    sys.exit(app.exec())