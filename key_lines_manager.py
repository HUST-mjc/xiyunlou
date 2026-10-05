# -*- coding: utf-8 -*-
"""
按键台词管理器 · 按角色加载各自的 lines.json
=========================================================
用法：
    mgr = KeyLineManager(base_dir="img")
    mgr.get("角色A", "a")        # → 该角色在 lines.json 里为 'a' 定义的台词
    mgr.get("角色B", "a")        # → 该角色自己的台词
    mgr.clear("角色A")           # 改完 lines.json 后清缓存
    mgr.has_own_table("角色A")   # 该角色是否有专属 lines.json

加载优先级（按下某个键时）：
    1) img/{当前角色}/lines.json 中的对应键
    2) DEFAULT_LINES 中的对应键
    3) 返回 None（由调用方决定如何回退显示）

组合键（如 "Ctrl+c"）不走台词表，直接返回 None。
=========================================================
"""
import sys
import json
import os
import time
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QMenu, QDialog, QMessageBox
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QAction, QIcon, QSurfaceFormat, QPixmap
from PyQt6.QtWidgets import QGraphicsOpacityEffect
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from pynput import mouse

from settings import GlobalSettings, SettingsDialog
from update_checker import UpdateChecker
from character_manager import CharacterManager
from input_handler import InputHandler, MouseTracker
from tray_manager import TrayManager
from window_manager import WindowManager
from custom_layer_manager import CustomLayerManager, CustomLayer, DefaultLayer, build_all_layers
from custom_layer_dialog import CustomLayerDialog
from path_manager import path_manager
# ==================== 默认台词表（兜底） ====================
# 键名统一使用小写；input_handler 传来的 key_identifier 也是小写
DEFAULT_LINES = {
    # ---------- 字母键 ----------
    'q': '全军出击', 'w': '我是不会客气的', 'e': '二弟天下无敌',
    'r': '容我告老还乡了', 't': '天意如此',
    'y': '愿闻其详', 'u': '吾乃常山赵子龙', 'i': '一将抵千军',
    'o': '呕心沥血', 'p': '匹夫之勇',
    'a': '爱死他了', 's': '是啊吃什么', 'd': '当浮一巨白',
    'f': '风从虎', 'g': '各位E一下吧',
    'h': '好极好极', 'j': '竟然不许',
    'k': '可供人无忧的安眠', 'l': '龙，可是帝王之征啊',
    'z': '战至最后一刻，自刎归天', 'x': '雪王真乃神人也',
    'c': '参见至尊雪王～！', 'v': '捅你一万个透明窟窿',
    'b': '不可能绝对不可能', 'n': '你是何人', 'm': '莫非我睡着了',

    # ---------- 数字键 ----------
    '1': '一对笑面虎', '2': '两头乌角鲨', '3': '三军听令', '4': '四轮车儿',
    '5': '5百校刀手', '6': '6亲不认', '7': '7十万大军', '8': '8万个馒头',
    '9': '9是老英雄', '0': '0陵上将,说出吾名,吓汝一跳',

    # ---------- 功能键 ----------
    'space': '恭喜雪王可以撑地了',
    'enter': '无情剑',
    'tab': '上表雪王',
    'esc': '叉出去',
    'backspace': '稍作修改',
    'delete': '后口之',
    'insert': '先用之',
    'home': '你们且退',
    'end': '我要睡了',
    'page_up': '上不愧于天',
    'page_down': '下不愧于民',
    'caps_lock': '来人换大盏',

    # ---------- 方向键 ----------
    'up': '哀兵必胜', 'down': '骄兵必败',
    'left': '败兵比哀', 'right': '胜兵必骄',

    # ---------- F 区 ----------
    'f1': '噔', 'f2': '噔', 'f3': '噔', 'f4': '噔',
    'f5': '噔', 'f6': '噔', 'f7': '噔', 'f8': '噔',
    'f9': '噔', 'f10': '噔', 'f11': '噔', 'f12': '噔',

    # ---------- 修饰键（单独按下时） ----------
    'shift': '东头一个汉', 'shift_l': '东头一个汉', 'shift_r': '西头一个汉',
    'ctrl': '臂挟天子', 'ctrl_l': '臂挟天子', 'ctrl_r': '握于掌中',
    'alt': '大奸似忠', 'alt_l': '大奸似忠', 'alt_r': '大伪似真',
    'alt_gr': '大伪似真',
    'cmd': '不败之地', 'cmd_l': '不败之地', 'cmd_r': '战无不胜',
    'super': '不败之地',
    'menu': '帅台设宴',

    # ---------- 特殊键 ----------
    'print_screen': '记下了',
    'scroll_lock': '滚！',
    'pause': '我跟你开玩笑呢',
}


