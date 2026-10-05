# -*- coding: utf-8 -*-
"""天气模块（PyQt6 版）"""

import os
import math
import json
import time
import random
import threading
import urllib.parse
from urllib.request import urlopen, Request

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

OP_VIDEO_NAME = "OP.mp4"
GEO_API = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_API = "https://api.open-meteo.com/v1/forecast"

WMO_CODE_MAP = {
    0: ("晴", "clear"), 1: ("晴间多云", "partly"), 2: ("多云", "cloudy"),
    3: ("阴", "overcast"), 45: ("雾", "fog"), 48: ("雾凇", "fog"),
    51: ("毛毛雨", "rain"), 53: ("小雨", "rain"), 55: ("中雨", "rain"),
    56: ("冻毛毛雨", "rain"), 57: ("冻雨", "rain"), 61: ("小雨", "rain"),
    63: ("中雨", "rain"), 65: ("大雨", "rain"), 66: ("冻雨", "rain"),
    67: ("强冻雨", "rain"), 71: ("小雪", "snow"), 73: ("中雪", "snow"),
    75: ("大雪", "snow"), 77: ("米雪", "snow"), 80: ("阵雨", "rain"),
    81: ("强阵雨", "rain"), 82: ("暴雨", "rain"), 85: ("阵雪", "snow"),
    86: ("强阵雪", "snow"), 95: ("雷阵雨", "thunder"),
    96: ("雷阵雨伴冰雹", "thunder"), 99: ("雷暴冰雹", "thunder"),
}


def find_op_video(*search_dirs):
    if search_dirs:
        candidates = [os.path.join(d, OP_VIDEO_NAME) for d in search_dirs if d]
    else:
        candidates = [OP_VIDEO_NAME, os.path.join("pets", OP_VIDEO_NAME)]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def geocode_city(city):
    if not city:
        return None
    try:
        url = (f"{GEO_API}?name={urllib.parse.quote(city)}"
               f"&count=1&language=zh&format=json")
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results") or []
        if results:
            r = results[0]
            return (float(r["latitude"]), float(r["longitude"]),
                    r.get("name", city))
    except Exception as e:
        print(f"[天气] 城市解析失败：{e}")
    return None


def fetch_weather(lat, lon):
    try:
        url = (f"{WEATHER_API}?latitude={lat}&longitude={lon}"
               f"&current=temperature_2m,weather_code,"
               f"relative_humidity_2m,wind_speed_10m&timezone=auto")
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cur = data.get("current", {}) or {}
        return {
            "temp": cur.get("temperature_2m"),
            "code": cur.get("weather_code", 0),
            "humidity": cur.get("relative_humidity_2m"),
            "wind": cur.get("wind_speed_10m"),
        }
    except Exception as e:
        print(f"[天气] 获取失败：{e}")
    return None


class WeatherService:
    def __init__(self, cfg, save_config_fn, emit_fn):
        self.cfg = cfg
        self.save_config = save_config_fn
        self.emit = emit_fn
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _emit(self, temp, code):
        try:
            self.emit(temp, code)
        except Exception:
            pass

    def _run(self):
        cached_city = None
        lat = lon = None
        for _ in range(2):
            if not self._running:
                return
            time.sleep(1)

        while self._running:
            city = (self.cfg.get("weather_city") or "北京").strip()
            if city != cached_city:
                geo = geocode_city(city)
                if not geo:
                    self._emit(None, None)
                    for _ in range(60):
                        if not self._running:
                            return
                        time.sleep(1)
                    continue
                lat, lon, _d = geo
                cached_city = city
            else:
                lat = self.cfg.get("weather_lat")
                lon = self.cfg.get("weather_lon")
                if lat is None or lon is None:
                    cached_city = None
                    continue

            w = fetch_weather(lat, lon)
            if w:
                self._emit(w.get("temp"), w.get("code"))
            else:
                self._emit(None, None)

            interval = max(300, int(self.cfg.get("weather_check_interval", 1800)))
            for _ in range(interval):
                if not self._running:
                    return
                time.sleep(1)


class WeatherAnimWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.weather = "none"
        self._particles = []
        self._tick = 0
        self._flash = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(50)

    def set_weather(self, kind):
        kind = kind or "none"
        if kind == self.weather:
            return
        self.weather = kind
        self._seed()
        self.update()

    def _seed(self):
        self._particles = []
        w, h = max(self.width(), 1), max(self.height(), 1)
        if self.weather in ("rain", "thunder"):
            n = 55 if self.weather == "rain" else 80
            for _ in range(n):
                self._particles.append({
                    "x": random.uniform(-w * 0.2, w),
                    "y": random.uniform(0, h),
                    "v": random.uniform(5.0, 10.0),
                    "l": random.uniform(7, 15),
                })
        elif self.weather == "snow":
            for _ in range(40):
                self._particles.append({
                    "x": random.uniform(0, w), "y": random.uniform(0, h),
                    "v": random.uniform(0.8, 2.2),
                    "r": random.uniform(1.2, 3.0),
                    "ph": random.uniform(0, math.pi * 2),
                })
        elif self.weather in ("cloudy", "overcast", "partly"):
            for _ in range(4):
                self._particles.append({
                    "x": random.uniform(0, w),
                    "y": random.uniform(0, h * 0.45),
                    "v": random.uniform(0.25, 0.8),
                    "s": random.uniform(0.6, 1.1),
                })
        elif self.weather == "fog":
            for _ in range(5):
                self._particles.append({
                    "x": random.uniform(-w * 0.4, w),
                    "y": random.uniform(0, h),
                    "v": random.uniform(0.3, 0.9),
                    "s": random.uniform(0.7, 1.5),
                })

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._seed()

    def _on_tick(self):
        self._tick += 1
        w, h = max(self.width(), 1), max(self.height(), 1)
        if self.weather in ("rain", "thunder"):
            for p in self._particles:
                p["y"] += p["v"]
                p["x"] -= p["v"] * 0.15
                if p["y"] > h + 5:
                    p["y"] = -p["l"]
                    p["x"] = random.uniform(0, w)
                if p["x"] < -12:
                    p["x"] = w + 5
            if self.weather == "thunder":
                if self._flash > 0:
                    self._flash = max(0, self._flash - 28)
                elif random.random() < 0.008:
                    self._flash = 200
        elif self.weather == "snow":
            for p in self._particles:
                p["y"] += p["v"]
                p["ph"] += 0.06
                p["x"] += math.sin(p["ph"]) * 0.7
                if p["y"] > h + 3:
                    p["y"] = -3
                    p["x"] = random.uniform(0, w)
        elif self.weather in ("cloudy", "overcast", "partly"):
            for p in self._particles:
                p["x"] += p["v"]
                if p["x"] > w + 50:
                    p["x"] = -50
        elif self.weather == "fog":
            for p in self._particles:
                p["x"] += p["v"]
                if p["x"] > w + 40:
                    p["x"] = -w * 0.4
        if self.weather != "none":
            self.update()

    def paintEvent(self, event):
        if self.weather == "none":
            return
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.weather == "clear":
            self._draw_sun(painter, w, h, 255)
        elif self.weather == "partly":
            self._draw_sun(painter, w, h, 150)
            self._draw_clouds(painter, w, h, dark=False)
        elif self.weather == "cloudy":
            self._draw_clouds(painter, w, h, dark=False)
        elif self.weather == "overcast":
            self._draw_clouds(painter, w, h, dark=True)
        elif self.weather in ("rain", "thunder"):
            self._draw_rain(painter)
            if self._flash > 0:
                painter.fillRect(self.rect(),
                                 QColor(255, 255, 200, min(200, self._flash)))
        elif self.weather == "snow":
            self._draw_snow(painter)
        elif self.weather == "fog":
            self._draw_fog(painter, w, h)

    def _draw_sun(self, painter, w, h, alpha=255):
        cx, cy = w * 0.82, h * 0.16
        r = min(w, h) * 0.10
        pulse = 1.0 + 0.12 * math.sin(self._tick * 0.08)
        glow = QRadialGradient(cx, cy, r * 3.2 * pulse)
        glow.setColorAt(0.0, QColor(255, 230, 120, int(alpha * 0.55)))
        glow.setColorAt(1.0, QColor(255, 230, 120, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(cx, cy), r * 3.2 * pulse, r * 3.2 * pulse)
        painter.setBrush(QColor(255, 210, 70, alpha))
        painter.drawEllipse(QPointF(cx, cy), r * pulse, r * pulse)
        painter.setPen(QPen(QColor(255, 220, 100, alpha), 1.6))
        for i in range(8):
            ang = i * math.pi / 4 + self._tick * 0.01
            rr = 2.1 + 0.2 * math.sin(self._tick * 0.1 + i)
            x1 = cx + math.cos(ang) * r * 1.5
            y1 = cy + math.sin(ang) * r * 1.5
            x2 = cx + math.cos(ang) * r * rr
            y2 = cy + math.sin(ang) * r * rr
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _draw_clouds(self, painter, w, h, dark=False):
        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._particles:
            color = (QColor(110, 118, 130, 165) if dark
                     else QColor(255, 255, 255, 120))
            cx = p["x"]
            cy = p["y"] + h * 0.14
            s = p["s"] * min(w, h) * 0.14
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), s * 1.5, s)
            painter.drawEllipse(QPointF(cx - s * 0.9, cy + s * 0.2), s * 0.9, s * 0.65)
            painter.drawEllipse(QPointF(cx + s * 0.9, cy + s * 0.2), s * 1.0, s * 0.7)

    def _draw_rain(self, painter):
        painter.setPen(QPen(QColor(155, 195, 240, 175), 1.2))
        for p in self._particles:
            painter.drawLine(
                QPointF(p["x"], p["y"]),
                QPointF(p["x"] - p["l"] * 0.15, p["y"] + p["l"]),
            )

    def _draw_snow(self, painter):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 215))
        for p in self._particles:
            painter.drawEllipse(QPointF(p["x"], p["y"]), p["r"], p["r"])

    def _draw_fog(self, painter, w, h):
        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._particles:
            band_w = w * 0.9 * p["s"]
            band_h = h * 0.09 * p["s"]
            grad = QLinearGradient(p["x"], 0, p["x"] + band_w, 0)
            grad.setColorAt(0.0, QColor(232, 238, 245, 0))
            grad.setColorAt(0.5, QColor(232, 238, 245, 125))
            grad.setColorAt(1.0, QColor(232, 238, 245, 0))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(
                QRectF(p["x"], p["y"], band_w, band_h),
                band_h / 2, band_h / 2,
            )