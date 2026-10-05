# -*- coding: utf-8 -*-
"""番茄钟模块（PyQt6 版）"""

import time
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class PomodoroTimer(QObject):
    tick = pyqtSignal(str, int)
    finished = pyqtSignal(str)

    MODE_FOCUS = "focus"
    MODE_SHORT = "short"
    MODE_LONG = "long"

    MODE_LABELS = {MODE_FOCUS: "专注", MODE_SHORT: "短休", MODE_LONG: "长休"}
    MODE_ICONS = {MODE_FOCUS: "🍅", MODE_SHORT: "☕", MODE_LONG: "🌿"}

    def __init__(self, cfg, save_config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._save = save_config

        p = cfg.setdefault("pomodoro", {})
        p.setdefault("focus_min", 25)
        p.setdefault("short_min", 5)
        p.setdefault("long_min", 15)
        p.setdefault("long_every", 4)
        p.setdefault("auto_next", True)
        p.setdefault("enable_voice", True)
        p.setdefault("finished_today", 0)
        p.setdefault("last_reset_date", "")

        self._mode = self.MODE_FOCUS
        self._running = False
        self._paused = False
        self._end_ts = 0.0
        self._remain = 0
        self._focus_count_today = p.get("finished_today", 0)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

    def _duration_seconds(self, mode=None):
        mode = mode or self._mode
        p = self.cfg.get("pomodoro", {})
        if mode == self.MODE_FOCUS:
            return max(1, int(p.get("focus_min", 25))) * 60
        if mode == self.MODE_SHORT:
            return max(1, int(p.get("short_min", 5))) * 60
        return max(1, int(p.get("long_min", 15))) * 60

    def _reset_daily_if_needed(self):
        today = time.strftime("%Y-%m-%d")
        p = self.cfg["pomodoro"]
        if p.get("last_reset_date") != today:
            p["last_reset_date"] = today
            p["finished_today"] = 0
            self._focus_count_today = 0
            self._save(self.cfg)

    def start(self, mode=MODE_FOCUS):
        self._reset_daily_if_needed()
        self._mode = mode
        self._running = True
        self._paused = False
        self._remain = self._duration_seconds(mode)
        self._end_ts = time.time() + self._remain
        self._tick_timer.start()
        self._emit_tick()
        print(f"[番茄钟] 开始 {self.MODE_LABELS[mode]} {self._remain // 60} 分钟")

    def pause(self):
        if not self._running or self._paused:
            return
        self._paused = True
        self._remain = max(0, int(self._end_ts - time.time()))
        self._tick_timer.stop()

    def resume(self):
        if not self._running or not self._paused:
            return
        self._paused = False
        self._end_ts = time.time() + self._remain
        self._tick_timer.start()

    def stop(self):
        self._running = False
        self._paused = False
        self._tick_timer.stop()
        self._remain = 0

    def is_running(self):
        return self._running and not self._paused

    def is_paused(self):
        return self._running and self._paused

    def mode(self):
        return self._mode

    def status_text(self):
        if not self._running:
            return ""
        icon = self.MODE_ICONS.get(self._mode, "⏱")
        if self._paused:
            return f"{icon} ⏸ {self._fmt(self._remain)}"
        remain = max(0, int(self._end_ts - time.time()))
        return f"{icon} {self._fmt(remain)}"

    @staticmethod
    def _fmt(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _on_tick(self):
        if not self._running or self._paused:
            return
        remain = int(self._end_ts - time.time())
        if remain <= 0:
            self._tick_timer.stop()
            self._running = False
            self._on_finished()
            return
        self._emit_tick()

    def _emit_tick(self):
        self.tick.emit(self.status_text(), self._remain)

    def _on_finished(self):
        mode = self._mode
        if mode == self.MODE_FOCUS:
            self._reset_daily_if_needed()
            p = self.cfg["pomodoro"]
            p["finished_today"] = p.get("finished_today", 0) + 1
            self._focus_count_today = p["finished_today"]
            self._save(self.cfg)

        self.finished.emit(mode)

        if self.cfg["pomodoro"].get("auto_next", True):
            if mode == self.MODE_FOCUS:
                every = self.cfg["pomodoro"].get("long_every", 4)
                if every > 0 and self._focus_count_today % every == 0:
                    next_mode = self.MODE_LONG
                else:
                    next_mode = self.MODE_SHORT
            else:
                next_mode = self.MODE_FOCUS
            QTimer.singleShot(1000, lambda: self.start(next_mode))