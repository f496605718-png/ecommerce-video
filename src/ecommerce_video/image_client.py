#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片生成客户端（provider 适配层，开放接入）。

用途：
  1. 合成首帧：视频模型不支持多参考图时，把「商品+模特/场景」合成一张图（图生视频前置）
  2. 样衣概念图：C 档无参考图时，文字描述生成样衣供客户确认
  3. 场景概念图：跨镜头一致性锚点

对外接口不变（调用方无感）：
    generate(prompt, ref_images, size, save_path) -> Path | str（图片 URL 或本地路径）
    ImageGenError

内部实现已迁移到 providers/ 包（统一协议 ImageProvider + @register_image 注册表，
与视频链路 VideoProvider 对称；开源改造第3步）。本文件只做三件事——
    1. 能力参数装载：读 knowledge/models.json 的 image_models 对应条目
       （查不到→保守默认 + ctx warning，只提示一次）
    2. 注册表分发：get_image_provider(config.IMAGE_PROVIDER, caps).generate(...)
    3. save_path 落地：复用 provider.download（URL 下载 / __b64__ 解码，逻辑与旧版一致）

新增 provider：在 providers/ 新建 image_<name>.py 实现 ImageProvider 并 @register_image，
无需改动本文件与任何调用方。
"""
import sys
from pathlib import Path

# Windows 控制台 GBK 兼容
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import config
from ecommerce_video.providers import (get_image_provider, list_image_providers,
                                       IMAGE_PROVIDERS)  # noqa: F401（IMAGE_PROVIDERS 供诊断/外部检查）
from ecommerce_video.providers.image_base import ImageGenError, load_image_capabilities

# 能力缺失警告只打印一次（防刷屏）
_warned = set()


def _resolve(provider_id: str):
    """装载能力参数 + 取 provider 实例；能力缺失时把 warning 写入 ctx 并提示一次。"""
    ctx = {}
    caps = load_image_capabilities(provider_id, ctx)
    if ctx.get("warnings") and provider_id not in _warned:
        _warned.add(provider_id)
        for w in ctx["warnings"]:
            print(f"[image_client] 警告: {w}", file=sys.stderr)
    return get_image_provider(provider_id, caps), ctx


def generate(prompt: str, ref_images: list = None, size: str = "1024x1024",
             save_path: Path | None = None) -> Path | str:
    """生成图片。save_path 给定时下载/解码到本地并返回路径；否则返回 URL。"""
    provider, ctx = _resolve(config.IMAGE_PROVIDER)
    result = provider.generate(prompt, ref_images or [], size, ctx)
    if not save_path:
        return result
    return provider.download(result, save_path)


if __name__ == "__main__":
    print(f"生图 provider 适配层就绪：IMAGE_PROVIDER={config.IMAGE_PROVIDER}, "
          f"model={config.IMAGE_MODEL}, 已注册={list_image_providers()}")
