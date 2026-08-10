#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置加载：从 .env 读取密钥与参数（规范见 CONFIG.md）。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv 缺失时静默降级，依赖系统环境变量
    pass

# src 布局下：src/ecommerce_video/config.py → 上上级即项目根（父=包目录，父父=src，父父父=项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

# ---------- 视觉识别（阶段 A1） ----------
VISION_API_KEY = get("VISION_API_KEY")
VISION_API_BASE = get("VISION_API_BASE", "https://apihub.agnes-ai.com/v1")  # 默认 Agnes 2.5 Flash
VISION_MODEL = get("VISION_MODEL", "agnes-2.5-flash")

# ---------- 提示词生成 LLM（AI 介入写提示词；缺省复用视觉识别配置） ----------
TEXT_LLM_API_KEY = get("TEXT_LLM_API_KEY")
TEXT_LLM_API_BASE = get("TEXT_LLM_API_BASE")
TEXT_LLM_MODEL = get("TEXT_LLM_MODEL")

# ---------- 视频生成（阶段 A2，开放接入） ----------
VIDEO_PROVIDER = get("VIDEO_PROVIDER", "seedance-2.0").strip().lower()  # 产品默认 Seedance 2.0（与 models.json default_model 一致）；测试/其他模型在 .env 显式指定

def _model_key(prefix: str, suffix: str) -> str:
    return get(f"{prefix}_{suffix}")

# provider 名 → 环境变量键前缀 规范化映射（键名以映射后为准，与 .env.example 一一对应）。
# 例：VIDEO_PROVIDER=seedance-2.0 → 找 SEEDANCE_API_KEY（而非 SEEDANCE-2.0_API_KEY）。
_VIDEO_KEY_PREFIX = {
    "seedance-2.0": "SEEDANCE",
    "seedance-2.5": "SEEDANCE25",
    "agnes-video": "AGNES",
    "agnes": "AGNES",
    "kling": "KLING",
    "jimeng": "JIMENG",
    "runway": "RUNWAY",
    "vidu": "VIDU",
    "custom": "CUSTOM",
}

def _key_prefix(provider: str, table: dict) -> str:
    """规范化键前缀：查映射表（provider 已 lower）；查不到退回原规则（provider 大写）。"""
    return table.get(provider, provider.upper())

_VIDEO_KEY_PREFIX_ACTIVE = _key_prefix(VIDEO_PROVIDER, _VIDEO_KEY_PREFIX)
# 查找顺序：映射前缀_API_KEY → 原规则（provider 大写_API_KEY）→ 通用兜底 VIDEO_API_KEY
VIDEO_API_KEY = (
    _model_key(_VIDEO_KEY_PREFIX_ACTIVE, "API_KEY")
    or _model_key(VIDEO_PROVIDER.upper(), "API_KEY")
    or get("VIDEO_API_KEY"))
VIDEO_API_BASE = (
    _model_key(_VIDEO_KEY_PREFIX_ACTIVE, "API_BASE")
    or _model_key(VIDEO_PROVIDER.upper(), "API_BASE")
    or get("VIDEO_API_BASE", "https://apihub.agnes-ai.com/v1"))
VIDEO_MODEL = (
    _model_key(_VIDEO_KEY_PREFIX_ACTIVE, "MODEL")
    or _model_key(VIDEO_PROVIDER.upper(), "MODEL")
    or ("agnes-video-v2.0" if VIDEO_PROVIDER in ("agnes-video", "agnes") else VIDEO_PROVIDER))

# ---------- 图片生成（合成首帧/概念图，开放接入） ----------
# 用途：视频模型不支持多参考图时，用生图把「商品+模特/场景」合成首帧；或 C 档生成样衣概念图
IMAGE_PROVIDER = get("IMAGE_PROVIDER", "agnes-image").strip().lower()
# 生图侧映射：custom-image / agnes-image 直接走 IMAGE_API_KEY 族（IMAGE_API_KEY 兜底仍可用，向后兼容）
_IMAGE_KEY_PREFIX = {
    "custom-image": "IMAGE",
    "agnes-image": "IMAGE",
}
_IMAGE_KEY_PREFIX_ACTIVE = _key_prefix(IMAGE_PROVIDER, _IMAGE_KEY_PREFIX)
# 查找顺序：映射前缀_API_KEY → 原规则（provider 大写_API_KEY）→ 通用兜底 IMAGE_API_KEY
IMAGE_API_KEY = (
    _model_key(_IMAGE_KEY_PREFIX_ACTIVE, "API_KEY")
    or _model_key(IMAGE_PROVIDER.upper(), "API_KEY")
    or get("IMAGE_API_KEY"))
