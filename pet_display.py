# -*- coding: utf-8 -*-
"""
桌面宠物整合模块 · 台词显示 + 键盘敲击动画 + 鼠标跟随动画
=========================================================
参考：BongoCat 的交互方式 + 禧运楼的动作逻辑
依赖：PyQt5, pynput
=========================================================
"""

import os
import json

from PyQt6.QtWidgets import (
    QWidget, QLabel, QApplication, QGraphicsOpacityEffect
)
from PyQt6.QtGui import QPixmap, QColor, QCursor
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject


# ==================== 默认键位映射 ====================
DEFAULT_KEY_MAP = {
    "A": "A", "B": "B", "C": "C", "D": "D", "E": "E", "F": "F",
    "G": "G", "H": "H", "I": "I", "J": "J", "K": "K", "L": "L",
    "M": "M", "N": "N", "O": "O", "P": "P", "Q": "Q", "R": "R",
    "S": "S", "T": "T", "U": "U", "V": "V", "W": "W", "X": "X",
    "Y": "Y", "Z": "Z",
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    "Space": "空格", "Enter": "回车", "Tab": "Tab",
    "Escape": "Esc", "Backspace": "退格", "Delete": "Delete",
    "Insert": "Ins", "Home": "Home", "End": "End",
    "PageUp": "PgUp", "PageDown": "PgDn",
    "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
    "Shift": "Shift", "LShift": "Shift", "RShift": "Shift",
    "Control": "Ctrl", "LControl": "Ctrl", "RControl": "Ctrl",
    "Alt": "Alt", "LAlt": "Alt", "RAlt": "Alt",
    "CapsLock": "Caps",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
    "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
    "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
}


# ==================== 阿米洛新三国键帽台词（104 配列全键） ====================
NEW_SANGUO_LINES = {
    # ---------- F 区（看图认梗区） ----------
    "F1": "噔", "F2": "噔", "F3": "噔", "F4": "噔",
    "F5": "噔", "F6": "噔", "F7": "噔", "F8": "噔",
    "F9": "噔", "F10": "噔", "F11": "噔", "F12": "噔",

    # ---------- 数字键 1-0（短歌行区） ----------
    "1": "一对笑面虎", "2": "两头乌角鲨", "3": "三军听令", "4": "四轮车儿",
    "5": "5百校刀手", "6": "6亲不认", "7": "7十万大军", "8": "8万个馒头",
    "9": "9是老英雄", "0": "0陵上将,说出吾名,吓汝一跳",

    # ---------- 主键区 · 名场面 ----------
    "Q": "全军出击", "W": "我是不会客气的", "E": "二弟天下无敌",
    "R": "容我告老还乡了", "T": "天意如此",
    "Y": "愿闻其详", "U": "吾乃常山赵子龙", "I": "一将抵千军",
    "O": "呕心沥血", "P": "匹夫之勇",
    "A": "爱死他了", "S": "是啊吃什么", "D": "当浮一巨白",
    "F": "风从虎", "G": "各位E一下吧",
    "H": "好极好极", "J": "竟然不许",
    "K": "可供人无忧的安眠", "L": "龙，可是帝王之征啊",

    # ---------- 扭三语录区 ----------
    "Z": "战至最后一刻，自刎归天", "X": "雪王真乃神人也",
    "C": "参见至尊雪王～！", "V": "捅你一万个透明窟窿",
    "B": "不可能绝对不可能", "N": "你是何人", "M": "莫非我睡着了",

    # ---------- 短歌行区 ----------
    "Space": "恭喜雪王可以撑地了",

    # ---------- 中军号令区 ----------
    "Insert": "先用之", "Home": "你们且退", "PageUp": "上不愧于天",
    "Delete": "后口之", "End": "我要睡了", "PageDown": "下不愧于民",

    # ---------- 符号键（主键区右上） ----------
    "OemMinus":         "对酒",
    "OemPlus":          "当歌",
    "OemOpenBrackets":  "人生",
    "OemCloseBrackets": "几何",
    "OemPipe":          "火焰流星雨",
    "OemSemicolon":     "仁之剑",
    "OemQuotes":        "义之剑",
    "OemComma":         "譬如",
    "OemPeriod":        "朝露",
    "OemQuestion":      "去日",
    "OemTilde":         "苦多",

    # ---------- 编辑键 ----------
    "PrintScreen": "记下了",
    "ScrollLock":  "滚！",
    "Pause":       "我跟你开玩笑呢",

    # ---------- 数字小键盘（孟德新书区） ----------
    "Num1": "144", "Num2": "2杯咖啡", "Num3": "事不过3",
    "Num4": "4轮车", "Num5": "5百校刀手", "Num6": "6亲不认",
    "Num7": "7十万大军", "Num8": "巴什么", "Num9": "氿什么",
    "Num0": "没听说过",
    "NumAdd":      "口的人越多医术越高明",
    "NumMinus":    "我赌你的枪里没有子弹",
    "NumMultiply": "数倍乃至数十倍",
    "NumDivide":   "像你这样的人要怎么改变",
    "NumDecimal":  "此乃天意",
    "NumEnter":    "徐州城不愧是中原第一雄关啊",
    "NumLock":     "钱粮在手",

    # ---------- 十万精兵营（方向键） ----------
    "Up": "哀兵必胜", "Down": "骄兵必败",
    "Left": "败兵比哀", "Right": "胜兵必骄",

    # ---------- 有情有义区 ----------
    "LShift": "东头一个汉", "RShift": "西头一个汉",
    "LControl": "臂挟天子", "RControl": "握于掌中",
    "LAlt": "大奸似忠", "RAlt": "大伪似真",
    "LWin": "不败之地", "RWin": "战无不胜",
    "Menu": "帅台设宴",
    "CapsLock": "来人换大盏",
    "Tab": "上表雪王",
    "Escape": "叉出去",
    "Backspace": "稍作修改",
    "Enter": "无情剑",
}


