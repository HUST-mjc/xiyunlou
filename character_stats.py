# -*- coding: utf-8 -*-
"""角色专属每日统计
梨安     → 今天摄入的卡路里（千卡）
恬豆     → 今天喝了几杯咖啡（杯）
又一     → 今天刷到了几个视频（个）
沐霂     → 今天狗妹上了几次厕所（次）
明前奶绿 → 距离上顿吃饭时间（计时器）
"""
import time
from datetime import datetime


CHARACTER_CONFIG = {
    "梨安":     {"label": "今天摄入的卡路里",   "unit": "千卡", "mode": "count",
                 "step": 100, "icon": "🍰"},
    "恬豆":     {"label": "今天喝了几杯咖啡",   "unit": "杯",   "mode": "count",
                 "step": 1,   "icon": "☕"},
    "又一":     {"label": "今天刷到了几个视频", "unit": "个",   "mode": "count",
                 "step": 1,   "icon": "📺"},
    "沐霂":     {"label": "今天狗妹上了几次厕所", "unit": "次", "mode": "count",
                 "step": 1,   "icon": "🐶"},
    "明前奶绿": {"label": "距离上顿吃饭时间",   "unit": "",     "mode": "timer",
                 "icon": "🍚"},
}


class CharacterDailyStats:
    def __init__(self, cfg, save_fn):
        self.cfg = cfg
        self._save = save_fn
        s = cfg.setdefault("char_stats", {})
        s.setdefault("daily", {})       # {character: {date: value}}
        s.setdefault("last_meal", {})   # {date_str: unix_ts}

    @staticmethod
    def _today():
        return datetime.now().strftime("%Y-%m-%d")

    def config_for(self, character):
        return CHARACTER_CONFIG.get(character, {
            "label": "今日统计", "unit": "", "mode": "count",
            "step": 1, "icon": "📊",
        })

    def value(self, character):
        d = self.cfg["char_stats"]["daily"].setdefault(character, {})
        return int(d.get(self._today(), 0))

    def add(self, character, n=1):
        d = self.cfg["char_stats"]["daily"].setdefault(character, {})
        d[self._today()] = self.value(character) + n
        self._save(self.cfg)

    def undo(self, character):
        d = self.cfg["char_stats"]["daily"].setdefault(character, {})
        cur = self.value(character)
        if cur <= 0:
            return
        d[self._today()] = cur - 1
        self._save(self.cfg)

    def reset_today(self, character):
        self.cfg["char_stats"]["daily"].setdefault(character, {})[
            self._today()] = 0
        self._save(self.cfg)

    # ---------- 明前奶绿计时 ----------
    def meal_elapsed_minutes(self):
        last = self.cfg["char_stats"]["last_meal"].get(self._today())
        if not last:
            return None
        return int((time.time() - float(last)) / 60)

    def mark_meal(self):
        s = self.cfg["char_stats"]
        s["last_meal"][self._today()] = time.time()
        keep = self._today()
        for k in list(s["last_meal"].keys()):
            if k != keep:
                s["last_meal"].pop(k, None)
        self._save(self.cfg)

    # ---------- 文本 ----------
    def summary_text(self, character):
        cfg = self.config_for(character)
        label = cfg["label"]
        if cfg["mode"] == "timer":
            mins = self.meal_elapsed_minutes()
            if mins is None:
                return f"{label}：未记录"
            h, m = divmod(mins, 60)
            return f"{label}：{h}小时{m}分钟" if h else f"{label}：{m}分钟"
        return f"{label}：{self.value(character)} {cfg['unit']}"

    def tray_text(self, character):
        cfg = self.config_for(character)
        if cfg["mode"] == "timer":
            mins = self.meal_elapsed_minutes()
            return f"{cfg['icon']}--" if mins is None else f"{cfg['icon']}{mins}m"
        return f"{cfg['icon']}{self.value(character)}"

    def weekly_text(self, character):
        from datetime import timedelta
        daily = self.cfg["char_stats"]["daily"].get(character, {})
        lines = [f"{character} · 近 7 天记录："]
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            lines.append(f"  {d}  {daily.get(d, 0)}")
        return "\n".join(lines)