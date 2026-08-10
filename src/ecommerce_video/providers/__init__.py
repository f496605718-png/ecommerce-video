#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider 注册表 + 发现机制（战役2 接口开放化的核心；开源改造第3步加入生图链路）。

- 视频协议：base.py 的 VideoProvider 基类（create_task/query_task/extract_url/download
  + capabilities 能力参数）；注册表 PROVIDERS + @register。
- 生图协议：image_base.py 的 ImageProvider 基类（generate/download + capabilities），
  与视频链路对称；注册表 IMAGE_PROVIDERS + @register_image。
  ★ 生图注册表独立于视频注册表（防 id 冲突：视频已占用 id="custom"，
    生图 OpenAI 兼容用 id="custom-image" + aliases("openai","seedance")）。
- 发现：每个 provider 模块用对应装饰器自注册；本包 import 全部模块即完成发现。
  禁止手写 if-else 分发——新增 provider = 新建模块 + 实现基类 + 对应 @register。
- 能力参数：get_provider / get_image_provider 未显式传入时自动读
  knowledge/models.json 对应条目（视频 models[] / 生图 image_models{}），
  查不到用保守默认值（base.DEFAULT_CAPABILITIES / image_base.DEFAULT_IMAGE_CAPABILITIES）。
"""
from __future__ import annotations

from .base import (VideoGenError, VideoProvider, DEFAULT_CAPABILITIES,
                   load_capabilities, download_file,
                   _request, _auth_headers, _proxies, _extract_url, _URL_KEYS)
from .image_base import (ImageGenError, ImageProvider, DEFAULT_IMAGE_CAPABILITIES,
                         load_image_capabilities, _image_request, _image_api_config)

PROVIDERS: dict[str, type[VideoProvider]] = {}      # 视频：id → 类
IMAGE_PROVIDERS: dict[str, type[ImageProvider]] = {}  # 生图：id → 类（独立注册表，防与视频 id 冲突）


def register(cls):
    """类装饰器（视频）：按 cls.id（+ 类自身 __dict__ 中的 aliases）注册进 PROVIDERS。"""
    if not (isinstance(cls, type) and issubclass(cls, VideoProvider)):
        raise TypeError(f"register 仅接受 VideoProvider 子类，收到 {cls!r}")
    for name in [cls.id] + list(cls.__dict__.get("aliases", ())):
        if name:
            PROVIDERS[name] = cls
    return cls


def register_image(cls):
    """类装饰器（生图）：按 cls.id（+ 类自身 __dict__ 中的 aliases）注册进 IMAGE_PROVIDERS。"""
    if not (isinstance(cls, type) and issubclass(cls, ImageProvider)):
        raise TypeError(f"register_image 仅接受 ImageProvider 子类，收到 {cls!r}")
    for name in [cls.id] + list(cls.__dict__.get("aliases", ())):
        if name:
            IMAGE_PROVIDERS[name] = cls
    return cls


def get_provider(provider_id: str, capabilities: dict | None = None) -> VideoProvider:
    """按 id 取视频 provider 实例（capabilities 构造时注入）。

    capabilities 未传/为空时自动装载：读 knowledge/models.json 对应条目，
    查不到用保守默认值（DEFAULT_CAPABILITIES，见 base.load_capabilities）。
    """
    cls = PROVIDERS.get(provider_id)
    if cls is None:
        raise VideoGenError(
            f"provider '{provider_id}' 未注册（当前支持: {list_providers()}）。"
            f"如为开放接入模型，请在 .env 设 VIDEO_PROVIDER=custom，"
            f"或新建 scripts/providers/<name>.py 实现 VideoProvider 并用 @register 注册。")
    caps = capabilities if capabilities else load_capabilities(provider_id)
    return cls(provider_id=provider_id, capabilities=caps)


def get_image_provider(provider_id: str, capabilities: dict | None = None) -> ImageProvider:
    """按 id 取生图 provider 实例（capabilities 构造时注入）。

    capabilities 未传/为空时自动装载：读 knowledge/models.json 的 image_models 对应条目，
    查不到用保守默认值（DEFAULT_IMAGE_CAPABILITIES，见 image_base.load_image_capabilities）。
    """
    cls = IMAGE_PROVIDERS.get(provider_id)
    if cls is None:
        raise ImageGenError(
            f"provider '{provider_id}' 未注册（当前支持: {list_image_providers()}）。"
            f"如为开放接入模型，请在 .env 设 IMAGE_PROVIDER=custom-image，"
            f"或新建 scripts/providers/image_<name>.py 实现 ImageProvider 并用 @register_image 注册。")
    caps = capabilities if capabilities else load_image_capabilities(provider_id)
    return cls(provider_id=provider_id, capabilities=caps)


def list_providers() -> list[str]:
    """已注册视频 provider id 列表（含别名）。"""
    return sorted(PROVIDERS)


def list_image_providers() -> list[str]:
    """已注册生图 provider id 列表（含别名）。"""
    return sorted(IMAGE_PROVIDERS)


# import 即触发各模块的 @register / @register_image 自注册（发现机制）；放在注册函数定义之后，
# 否则 provider 模块里 `from . import register` 会因包未初始化完成而失败
from . import seedance, agnes, custom  # noqa: E402,F401（视频）
from . import image_base, image_agnes, image_openai  # noqa: E402,F401（生图）


__all__ = ["PROVIDERS", "IMAGE_PROVIDERS",
           "register", "register_image",
           "get_provider", "list_providers",
           "get_image_provider", "list_image_providers",
           "VideoProvider", "VideoGenError", "load_capabilities", "DEFAULT_CAPABILITIES",
           "ImageProvider", "ImageGenError", "load_image_capabilities", "DEFAULT_IMAGE_CAPABILITIES"]
