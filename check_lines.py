# -*- coding: utf-8 -*-
import os
import json

path = os.path.join("img", "梨安", "lines.json")

print("路径:", os.path.abspath(path))
print("存在:", os.path.exists(path))

if not os.path.exists(path):
    print("→ 文件不存在。检查文件名、目录名、大小写。")
    raise SystemExit

size = os.path.getsize(path)
print("大小:", size, "字节")

with open(path, "rb") as f:
    head = f.read(6)
print("前 6 字节:", head)
if head.startswith(b"\xef\xbb\xbf"):
    print("→ 有 BOM，请另存为 UTF-8 无 BOM")
else:
    print("→ 无 BOM")

try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print("JSON 合法，共", len(data), "条")
    print("示例 a =", data.get("a"))
except Exception as e:
    print("JSON 读取失败:", e)