def load_json(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[配置] 读取 {path} 失败: {e}")
        return {}


# ==================== 整合浮层窗口 ====================
class PetDisplayWindow(QWidget):
    """
    一个窗口同时承载：
      · 角色背景图
      · 键盘图（按下时下移回弹）
      · 鼠标图（随真实鼠标偏移 + 左右键切换）
      · 台词标签（按键时显示，带淡出）
    """

    SHOW_MS = 1500      # 台词停留时长
    FADE_MS = 300       # 淡出总时长

    KB_PRESS_PIXELS = 4     # 键盘按下位移
    MOUSE_RANGE_X = 30      # 鼠标图左右最大偏移
    MOUSE_RANGE_Y = 20      # 鼠标图上下最大偏移

    def __init__(self, resource_dir=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("禧运楼 · 台词桌宠")

        # ---------- 子控件 ----------
        self.bg_label    = QLabel(self)
        self.kb_label    = QLabel(self)
        self.mouse_label = QLabel(self)
        self.text_label  = QLabel(self)

        self.bg_label.setStyleSheet("background: transparent;")
        self.kb_label.setStyleSheet("background: transparent;")
        self.mouse_label.setStyleSheet("background: transparent;")

        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setStyleSheet(
            "color: #FFFFFF;"
            "font-size: 28px; font-weight: bold;"
            "background: rgba(0, 0, 0, 180);"
            "border-radius: 14px;"
            "padding: 6px 26px;"
        )

        # 台词标签的透明度效果（真正生效的淡出）
        self._text_effect = QGraphicsOpacityEffect(self.text_label)
        self._text_effect.setOpacity(1.0)
        self.text_label.setGraphicsEffect(self._text_effect)

        # 图层顺序
        self.bg_label.lower()
        self.kb_label.raise_()
        self.mouse_label.raise_()
        self.text_label.raise_()

        # ---------- 资源 ----------
        self._pix_bg          = QPixmap()
        self._pix_kb          = QPixmap()
        self._pix_mouse       = QPixmap()
        self._pix_mouse_left  = QPixmap()
        self._pix_mouse_right = QPixmap()

        # ---------- 基准位置 ----------
        self._kb_base_pos    = QPoint(0, 0)
        self._mouse_base_pos = QPoint(0, 0)

        # ---------- 定时器 ----------
        self._kb_release_timer = QTimer(self)
        self._kb_release_timer.setSingleShot(True)
        self._kb_release_timer.timeout.connect(self._kb_release)

        self._mouse_click_timer = QTimer(self)
        self._mouse_click_timer.setSingleShot(True)
        self._mouse_click_timer.timeout.connect(self._mouse_reset)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_step)
        self._opacity = 1.0

        # ---------- 锚点 ----------
        self._anchor = "bottom_right"
        self._margin = 40

        if resource_dir:
            self.set_resource_dir(resource_dir)

    # ============================================================
    #   资源加载
    # ============================================================
    def set_resource_dir(self, d):
        """一次性加载一个角色文件夹下的全部图片。"""
        def _load(name):
            p = os.path.join(d, name)
            if os.path.exists(p):
                pix = QPixmap(p)
                print(f"[资源] 加载 {name}: {pix.width()}x{pix.height()}")
                return pix
            else:
                print(f"[资源] 缺失 {name}: {p}")
                return QPixmap()

        self._pix_bg          = _load("bgImage.png")
        self._pix_kb          = _load("keyboardImage.png")
        self._pix_mouse       = _load("mouseImage.png")
        self._pix_mouse_left  = _load("leftClickImage.png")
        self._pix_mouse_right = _load("rightClickImage.png")

        self._apply_pixmaps()
        self._layout_children()

    def _apply_pixmaps(self):
        # 背景
        if self._pix_bg.isNull():
            self.bg_label.clear()
            self.bg_label.setFixedSize(0, 0)
            self.bg_label.hide()
        else:
            self.bg_label.setPixmap(self._pix_bg)
            self.bg_label.setFixedSize(self._pix_bg.size())
            self.bg_label.show()

        # 键盘
        if self._pix_kb.isNull():
            self.kb_label.clear()
            self.kb_label.setFixedSize(0, 0)
            self.kb_label.hide()
        else:
            self.kb_label.setPixmap(self._pix_kb)
            self.kb_label.setFixedSize(self._pix_kb.size())
            self.kb_label.show()

        # 鼠标
        if self._pix_mouse.isNull():
            self.mouse_label.clear()
            self.mouse_label.setFixedSize(0, 0)
            self.mouse_label.hide()
        else:
            self.mouse_label.setPixmap(self._pix_mouse)
            self.mouse_label.setFixedSize(self._pix_mouse.size())
            self.mouse_label.show()

    def _layout_children(self):
        if self._pix_bg.isNull():
            w, h = 400, 400
        else:
            w, h = self._pix_bg.width(), self._pix_bg.height()
        self.setFixedSize(w, h)

        self.bg_label.move(0, 0)

        # 键盘：居中偏下
        kw, kh = self.kb_label.width(), self.kb_label.height()
        self._kb_base_pos = QPoint((w - kw) // 2, int(h * 0.62))
        self.kb_label.move(self._kb_base_pos)

        # 鼠标：键盘右侧
        mw, mh = self.mouse_label.width(), self.mouse_label.height()
        self._mouse_base_pos = QPoint(
            (w + kw) // 2 - mw // 2 + 20,
            int(h * 0.60)
        )
        self.mouse_label.move(self._mouse_base_pos)

        # 台词：窗口顶部居中
        self.text_label.adjustSize()
        self.text_label.move((w - self.text_label.width()) // 2, 10)

        self._reposition_window()

    # ============================================================
    #   键盘动作
    # ============================================================
    def press_key(self, text):
        """按下键：键盘下移 + 显示台词。"""
        if text:
            self.text_label.setText(text)
            self.text_label.adjustSize()
            self.text_label.move(
                (self.width() - self.text_label.width()) // 2, 10
            )
            self._opacity = 1.0
            self._text_effect.setOpacity(1.0)
            self._hide_timer.start(self.SHOW_MS)

        # 键盘下移
        self.kb_label.move(
            self._kb_base_pos.x(),
            self._kb_base_pos.y() + self.KB_PRESS_PIXELS
        )
        self._kb_release_timer.start(80)

        self.show()
        self.raise_()

    def release_key(self):
        self._kb_release_timer.stop()
        self._kb_release()

    def _kb_release(self):
        self.kb_label.move(self._kb_base_pos)

    # ============================================================
    #   鼠标动作
    # ============================================================
    def move_mouse(self, screen_x, screen_y):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.geometry()
        if geo.width() <= 0 or geo.height() <= 0:
            return

        rel_x = (screen_x / geo.width()) * 2.0 - 1.0
        rel_y = (screen_y / geo.height()) * 2.0 - 1.0
        rel_x = max(-1.0, min(1.0, rel_x))
        rel_y = max(-1.0, min(1.0, rel_y))

        ox = int(rel_x * self.MOUSE_RANGE_X)
        oy = int(rel_y * self.MOUSE_RANGE_Y)

        self.mouse_label.move(
            self._mouse_base_pos.x() + ox,
            self._mouse_base_pos.y() + oy
        )

    def click_mouse(self, button):
        if button == "left" and not self._pix_mouse_left.isNull():
            self.mouse_label.setPixmap(self._pix_mouse_left)
        elif button == "right" and not self._pix_mouse_right.isNull():
            self.mouse_label.setPixmap(self._pix_mouse_right)
        self._mouse_click_timer.start(120)

    def _mouse_reset(self):
        if not self._pix_mouse.isNull():
            self.mouse_label.setPixmap(self._pix_mouse)

    # ============================================================
    #   台词淡出（用 QGraphicsOpacityEffect，真正生效）
    # ============================================================
    def _fade_out(self):
        self._fade_timer.start(30)

    def _fade_step(self):
        self._opacity -= 30.0 / self.FADE_MS
        if self._opacity <= 0.0:
            self._opacity = 0.0
            self._fade_timer.stop()
            self._text_effect.setOpacity(0.0)
            self.text_label.clear()
            self._text_effect.setOpacity(1.0)
            return
        self._text_effect.setOpacity(self._opacity)

    # ============================================================
    #   窗口锚点
    # ============================================================
    def set_anchor(self, anchor):
        self._anchor = anchor
        self._reposition_window()

    def _reposition_window(self):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.availableGeometry()

        if self._anchor == "top_center":
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + self._margin
        elif self._anchor == "bottom_center":
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + geo.height() - self.height() - self._margin
        elif self._anchor == "mouse":
            pos = QCursor.pos()
            x = pos.x() - self.width() // 2
            y = pos.y() - self.height() - 20
        else:  # bottom_right
            x = geo.x() + geo.width() - self.width() - self._margin
            y = geo.y() + geo.height() - self.height() - self._margin
        self.move(x, y)

    # 允许拖动窗口
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and hasattr(self, "_drag_pos"):
            self.move(e.globalPos() - self._drag_pos)
            e.accept()


# ==================== 全局键盘监听 ====================
class GlobalKeyListener(QObject):
    """监听全局键盘，发信号 key_pressed(text, name) / key_released(name)。"""

    key_pressed  = pyqtSignal(str, str)
    key_released = pyqtSignal(str)

    def __init__(self, key_map=None, key_lines=None, parent=None):
        super().__init__(parent)
        self._map   = dict(DEFAULT_KEY_MAP)
        self._lines = dict(NEW_SANGUO_LINES)
        if key_map:
            self._map.update(key_map)
        if key_lines:
            self._lines.update(key_lines)
        self._listener = None
        self._running = False

    def set_key_map(self, key_map):
        self._map = dict(DEFAULT_KEY_MAP)
        if key_map:
            self._map.update(key_map)

    def set_key_lines(self, key_lines):
        self._lines = dict(NEW_SANGUO_LINES)
        if key_lines:
            self._lines.update(key_lines)

    def map_display(self, raw_name):
        # 优先台词表，其次普通映射
        if raw_name in self._lines:
            return self._lines[raw_name]
        return self._map.get(raw_name, raw_name)

    # ============================================================
    #   pynput 键名 → 104 配列通用键名
    # ============================================================
    @staticmethod
    def _vk_to_name(key):
        try:
            from pynput.keyboard import Key
        except ImportError:
            return str(key)

        # 1) 小键盘优先用 vk 号
        vk = getattr(key, "vk", None)
        if vk is not None:
            if 0x60 <= vk <= 0x69:
                return f"Num{vk - 0x60}"
            if vk == 0x6A: return "NumMultiply"
            if vk == 0x6B: return "NumAdd"
            if vk == 0x6C: return "NumEnter"
            if vk == 0x6D: return "NumMinus"
            if vk == 0x6E: return "NumDecimal"
            if vk == 0x6F: return "NumDivide"

        # 2) 字母 / 数字 / 符号
        if hasattr(key, "char") and key.char:
            ch = key.char.upper()
            if ch.isalnum():
                return ch
            sym_map = {
                "-":  "OemMinus",
                "=":  "OemPlus",
                "[":  "OemOpenBrackets",
                "]":  "OemCloseBrackets",
                "\\": "OemPipe",
                ";":  "OemSemicolon",
                "'":  "OemQuotes",
                ",":  "OemComma",
                ".":  "OemPeriod",
                "/":  "OemQuestion",
                "`":  "OemTilde",
            }
            return sym_map.get(key.char, key.char)

        # 3) 功能键 / 修饰键
        def _k(name):
            return getattr(Key, name, None)

        name_map = {
            _k("space"):        "Space",
            _k("enter"):        "Enter",
            _k("tab"):          "Tab",
            _k("esc"):          "Escape",
            _k("backspace"):    "Backspace",
            _k("delete"):       "Delete",
            _k("insert"):       "Insert",
            _k("home"):         "Home",
            _k("end"):          "End",
            _k("page_up"):      "PageUp",
            _k("page_down"):    "PageDown",
            _k("up"):           "Up",
            _k("down"):         "Down",
            _k("left"):         "Left",
            _k("right"):        "Right",
            _k("print_screen"): "PrintScreen",
            _k("scroll_lock"):  "ScrollLock",
            _k("pause"):        "Pause",
            _k("shift"):        "Shift",
            _k("shift_l"):      "LShift",
            _k("shift_r"):      "RShift",
            _k("ctrl"):         "Control",
            _k("ctrl_l"):       "LControl",
            _k("ctrl_r"):       "RControl",
            _k("alt"):          "Alt",
            _k("alt_l"):        "LAlt",
            _k("alt_r"):        "RAlt",
            _k("alt_gr"):       "RAlt",
            _k("cmd"):          "LWin",
            _k("cmd_l"):        "LWin",
            _k("cmd_r"):        "RWin",
            _k("menu"):         "Menu",
            _k("caps_lock"):    "CapsLock",
            _k("num_lock"):     "NumLock",
            _k("f1"):  "F1",  _k("f2"):  "F2",  _k("f3"):  "F3",
            _k("f4"):  "F4",  _k("f5"):  "F5",  _k("f6"):  "F6",
            _k("f7"):  "F7",  _k("f8"):  "F8",  _k("f9"):  "F9",
            _k("f10"): "F10", _k("f11"): "F11", _k("f12"): "F12",
        }
        name_map = {k: v for k, v in name_map.items() if k is not None}

        if key in name_map:
            return name_map[key]

        # 4) 兜底
        s = str(key)
        if s.startswith("Key."):
            return s[4:]
        return s

    # ============================================================
    #   监听回调
    # ============================================================
    def _on_press(self, key):
        if not self._running:
            return
        try:
            name = self._vk_to_name(key)
            display = self.map_display(name)
            print(f"[映射] name={name!r} -> display={display!r}")
            self.key_pressed.emit(display, name)
        except Exception as e:
            print(f"[键盘] press 异常：{e}")

    def _on_release(self, key):
        if not self._running:
            return
        try:
            name = self._vk_to_name(key)
            self.key_released.emit(name)
        except Exception as e:
            print(f"[键盘] release 异常：{e}")

    # ============================================================
    #   启动 / 停止
    # ============================================================
    def start(self):
        if self._running:
            return
        try:
            from pynput import keyboard
        except ImportError:
            print("[pynput] 未安装，请执行：pip install pynput")
            return

        self._running = True
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        print("[pynput] 全局键盘监听已启动")

    def stop(self):
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        print("[pynput] 全局键盘监听已停止")


# ==================== 全局鼠标监听 ====================
class GlobalMouseListener(QObject):
    """监听全局鼠标：移动 / 左右键点击。"""

    mouse_moved   = pyqtSignal(int, int)
    mouse_clicked = pyqtSignal(str)   # 'left' / 'right'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None
        self._running = False

    def _on_move(self, x, y):
        if self._running:
            self.mouse_moved.emit(int(x), int(y))

    def _on_click(self, x, y, button, pressed):
        if not self._running or not pressed:
            return
        try:
            from pynput.mouse import Button
            if button == Button.left:
                self.mouse_clicked.emit("left")
            elif button == Button.right:
                self.mouse_clicked.emit("right")
        except Exception:
            pass

    def start(self):
        if self._running:
            return
        try:
            from pynput import mouse
        except ImportError:
            print("[pynput] 未安装，请执行：pip install pynput")
            return
        self._running = True
        self._listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
        )
        self._listener.daemon = True
        self._listener.start()
        print("[pynput] 全局鼠标监听已启动")

    def stop(self):
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        print("[pynput] 全局鼠标监听已停止")


# ==================== 便捷启动器 ====================
class PetApp:
    """把窗口 + 键盘监听 + 鼠标监听组装在一起。"""

    def __init__(self, resource_dir=None, anchor="bottom_right"):
        self.window = PetDisplayWindow(resource_dir=resource_dir)
        self.window.set_anchor(anchor)

        self.key_listener   = GlobalKeyListener()
        self.mouse_listener = GlobalMouseListener()

        # 键盘 → 窗口动作
        self.key_listener.key_pressed.connect(self._on_key_press)
        self.key_listener.key_released.connect(
            lambda _: self.window.release_key()
        )

        # 鼠标 → 窗口动作
        self.mouse_listener.mouse_moved.connect(self.window.move_mouse)
        self.mouse_listener.mouse_clicked.connect(self.window.click_mouse)

    def _on_key_press(self, display, name):
        print(f"[窗口] 收到台词: {display}")
        self.window.press_key(display)

    def start(self):
        self.window.show()
        self.key_listener.start()
        self.mouse_listener.start()

    def stop(self):
        self.key_listener.stop()
        self.mouse_listener.stop()