# -*- coding: utf-8 -*-
"""游戏启动器（PyQt6 版）"""

import os
import shutil
import subprocess

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QHBoxLayout, QDialogButtonBox, QFileDialog,
)
from PyQt6.QtCore import Qt


GAME_PRESETS = [
    ("steam", "Steam", [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
    ]),
    ("epic", "Epic Games", [
        r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
        r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
    ]),
    ("custom", "自定义 EXE", []),
]

_EXE_ALIASES = {"steam": "steam", "epic": "EpicGamesLauncher"}


def find_launcher_exe(key, custom_path=""):
    if key == "custom":
        return custom_path if (custom_path and os.path.exists(custom_path)) else None
    for k, _n, paths in GAME_PRESETS:
        if k == key:
            for p in paths:
                if os.path.exists(p):
                    return p
            alias = _EXE_ALIASES.get(key)
            if alias:
                found = shutil.which(alias)
                if found:
                    return found
    return None


def launch_game(key, custom_path=""):
    exe = find_launcher_exe(key, custom_path)
    creationflags = 0x08000000 if os.name == "nt" else 0

    if exe:
        try:
            subprocess.Popen([exe], creationflags=creationflags)
            return True, exe, "exe"
        except Exception as e:
            print(f"[游戏] 启动失败：{exe} -> {e}")

    try:
        if key == "steam":
            os.startfile("steam://open/main")
            return True, "steam://open/main", "protocol"
        if key == "epic":
            os.startfile("com.epicgames.launcher://apps")
            return True, "com.epicgames.launcher://apps", "protocol"
    except Exception as e:
        print(f"[游戏] 协议启动失败：{e}")

    return False, "", "fail"