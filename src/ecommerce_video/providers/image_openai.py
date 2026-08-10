#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""custom / OpenAI 兼容生图实现（第三方生图开放接入的默认落点）。

迁移自 image_client._openai_compat_generate / _seedance_compat_generate（逐行等价）：
- 文生图：POST /images/generations；有参考图 → 先试 /images/edits（融合），失败回退文生图。
- 返回兼容三种形态：{data:[{url|b64_json}]} / {url} / {image_url}。
- seedance（即梦同族）与 openai 同为别名 → 同一实现（旧 seedance 实现就是委托 openai 兼容）。
- ctx 逐调用覆盖 api_key/api_base/model（新协议能力）。
"""
from . import register_image
from .image_base import ImageProvider, ImageGenError, _image_request, _image_api_config
from ecommerce_video import config


@register_image
class OpenAICompatImageProvider(ImageProvider):
    """custom/OpenAI 兼容：images/generations（文生图）+ images/edits（图生图/多图融合）。"""

    id = "custom-image"  # 与视频链路 custom 区分（视频已占用 id="custom"，见 providers/__init__.py）
    display_name = "自定义接入（OpenAI 兼容生图）"
    aliases = ("openai", "seedance")  # 历史名/同族实现

    def generate(self, prompt: str, ref_images: list, size: str, ctx: dict) -> str:
        base = (_image_api_config(ctx, "api_base", config.IMAGE_API_BASE) or "").rstrip("/")
        api_key = _image_api_config(ctx, "api_key", config.IMAGE_API_KEY)
        body = {"model": _image_api_config(ctx, "model", config.IMAGE_MODEL),
                "prompt": prompt, "n": 1, "size": size}
        if ref_images:
            # 有参考图 → 走 edits（融合）：多参考图作为 image + mask 或参考列表（按厂商规范）
            try:
                data = _image_request("POST", base + "/images/edits", api_key, json=body)
            except ImageGenError:
                # 部分厂商 edits 用 multipart；无 edits 则退回文生图（提示词承载描述）
                data = _image_request("POST", base + "/images/generations", api_key, json=body)
        else:
            data = _image_request("POST", base + "/images/generations", api_key, json=body)
        # 兼容返回：{data:[{url|b64_json}]} / {url} / {image_url}
        if isinstance(data, dict):
            d = data.get("data") or data.get("images") or []
            if isinstance(d, list) and d:
                item = d[0]
                if item.get("url"):
                    return item["url"]
                if item.get("b64_json"):
                    return f"__b64__:{item['b64_json']}"
            if data.get("url"):
                return data["url"]
            if data.get("image_url"):
                return data["image_url"]
        raise ImageGenError(f"无法解析生图结果: {str(data)[:200]}")
