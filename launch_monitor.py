# -*- coding: utf-8 -*-
"""
监控室启动器
================================================
· 检测 梨安 / 恬豆 / 又一 / 沐霂（以及其它预置角色）是否正在直播
· 默认行为：无条件启动 video.py
    - 有角色直播 → 自动预填正在直播的房间号
    - 无角色直播 → 启动空的监控室（不预填）
· 可加 --only-if-live 参数：只有检测到直播才启动
"""

import argparse
import json
import os
import subprocess
import sys
import time
from urllib.request import urlopen, Request


# 关注的直播间（角色 → B 站房间号）
DEFAULT_LIVE_ROOMS = {
    "梨安": 23770996,
    "又一": 23771092,
    "沐霂": 23771139,
    "恬豆": 23771189,
    "明前奶绿": 26966466,
    "栞栞Shiori": 26966466
}

# 主要关注的四位（默认检查目标）
PRIMARY_TARGETS = ["梨安", "又一", "沐霂", "恬豆"]

LIVE_API = ("https://api.live.bilibili.com/room/v1/Room/get_info"
            "?room_id={room_id}")
LIVE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/120.0.0.0 Safari/537.36")


def check_live_status(room_id):
    """返回 (live_status, title)。live_status: 0=未播 1=直播中 2=轮播 -1=失败"""
    try:
        url = LIVE_API.format(room_id=room_id)
        req = Request(url, headers={
            "User-Agent": LIVE_UA,
            "Referer": f"https://live.bilibili.com/{room_id}",
            "Accept": "application/json, text/plain, */*",
        })
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            d = data.get("data", {}) or {}
            return int(d.get("live_status", 0)), d.get("title", "")
        print(f"[监控室] room={room_id} API code={data.get('code')} "
              f"msg={data.get('message')}")
    except Exception as e:
        print(f"[监控室] 检查 {room_id} 失败: {e}")
    return -1, ""


def find_live_rooms(targets=None):
    """返回 {角色名: (房间号, 标题)}，只包含 live_status == 1 的"""
    rooms = targets or DEFAULT_LIVE_ROOMS
    result = {}
    for name, rid in rooms.items():
        status, title = check_live_status(rid)
        if status == 1:
            result[name] = (rid, title)
    return result


def find_video_py():
    """查找同目录下的 video.py"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ("video.py", "video"):
        p = os.path.join(script_dir, name)
        if os.path.exists(p):
            return p
    return None


def launch_video(room_ids, rows=0, cols=0, extra_args=None):
    """启动 video.py 并预填房间号
    room_ids: List[int|str]（可为空，表示启动空监控室）
    """
    video_path = find_video_py()
    if not video_path:
        print("[监控室] 找不到 video.py")
        return False

    args = [sys.executable, video_path]
    for rid in room_ids:
        args += ["--room", str(rid)]
    args += ["--skip-dialog"]
    if rows > 0 and cols > 0:
        args += ["--rows", str(rows), "--cols", str(cols)]
    if extra_args:
        args += extra_args

    print(f"[监控室] 启动命令: {' '.join(args)}")
    try:
        subprocess.Popen(args, cwd=os.path.dirname(video_path))
        return True
    except Exception as e:
        print(f"[监控室] 启动失败: {e}")
        return False

def _pick_grid(n):
    if n <= 4:
        return 2, 2
    if n <= 6:
        return 2, 3
    if n <= 9:
        return 3, 3
    return 4, 4

def main():
    parser = argparse.ArgumentParser(description="监控室启动器")
    parser.add_argument("--wait", type=int, default=0,
                        help="等待 N 秒再检测（用于 main 触发后的缓冲）")
    parser.add_argument("--character", type=str, default="",
                        help="只检查指定角色（用于 main 单角色触发）")
    parser.add_argument("--all", action="store_true",
                        help="检查全部预置角色（默认检查主要四位）")
    parser.add_argument("--only-if-live", action="store_true",
                        help="只有检测到直播才启动（默认无论是否直播都启动）")
    args = parser.parse_args()

    if args.wait > 0:
        time.sleep(args.wait)

    # 决定检查哪些角色
    if args.character:
        if args.character not in DEFAULT_LIVE_ROOMS:
            print(f"[监控室] 未知角色: {args.character}")
            targets = {}
        else:
            targets = {args.character: DEFAULT_LIVE_ROOMS[args.character]}
    elif args.all:
        targets = DEFAULT_LIVE_ROOMS
    else:
        targets = {k: DEFAULT_LIVE_ROOMS[k] for k in PRIMARY_TARGETS
                   if k in DEFAULT_LIVE_ROOMS}

    live = {}
    if targets:
        print(f"[监控室] 检测角色: {list(targets.keys())}")
        live = find_live_rooms(targets)

    # ★ 默认总是启动；只有 --only-if-live 时才在无直播时跳过
    if not live and args.only_if_live:
        print("[监控室] 当前无角色直播，且指定 --only-if-live，不启动")
        return 0

    if live:
        print(f"[监控室] 发现 {len(live)} 个角色直播:")
        for name, (rid, title) in live.items():
            t = title or "（无标题）"
            print(f"  · {name} (房间 {rid}): {t}")
        room_ids = [rid for rid, _ in live.values()]
        rows, cols = _pick_grid(len(room_ids))
        ok = launch_video(room_ids, rows=rows, cols=cols)
        if ok:
            print(f"[监控室] 已启动监控室（预填 {len(room_ids)} 个直播间），"
                  f"布局: {rows}×{cols}")
            return 0
        return 1
    else:
        print("[监控室] 当前无角色直播，启动空监控室")
        # 用 4 路默认布局
        ok = launch_video([], rows=2, cols=2)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())