class KeyLineManager:
    """管理每个角色的按键台词表，文件位于 {base_dir}/{角色名}/lines.json。"""

    LINES_FILENAME = "lines.json"

    def __init__(self, base_dir="img", default_lines=None):
        """
        :param base_dir: 角色目录的父目录，默认 "img"
        :param default_lines: 自定义的默认台词表；不传则使用 DEFAULT_LINES
        """
        self.base_dir = base_dir
        self.default_lines = dict(default_lines or DEFAULT_LINES)
        self._cache = {}         # {角色名: {键名: 台词}}
        self._missing = set()    # 已知没有 lines.json 的角色，避免反复读盘

    # ============================================================
    #   路径
    # ============================================================
    def _lines_path(self, character):
        """返回某角色 lines.json 的完整路径。"""
        return os.path.join(self.base_dir, character, self.LINES_FILENAME)

    # ============================================================
    #   加载
    # ============================================================
    def load(self, character):
        """
        加载（并缓存）某角色的台词表。
        返回 dict 或 None（无文件/加载失败）。
        """
        if not character:
            return None

        # 已有缓存
        if character in self._cache:
            return self._cache[character]

        # 已知该角色无专属表，直接跳过
        if character in self._missing:
            return None

        path = self._lines_path(character)
        if not os.path.exists(path):
            self._missing.add(character)
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                print(f"[台词] {path} 不是字典格式，已忽略")
                self._missing.add(character)
                return None

            # 键名统一转小写字符串，值统一转字符串
            table = {str(k).lower(): str(v) for k, v in data.items()}
            self._cache[character] = table
            print(f"[台词] 已加载 {character} 的台词表（{len(table)} 条）")
            return table

        except Exception as e:
            print(f"[台词] 读取 {path} 失败: {e}")
            self._missing.add(character)
            return None

    # ============================================================
    #   查询
    # ============================================================
    def get(self, character, key_identifier):
        """
        返回该角色下这个键对应的台词。
        查不到返回 None（由调用方决定回退方式）。
        组合键（含 '+'）直接返回 None。
        """
        if not key_identifier:
            return None

        # 组合键不走台词表
        if '+' in key_identifier:
            return None

        key = str(key_identifier).lower()

        # 1) 角色专属表
        table = self.load(character)
        if table and key in table:
            return table[key]

        # 2) 默认表
        if key in self.default_lines:
            return self.default_lines[key]

        # 3) 都没有
        return None

    # ============================================================
    #   缓存管理
    # ============================================================
    def clear(self, character=None):
        """
        清缓存。
        character=None 时清掉所有角色的缓存。
        """
        if character is None:
            self._cache.clear()
            self._missing.clear()
        else:
            self._cache.pop(character, None)
            self._missing.discard(character)

    def has_own_table(self, character):
        """该角色是否有专属 lines.json。"""
        self.load(character)  # 触发一次加载判断
        return character in self._cache

    def list_loaded(self):
        """返回当前已缓存的角色名列表（调试用）。"""
        return list(self._cache.keys())