IMAGE_API_BASE = (
    _model_key(_IMAGE_KEY_PREFIX_ACTIVE, "API_BASE")
    or _model_key(IMAGE_PROVIDER.upper(), "API_BASE")
    or get("IMAGE_API_BASE", "https://apihub.agnes-ai.com/v1"))
IMAGE_MODEL = (
    _model_key(_IMAGE_KEY_PREFIX_ACTIVE, "MODEL")
    or _model_key(IMAGE_PROVIDER.upper(), "MODEL")
    or ("agnes-image-2.1-flash" if IMAGE_PROVIDER == "agnes-image" else IMAGE_PROVIDER))
IMAGE_SIZE = get("IMAGE_SIZE", "2K:9:16")  # 生图尺寸：档位:比例（如 2K:9:16）或精确尺寸

# ---------- 网络 ----------
HTTP_PROXY = get("HTTP_PROXY") or get("HTTPS_PROXY")
API_TIMEOUT = int(get("API_TIMEOUT_SECONDS", "120"))
API_MAX_RETRIES = int(get("API_MAX_RETRIES", "1"))
API_RETRY_INTERVAL = int(get("API_RETRY_INTERVAL_SECONDS", "5"))

# ---------- 路径 ----------
# 知识库定位优先级：1) 环境变量 KNOWLEDGE_DIR（最高） 2) 包内随 package-data 打进的 knowledge/
# （src/ecommerce_video/knowledge，wheel 安装后即包内数据） 3) 项目根 knowledge/（源码检出兜底）
_PACKAGE_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
KNOWLEDGE_DIR = Path(get("KNOWLEDGE_DIR")) if get("KNOWLEDGE_DIR") else (
    _PACKAGE_KNOWLEDGE_DIR if _PACKAGE_KNOWLEDGE_DIR.is_dir() else PROJECT_ROOT / "knowledge")
OUTPUT_DIR = Path(get("OUTPUT_DIR")) if get("OUTPUT_DIR") else PROJECT_ROOT / "output"
VIDEO_DIR = OUTPUT_DIR / "videos"
DB_PATH = PROJECT_ROOT / "data" / "video_jobs.db"

# ---------- 配置自检（接单前/入队前必跑，防密钥省略导致 401/403） ----------
def check_config(require_video_key: bool = True) -> list:
    """返回缺失项列表；空列表=通过。"""
    missing = []
    if not VISION_API_KEY:
        missing.append("VISION_API_KEY（视觉识别；缺失则走人工模式）")
    if require_video_key and not VIDEO_API_KEY:
        missing.append(f"{_VIDEO_KEY_PREFIX_ACTIVE}_API_KEY（视频生成；缺失则禁止入队）")
    # 密钥格式粗检：非空且不含空白/换行残留
    for name, val in [("VISION_API_KEY", VISION_API_KEY), (f"{_VIDEO_KEY_PREFIX_ACTIVE}_API_KEY", VIDEO_API_KEY)]:
        if val and (val != val.strip() or any(ch.isspace() for ch in val)):
            missing.append(f"{name}（含空白/换行，疑似粘贴残留）")
    return missing


def mask_key(key: str) -> str:
    """日志脱敏：只显示前 4 位。"""
    return f"{key[:4]}…" if key and len(key) > 4 else "(未配置)"


if __name__ == "__main__":
    print(f"VIDEO_PROVIDER = {VIDEO_PROVIDER}")
    print(f"VIDEO_MODEL    = {VIDEO_MODEL}")
    print(f"VISION_MODEL   = {VISION_MODEL}")
    print(f"VISION key     = {mask_key(VISION_API_KEY)}")
    print(f"VIDEO key      = {mask_key(VIDEO_API_KEY)}")
    print(f"KNOWLEDGE_DIR  = {KNOWLEDGE_DIR}")
    print(f"DB_PATH        = {DB_PATH}")
    print("--- 配置自检 ---")
    miss = check_config(require_video_key=False)
    print("缺失项:", miss if miss else "无（视觉识别就绪）")
