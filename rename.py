# -*- coding: utf-8 -*-
"""
禧运楼 · 项目文字批量替换脚本
================================
把项目里所有"枝江小馒头"及相关旧标识统一替换为新标识。

默认替换规则（按顺序执行，长的在前）：
    1. github.com/Evelynall/ASoul-Little-Bun  →  github.com/HUST-mjc/xiyunlou
    2. Evelynall/ASoul-Little-Bun             →  HUST-mjc/xiyunlou
    3. ASoul-Little-Bun                       →  xiyunlou
    4. ASoul Little Bun                       →  Xiyunlou
    5. ASoulLittleBun                         →  Xiyunlou
    6. 枝江小馒头                              →  禧运楼
    7. Desktop Pet                            →  Xiyunlou

用法：
    python rename.py                 # 执行替换（自动备份到 .rename_backup/）
    python rename.py --dry-run       # 只预览，不改文件
    python rename.py --no-backup     # 不备份
    python rename.py --verbose       # 打印每个文件内的替换明细
    python rename.py --ext .py .md   # 只处理指定扩展名
"""

import os
import sys
import shutil
import argparse
from datetime import datetime


# ============================================================
#  替换规则（顺序很重要：长的、更具体的放前面）
# ============================================================
REPLACE_RULES = [
    # ---- GitHub 仓库完整路径（要先替换，避免被后面拆掉） ----
    ("github.com/Evelynall/ASoul-Little-Bun",
     "github.com/HUST-mjc/xiyunlou"),
    ("Evelynall/ASoul-Little-Bun",
     "HUST-mjc/xiyunlou"),

    # ---- 英文标识的几种拼写形式 ----
    ("ASoul-Little-Bun", "xiyunlou"),
    ("ASoul Little Bun", "Xiyunlou"),
    ("ASoulLittleBun",   "Xiyunlou"),

    # ---- 中文名 ----
    ("枝江小馒头", "禧运楼"),

    # ---- 窗口标题 / 关于对话框 ----
    ("Desktop Pet", "Xiyunlou"),
]


# ============================================================
#  要处理的文件扩展名
# ============================================================
DEFAULT_EXTS = {
    '.py', '.md', '.txt', '.json', '.bat', '.cmd', '.ps1',
    '.spec', '.cfg', '.ini', '.toml', '.yaml', '.yml',
    '.html', '.css', '.js', '.ts', '.qml', '.ui',
    '.c', '.h', '.cpp', '.hpp', '.java', '.cs',
    '.sh', '.gitignore', '.gitattributes',
}


# ============================================================
#  要跳过的目录
# ============================================================
SKIP_DIRS = {
    '.git', '.github',
    '__pycache__', '.pytest_cache', '.mypy_cache',
    'build', 'dist', 'temp_update', 'backup_before_update',
    '.rename_backup',
    'clips', 'screenshots',
    'node_modules', '.venv', 'venv', 'env', '.env',
    '.idea', '.vscode',
}


# ============================================================
#  具体实现
# ============================================================
def find_target_files(root, exts):
    """遍历 root，返回所有需要处理的文本文件路径"""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 原地修改 dirnames，os.walk 就不会进入这些目录
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith('.rename_backup')
        ]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            # 支持 .gitignore 这类无扩展名的特殊文件
            if ext in exts or fn in exts:
                results.append(os.path.join(dirpath, fn))
    return results


def apply_replacements(text, rules, verbose=False):
    """对 text 应用所有替换规则，返回 (新文本, 替换明细列表)"""
    detail = []
    new_text = text
    for old, new in rules:
        if old not in new_text:
            continue
        count = new_text.count(old)
        new_text = new_text.replace(old, new)
        detail.append((old, new, count))
        if verbose:
            print(f"    · '{old}' → '{new}'  × {count}")
    return new_text, detail


def read_text(path):
    """尝试多种编码读取文本，失败返回 (None, None)"""
    for enc in ('utf-8', 'utf-8-sig', 'gbk', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc, newline='') as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
        except (PermissionError, IsADirectoryError, OSError):
            return None, None
    return None, None


