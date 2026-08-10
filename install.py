#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""电商AI视频工作流 · 一键安装脚本（给使用方运行）

用法：
  python install.py            # 完整安装（依赖+本包+目录+.env引导+数据库+自检）
  python install.py --check    # 只检查环境
  python install.py --deps     # 只装依赖（含本包 editable，生成 ecommerce-video 命令）
  python install.py --init     # 只初始化（目录+db）
  python install.py --env      # 只引导配置 .env

流程：检测Python → 装依赖+装本包 → 建目录 → 引导.env → 初始化数据库 → 配置自检
安装完成后可直接使用统一命令：ecommerce-video status / check / run ...（详见 INSTALL.md）

说明（开源改造第2步）：
  - 程序本体在 src/ecommerce_video/ 包内，知识库单一数据源也在包内
    （src/ecommerce_video/knowledge/），根目录不再复制 knowledge/；
  - 安装时执行 `pip install -e .`，保证 `ecommerce-video` 命令入口可用。
"""
import shutil
import subprocess
import sys
from pathlib import Path

# Windows 控制台 GBK 兼容
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
ENV_TEMPLATE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"
SRC_DIR = ROOT / "src"  # 包源码目录（未安装时兜底 import 用）

# 运行期目录（知识库在包内随包分发，不再在根目录建 knowledge/）
REQUIRED_DIRS = ["assets", "output", "output/videos", "data", "refs"]


def log(step, ok=True, msg=""):
    flag = "✓" if ok else "✗"
    print(f"[{flag}] {step}" + (f" - {msg}" if msg else ""))


def check_python() -> bool:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 9):
        log("Python 版本", False, f"需要 Python 3.9+，当前 {v.major}.{v.minor}.{v.micro}")
        return False
    log("Python 版本", True, f"{v.major}.{v.minor}.{v.micro}")
    return True


def install_deps() -> bool:
    """安装 requirements.txt 依赖 + 本包（editable，生成 ecommerce-video 命令入口）。"""
    req = ROOT / "requirements.txt"
    if not req.exists():
        log("依赖清单", False, "requirements.txt 缺失")
        return False
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req)],
                              stdout=subprocess.DEVNULL if hasattr(sys.stdout, "reconfigure") else None)
        log("依赖安装", True)
    except Exception as e:
        log("依赖安装", False, str(e))
        return False
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", str(ROOT)],
                              stdout=subprocess.DEVNULL if hasattr(sys.stdout, "reconfigure") else None)
        log("本包安装", True, "ecommerce-video 命令可用（pip install -e .）")
        return True
    except Exception as e:
        log("本包安装", False, str(e))
        return False


def make_dirs() -> bool:
    for d in REQUIRED_DIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    log("目录创建", True, ", ".join(REQUIRED_DIRS))
    return True


def setup_env() -> bool:
    if ENV_FILE.exists():
        log(".env 已存在", True, "跳过（如需重配请手动编辑 .env）")
        return True
    if not ENV_TEMPLATE.exists():
        log(".env.example", False, "模板缺失")
        return False
    shutil.copy2(ENV_TEMPLATE, ENV_FILE)
    log(".env 已生成", True, "请编辑 .env 填入 API Key（见 CONFIG.md）")
    return True


def init_db() -> bool:
    try:
        if SRC_DIR.is_dir():
            sys.path.insert(0, str(SRC_DIR))
        from ecommerce_video import db
        db.init_db()
        log("数据库初始化", True)
        return True
    except Exception as e:
        log("数据库初始化", False, str(e))
        return False


def check_config() -> bool:
    try:
        if SRC_DIR.is_dir():
            sys.path.insert(0, str(SRC_DIR))
        from ecommerce_video import config
        missing = config.check_config(require_video_key=False)
        if missing:
            log("配置自检", False, "缺失: " + "; ".join(missing))
            return False
        log("配置自检", True, "视觉识别就绪（视频模型 key 需在 .env 配置）")
        return True
    except Exception as e:
        log("配置自检", False, str(e))
        return False


def main():
    args = sys.argv[1:]
    only = args[0].lstrip("-") if args else "all"

    steps = {
        "check": [("环境检查", check_python)],
        "deps": [("依赖安装", install_deps)],
        "init": [("目录创建", make_dirs), ("数据库初始化", init_db)],
        "env": [(".env 引导", setup_env)],
        "all": [("环境检查", check_python), ("依赖安装", install_deps), ("目录创建", make_dirs),
                (".env 引导", setup_env), ("数据库初始化", init_db), ("配置自检", check_config)],
    }
    if only not in steps:
        print(__doc__)
        sys.exit(1)
    ok = True
    for name, fn in steps[only]:
        if not fn():
            ok = False
    print("\n" + ("🎉 安装完成，可开始使用（命令入口：ecommerce-video，详见 INSTALL.md）" if ok else "⚠️ 部分步骤未通过，请按提示处理"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