class DesktopPet(QOpenGLWidget):
    key_press_signal = pyqtSignal(object)
    key_release_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.key_press_signal.connect(self._on_key_press_signal)
        self.key_release_signal.connect(self._on_key_release_signal)

        # 加载全局设置
        self.global_settings = GlobalSettings()

        # 初始化窗口管理器
        self.window_manager = WindowManager(self, self.global_settings)
        self.always_on_top = self.window_manager.always_on_top
        self.mouse_passthrough = self.window_manager.mouse_passthrough
        self.hide_taskbar = self.window_manager.hide_taskbar
        self.mouse_locked = self.window_manager.mouse_locked
        self.keyboard_horizontal_offset = self.window_manager.keyboard_horizontal_offset
        self.keypress_display_enabled = self.window_manager.keypress_display_enabled
        self.keypress_display_background = self.window_manager.keypress_display_background

        # 初始化角色管理器
        self.character_manager = CharacterManager()
        self.character_manager.initialize_from_global_settings(
            self.global_settings)

        # 初始化按键台词管理器（按角色加载各自 img/<角色>/lines.json）
        self.key_lines_manager = KeyLineManager(base_dir="img")

        # 初始化自定义图层管理器
        self.custom_layer_manager = CustomLayerManager(
            self.character_manager.current_character)
        self.custom_layers = []  # 存储自定义图层的QLabel

        # 从角色管理器获取设置
        self.settings = self.character_manager.settings
        self.window_width = self.settings.get('window_width')
        self.window_height = self.settings.get('window_height')

        # 加载累计运行时长
        self._load_runtime_stats()

        # 记录本次启动时间
        self.start_time = time.time()

        # 初始化系统托盘
        self.tray_manager = TrayManager(self)
        self.tray_manager.init_tray()

        # 初始化UI
        self.init_ui()

        # 初始化输入处理器
        self.input_handler = InputHandler(
            self.settings,
            self._handle_key_press,
            self._handle_key_release,
            self._handle_mouse_click,
            self.keyboard_horizontal_offset
        )

        # 初始化鼠标跟踪器
        self.mouse_tracker = MouseTracker(self.settings, self.mouse_locked)

        # 启动监听器
        self.input_handler.start_listeners()

        # 启动鼠标同步定时器
        self.mouse_timer = QTimer()
        self.mouse_timer.timeout.connect(self._update_mouse_position)
        self.mouse_timer.start(16)  # 约60fps

        # 启动自定义图层位置更新定时器
        self.custom_layer_timer = QTimer()
        self.custom_layer_timer.timeout.connect(
            self.update_custom_layers_position)
        self.custom_layer_timer.start(16)  # 约60fps，与鼠标同步

        # 陪伴时间定时器 - 每秒更新显示
        self._companion_action = None
        self.companion_timer = QTimer()
        self.companion_timer.timeout.connect(self._update_companion_display)
        self.companion_timer.start(1000)

        # 关闭时保存统计
        self.closeRequested = False
        app.aboutToQuit.connect(self._save_runtime_stats)

        # 按键预览状态标志
        self._is_keypress_preview_active = False
        self._keypress_preview_text = "Ctrl"  # 预览时的示例文本

    def _load_runtime_stats(self):
        """加载累计运行时长"""
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
        """保存累计运行时长"""
        if hasattr(self, 'start_time') and hasattr(self, 'total_runtime'):
            self.total_runtime += time.time() - self.start_time
        stats_file = path_manager.get_stats_file()
        try:
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump({'total_runtime': getattr(self, 'total_runtime', 0)}, f, ensure_ascii=False)
        except Exception as e:
            print(f"保存运行时长失败: {e}")

    def get_companion_time_text(self):
        """获取陪伴时间显示文本"""
        if not hasattr(self, 'total_runtime'):
            return "陪伴：0秒"
        elapsed = self.total_runtime + (time.time() - self.start_time)
        if elapsed < 60:
            return f"陪伴：{int(elapsed)}秒"
        elif elapsed < 3600:
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            return f"陪伴：{minutes}分{seconds}秒"
        else:
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            return f"陪伴：{hours}时{minutes}分"

    def _update_companion_display(self):
        """更新陪伴时间显示"""
        if self._companion_action:
            self._companion_action.setText(self.get_companion_time_text())

    def add_companion_action_to_menu(self, menu):
        """将陪伴时间菜单项添加到指定菜单"""
        companion_label = QAction(self.get_companion_time_text(), self)
        companion_label.setEnabled(False)
        menu.addAction(companion_label)
        self._companion_action = companion_label
        return companion_label

    def init_ui(self):
        """初始化UI"""
        # 设置基础窗口属性
        flags = Qt.WindowType.FramelessWindowHint
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint

        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(
            Qt.WidgetAttribute.WA_AlwaysStackOnTop, self.always_on_top)
        self.setWindowTitle("Xiyunlou")

        # 设置窗口图标（使用当前角色的背景图，没有就跳过）
        if self.character_manager.current_character:
            icon_path = os.path.join(
                "img", self.character_manager.current_character, "bgImage.png"
            )
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))

        # 设置窗口大小
        self.resize(self.window_width, self.window_height)

        # 设置窗口位置
        self._set_window_position()

        # 创建图层标签
        self.bg_label = QLabel(self)
        self.keyboard_label = QLabel(self)
        self.mouse_label = QLabel(self)
        self.left_click_label = QLabel(self)
        self.right_click_label = QLabel(self)

        # 创建按键显示标签
        self.keypress_display_label = QLabel(self)
        self._update_keypress_display_style()
        self.keypress_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.keypress_display_label.hide()
        self.keypress_display_label.setGeometry(
            self.settings.get('keypress_display_x', 10),
            self.settings.get('keypress_display_y', 10),
            100, 40
        )

        # 按键显示定时器
        self.keypress_display_timer = QTimer()
        self.keypress_display_timer.timeout.connect(
            self._hide_keypress_display)
        self.keypress_display_timer.setSingleShot(True)

        # 加载当前角色图片
        self.load_character_images()

        # 创建和加载自定义图层（含默认图层配置应用和堆叠顺序）
        self.create_custom_layers()

        # 应用鼠标穿透设置
        self.window_manager.apply_mouse_passthrough()

        # 允许拖动窗口
        self.dragging = False
        self.drag_position = QPoint()

        self.show()

        # 根据设置决定是否隐藏任务栏
        if self.hide_taskbar:
            self.window_manager.apply_hide_taskbar()

        # 显示首次启动提示
        self.window_manager.show_first_launch_tip()

        # 检查更新
        QTimer.singleShot(1000, self.check_for_updates)

    def _set_window_position(self):
        """设置窗口位置"""
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()

        window_x = self.global_settings.get('window_x')
        window_y = self.global_settings.get('window_y')

        if window_x is None or window_y is None:
            center_x = (screen_geometry.width() - self.window_width) // 2
            center_y = (screen_geometry.height() - self.window_height) // 2
            self.move(center_x, center_y)
        else:
            self.move(window_x, window_y)

    def paintEvent(self, event):
        """重写 paintEvent 以支持 OpenGL 渲染和透明背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.end()

    def load_character_images(self):
        """加载当前角色的图片"""
        labels_dict = {
            'bg': self.bg_label,
            'keyboard': self.keyboard_label,
            'mouse': self.mouse_label,
            'left_click': self.left_click_label,
            'right_click': self.right_click_label
        }
        self.character_manager.load_character_images(labels_dict)

    def create_custom_layers(self):
        """创建自定义图层，并按完整有序列表重排堆叠顺序"""
        all_layers = build_all_layers(self.character_manager.current_character,
                                      self.custom_layer_manager)
        self._rebuild_custom_layer_labels(all_layers)
        self._apply_default_layers_from_list(all_layers)
        self._restack_all_layers(all_layers)

    def _rebuild_custom_layer_labels(self, all_layers):
        """根据有序图层列表重建自定义图层 QLabel"""
        for label in self.custom_layers:
            label.deleteLater()
        self.custom_layers.clear()

        for layer in all_layers:
            if isinstance(layer, CustomLayer):
                if os.path.exists(layer.image_path):
                    label = QLabel(self)
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
                    label = QLabel(self)
                    label.hide()
                    self.custom_layers.append(label)

    def calculate_layer_position(self, layer):
        """计算图层位置（考虑跟随设置）"""
        base_x, base_y = layer.x, layer.y

        if layer.follow_type == "keyboard":
            kb_geometry = self.keyboard_label.geometry()
            return base_x + kb_geometry.x(), base_y + kb_geometry.y()
        elif layer.follow_type == "mouse":
            mouse_geometry = self.mouse_label.geometry()
            return base_x + mouse_geometry.x(), base_y + mouse_geometry.y()
        else:
            return base_x, base_y

    def update_custom_layers_position(self):
        """更新自定义图层位置"""
        if not hasattr(self, 'custom_layers') or not self.custom_layers:
            return

        custom_layers = sorted(
            [l for l in self.custom_layer_manager.layers if l.visible],
            key=lambda x: x.z_index
        )

        for i, layer in enumerate(custom_layers):
            if i < len(self.custom_layers):
                label = self.custom_layers[i]
                x, y = self.calculate_layer_position(layer)
                current = label.geometry()
                if current.x() != x or current.y() != y:
                    label.setGeometry(x, y, layer.width, layer.height)

    def open_custom_layer_manager(self):
        """打开图层管理对话框"""
        self.pause_input_monitoring()

        try:
            dialog = CustomLayerDialog(
                self.custom_layer_manager, self,
                character_name=self.character_manager.current_character,
                settings=self.settings
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
        """实时预览回调"""
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
        """应用/关闭回调"""
        if ordered_layers is None:
            self.create_custom_layers()
            self._apply_default_layers_config()
        else:
            self.apply_settings()

    def _apply_default_layers_config(self):
        """从已保存配置应用默认图层的透明度/可见性/堆叠顺序"""
        all_layers = build_all_layers(self.character_manager.current_character,
                                      self.custom_layer_manager)
        self._apply_default_layers_from_list(all_layers)
        self._restack_all_layers(all_layers)

    def _apply_default_layers_from_list(self, all_layers):
        """将有序图层列表中默认图层的属性应用到对应 QLabel"""
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
        """按有序图层列表重排所有 QLabel 的堆叠顺序"""
        label_map = {
            'bg': self.bg_label,
            'keyboard': self.keyboard_label,
            'mouse_click': self.mouse_label,
        }

        custom_layer_index = 0
        mouse_click_processed = False
        keypress_display_processed = False

        for layer in all_layers:
            if isinstance(layer, DefaultLayer):
                label = label_map.get(layer.layer_key)
                if label:
                    label.raise_()

                if layer.layer_key == 'mouse_click':
                    self.left_click_label.raise_()
                    self.right_click_label.raise_()
                    mouse_click_processed = True

                if layer.layer_key == 'keypress_display' and hasattr(self, 'keypress_display_label'):
                    self.keypress_display_label.raise_()
                    keypress_display_processed = True

            elif isinstance(layer, CustomLayer):
                if custom_layer_index < len(self.custom_layers):
                    label = self.custom_layers[custom_layer_index]
                    label.raise_()
                    custom_layer_index += 1

        if not mouse_click_processed:
            self.left_click_label.raise_()
            self.right_click_label.raise_()

        if not keypress_display_processed and hasattr(self, 'keypress_display_label'):
            self.keypress_display_label.raise_()

    def pause_input_monitoring(self):
        """暂停输入监听"""
        if hasattr(self, 'input_handler'):
            self.input_handler.stop_listeners()
        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.stop()
        if hasattr(self, 'custom_layer_timer'):
            self.custom_layer_timer.stop()

    def resume_input_monitoring(self):
        """恢复输入监听"""
        if hasattr(self, 'input_handler'):
            self.input_handler.start_listeners()

        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.start(16)
        if hasattr(self, 'custom_layer_timer'):
            self.custom_layer_timer.start(16)

    def switch_to_character(self, character_name):
        """切换到指定角色"""
        if self.character_manager.set_character(character_name, self.global_settings):
            self.settings = self.character_manager.settings
            self.custom_layer_manager = CustomLayerManager(character_name)
            # 清掉该角色的台词缓存，保证新改的 lines.json 立刻生效
            self.key_lines_manager.clear(character_name)
            self.apply_settings()
            self.tray_manager.create_tray_menu()

    # 输入处理回调
    def _handle_key_press(self, key_identifier):
        """处理按键按下"""
        self.key_press_signal.emit(key_identifier)

    def _handle_key_release(self):
        """处理按键释放"""
        self.key_release_signal.emit()

    def _handle_mouse_click(self, button, pressed):
        """处理鼠标点击"""
        if pressed:
            if button == mouse.Button.left:
                self.show_left_click()
            elif button == mouse.Button.right:
                self.show_right_click()
        else:
            self.hide_click_images()

    def _on_key_press_signal(self, key_identifier):
        """键盘按下信号处理"""
        self.input_handler.animate_key_press(
            self.keyboard_label, key_identifier)
        if self.keypress_display_enabled:
            self._show_keypress_display(key_identifier)
        self.update_custom_layers_position()

    def _on_key_release_signal(self):
        """键盘释放信号处理"""
        self.input_handler.animate_key_release(self.keyboard_label)
        self.update_custom_layers_position()

    # ============================================================
    #   按键显示：优先显示当前角色的台词，找不到才回退到默认键名
    # ============================================================
    def _show_keypress_display(self, key_identifier):
        """显示按键（使用当前角色的台词映射）"""
        if not key_identifier:
            return

        display_text = self._get_key_line(key_identifier)

        self.keypress_display_label.setText(display_text)
        self._auto_fit_keypress_font(display_text)
        self.keypress_display_label.show()

        self.keypress_display_timer.start(1000)

    def _get_key_line(self, key_identifier):
        """按当前角色查台词；无匹配时回退到默认格式化。"""
        # 组合键保持原样
        if '+' in key_identifier:
            return self._format_key_display(key_identifier)

        line = self.key_lines_manager.get(
            self.character_manager.current_character,
            key_identifier,
        )
        if line is not None:
            return line

        return self._format_key_display(key_identifier)

    def _auto_fit_keypress_font(self, text):
        """自动调整字体大小，使按键文本适应最大宽度和用户设置的高度"""
        from PyQt6.QtGui import QFontMetrics, QFont

        base_font_size = self.settings.get('keypress_display_font_size', 16)
        user_height = self.settings.get('keypress_display_height', 40)
        user_max_width = self.settings.get('keypress_display_max_width', None)
        if user_max_width and user_max_width > 0:
            max_width = user_max_width
        else:
            max_width = self.window_width - \
                self.settings.get('keypress_display_x', 10) - 10
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
                f"color: white; "
                f"background-color: rgba(0, 0, 0, 150); "
                f"border-radius: 5px; "
                f"font-size: {font_size}px; "
                f"font-weight: bold;"
            )
        else:
            style = (
                f"color: white; "
                f"font-size: {font_size}px; "
                f"font-weight: bold;"
            )
        label.setStyleSheet(style)

        font.setPointSize(font_size)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)

        actual_width = max(min_width, text_width)
        label.setFixedSize(actual_width, user_height)

    def _hide_keypress_display(self):
        """隐藏按键显示"""
        self.keypress_display_label.hide()

    def _on_keypress_preview_requested(self, show):
        """图层管理对话框请求显示/隐藏按键预览"""
        self._is_keypress_preview_active = show
        if show:
            self.keypress_display_timer.stop()
            self.keypress_display_label.setText(self._keypress_preview_text)
            self._auto_fit_keypress_font(self._keypress_preview_text)
            self.keypress_display_label.show()
        else:
            self.keypress_display_label.hide()

    def _update_keypress_display_style(self):
        """更新按键显示样式"""
        if self.keypress_display_background:
            style = (
                f"color: white; "
                f"background-color: rgba(0, 0, 0, 150); "
                f"padding: 5px; "
                f"border-radius: 5px; "
                f"font-size: {self.settings.get('keypress_display_font_size', 16)}px; "
                f"font-weight: bold;"
            )
        else:
            style = (
                f"color: white; "
                f"padding: 5px; "
                f"font-size: {self.settings.get('keypress_display_font_size', 16)}px; "
                f"font-weight: bold;"
            )
        self.keypress_display_label.setStyleSheet(style)

    def _format_key_display(self, key_identifier):
        """格式化按键显示文本（原始逻辑，作为兜底保留）"""
        key_map = {
            'space': 'Space',
            'enter': 'Enter',
            'backspace': 'Backspace',
            'delete': 'Delete',
            'tab': 'Tab',
            'esc': 'Esc',
            'caps_lock': 'Caps',
            'shift': 'Shift',
            'shift_l': 'L-Shift',
            'shift_r': 'R-Shift',
            'ctrl': 'Ctrl',
            'ctrl_l': 'L-Ctrl',
            'ctrl_r': 'R-Ctrl',
            'alt': 'Alt',
            'alt_l': 'L-Alt',
            'alt_r': 'R-Alt',
            'alt_gr': 'AltGr',
            'cmd': 'Win',
            'cmd_l': 'L-Win',
            'cmd_r': 'R-Win',
            'super': 'Win',
            'up': '↑',
            'down': '↓',
            'left': '←',
            'right': '→',
            'page_up': 'PgUp',
            'page_down': 'PgDn',
            'home': 'Home',
            'end': 'End',
            'insert': 'Insert',
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

        return key_map.get(key_identifier, key_identifier.upper() if len(key_identifier) == 1 else key_identifier.title())

    def show_left_click(self):
        """显示左键图片"""
        self.hide_click_images()
        if self.left_click_label.pixmap() and not self.left_click_label.pixmap().isNull():
            self.left_click_label.show()

    def show_right_click(self):
        """显示右键图片"""
        self.hide_click_images()
        if self.right_click_label.pixmap() and not self.right_click_label.pixmap().isNull():
            self.right_click_label.show()

    def hide_click_images(self):
        """隐藏所有鼠标按键图片"""
        self.left_click_label.hide()
        self.right_click_label.hide()

    def _update_mouse_position(self):
        """更新鼠标位置"""
        self.mouse_tracker.update_mouse_position(
            self.mouse_label,
            self.left_click_label,
            self.right_click_label
        )

    # 窗口管理相关方法
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
            mouse_width = self.settings.get('mouse_width')
            mouse_height = self.settings.get('mouse_height')
            self.mouse_label.setGeometry(
                base_x, base_y, mouse_width, mouse_height)
            self.left_click_label.setGeometry(
                base_x, base_y, mouse_width, mouse_height)
            self.right_click_label.setGeometry(
                base_x, base_y, mouse_width, mouse_height)

        self.tray_manager.create_tray_menu()

    def toggle_keyboard_horizontal_offset(self):
        self.window_manager.toggle_keyboard_horizontal_offset()
        self.keyboard_horizontal_offset = self.window_manager.keyboard_horizontal_offset
        self.input_handler.keyboard_horizontal_offset = self.keyboard_horizontal_offset
        self.tray_manager.create_tray_menu()

    def toggle_keypress_display(self):
        self.window_manager.toggle_keypress_display()
        self.keypress_display_enabled = self.window_manager.keypress_display_enabled

        if not self.keypress_display_enabled:
            self.keypress_display_label.hide()

        self.tray_manager.create_tray_menu()

    def toggle_keypress_display_background(self):
        self.window_manager.toggle_keypress_display_background()
        self.keypress_display_background = self.window_manager.keypress_display_background
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

    # 设置和关于
    def open_settings(self):
        """打开设置对话框"""
        self.pause_input_monitoring()
        try:
            dialog = SettingsDialog(self.settings, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.apply_settings()
        finally:
            self.resume_input_monitoring()

    def show_about(self):
        """显示关于对话框（中性版本）"""
        version = self.get_version()
        about_text = f"""
