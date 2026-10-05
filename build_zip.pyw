# -*- coding: utf-8 -*-
"""打包 dist 目录为发布 zip（供 GitHub Release 上传）"""
import json
import os
import zipfile
from datetime import datetime


DIST_DIR = "dist"
# 输出目录（可改成 dist_release 之类）
OUTPUT_DIR = "dist_release"


def read_version():
    """从 version.json 读取版本号"""
    try:
        with open("version.json", "r", encoding="utf-8") as f:
            return json.load(f).get("version", "0.0.0")
    except Exception:
        return "0.0.0"


def zip_dist():
    if not os.path.isdir(DIST_DIR):
        print(f"错误: 目录 '{DIST_DIR}' 不存在，请先运行 build.bat")
        return

    version = read_version()
    # ★ 输出名与 version.json 的 download_url 保持一致
    out_name = f"Xiyunlou-win-v{version}.zip"

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output = os.path.join(OUTPUT_DIR, out_name)

    count = 0
    total_size = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, ".")
                zf.write(filepath, arcname)
                count += 1
                total_size += os.path.getsize(filepath)

    size_mb = os.path.getsize(output) / (1024 * 1024)
    raw_mb = total_size / (1024 * 1024)
    print(f"打包完成: {output}")
    print(f"文件数  : {count}")
    print(f"原始大小: {raw_mb:.2f} MB")
    print(f"压缩后  : {size_mb:.2f} MB")
    print(f"\n下一步：把 {out_name} 上传到 GitHub Release")
    print(f"        并确保 version.json 的 download_url 指向它")


if __name__ == "__main__":
    zip_dist()