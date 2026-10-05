"""
music_player.py - 轻量化B站音乐播放器（单行跟唱版）
歌词窗口只显示当前一行，按播放进度逐字高亮。
"""

import os
import re
import sys

os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

import threading
from dataclasses import dataclass
from typing import Optional, List

import requests

# ============================================================
#  VLC 路径预处理
# ============================================================
def _ensure_vlc_path():
    if not sys.platform.startswith("win"):
        return
    for p in (r"C:\Program Files\VideoLAN\VLC",
              r"C:\Program Files (x86)\VideoLAN\VLC"):
        if os.path.isdir(p):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(p)
            except Exception:
                pass

_ensure_vlc_path()

try:
    import vlc
    HAS_VLC = True
except Exception as _e:
    print(f"[音乐] 未找到 python-vlc 或 libvlc：{_e}")
    vlc = None
    HAS_VLC = False

try:
    import syncedlyrics  # type: ignore[import-not-found]
    HAS_SYNCEDLYRICS = True
except Exception:
    HAS_SYNCEDLYRICS = False

from PyQt6.QtCore import (
    Qt, QObject, QTimer, QPoint, pyqtSignal, QRectF,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QFont, QFontMetrics, QAction,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QDialog,
    QSlider, QMenu, QApplication, QMessageBox, QFileDialog,
)

# ============================================================
#  B站 API
# ============================================================
BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
}

def _fix_url(url: str) -> str:
    if not url:
        return ""
    return "https:" + url if url.startswith("//") else url

def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()