def write_text(path, text, encoding):
    """用原编码写回文件，保持换行符不变"""
    with open(path, 'w', encoding=encoding, newline='') as f:
        f.write(text)


def backup_file(path, root, backup_root):
    """把文件复制到备份目录，保持相对目录结构"""
    rel = os.path.relpath(path, root)
    dst = os.path.join(backup_root, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)


def main():
    parser = argparse.ArgumentParser(
        description="禧运楼项目文字批量替换脚本")
    parser.add_argument('--dry-run', action='store_true',
                        help='只预览，不修改任何文件')
    parser.add_argument('--no-backup', action='store_true',
                        help='不备份被修改的文件')
    parser.add_argument('--verbose', action='store_true',
                        help='打印每个文件内的替换明细')
    parser.add_argument('--root', default=None,
                        help='项目根目录（默认脚本所在目录）')
    parser.add_argument('--ext', nargs='+', default=None,
                        help='只处理这些扩展名，如 --ext .py .md')
    args = parser.parse_args()

    root = args.root or os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(root)

    # 脚本自身不能被处理（否则里面的规则字面量会被改掉）
    self_path = os.path.abspath(__file__)

    # 扩展名集合
    exts = DEFAULT_EXTS
    if args.ext:
        exts = {e.lower() if e.startswith('.') else '.' + e.lower()
                for e in args.ext}

    # 备份目录
    backup_root = None
    if not args.dry_run and not args.no_backup:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_root = os.path.join(root, '.rename_backup', ts)
        os.makedirs(backup_root, exist_ok=True)
        print(f"[备份] 被修改的文件将备份到: {backup_root}")

    print(f"[扫描] 项目根目录: {root}")
    print(f"[扫描] 处理扩展名: {sorted(exts)}")
    print(f"[扫描] 跳过目录  : {sorted(SKIP_DIRS)}")
    print("-" * 62)

    files = find_target_files(root, exts)
    print(f"[扫描] 共发现 {len(files)} 个候选文件\n")

    total_files_changed = 0
    total_replacements = 0
    changed_paths = []

    for path in files:
        # 跳过脚本自身
        if os.path.abspath(path) == self_path:
            continue

        text, enc = read_text(path)
        if text is None or enc is None:
            continue

        new_text, detail = apply_replacements(
            text, REPLACE_RULES, verbose=args.verbose)

        if not detail:
            continue

        rel = os.path.relpath(path, root)
        file_total = sum(c for _, _, c in detail)

        print(f"[改] {rel}  ({file_total} 处)")
        if args.verbose:
            for old, new, cnt in detail:
                print(f"       '{old}' → '{new}'  × {cnt}")

        if args.dry_run:
            total_files_changed += 1
            total_replacements += file_total
            changed_paths.append(rel)
            continue

        # 备份
        if backup_root:
            try:
                backup_file(path, root, backup_root)
            except Exception as e:
                print(f"    [!] 备份失败: {e}")

        # 写回
        try:
            write_text(path, new_text, enc)
        except Exception as e:
            print(f"    [!] 写入失败: {e}")
            continue

        total_files_changed += 1
        total_replacements += file_total
        changed_paths.append(rel)

    print("-" * 62)
    if args.dry_run:
        print(f"[预览] 共会修改 {total_files_changed} 个文件，"
              f"{total_replacements} 处")
        print("[预览] 未做任何改动。去掉 --dry-run 即可执行。")
    else:
        print(f"[完成] 共修改 {total_files_changed} 个文件，"
              f"{total_replacements} 处")
        if backup_root:
            print(f"[完成] 备份目录: {backup_root}")

    if not changed_paths:
        print("\n提示：没有找到任何需要替换的内容。")
        print("     可能项目里已经改过了，或者替换规则不匹配。")
    else:
        print("\n被修改的文件清单：")
        for p in changed_paths:
            print(f"   {p}")

    print("\n下一步建议：")
    print("  1) 人工检查 README.md、main.py、update_checker.py 的关键内容")
    print("  2) 运行 python main.py 确认程序能正常启动")
    print("  3) git add . && git commit -m \"重命名：枝江小馒头 → 禧运楼\"")
    print("  4) git push")


if __name__ == '__main__':
    main()