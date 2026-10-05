import json
import os
import re
import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QPushButton, QGroupBox, QFormLayout,
    QWidget, QApplication, QTabWidget, QLineEdit, QComboBox,
    QCheckBox,
)
from PyQt6.QtCore import Qt
from path_manager import path_manager


class GlobalSettings:
    """全局设置管理类"""
    DEFAULT_SETTINGS = {
        'window_x': 0,
        'window_y': 0,
        'last_character': None,
    }

    def __init__(self, config_file='global_config.json'):
        if not os.path.isabs(config_file):
            self.config_file = path_manager.get_global_config_file()
        else:
            self.config_file = config_file
        self.settings = self.load()

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    settings = self.DEFAULT_SETTINGS.copy()
                    settings.update(loaded)
                    return settings
            except Exception as e:
                print(f"加载全局设置失败: {e}")
                return self.DEFAULT_SETTINGS.copy()
        return self.DEFAULT_SETTINGS.copy()

    def save(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存全局设置失败: {e}")
            return False

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value

    @staticmethod
    def get_startup_folder():
        try:
            from win32com.shell import shell, shellcon  # type: ignore
            return shell.SHGetFolderPath(
                0, shellcon.CSIDL_STARTUP, None, 0)
        except Exception:
            return os.path.join(
                os.environ.get('APPDATA', ''),
                'Microsoft', 'Windows', 'Start Menu',
                'Programs', 'Startup')

    @staticmethod
    def open_startup_folder():
        try:
            import subprocess
            folder = GlobalSettings.get_startup_folder()
            if os.path.exists(folder):
                subprocess.Popen(f'explorer "{folder}"')
                return True
            return False
        except Exception as e:
            print(f"打开启动文件夹失败: {e}")
            return False

    @staticmethod
    def get_program_path():
        if getattr(sys, 'frozen', False):
            return sys.executable
        return path_manager.get_path('main.py')


class Settings:
    """角色配置管理类"""

    DEFAULT_SETTINGS = {
        'window_width': 240,
        'window_height': 135,
        'bg_width': 240,
        'bg_height': 135,
        'keyboard_x': 94,
        'keyboard_y': 84,
        'keyboard_width': 25,
        'keyboard_height': 25,
        'keyboard_press_offset': 5,
        'keyboard_horizontal_travel': 50,
        'mouse_x': 190,
        'mouse_y': 90,
        'mouse_width': 25,
        'mouse_height': 25,
        'max_mouse_offset': 20,
        'mouse_sensitivity': 0.3,
        'mouse_return_speed': 0.05,
        'sync_scale_enabled': False,
        'keypress_display_enabled': True,
        'keypress_display_x': 8,
        'keypress_display_y': 46,
        'keypress_display_font_size': 20,
        'keypress_display_max_width': 50,
        'keypress_display_height': 49,

        # ---------- 新增 ----------
        'live_room_id': 0,
        'live_check_interval': 60,
        'weather_city': '北京',
        'note_bg_file': '',
        'show_weather': True,

        # ---------- 便利贴（floral-notepaper 集成） ----------
        'sticky_markdown_mode': False,
        'sticky_pinned': False,

        # ---------- B站直播预告抓取 ----------
        'bili_auto_fetch': True,
        'bili_fetch_hour': 15,
        'bili_fetch_minute': 0,
        'bili_keywords': ['梨安', '又一', '沐霂', '恬豆'],
    }

    def __init__(self, character_name, character_folder):
        self.character_name = character_name
        self.character_folder = character_folder
        self.config_file = os.path.join(character_folder, 'config.json')
        self.settings = self.load()

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    settings = self.DEFAULT_SETTINGS.copy()
                    settings.update(loaded)
                    if settings.get('keyboard_press_offset', 0) <= 0:
                        settings['keyboard_press_offset'] = \
                            self.DEFAULT_SETTINGS['keyboard_press_offset']
                    # 保证 bili_keywords 始终是 list
                    if not isinstance(
                            settings.get('bili_keywords'), list):
                        settings['bili_keywords'] = \
                            self.DEFAULT_SETTINGS['bili_keywords']
                    return settings
            except Exception as e:
                print(f"加载{self.character_name}配置失败: {e}")
                return self.DEFAULT_SETTINGS.copy()
        return self.DEFAULT_SETTINGS.copy()

    def save(self):
        try:
            data = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data.update(self.settings)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存{self.character_name}配置失败: {e}")
            return False

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value

    def reset(self):
        self.settings = self.DEFAULT_SETTINGS.copy()


# ============================================================
#  设置对话框
# ============================================================
class SettingsDialog(QDialog):
    """设置对话框 —— 天气/直播间/便利贴 都在这里配置"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.parent_widget = parent
        self.global_settings = (
            parent.global_settings if parent else None)

        # 暂停鼠标同步
        self._mouse_timer_was_running = False
        if parent and hasattr(parent, 'mouse_timer'):
            try:
                self._mouse_timer_was_running = parent.mouse_timer.isActive()
                if self._mouse_timer_was_running:
                    parent.mouse_timer.stop()
            except Exception:
                pass

        # 保存初始值（用于取消时回滚 UI 无关的设置）
        self._initial_weather_city = self.settings.get(
            'weather_city', '北京')
        self._initial_live_room = self.settings.get('live_room_id', 0)
        self._initial_live_interval = self.settings.get(
            'live_check_interval', 60)
        self._initial_note_bg = self.settings.get('note_bg_file', '')
        self._initial_md_mode = self.settings.get(
            'sticky_markdown_mode', False)
        self._initial_bili_fetch = self.settings.get(
            'bili_auto_fetch', True)
        self._initial_bili_keywords = list(self.settings.get(
            'bili_keywords', ['梨安', '又一', '沐霂', '恬豆']))

        self.init_ui()

    # ------------------------------------------------------
    #  UI
    # ------------------------------------------------------
    def init_ui(self):
        self.setWindowTitle('设置')
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(560)

        self.tab_widget = QTabWidget()
        self.create_general_tab()
        self.create_image_adjustment_tab()

        button_layout = QHBoxLayout()

        reset_btn = QPushButton('重置默认')
        reset_btn.clicked.connect(self.reset_settings)
        button_layout.addWidget(reset_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton('保存')
        save_btn.clicked.connect(self.save_settings)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tab_widget)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self.tab_widget.setCurrentIndex(0)
        save_btn.setFocus()

    def create_general_tab(self):
        general_widget = QWidget()
        layout = QVBoxLayout(general_widget)

        # ---------- 启动设置 ----------
        startup_group = QGroupBox('启动设置')
        startup_layout = QHBoxLayout()

        self.startup_guide_btn = QPushButton('开机自启动')
        self.startup_guide_btn.clicked.connect(self.show_startup_guide)
        startup_layout.addWidget(self.startup_guide_btn)

        self.open_startup_folder_btn = QPushButton('打开启动文件夹')
        self.open_startup_folder_btn.clicked.connect(
            self.open_startup_folder)
        startup_layout.addWidget(self.open_startup_folder_btn)

        startup_group.setLayout(startup_layout)
        layout.addWidget(startup_group)

        # ---------- 天气设置 ----------
        weather_group = QGroupBox('天气设置')
        weather_form = QFormLayout()

        self.city_edit = QLineEdit()
        self.city_edit.setText(self.settings.get('weather_city', '北京'))
        self.city_edit.setPlaceholderText('例如：北京 / 上海 / 广州 / 杭州')
        weather_form.addRow('城市：', self.city_edit)

        weather_group.setLayout(weather_form)
        layout.addWidget(weather_group)

        # ---------- 直播间设置 ----------
        live_group = QGroupBox('直播间设置')
        live_form = QFormLayout()

        self.live_room_edit = QLineEdit()
        cur_room = self.settings.get('live_room_id', 0)
        self.live_room_edit.setText(str(cur_room) if cur_room else '')
        self.live_room_edit.setPlaceholderText(
            '例如：21756924（留空 = 不监听）')
        live_form.addRow('房间号：', self.live_room_edit)

        self.live_interval_spin = QSpinBox()
        self.live_interval_spin.setRange(30, 3600)
        self.live_interval_spin.setValue(
            int(self.settings.get('live_check_interval', 60)))
        self.live_interval_spin.setSuffix(' 秒')
        live_form.addRow('检查间隔：', self.live_interval_spin)

        tip = QLabel('※ 每个角色独立配置，只监听当前显示角色的直播间')
        tip.setStyleSheet('color: #888; font-size: 11px;')
        live_form.addRow('', tip)

        live_group.setLayout(live_form)
        layout.addWidget(live_group)

        # ---------- 便利贴设置 ----------
        note_group = QGroupBox('便利贴设置')
        note_form = QFormLayout()

        self.note_bg_combo = QComboBox()
        self.note_bg_combo.addItem('（默认黄底）', '')
        try:
            from sticky_note import list_note_bg_files
            for name in list_note_bg_files():
                self.note_bg_combo.addItem(name, name)
        except Exception as e:
            print(f"[设置] 读取便利贴背景图列表失败: {e}")

        cur_bg = self.settings.get('note_bg_file', '') or ''
        idx = self.note_bg_combo.findData(cur_bg)
        if idx >= 0:
            self.note_bg_combo.setCurrentIndex(idx)
        note_form.addRow('背景图：', self.note_bg_combo)

        bg_tip = QLabel('※ 背景图放在 note/ 目录下')
        bg_tip.setStyleSheet('color: #888; font-size: 11px;')
        note_form.addRow('', bg_tip)

        # Markdown 预览开关
        self.md_mode_check = QCheckBox('启用 Markdown 预览（Ctrl+P 切换）')
        self.md_mode_check.setChecked(
            self.settings.get('sticky_markdown_mode', False))
        note_form.addRow('', self.md_mode_check)

        note_group.setLayout(note_form)
        layout.addWidget(note_group)

        # ---------- B站直播预告设置 ----------
        bili_group = QGroupBox('B站直播预告检索')
        bili_form = QFormLayout()

        self.bili_fetch_check = QCheckBox(
            '每天 15:00 自动检索并追加到便利贴')
        self.bili_fetch_check.setChecked(
            self.settings.get('bili_auto_fetch', True))
        bili_form.addRow('', self.bili_fetch_check)

        self.bili_keywords_edit = QLineEdit()
        kws = self.settings.get(
            'bili_keywords', ['梨安', '又一', '沐霂', '恬豆'])
        self.bili_keywords_edit.setText('、'.join(kws))
        self.bili_keywords_edit.setPlaceholderText(
            '用顿号分隔，如：梨安、又一、沐霂、恬豆')
        bili_form.addRow('检索关键词：', self.bili_keywords_edit)

        bili_tip = QLabel(
            '※ 检索对象：https://space.bilibili.com/413748120/dynamic\n'
            '※ 需安装 requests：pip install requests')
        bili_tip.setStyleSheet('color: #888; font-size: 11px;')
        bili_form.addRow('', bili_tip)

        bili_group.setLayout(bili_form)
        layout.addWidget(bili_group)

        layout.addStretch()
        self.tab_widget.addTab(general_widget, '常规设置')

    def create_image_adjustment_tab(self):
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        info_label = QLabel(
            '图像调整功能已移至图层管理器中。\n\n'
            '请通过右键菜单选择"自定义图层管理器"来调整图像位置、大小等属性。')
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet(
            'QLabel { font-size: 14px; color: #666; padding: 50px; }')
        layout.addWidget(info_label)

        open_button = QPushButton('打开图层管理器')
        open_button.clicked.connect(self.open_layer_manager)
        open_button.setMaximumWidth(200)
        layout.addWidget(open_button,
                         alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        self.tab_widget.addTab(content_widget, '图像调整')

    def open_layer_manager(self):
        if self.parent_widget and hasattr(
                self.parent_widget, 'open_custom_layer_manager'):
            self.parent_widget.open_custom_layer_manager()
            self.close()

    # ------------------------------------------------------
    #  按钮回调
    # ------------------------------------------------------
    def show_startup_guide(self):
        from PyQt6.QtWidgets import QMessageBox

        program_path = GlobalSettings.get_program_path()
        startup_folder = GlobalSettings.get_startup_folder()

        guide_text = f"""<h3>开机自启动设置教程</h3>
<p><b>手动创建快捷方式</b></p>
<ol>
<li>右键点击程序文件，选择"创建快捷方式"<br>
   应该显示的程序位置：<code>{program_path}</code></li>
<li>将创建的快捷方式移动到启动文件夹<br>
   启动文件夹的位置：<code>{startup_folder}</code></li>
   可以直接点击设置中的按钮打开
<li>重启电脑测试是否自动启动</li>
</ol>
<p><b>提示：</b>如果已经创建了快捷方式但无法自启动，请尝试：
使用 windows 计划任务启动。</p>"""

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("开机自启动教程")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(guide_text)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def open_startup_folder(self):
        from PyQt6.QtWidgets import QMessageBox

        if GlobalSettings.open_startup_folder():
            QMessageBox.information(self, "成功", "已打开启动文件夹")
        else:
            startup_folder = GlobalSettings.get_startup_folder()
            QMessageBox.warning(
                self, "失败",
                f"无法打开启动文件夹\n路径：{startup_folder}")

    def reset_settings(self):
        """重置 UI 控件到默认值（不直接改 self.settings，保存时再生效）"""
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, '确认重置',
            '确定要把所有设置恢复为默认值吗？\n（保存后才会生效）',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ok != QMessageBox.StandardButton.Yes:
            return

        self.city_edit.setText('北京')
        self.live_room_edit.setText('')
        self.live_interval_spin.setValue(60)
        if self.note_bg_combo.count() > 0:
            self.note_bg_combo.setCurrentIndex(0)

        # 便利贴 Markdown / B站
        self.md_mode_check.setChecked(False)
        self.bili_fetch_check.setChecked(True)
        self.bili_keywords_edit.setText('梨安、又一、沐霂、恬豆')

    # ------------------------------------------------------
    #  保存 / 取消
    # ------------------------------------------------------
    def _apply_ui_to_settings(self):
        """把 UI 值写回 self.settings"""

        # 天气城市
        city = self.city_edit.text().strip() or '北京'
        self.settings.set('weather_city', city)

        # 直播间
        txt = self.live_room_edit.text().strip()
        try:
            room_id = int(txt) if txt else 0
        except ValueError:
            room_id = 0
        self.settings.set('live_room_id', room_id)
        self.settings.set('live_check_interval',
                          self.live_interval_spin.value())

        # 便利贴背景
        self.settings.set(
            'note_bg_file', self.note_bg_combo.currentData() or '')

        # 便利贴 Markdown
        self.settings.set(
            'sticky_markdown_mode', self.md_mode_check.isChecked())

        # B站直播预告
        self.settings.set(
            'bili_auto_fetch', self.bili_fetch_check.isChecked())
        kws_text = self.bili_keywords_edit.text().strip()
        if kws_text:
            kws = [k.strip() for k in re.split(r'[、,，]', kws_text)
                   if k.strip()]
        else:
            kws = ['梨安', '又一', '沐霂', '恬豆']
        self.settings.set('bili_keywords', kws)

    def save_settings(self):
        self._apply_ui_to_settings()

        if self.settings.save():
            # 恢复鼠标定时器
            if (self.parent_widget
                    and hasattr(self.parent_widget, 'mouse_timer')
                    and self._mouse_timer_was_running):
                try:
                    self.parent_widget.mouse_timer.start(16)
                except Exception:
                    pass
            self.accept()

    def reject(self):
        # 恢复鼠标定时器
        if (self.parent_widget
                and hasattr(self.parent_widget, 'mouse_timer')
                and self._mouse_timer_was_running):
            try:
                self.parent_widget.mouse_timer.start(16)
            except Exception:
                pass

        # 恢复初始设置（避免 UI 改了没保存）
        self.settings.set('weather_city', self._initial_weather_city)
        self.settings.set('live_room_id', self._initial_live_room)
        self.settings.set('live_check_interval', self._initial_live_interval)
        self.settings.set('note_bg_file', self._initial_note_bg)
        self.settings.set('sticky_markdown_mode', self._initial_md_mode)
        self.settings.set('bili_auto_fetch', self._initial_bili_fetch)
        self.settings.set(
            'bili_keywords', list(self._initial_bili_keywords))

        super().reject()