# ============================================================
#  歌词源
# ============================================================
def _fetch_netease_lyric(title: str, artist: str) -> Optional[str]:
    try:
        r = requests.get("https://music.163.com/api/search/get", params={
            "s": f"{title} {artist}", "type": 1, "limit": 5,
        }, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        songs = (r.json().get("result") or {}).get("songs") or []
        if not songs:
            return None
        song_id = songs[0]["id"]
        r2 = requests.get("https://music.163.com/api/song/lyric", params={
            "id": song_id, "lv": -1, "kv": -1, "tv": -1,
        }, headers={"User-Agent": "Mozilla/5.0",
                    "Referer": "https://music.163.com/"}, timeout=8)
        lrc = (r2.json().get("lrc") or {}).get("lyric", "")
        return lrc if lrc and "[00:" in lrc else None
    except Exception:
        return None

def _fetch_qq_lyric(title: str, artist: str) -> Optional[str]:
    try:
        r = requests.get(
            "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
            params={"w": f"{title} {artist}", "format": "json", "n": 5},
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://y.qq.com/"}, timeout=8)
        songs = (r.json().get("data") or {}).get("song", {}).get("list") or []
        if not songs:
            return None
        mid = songs[0]["songmid"]
        r2 = requests.get(
            "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
            params={"songmid": mid, "format": "json",
                    "nobase64": 1, "g_tk": 5381},
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://y.qq.com/"}, timeout=8)
        lyric = r2.json().get("lyric", "")
        lyric = re.sub(r"\[\d+,\d+\]", "", lyric)
        lyric = re.sub(r"<\d+,\d+,\d+>", "", lyric)
        return lyric if "[00:" in lyric else None
    except Exception:
        return None

# ============================================================
#  Worker 基类（threading.Thread，避免 QThread 生命周期问题）
# ============================================================
_ACTIVE_WORKERS: list = []

class _WorkerBase(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def start(self):
        _ACTIVE_WORKERS.append(self)
        t = threading.Thread(target=self._safe_run, daemon=True)
        t.start()

    def _safe_run(self):
        try:
            self.run()
        except Exception as e:
            print(f"[Worker] 异常：{e}")
        finally:
            try:
                _ACTIVE_WORKERS.remove(self)
            except ValueError:
                pass

    def run(self):
        raise NotImplementedError

# ============================================================
#  Workers
# ============================================================
class BiliSearchWorker(_WorkerBase):
    results = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, keyword: str, page: int = 1, parent=None):
        super().__init__(parent)
        self.keyword = keyword
        self.page = page

    def run(self):
        try:
            r = requests.get(
                "https://api.bilibili.com/x/web-interface/search/type",
                params={"search_type": "video", "keyword": self.keyword,
                        "page": self.page},
                headers=BILI_HEADERS, timeout=12)
            items = (r.json().get("data") or {}).get("result") or []
            self.results.emit([{
                "bvid": it.get("bvid", ""),
                "title": _strip_html(it.get("title", "")),
                "author": it.get("author", ""),
                "duration": it.get("duration", ""),
                "cover": _fix_url(it.get("pic", "")),
                "play": it.get("play", 0),
            } for it in items])
        except Exception as e:
            self.error.emit(str(e))

class BiliAudioWorker(_WorkerBase):
    ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, bvid: str, parent=None):
        super().__init__(parent)
        self.bvid = bvid

    def run(self):
        try:
            r = requests.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": self.bvid},
                headers=BILI_HEADERS, timeout=12)
            data = r.json().get("data") or {}
            cid = data.get("cid")
            if not cid:
                self.error.emit("无法获取 cid")
                return

            r2 = requests.get(
                "https://api.bilibili.com/x/player/playurl",
                params={"bvid": self.bvid, "cid": cid,
                        "fnval": 16, "fourk": 1},
                headers=BILI_HEADERS, timeout=12)
            dash = (r2.json().get("data") or {}).get("dash") or {}
            audios = dash.get("audio") or []
            if not audios:
                self.error.emit("未找到音频流")
                return
            best = max(audios, key=lambda x: x.get("bandwidth", 0))
            self.ready.emit({
                "url": best.get("baseUrl") or best.get("base_url"),
                "bvid": self.bvid, "cid": cid,
                "title": data.get("title", ""),
                "owner": (data.get("owner") or {}).get("name", ""),
                "cover": _fix_url(data.get("pic", "")),
                "duration": dash.get("duration", 0),
            })
        except Exception as e:
            self.error.emit(str(e))

class LyricsWorker(_WorkerBase):
    ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, title: str, artist: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.artist = artist

    def run(self):
        # 1. syncedlyrics
        if HAS_SYNCEDLYRICS:
            try:
                lrc = syncedlyrics.search(
                    f"{self.title} {self.artist}".strip(),
                    allow_plain_format=True)
                if lrc and "[00:" in lrc:
                    self.ready.emit(lrc)
                    return
            except Exception:
                pass
        # 2. LRCLIB
        try:
            r = requests.get("https://lrclib.net/api/search", params={
                "q": f"{self.title} {self.artist}".strip()}, timeout=8)
            for item in (r.json() or []):
                if item.get("syncedLyrics"):
                    self.ready.emit(item["syncedLyrics"])
                    return
        except Exception:
            pass
        # 3. 网易云
        lrc = _fetch_netease_lyric(self.title, self.artist)
        if lrc:
            self.ready.emit(lrc)
            return
        # 4. QQ音乐
        lrc = _fetch_qq_lyric(self.title, self.artist)
        if lrc:
            self.ready.emit(lrc)
            return
        self.error.emit("未找到歌词")

# ============================================================
#  LRC 解析
# ============================================================
@dataclass
class LyricLine:
    time: float
    text: str

_LRC_PATTERN = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")

def parse_lrc(lrc_text: str) -> List[LyricLine]:
    if not lrc_text:
        return []
    lines = []
    for raw in lrc_text.splitlines():
        text = _LRC_PATTERN.sub("", raw).strip()
        if not text:
            continue
        for m in _LRC_PATTERN.finditer(raw):
            mm, ss = int(m.group(1)), int(m.group(2))
            ms = m.group(3) or "0"
            ms_int = int(ms)
            if len(ms) == 1:
                ms_int *= 100
            elif len(ms) == 2:
                ms_int *= 10
            lines.append(LyricLine(mm * 60 + ss + ms_int / 1000.0, text))
    lines.sort(key=lambda x: x.time)
    return lines

# ============================================================
#  单行跟唱控件（QPainter 自绘）
# ============================================================
class KaraokeLineWidget(QWidget):
    """
    只显示一行歌词。
    · progress=0.0 → 整行灰色
    · progress=1.0 → 整行白色高亮
    · 中间值 → 从左到右逐字点亮

    字体根据文字长度自适应缩放，保证不溢出。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._progress = 0.0
        self._base_font_size = 26
        self._min_font_size = 12
        self._padding_x = 24
        self.setMinimumHeight(70)

    # ---- 公共接口 ----
    def set_line(self, text: str, progress: float):
        text = text or ""
        progress = max(0.0, min(1.0, float(progress)))
        # 只有真正变化才重绘
        if text == self._text and abs(progress - self._progress) < 0.005:
            return
        self._text = text
        self._progress = progress
        self.update()

    def clear_line(self):
        self._text = ""
        self._progress = 0.0
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, event):
        if not self._text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 自适应字号：把文字挤进控件宽度
        avail_w = self.width() - self._padding_x * 2
        font = QFont("Microsoft YaHei")
        font.setBold(True)
        size = self._base_font_size
        font.setPointSize(size)
        fm = QFontMetrics(font)
        while fm.horizontalAdvance(self._text) > avail_w and size > self._min_font_size:
            size -= 1
            font.setPointSize(size)
            fm = QFontMetrics(font)
        painter.setFont(font)

        text_w = fm.horizontalAdvance(self._text)
        x = (self.width() - text_w) // 2
        # 垂直居中：baseline 位置 = (h + ascent - descent) / 2
        y = (self.height() + fm.ascent() - fm.descent()) // 2

        # 已唱部分的宽度（按整行宽度线性插值，中文/英文通吃）
        drawn_w = int(text_w * self._progress)

        # 1. 底层：整行淡灰
        painter.setPen(QColor(255, 255, 255, 75))
        painter.drawText(x, y, self._text)

        # 2. 高亮层：裁剪到已唱宽度，再画一遍白色
        if drawn_w > 0:
            painter.save()
            painter.setClipRect(QRectF(x, 0, drawn_w, self.height()))
            painter.setPen(QColor(255, 255, 255, 255))
            painter.drawText(x, y, self._text)
            painter.restore()

        painter.end()

# ============================================================
#  悬浮歌词窗口（单行）
# ============================================================
class FloatingLyrics(QWidget):
    def __init__(self, pet_window=None):
        super().__init__(None)
        self.pet_window = pet_window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.karaoke = KaraokeLineWidget(self)
        layout.addWidget(self.karaoke)

        # 单行模式，窗口更扁
        self.setFixedSize(640, 90)
        self.hide()

        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(60)
        self._follow_timer.timeout.connect(self._follow_pet)
        self._follow_timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, self.width(), self.height()), 20, 20)
        painter.fillPath(path, QColor(0, 0, 0, 155))
        painter.end()

    def _follow_pet(self):
        if not self.isVisible():
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        sg = screen.geometry()
        if self.pet_window and self.pet_window.isVisible():
            pg = self.pet_window.geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() - self.height() - 8
        else:
            x = (sg.width() - self.width()) // 2
            y = 20
        x = max(sg.x(), min(x, sg.x() + sg.width() - self.width()))
        if y < sg.y():
            y = sg.y() + 8
        if self.pos() != QPoint(x, y):
            self.move(x, y)

    def set_line(self, text: str, progress: float = 0.0):
        self.karaoke.set_line(text, progress)

    def clear(self):
        self.karaoke.clear_line()

    def showEvent(self, event):
        super().showEvent(event)
        self._follow_pet()

    def close_safely(self):
        try:
            self._follow_timer.stop()
        except Exception:
            pass
        self.close()

# ============================================================
#  音乐播放器
# ============================================================
class MusicPlayer(QObject):
    state_changed = pyqtSignal(str)
    track_changed = pyqtSignal(dict)

    def __init__(self, pet_window=None, parent=None):
        super().__init__(parent)
        self.pet_window = pet_window
        self.floating = FloatingLyrics(pet_window=pet_window)

        self._vlc_instance = None
        self._vlc_player = None
        if HAS_VLC:
            try:
                self._vlc_instance = vlc.Instance("--no-video", "--quiet")
                if self._vlc_instance:
                    self._vlc_player = self._vlc_instance.media_player_new()
                    self._vlc_player.audio_set_volume(80)
            except Exception as e:
                print(f"[音乐] VLC 初始化失败：{e}")

        self._lyrics_lines: List[LyricLine] = []
        self._lyrics_idx = -1
        self._lyrics_offset = 0.0
        self._last_progress = -1.0
        self._current_track = None

        self._tick = QTimer(self)
        self._tick.setInterval(100)   # 100ms 刷新，跟唱更顺滑
        self._tick.timeout.connect(self._on_tick)

        self._audio_worker = None
        self._lyrics_worker = None

    # -------------------- 公共接口 --------------------
    def play_bvid(self, bvid: str):
        if not HAS_VLC or not self._vlc_player:
            QMessageBox.warning(None, "音乐播放器",
                                "未检测到 VLC，请安装后重试。")
            return
        self._audio_worker = BiliAudioWorker(bvid)
        self._audio_worker.ready.connect(self._on_audio_ready)
        self._audio_worker.error.connect(
            lambda e: print(f"[音乐] 获取音频失败：{e}"))
        self._audio_worker.start()

    def toggle_pause(self):
        if not self._vlc_player:
            return
        if self._vlc_player.is_playing():
            self._vlc_player.pause()
            self.state_changed.emit("paused")
        else:
            self._vlc_player.play()
            self._tick.start()
            self.state_changed.emit("playing")
            if not self.floating.isVisible():
                self.floating.show()

    def stop(self):
        if self._vlc_player:
            self._vlc_player.stop()
        self._tick.stop()
        self._lyrics_lines = []
        self._lyrics_idx = -1
        self.floating.hide()
        self.state_changed.emit("stopped")

    def set_volume(self, vol: int):
        if self._vlc_player:
            self._vlc_player.audio_set_volume(max(0, min(100, int(vol))))

    def set_lyrics(self, lrc_text: str):
        self._lyrics_lines = parse_lrc(lrc_text)
        self._lyrics_idx = -1
        self._last_progress = -1.0
        if self._lyrics_lines:
            self.floating.set_line(self._lyrics_lines[0].text, 0.0)
        else:
            self.floating.set_line("♪", 0.0)

    # -------------------- 内部回调 --------------------
    def _on_audio_ready(self, info: dict):
        self._current_track = info
        self.track_changed.emit(info)

        media = self._vlc_instance.media_new(info["url"])
        media.add_option(":http-referrer=https://www.bilibili.com/")
        media.add_option(":http-user-agent=Mozilla/5.0")
        self._vlc_player.set_media(media)
        self._vlc_player.play()
        self._tick.start()
        self.state_changed.emit("playing")

        self.floating.set_line("♪ 正在加载歌词…", 0.0)
        self.floating.show()

        title = self._clean_title(info.get("title", ""))
        artist = info.get("owner", "")
        self._lyrics_worker = LyricsWorker(title, artist)
        self._lyrics_worker.ready.connect(self.set_lyrics)
        self._lyrics_worker.error.connect(self._on_lyrics_error)
        self._lyrics_worker.start()

    def _on_lyrics_error(self, msg: str):
        print(f"[音乐] 歌词失败：{msg}")
        self.floating.set_line(f"— {msg} —", 0.0)

    @staticmethod
    def _clean_title(raw: str) -> str:
        t = raw or ""
        t = re.sub(r"[【\[（(].*?[】\]）)]", " ", t)
        t = re.sub(r"(4K|8K|1080P|720P|HD|MV|官方|完整版|高清|"
                   r"纯音乐|无损|完整|动态歌词|字幕版|中文字幕|LIVE|现场|翻唱|cover)",
                   " ", t, flags=re.I)
        t = re.sub(r"^.*?[-–—]\s*", "", t)
        return re.sub(r"\s+", " ", t).strip()

    def _on_tick(self):
        if not self._vlc_player:
            return
        try:
            st = self._vlc_player.get_state()
            if st in (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped):
                self._tick.stop()
                self.floating.hide()
                self.state_changed.emit("ended")
                return
        except Exception:
            pass

        cur_ms = self._vlc_player.get_time()
        if cur_ms < 0:
            return

        if not self._lyrics_lines:
            return

        cur = cur_ms / 1000.0 - self._lyrics_offset
        n = len(self._lyrics_lines)

        # 游标法定位当前行
        idx = self._lyrics_idx
        while idx + 1 < n and self._lyrics_lines[idx + 1].time <= cur:
            idx += 1
        while idx >= 0 and self._lyrics_lines[idx].time > cur:
            idx -= 1
        if idx < 0:
            idx = 0

        # 当前行的进度比例
        line_start = self._lyrics_lines[idx].time
        if idx + 1 < n:
            line_end = self._lyrics_lines[idx + 1].time
        else:
            line_end = line_start + 4.0
        span = max(0.01, line_end - line_start)
        progress = max(0.0, min(1.0, (cur - line_start) / span))

        # 只在必要时刷新（行变化 / 进度变化超过阈值）
        line_changed = idx != self._lyrics_idx
        progress_changed = abs(progress - self._last_progress) > 0.01
        if line_changed or progress_changed:
            self._lyrics_idx = idx
            self._last_progress = progress
            self.floating.set_line(self._lyrics_lines[idx].text, progress)

    def shutdown(self):
        try:
            if self._vlc_player:
                self._vlc_player.stop()
        except Exception:
            pass
        try:
            self.floating.close_safely()
        except Exception:
            pass
        try:
            if self._vlc_player:
                self._vlc_player.release()
                self._vlc_player = None
        except Exception:
            pass
        try:
            if self._vlc_instance:
                self._vlc_instance.release()
                self._vlc_instance = None
        except Exception:
            pass

# ============================================================
#  对话框
# ============================================================
class MusicPlayerDialog(QDialog):
    def __init__(self, player: MusicPlayer, parent=None):
        super().__init__(parent)
        self.player = player
        self.setWindowTitle("BiliMusic · 单行跟唱")
        self.setMinimumSize(580, 500)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索歌曲、歌手…")
        self.search_edit.returnPressed.connect(self._on_search)
        btn = QPushButton("搜索")
        btn.clicked.connect(self._on_search)
        row.addWidget(self.search_edit, 1)
        row.addWidget(btn)
        root.addLayout(row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_play)
        root.addWidget(self.list_widget, 1)

        self.lbl_now = QLabel("未在播放")
        self.lbl_now.setStyleSheet("color:#888; font-size:12px;")
        root.addWidget(self.lbl_now)

        ctrl = QHBoxLayout()
        self.btn_toggle = QPushButton("▶ 播放 / ⏸ 暂停")
        self.btn_toggle.clicked.connect(self.player.toggle_pause)
        btn_stop = QPushButton("⏹ 停止")
        btn_stop.clicked.connect(self.player.stop)
        ctrl.addWidget(self.btn_toggle)
        ctrl.addWidget(btn_stop)
        ctrl.addStretch()
        ctrl.addWidget(QLabel("音量"))
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(80)
        self.slider_vol.setFixedWidth(120)
        self.slider_vol.valueChanged.connect(self.player.set_volume)
        ctrl.addWidget(self.slider_vol)
        root.addLayout(ctrl)

        off_row = QHBoxLayout()
        off_row.addWidget(QLabel("歌词偏移"))
        b1 = QPushButton("提前 0.5s")
        b1.clicked.connect(lambda: self._bump(-0.5))
        b2 = QPushButton("延后 0.5s")
        b2.clicked.connect(lambda: self._bump(+0.5))
        b3 = QPushButton("📂 加载本地 LRC")
        b3.clicked.connect(self._load_local)
        off_row.addWidget(b1)
        off_row.addWidget(b2)
        off_row.addStretch()
        off_row.addWidget(b3)
        root.addLayout(off_row)

        self.player.track_changed.connect(self._on_track)
        self.player.state_changed.connect(self._on_state)
        self._search_worker = None

    def _bump(self, delta):
        self.player._lyrics_offset = round(
            self.player._lyrics_offset + delta, 2)

    def _load_local(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 LRC 文件", "", "歌词文件 (*.lrc *.txt)")
        if path:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                self.player.set_lyrics(f.read())

    def _on_search(self):
        kw = self.search_edit.text().strip()
        if not kw:
            return
        self.list_widget.clear()
        self.list_widget.addItem("🔍 搜索中…")
        self._search_worker = BiliSearchWorker(kw)
        self._search_worker.results.connect(self._on_results)
        self._search_worker.error.connect(
            lambda e: self.list_widget.addItem(f"❌ {e}"))
        self._search_worker.start()

    def _on_results(self, items):
        self.list_widget.clear()
        for it in items:
            item = QListWidgetItem(
                f"{it['title']}  —  {it['author']}  [{it['duration']}]")
            item.setData(Qt.ItemDataRole.UserRole, it)
            self.list_widget.addItem(item)

    def _on_item_play(self, item):
        d = item.data(Qt.ItemDataRole.UserRole)
        if d:
            self.player.play_bvid(d["bvid"])

    def _on_track(self, info):
        self.lbl_now.setText(
            f"♪ {info.get('title','')}  —  {info.get('owner','')}")

    def _on_state(self, state):
        if state == "playing":
            self.btn_toggle.setText("⏸ 暂停")
        elif state == "paused":
            self.btn_toggle.setText("▶ 继续")
        else:
            self.btn_toggle.setText("▶ 播放 / ⏸ 暂停")

    def closeEvent(self, event):
        event.accept()

# ============================================================
#  独立运行
# ============================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = MusicPlayer()
    dlg = MusicPlayerDialog(player)
    dlg.show()
    app.aboutToQuit.connect(player.shutdown)
    sys.exit(app.exec())