# -*- coding: utf-8 -*-
"""B站动态抓取测试脚本（带 Cookie 初始化 + 调试输出）"""

import os
import re
import time
import json
import hashlib
import urllib.parse
from datetime import datetime, date

try:
    import requests
except ImportError:
    print("请先安装 requests：pip install requests")
    raise SystemExit(1)


# ============================================================
#  配置
# ============================================================
BILI_UID = 413748120
BILI_KEYWORDS = ["梨安", "又一", "沐霂", "恬豆"]
BILI_SPACE_URL = f"https://space.bilibili.com/{BILI_UID}/dynamic"
MAX_PAGES = 3
LIVE_PATTERN = r"直播|预告|开播|上播|今晚|直播间"

# 如果你想手动填 Cookie，把 SESSDATA / buvid3 填进来即可
MANUAL_COOKIE = ""   # 例如: "SESSDATA=xxx; buvid3=xxx; buvid4=xxx"


MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://space.bilibili.com/",
    "Origin": "https://space.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ============================================================
#  初始化 Session（关键！补 buvid3/buvid4）
# ============================================================
def build_session():
    s = requests.Session()
    s.headers.update(BASE_HEADERS)

    # 手动填的 Cookie 优先
    if MANUAL_COOKIE.strip():
        s.headers["Cookie"] = MANUAL_COOKIE.strip()
        print("[session] 使用手动 Cookie")
        return s

    # 1) 访问首页，让 B站下发 buvid3 等 Cookie
    print("[session] 访问 bilibili 首页获取初始 Cookie ...")
    try:
        s.get("https://www.bilibili.com/", timeout=10)
    except Exception as e:
        print(f"[session] 首页访问失败: {e}")

    # 2) 调用 finger/spi 获取 buvid3 / buvid4（新版必需）
    print("[session] 调用 finger/spi 获取 buvid3/buvid4 ...")
    try:
        r = s.get(
            "https://api.bilibili.com/x/frontend/finger/spi",
            timeout=10,
        )
        data = r.json().get("data", {})
        b3 = data.get("b_3", "")
        b4 = data.get("b_4", "")
        if b3:
            s.cookies.set("buvid3", b3, domain=".bilibili.com")
        if b4:
            s.cookies.set("buvid4", b4, domain=".bilibili.com")
        print(f"[session] buvid3={b3[:16]}... buvid4={b4[:16]}...")
    except Exception as e:
        print(f"[session] finger/spi 失败: {e}")

    # 3) 打印当前 Cookie
    print(f"[session] 当前 Cookie: {s.cookies.get_dict()}")

    # 4) 再访问一次首页，模拟真实浏览
    try:
        s.get(
            f"https://space.bilibili.com/{BILI_UID}/dynamic",
            timeout=10,
        )
    except Exception as e:
        print(f"[session] 空间页访问失败: {e}")

    return s


# ============================================================
#  wbi 签名
# ============================================================
def get_mixin_key(raw):
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def fetch_wbi_keys(session):
    print("[wbi] 获取 img_key / sub_key ...")
    r = session.get(
        "https://api.bilibili.com/x/web-interface/nav",
        timeout=10,
    )
    data = r.json().get("data", {})
    wbi = data.get("wbi_img", {})
    img_url = wbi.get("img_url", "")
    sub_url = wbi.get("sub_url", "")
    img_key = os.path.splitext(os.path.basename(img_url))[0] if img_url else ""
    sub_key = os.path.splitext(os.path.basename(sub_url))[0] if sub_url else ""
    print(f"[wbi] img_key = {img_key}")
    print(f"[wbi] sub_key = {sub_key}")
    if not img_key or not sub_key:
        raise RuntimeError("无法获取 wbi keys")
    return img_key, sub_key


def sign_params(params, img_key, sub_key):
    mixin_key = get_mixin_key(img_key + sub_key)
    params["wts"] = round(time.time())
    params = dict(sorted(params.items()))
    query = urllib.parse.urlencode(params)
    params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params


# ============================================================
#  抓取动态（带调试输出）
# ============================================================
def safe_json(resp):
    """尝试解析 JSON，失败则打印原始响应"""
    text = resp.text
    try:
        return resp.json()
    except Exception:
        print("\n[DEBUG] JSON 解析失败！")
        print(f"[DEBUG] 状态码: {resp.status_code}")
        print(f"[DEBUG] Content-Type: {resp.headers.get('Content-Type')}")
        print(f"[DEBUG] 响应长度: {len(text)}")
        print(f"[DEBUG] 响应前 500 字符:\n{text[:500]}")
        return None


