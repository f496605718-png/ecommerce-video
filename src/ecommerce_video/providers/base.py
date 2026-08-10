#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider 基类 + 统一协议定义 + 公共工具。

协议（第三方接入核心）：
    class MyProvider(VideoProvider):
        id = "my-model"            # 注册名
        display_name = "My Model"  # 人读名
        def create_task(self, prompt, ref_images, duration, resolution,
                        aspect_ratio, negative_prompt, ctx) -> str: ...
        def query_task(self, task_id, ctx) -> dict: ...
    然后在 providers/__init__.py 里 `from . import my_provider` 即完成发现。
    （可选）覆盖 extract_url / download；默认实现已覆盖绝大多数场景。

约定：
- create_task 返回 task_id 字符串；同步返回 URL 的接口用前缀 `__direct_url__:http...`
  （poll_until_done 会直接识别为已完成任务）。
- query_task 返回 dict，须含 status（succeeded/failed/...）与结果字段（url 等），
  供默认 extract_url 递归提取（Agnes 特例 metadata.url 已内置）。
- ctx：逐调用上下文 dict（如 {"warnings": [...]}），可携带 api_key/api_base/model
  覆盖全局 config（见 _api_config），供第三方接入方做多账号/多端点路由。
"""
from __future__ import annotations

import json
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

try:
    import requests
except ImportError:  # 未安装时仅影响真实网络调用，导入与自测不受影响
    requests = None

from ecommerce_video import config


class VideoGenError(Exception):
    """视频生成链路错误（鉴权/网络/解析/超时/未注册等）。"""


# ================= 公共请求工具 =================

def _proxies():
    """代理配置（从 .env HTTP_PROXY/HTTPS_PROXY 读取）。"""
    return {"http": config.HTTP_PROXY, "https": config.HTTP_PROXY} if config.HTTP_PROXY else None


def _auth_headers(api_key: str):
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _request(method: str, url: str, api_key: str, **kw):
    """带重试的请求；401/403 明确提示密钥问题（防密钥省略）。"""
    if requests is None:
        raise VideoGenError("依赖 requests 未安装：pip install requests")
    last_err = None
    for attempt in range(config.API_MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=_auth_headers(api_key),
                                    timeout=config.API_TIMEOUT, proxies=_proxies(), **kw)
            if resp.status_code in (401, 403):
                raise VideoGenError(
                    f"鉴权失败({resp.status_code})：请检查 .env 中 {config.VIDEO_PROVIDER.upper()}_API_KEY "
                    f"（当前 {config.mask_key(api_key)}）——见 CONFIG.md")
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except VideoGenError:
            raise
        except Exception as e:
            last_err = e
            if attempt < config.API_MAX_RETRIES:
                time.sleep(config.API_RETRY_INTERVAL)
    raise VideoGenError(f"请求失败（已重试 {config.API_MAX_RETRIES} 次）: {last_err}")


def _api_config(ctx: dict, name: str, default: str = "") -> str:
    """API 配置取值：ctx 逐调用覆盖优先，其次 config 全局。
    name ∈ {"api_key", "api_base", "model"} → config.VIDEO_API_KEY/VIDEO_API_BASE/VIDEO_MODEL。
    """
    if ctx and ctx.get(name):
        return ctx[name]
    return getattr(config, {"api_key": "VIDEO_API_KEY",
                            "api_base": "VIDEO_API_BASE",
                            "model": "VIDEO_MODEL"}[name], default) or default


# ================= URL 提取 =================

_URL_KEYS = ("url", "video_url", "download_url", "content", "file_url")


def _extract_url(obj) -> str | None:
    """递归在返回结构中找视频 URL（Agnes 在 metadata.url，含兼容键）。"""
    if isinstance(obj, dict):
        # Agnes 特例：metadata.url 优先
        meta = obj.get("metadata")
        if isinstance(meta, dict) and isinstance(meta.get("url"), str) and meta["url"].startswith(("http", "https")):
            return meta["url"]
        for k, v in obj.items():
            if k in _URL_KEYS and isinstance(v, str) and v.startswith(("http", "https")):
                return v
            r = _extract_url(v)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _extract_url(item)
            if r:
                return r
    return None


# ================= 能力参数装载（knowledge/models.json） =================

DEFAULT_CAPABILITIES = {
    "ref_images": 1,                 # 保守：最多 1 张参考图
    "duration_min": 1,
    "duration_max": 10,              # 保守：最长 10s
    "resolutions": [],
    "image_to_video": True,
    "chinese_prompt": "未知",        # 保守：提示词语言未知
    "multi_ref_supported": False,    # 保守：不支持多参考图（走 S 合成）
    "need_composite": True,
}

# provider id → models.json 能力条目 id（别名复用同族能力，避免误降级保守值）
_CAPABILITY_ALIASES = {
    "seedance": "seedance-2.0",
    "agnes": "agnes-video-v2.0",
    "agnes-video": "agnes-video-v2.0",
}


def load_capabilities(provider_id: str, ctx: dict | None = None) -> dict:
    """读 knowledge/models.json，按 provider id 匹配 models[].capabilities。

    查不到（或文件缺失/损坏）→ 返回保守默认值，并把 warning 追加到 ctx["warnings"]。
    models.json 中显式为 null 的字段视为未确认，按保守默认处理。
    """
    warnings = []
    caps = {}
    lookup = _CAPABILITY_ALIASES.get(provider_id, provider_id)
    try:
        data = json.loads((config.KNOWLEDGE_DIR / "models.json").read_text(encoding="utf-8"))
        entry = next((m for m in data.get("models", []) if m.get("id") == lookup), None)
        if entry and isinstance(entry.get("capabilities"), dict):
            caps = {k: v for k, v in entry["capabilities"].items() if v is not None}
        else:
            warnings.append(
                f"models.json 未找到 provider '{provider_id}' 的能力参数，已用保守默认值；"
                f"接入后请在 knowledge/models.json 回填该模型能力")
    except FileNotFoundError:
        warnings.append(f"knowledge/models.json 不存在，使用保守默认能力参数 {DEFAULT_CAPABILITIES}")
    except Exception as e:
        warnings.append(f"读取 knowledge/models.json 失败（{e}），使用保守默认能力参数 {DEFAULT_CAPABILITIES}")
    merged = dict(DEFAULT_CAPABILITIES)
    merged.update(caps)  # 显式非空值覆盖保守默认
    if warnings and ctx is not None:
        ctx.setdefault("warnings", []).extend(warnings)
    return merged


# ================= 默认下载实现 =================

def download_file(url: str, save_path) -> Path:
    """默认下载：requests 流式写盘。VideoProvider.download 的默认实现。"""
    if requests is None:
        raise VideoGenError("依赖 requests 未安装：pip install requests")
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=config.API_TIMEOUT, proxies=_proxies()) as r:
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return save_path


# ================= Provider 基类（协议本体） =================

class VideoProvider(ABC):
    """统一视频生成 Provider 协议。

    属性：
        id              注册名（如 "seedance-2.0" / "agnes-video" / "custom"）
        display_name    人读名
        capabilities    能力参数（构造时注入，来源 knowledge/models.json 对应条目；
                        ref_images / duration_min / duration_max / resolutions /
                        image_to_video / chinese_prompt / multi_ref_supported ...）
    第三方接入：实现 create_task / query_task，用 @register 注册即被自动发现。
    """

    id: str = ""
    display_name: str = ""
    aliases: tuple = ()  # 额外注册名（同一实现族），只在类自身 __dict__ 中生效

    def __init__(self, provider_id: str = "", capabilities: dict | None = None):
        self.id = provider_id or self.id
        self.capabilities = dict(capabilities or {})

    @abstractmethod
    def create_task(self, prompt: str, ref_images: list, duration: int,
                    resolution: str, aspect_ratio: str, negative_prompt: str,
                    ctx: dict) -> str:
        """创建生成任务，返回 task_id；同步返回 URL 时用前缀 __direct_url__:http..."""

    @abstractmethod
    def query_task(self, task_id: str, ctx: dict) -> dict:
        """查询任务，返回 dict（含 status: succeeded/failed/... 与 url 字段）"""

    def extract_url(self, data: dict) -> str | None:
        """从查询结果中提取视频 URL；默认走通用递归（Agnes metadata.url 已兼容），可覆盖。"""
        return _extract_url(data)

    def download(self, url: str, save_path) -> Path:
        """下载视频到 save_path；默认 requests 流式，可覆盖。"""
        return download_file(url, save_path)
