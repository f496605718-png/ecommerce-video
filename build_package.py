#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布包打包脚本（开源改造第2步：标准包布局 + 知识库单一数据源在包内）。

收集（白名单为主）：
  - src/ecommerce_video/**        包本体（源码 + 包内 knowledge/ 单一数据源 + 提示词模板）
  - tests/**                      测试套件（78 用例安全锚点）
  - 01-07 方法论文档 md + README.md / README_EN.md / LICENSE / CONTRIBUTING.md
  - INSTALL.md / CONFIG.md / ASSETS.md + docs/**（PROVIDERS.md / ARCHITECTURE.md 等）
  - pyproject.toml / build_package.py
  - .env.example / .gitignore
  - data/schema.sql               数据库建表脚本（`ecommerce-video init` 依赖；.db 产物不打包）
  - examples/**（若存在）

排除：
  - 00-项目进度快照.md            内部项目管理文件（含 .env 现状/测试 key 来源/内部决策），不随包发布
  - dist/、output/、refs/、jobs/、data/*.db*、.env、.git、.venv、node_modules
  - __pycache__ / *.pyc / *.zip
  - 根目录调试脚本（_ 开头 / tmp_ 开头）

zip 内目录结构（标准包布局，顶层目录保留包名 ecommerce-video/）：
  ecommerce-video/
  ├── src/ecommerce_video/...      （含 knowledge/、prompt_gen_template.md）
  ├── tests/...
  ├── pyproject.toml / build_package.py
  ├── README.md / README_EN.md / LICENSE / CONTRIBUTING.md
  ├── 01-*.md ... 07-*.md / INSTALL.md / CONFIG.md / ASSETS.md
  ├── docs/PROVIDERS.md / docs/ARCHITECTURE.md
  ├── .env.example / .gitignore
  └── data/schema.sql

用法：
  python build_package.py                # 打包到 dist/ecommerce-ai-video-workflow-v1.6.0.zip
  python build_package.py --version 1.4.1
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "1.6.0"              # 与 pyproject.toml 版本号保持同步（--version 可覆盖）
ZIP_ROOT = "ecommerce-video"   # zip 内顶层目录名

# 根级文档/配置白名单（保持 zip 内干净，不含调试残留）
ROOT_FILES = [
    "pyproject.toml", "build_package.py",
    "README.md", "README_EN.md", "LICENSE", "CONTRIBUTING.md",
    "INSTALL.md", "CONFIG.md", "ASSETS.md", ".env.example", ".gitignore",
    "demo_storyboard.json", "demo_jobs.json", "demo_jobs_full.json",
]

# 排除目录（任意层级命中即跳过）
EXCLUDE_DIRS = {".git", "__pycache__", "dist", "output", "refs", "jobs", "data",
                ".venv", "venv", "node_modules"}


def should_exclude(rel: str) -> bool:
    """按 zip 内相对路径（posix）判断是否排除。"""
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    name = parts[-1]
    # 产物/缓存/密钥
    if name.endswith((".pyc", ".zip", ".db", ".db-wal", ".db-shm")) or name in (".DS_Store", ".env"):
        return True
    # 根目录调试/临时脚本（_xxx 开头或 tmp_ 开头；包内 __init__.py 等不受影响，因为只在根层级判断）
    if len(parts) == 1 and (name.startswith("_") or name.startswith("tmp_")):
        return True
    return False


def _walk(base: Path) -> list:
    """递归收集 base 下文件（相对项目根的 posix 路径），应用排除规则。"""
    out = []
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if should_exclude(rel):
            continue
        out.append((p, rel))
    return out


def collect() -> list:
    """收集全部待打包文件，返回 [(绝对路径, zip内相对路径)]，按路径排序并去重。"""
    files = []
    # 1) 包本体：src/ecommerce_video/**（含 knowledge/ 与 prompt_gen_template.md）
    files += _walk(ROOT / "src" / "ecommerce_video")
    # 2) 测试套件：tests/**
    files += _walk(ROOT / "tests")
    # 3) 根级文档：01-07 方法论文档（7 份；00-项目进度快照.md 为内部项目管理文件，不随包发布）
    for p in sorted(ROOT.glob("0[1-7]-*.md")):
        if p.is_file():
            files.append((p, p.name))
    # 3b) docs/**：架构与接入文档（PROVIDERS.md / ARCHITECTURE.md，将来新增文档默认也收）
    files += _walk(ROOT / "docs")
    # 4) 根级配置/安装脚本白名单
    for name in ROOT_FILES:
        p = ROOT / name
        if p.is_file():
            files.append((p, name))
    # 5) data/：仅 schema.sql（建表脚本；video_jobs.db 等产物不打包）
    schema = ROOT / "data" / "schema.sql"
    if schema.is_file():
        files.append((schema, "data/schema.sql"))
    # 6) examples/**（若存在）
    files += _walk(ROOT / "examples")

    # 去重（_walk 与显式列表可能重叠）并按 zip 路径排序
    seen, out = set(), []
    for p, rel in files:
        if rel in seen:
            continue
        seen.add(rel)
        out.append((p, rel))
    out.sort(key=lambda x: x[1])
    return out


def main():
    version = VERSION
    args = sys.argv[1:]
    if "--version" in args:
        version = args[args.index("--version") + 1]
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"ecommerce-ai-video-workflow-v{version}.zip"
    files = collect()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in files:
            z.write(p, f"{ZIP_ROOT}/{rel}")
    total_kb = sum(p.stat().st_size for p, _ in files) / 1024
    print(f"打包完成: {out}")
    print(f"文件数: {len(files)} | 体积: {total_kb:.0f} KB")
    print("（已排除: .env 密钥、数据库产物、output/assets/refs/jobs、__pycache__、根目录调试脚本）")
    print(f"（zip 内布局: {ZIP_ROOT}/src/ecommerce_video/... 标准包布局；知识库在包内）")


if __name__ == "__main__":
    main()
