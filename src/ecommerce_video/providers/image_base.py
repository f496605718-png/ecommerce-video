#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生图 Provider 基类 + 统一协议定义（开源改造第3步：与视频链路对称）。

协议（第三方生图接入核心，与 base.py 的 VideoProvider 对称）：
    class MyImageProvider(ImageProvider):
        id = "my-image-model"        # 注册名
        display_name = "My Image"    # 人读名
        def generate(self, prompt, ref_images, size, ctx) -> str:
            # 返回图片 URL，或 "__b64__:<base64>"（本地/私有交付场景）
            ...
    然后在 providers/__init__.py 里 `from . import image_my` 即完成发现
    （或直接在模块里 `@register_image` 自注册）。

约定：
- generate 返回字符串：http(s) URL，或 "__b64__:<base64>" 内嵌图片。
  默认 download() 两者都处理（URL → requests 流式下载；__b64__ → 直接解码写盘）。
- ctx：逐调用上下文 dict（如 {"warnings": [...]}），可携带 api_key/api_base/model
  覆盖全局 config（见 _image_api_config），供第三方接入方做多账号/多端点路由。
- 能力参数：capabilities 由 __init__.get_image_provider 按 knowledge/models.json 的
  image_models 对应条目注入（注意：image_models 是 dict 非 list，与 models[] 结构不同）。
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

try:
    import requests
except ImportError:  # 未安装时仅影响真实网络调用，导入与自测不受影响
    requests = None

from ecommerce_video import config
from .base import download_file, _proxies


class ImageGenError(Exception):
    """生图链路错误（鉴权/网络/解析/未注册等）。"""


# ================= 公共请求工具（镜像 base.py，但面向生图链路） =================

def _image_request(method: str, url: str, api_key: str, **kw):
    """带重试的请求；401/403 明确提示密钥问题（防密钥省略）。

    错误文本与旧 image_client 完全一致（行为零变化红线）。
    """
    if requests is None:
        raise ImageGenError("依赖 requests 未安装：pip install requests")
    last_err = None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(config.API_MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=headers,
                                    timeout=config.API_TIMEOUT, proxies=_proxies(), **kw)
            if resp.status_code in (401, 403):
                raise ImageGenError(
                    f"鉴权失败({resp.status_code})：请检查 .env 中 {config.IMAGE_PROVIDER.upper()}_API_KEY "
                    f"（当前 {config.mask_key(api_key)}）——见 CONFIG.md")
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except ImageGenError:
            raise
        except Exception as e:
            last_err = e
            if attempt < config.API_MAX_RETRIES:
                time.sleep(config.API_RETRY_INTERVAL)
    raise ImageGenError(f"请求失败（已重试 {config.API_MAX_RETRIES} 次）: {last_err}")


def _image_api_config(ctx: dict, name: str, default: str = "") -> str:
    """生图 API 配置取值：ctx 逐调用覆盖优先，其次 config 全局。
    name ∈ {"api_key", "api_base", "model"} → config.IMAGE_API_KEY/IMAGE_API_BASE/IMAGE_MODEL。
    （与 base._api_config 同逻辑，面向生图配置项。）
    """
    if ctx and ctx.get(name):
        return ctx[name]
    return getattr(config, {"api_key": "IMAGE_API_KEY",
                            "api_base": "IMAGE_API_BASE",
                            "model": "IMAGE_MODEL"}[name], default) or default


# ================= 能力参数装载（knowledge/models.json image_models） =================

# 生图能力保守默认（与任务约定一致）
DEFAULT_IMAGE_CAPABILITIES = {
    "text_to_image": True,        # 保守：文生图一定有
    "image_to_image": False,      # 保守：图生图未确认按不支持
    "multi_image_compose": False,  # 保守：多图合成未确认按不支持（走 S 合成前置判断）
    "size_system": "1024x1024",   # 保守：精确尺寸
}

# provider id → image_models 条目 key（别名复用同族能力，避免误降级保守值）
_IMAGE_CAPABILITY_ALIASES = {
    "agnes-image": "agnes-image-2.1-flash",
    "agnes": "agnes-image-2.1-flash",
    "openai": "custom-image",
}


def load_image_capabilities(provider_id: str, ctx: dict | None = None) -> dict:
    """读 knowledge/models.json 的 image_models（dict 非 list），按 key 匹配能力。

    查不到（或文件缺失/损坏）→ 返回保守默认值，并把 warning 追加到 ctx["warnings"]。
    image_models 条目中显式为 null 的字段视为未确认，按保守默认处理。
    """
    warnings = []
    caps = {}
    lookup = _IMAGE_CAPABILITY_ALIASES.get(provider_id, provider_id)
    try:
        data = json.loads((config.KNOWLEDGE_DIR / "models.json").read_text(encoding="utf-8"))
        entry = data.get("image_models", {}).get(lookup)
        if entry and isinstance(entry.get("capabilities"), dict):
            caps = {k: v for k, v in entry["capabilities"].items() if v is not None}
        else:
            warnings.append(
                f"models.json 未找到生图 provider '{provider_id}' 的能力参数，已用保守默认值；"
                f"接入后请在 knowledge/models.json 的 image_models 回填该模型能力")
    except FileNotFoundError:
        warnings.append(f"knowledge/models.json 不存在，使用保守默认生图能力参数 {DEFAULT_IMAGE_CAPABILITIES}")
    except Exception as e:
        warnings.append(f"读取 knowledge/models.json 失败（{e}），使用保守默认生图能力参数 {DEFAULT_IMAGE_CAPABILITIES}")
    merged = dict(DEFAULT_IMAGE_CAPABILITIES)
    merged.update(caps)  # 显式非空值覆盖保守默认
    if warnings and ctx is not None:
        ctx.setdefault("warnings", []).extend(warnings)
    return merged


# ================= Provider 基类（协议本体） =================

class ImageProvider(ABC):
    """统一生图 Provider 协议（与 VideoProvider 对称）。

    属性：
        id              注册名（如 "agnes-image" / "custom-image"）
        display_name    人读名
        capabilities    能力参数（构造时注入，来源 knowledge/models.json image_models
                        对应条目；text_to_image / image_to_image / multi_image_compose /
                        size_system ...）
    第三方接入：实现 generate，用 @register_image 注册即被自动发现。
    """

    id: str = ""
    display_name: str = ""
    aliases: tuple = ()  # 额外注册名（同一实现族），只在类自身 __dict__ 中生效

    def __init__(self, provider_id: str = "", capabilities: dict | None = None):
        self.id = provider_id or self.id
        self.capabilities = dict(capabilities or {})

    @abstractmethod
    def generate(self, prompt: str, ref_images: list, size: str, ctx: dict) -> str:
        """生成图片：返回图片 URL，或 '__b64__:<base64>' 内嵌图片字符串。"""

    def download(self, url_or_b64: str, save_path) -> Path:
        """把 generate 的返回值落地到 save_path（默认实现，可覆盖）。

        __b64__: 前缀 → base64 解码直接写盘；否则 requests 流式下载（复用 base.download_file）。
        """
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        if url_or_b64.startswith("__b64__:"):
            import base64
            save_path.write_bytes(base64.b64decode(url_or_b64.split(":", 1)[1]))
            return save_path
        return download_file(url_or_b64, save_path)
