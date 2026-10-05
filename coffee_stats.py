# -*- coding: utf-8 -*-
"""
咖啡统计模块
=========================================================
功能：
  · 记录每日咖啡杯数
  · 支持手加 / 撤销 / 重置
  · 提供近 7 天数据用于绘制简易柱状图
  · 持久化到 pet_config.json 的 "coffee_stats" 字段

【对外接口】
  CoffeeStats(cfg, save_config)
    · add(n=1)          +n 杯
    · undo()            撤销上一杯（今日）
    · reset_today()     清零今日
    · today()           今日杯数
    · weekly()          近 7 天 [(日期, 杯数), ...]
    · weekly_total()    近 7 天总计
    · mood_hint()       根据今日杯数返回情绪建议
=========================================================
"""

import json
import time
from datetime import datetime, timedelta


class CoffeeStats:
    def __init__(self, cfg, save_config):
        self.cfg = cfg
        self._save = save_config

        stats = cfg.setdefault("coffee_stats", {})
        stats.setdefault("daily", {})       # {"2026-10-02": 3, ...}
        stats.setdefault("limit", 4)        # 每日建议上限

    # ---------- 内部 ----------
    @staticmethod
    def _today():
        return datetime.now().strftime("%Y-%m-%d")

    def _prune(self):
        """只保留最近 60 天，防止配置文件无限膨胀"""
        daily = self.cfg["coffee_stats"]["daily"]
        cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        for d in list(daily.keys()):
            if d < cutoff:
                daily.pop(d, None)

    # ---------- 查询 ----------
    def today(self):
        return int(self.cfg["coffee_stats"]["daily"].get(self._today(), 0))

    def weekly(self):
        """返回 [(YYYY-MM-DD, 杯数), ...]，按时间升序，共 7 天"""
        daily = self.cfg["coffee_stats"]["daily"]
        result = []
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            result.append((d, int(daily.get(d, 0))))
        return result

    def weekly_total(self):
        return sum(n for _, n in self.weekly())

    def limit(self):
        return int(self.cfg["coffee_stats"].get("limit", 4))

    def mood_hint(self):
        """返回一个建议的表情键名"""
        n = self.today()
        limit = self.limit()
        if n == 0:
            return "normal"
        if n < limit:
            return "normal"
        if n == limit:
            return "queshi"      # 刚好到量
        if n <= limit + 2:
            return "down"        # 超了一点
        return "boom"            # 超太多了

    def summary_text(self):
        n = self.today()
        limit = self.limit()
        bar = "☕" * min(n, 10)
        if n > limit:
            bar += f"  (超标 +{n - limit})"
        return f"今日咖啡：{n}/{limit} {bar}"

    def weekly_text(self):
        """多行文本，用于消息提示"""
        lines = ["近 7 天咖啡记录："]
        for d, n in self.weekly():
            bar = "☕" * n if n > 0 else "·"
            lines.append(f"  {d}  {bar}  ({n})")
        lines.append(f"合计：{self.weekly_total()} 杯")
        return "\n".join(lines)

    # ---------- 修改 ----------
    def add(self, n=1):
        daily = self.cfg["coffee_stats"]["daily"]
        today = self._today()
        daily[today] = int(daily.get(today, 0)) + n
        self._prune()
        self._save(self.cfg)
        print(f"[咖啡] +{n}，今日共 {self.today()} 杯")
        return self.today()

    def undo(self):
        daily = self.cfg["coffee_stats"]["daily"]
        today = self._today()
        cur = int(daily.get(today, 0))
        if cur <= 0:
            return 0
        daily[today] = cur - 1
        self._save(self.cfg)
        print(f"[咖啡] 撤销一杯，今日剩 {self.today()} 杯")
        return self.today()

    def reset_today(self):
        daily = self.cfg["coffee_stats"]["daily"]
        daily[self._today()] = 0
        self._save(self.cfg)
        print("[咖啡] 今日已清零")
        return 0

    def set_limit(self, n):
        self.cfg["coffee_stats"]["limit"] = max(1, int(n))
        self._save(self.cfg)


# ---------- 简易柱状图（终端渲染，用于调试或菜单提示） ----------
def bar_chart_text(stats: CoffeeStats, width=20):
    """
    生成纯文本柱状图，比如：
        10-01  ████████   (4)
        10-02  ████████████ (6)
    """
    lines = []
    max_n = max((n for _, n in stats.weekly()), default=1) or 1
    for d, n in stats.weekly():
        bar_len = int(width * n / max_n) if max_n > 0 else 0
        bar = "█" * bar_len
        lines.append(f"  {d[5:]}  {bar}  ({n})")
    return "\n".join(lines)