def fetch_dynamics(session, host_mid, max_pages=3):
    img_key, sub_key = fetch_wbi_keys(session)
    all_items = []
    offset = ""

    for page in range(max_pages):
        params = {
            "host_mid": host_mid,
            "offset": offset,
            "timezone_offset": -480,
        }
        signed = sign_params(params, img_key, sub_key)
        print(f"\n[动态] 抓取第 {page + 1} 页 ...")
        print(f"[动态] 请求 URL: "
              f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space")
        print(f"[动态] 请求参数: {signed}")

        try:
            resp = session.get(
                "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                params=signed,
                timeout=15,
            )
        except Exception as e:
            print(f"[动态] 请求异常: {e}")
            break

        print(f"[动态] HTTP {resp.status_code}, "
              f"长度 {len(resp.text)}")

        data = safe_json(resp)
        if data is None:
            break

        code = data.get("code")
        if code != 0:
            print(f"[动态] API 错误 code={code} "
                  f"message={data.get('message')}")
            print(f"[动态] 完整响应: "
                  f"{json.dumps(data, ensure_ascii=False)[:500]}")
            # -352 通常需要 Cookie；-412 是风控
            if code in (-352, -412):
                print("[提示] 可能被风控，请尝试在 MANUAL_COOKIE 中填入浏览器 Cookie")
            break

        items = data.get("data", {}).get("items", [])
        all_items.extend(items)
        print(f"[动态] 本页 {len(items)} 条，累计 {len(all_items)} 条")

        has_more = data.get("data", {}).get("has_more", False)
        offset = data.get("data", {}).get("offset", "")
        if not has_more or not offset:
            break
        time.sleep(0.6)

    return all_items


# ============================================================
#  解析
# ============================================================
def extract_text(item):
    modules = item.get("modules", {})
    dyn = modules.get("module_dynamic", {})
    desc = dyn.get("desc") or {}
    text = desc.get("text", "")
    if not text:
        major = dyn.get("major") or {}
        opus = major.get("opus") or {}
        if opus:
            text = (opus.get("summary") or {}).get("text", "")
    return text


def extract_author(item):
    modules = item.get("modules", {})
    auth = modules.get("module_author", {})
    return auth.get("name", ""), auth.get("pub_time", "")


def extract_link(item):
    dyn_id = item.get("id_str", "")
    return f"https://t.bilibili.com/{dyn_id}" if dyn_id else ""


def extract_type(item):
    return item.get("type", "")


def parse_pub_time_to_date(pub_time_str):
    if not pub_time_str:
        return None
    today = date.today()
    try:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", pub_time_str)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"(\d{2})-(\d{2})", pub_time_str)
        if m:
            return date(today.year, int(m.group(1)), int(m.group(2)))
    except Exception:
        pass
    return None


# ============================================================
#  主流程
# ============================================================
def main():
    print("=" * 70)
    print(f"测试目标：{BILI_SPACE_URL}")
    print(f"关键词   ：{BILI_KEYWORDS}")
    print(f"当前时间 ：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    session = build_session()
    items = fetch_dynamics(session, BILI_UID, MAX_PAGES)

    if not items:
        print("\n未抓取到任何动态。")
        print("排查建议：")
        print("  1) 看上面 [DEBUG] 输出的响应内容，是 HTML 说明被风控")
        print("  2) 在浏览器打开空间页，F12 复制 Cookie，"
              "填入脚本顶部 MANUAL_COOKIE")
        print("  3) 稍等几分钟重试，避免短时间频繁请求")
        return

    today = date.today()
    matched_items, live_items, today_items = [], [], []
    for idx, item in enumerate(items, 1):
        text = extract_text(item)
        author, pub_time = extract_author(item)
        matched = [kw for kw in BILI_KEYWORDS if kw in text]
        is_live = bool(re.search(LIVE_PATTERN, text))
        pub_date = parse_pub_time_to_date(pub_time)
        is_today = (pub_date == today)
        info = {
            "idx": idx, "author": author, "time": pub_time,
            "text": text, "link": extract_link(item),
            "type": extract_type(item),
            "matched": matched, "is_live": is_live, "is_today": is_today,
        }
        if is_today:
            today_items.append(info)
        if matched:
            matched_items.append(info)
        if matched and is_live:
            live_items.append(info)

    print("\n" + "=" * 70)
    print(f"【今天的动态】共 {len(today_items)} 条")
    print("=" * 70)
    for info in today_items:
        print(f"\n--- 第 {info['idx']} 条 ---")
        print(f"作者   : {info['author']}")
        print(f"时间   : {info['time']}")
        print(f"类型   : {info['type']}")
        print(f"链接   : {info['link']}")
        print(f"关键词 : {info['matched'] or '（无）'}")
        print(f"直播预告: {'是' if info['is_live'] else '否'}")
        print(f"正文   :\n{info['text'][:500]}")

    print("\n" + "=" * 70)
    print(f"【命中关键词】共 {len(matched_items)} 条")
    print("=" * 70)
    for info in matched_items:
        print(f"\n--- 第 {info['idx']} 条 ---")
        print(f"时间   : {info['time']}")
        print(f"关键词 : {info['matched']}")
        print(f"链接   : {info['link']}")
        print(f"正文   :\n{info['text'][:500]}")

    print("\n" + "=" * 70)
    print(f"【命中关键词 + 直播预告】共 {len(live_items)} 条")
    print("=" * 70)
    for info in live_items:
        print(f"\n--- 第 {info['idx']} 条 ---")
        print(f"时间   : {info['time']}")
        print(f"关键词 : {info['matched']}")
        print(f"链接   : {info['link']}")
        print(f"正文   :\n{info['text'][:500]}")

    out_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "bili_dynamic_dump.json"
    )
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"\n[原始数据已保存] {out_file}")
    except Exception as e:
        print(f"\n[保存原始数据失败] {e}")


if __name__ == "__main__":
    main()