<h2>Xiyunlou v{version}</h2>
<p>一个轻量级桌面宠物程序，支持键盘敲击动画、鼠标跟随、按角色自定义台词。</p>
<br>
<p><b>使用说明：</b></p>
<p>· 右键点击窗口可呼出菜单</p>
<p>· 将角色素材放入 <code>img/&lt;角色名&gt;/</code> 目录，需包含 bgImage.png / keyboardImage.png / mouseImage.png / leftClickImage.png / rightClickImage.png</p>
<p>· 在角色目录下可放置 <code>lines.json</code> 定义该角色的按键台词</p>
        """

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("关于")
        msg_box.setText(about_text)
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setMinimumWidth(400)
        msg_box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        msg_box.exec()

    def apply_settings(self):
        """应用设置"""
        self.window_width = self.settings.get('window_width')
        self.window_height = self.settings.get('window_height')
        self.resize(self.window_width, self.window_height)

        self.mouse_tracker.update_settings(self.settings)
        self._update_keypress_display_style()
        self.keypress_display_label.setGeometry(
            self.settings.get('keypress_display_x', 10),
            self.settings.get('keypress_display_y', 10),
            100, 40
        )

        self.load_character_images()
        self.create_custom_layers()

    def _apply_geometry_from_settings(self):
        """仅更新各图层的几何尺寸（不保存、不重载图片），用于实时预览"""
        s = self.settings
        w = s.get('window_width')
        h = s.get('window_height')
        self.resize(w, h)

        self.bg_label.setGeometry(0, 0, s.get('bg_width'), s.get('bg_height'))

        kb_x = s.get('keyboard_x')
        kb_y = s.get('keyboard_y')
        kb_w = s.get('keyboard_width')
        kb_h = s.get('keyboard_height')
        self.keyboard_label.setGeometry(kb_x, kb_y, kb_w, kb_h)

        mx = s.get('mouse_x')
        my = s.get('mouse_y')
        mw = s.get('mouse_width')
        mh = s.get('mouse_height')
        self.mouse_label.setGeometry(mx, my, mw, mh)
        self.left_click_label.setGeometry(mx, my, mw, mh)
        self.right_click_label.setGeometry(mx, my, mw, mh)

        self.keypress_display_label.setGeometry(
            s.get('keypress_display_x', 10),
            s.get('keypress_display_y', 10),
            100, 40
        )

    def get_version(self):
        """从version.json文件读取版本号"""
        try:
            version_file = path_manager.get_version_file()
            with open(version_file, 'r', encoding='utf-8') as f:
                version_data = json.load(f)
                return version_data.get('version', '1.0.0')
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return '1.0.0'

    def check_for_updates(self):
        """检查更新"""
        try:
            checker = UpdateChecker()
            checker.check_for_updates(self, self.global_settings)
        except Exception as e:
            print(f"检查更新失败: {e}")

    # 鼠标事件处理
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - \
                self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False

    def contextMenuEvent(self, event):
        """右键菜单"""
        menu = QMenu(self)

        self.add_companion_action_to_menu(menu)

        menu.addSeparator()

        minimize_action = QAction('最小化到托盘', self)
        minimize_action.triggered.connect(self.hide)
        menu.addAction(minimize_action)

        menu.addSeparator()

        self._add_window_settings_menu(menu)

        menu.addSeparator()

        self._add_input_settings_menu(menu)

        menu.addSeparator()

        self._add_character_menu(menu)

        custom_layer_action = QAction('自定义图层管理', self)
        custom_layer_action.triggered.connect(self.open_custom_layer_manager)
        menu.addAction(custom_layer_action)

        settings_action = QAction('设置', self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

        menu.exec(event.globalPos())

    def _add_window_settings_menu(self, parent_menu):
        """添加窗口设置子菜单"""
        window_settings_menu = parent_menu.addMenu('窗口设置')

        always_on_top_action = QAction('窗口置顶', self)
        always_on_top_action.setCheckable(True)
        always_on_top_action.setChecked(self.always_on_top)
        always_on_top_action.triggered.connect(self.toggle_always_on_top)
        window_settings_menu.addAction(always_on_top_action)

        mouse_passthrough_action = QAction('鼠标穿透', self)
        mouse_passthrough_action.setCheckable(True)
        mouse_passthrough_action.setChecked(self.mouse_passthrough)
        mouse_passthrough_action.triggered.connect(
            self.toggle_mouse_passthrough)
        window_settings_menu.addAction(mouse_passthrough_action)

        hide_taskbar_action = QAction('隐藏任务栏 (OBS不可识别)', self)
        hide_taskbar_action.setCheckable(True)
        hide_taskbar_action.setChecked(self.hide_taskbar)
        hide_taskbar_action.triggered.connect(self.toggle_hide_taskbar)
        window_settings_menu.addAction(hide_taskbar_action)

    def _add_input_settings_menu(self, parent_menu):
        """添加输入设置菜单项"""
        mouse_locked_action = QAction('锁定鼠标', self)
        mouse_locked_action.setCheckable(True)
        mouse_locked_action.setChecked(self.mouse_locked)
        mouse_locked_action.triggered.connect(self.toggle_mouse_locked)
        parent_menu.addAction(mouse_locked_action)

        keyboard_horizontal_offset_action = QAction('键盘横向偏移', self)
        keyboard_horizontal_offset_action.setCheckable(True)
        keyboard_horizontal_offset_action.setChecked(
            self.keyboard_horizontal_offset)
        keyboard_horizontal_offset_action.triggered.connect(
            self.toggle_keyboard_horizontal_offset)
        parent_menu.addAction(keyboard_horizontal_offset_action)

        keypress_menu = parent_menu.addMenu('按键显示')

        keypress_display_action = QAction('启用按键显示', self)
        keypress_display_action.setCheckable(True)
        keypress_display_action.setChecked(self.keypress_display_enabled)
        keypress_display_action.triggered.connect(self.toggle_keypress_display)
        keypress_menu.addAction(keypress_display_action)

        keypress_background_action = QAction('显示按键背景', self)
        keypress_background_action.setCheckable(True)
        keypress_background_action.setChecked(self.keypress_display_background)
        keypress_background_action.triggered.connect(
            self.toggle_keypress_display_background)
        keypress_menu.addAction(keypress_background_action)

    def _add_character_menu(self, parent_menu):
        """添加角色切换子菜单"""
        if self.character_manager.characters:
            character_menu = parent_menu.addMenu('切换角色')
            for character in self.character_manager.characters.keys():
                char_action = QAction(character, self)
                char_action.triggered.connect(
                    lambda checked, c=character: self.switch_to_character(c))
                character_menu.addAction(char_action)
            parent_menu.addSeparator()

    def closeEvent(self, event):
        """关闭事件"""
        pos = self.pos()
        self.global_settings.set('window_x', pos.x())
        self.global_settings.set('window_y', pos.y())
        self.global_settings.set(
            'last_character', self.character_manager.current_character)
        self.global_settings.save()

        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.stop()
        if hasattr(self, 'custom_layer_timer'):
            self.custom_layer_timer.stop()

        self.input_handler.stop_listeners()
        self.input_handler.stop_animation()
        self.tray_manager.hide()

        event.accept()
        QApplication.quit()


if __name__ == '__main__':
    # 设置 OpenGL 渲染以支持 OBS 游戏捕获
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    pet = DesktopPet()
    sys.exit(app.exec())