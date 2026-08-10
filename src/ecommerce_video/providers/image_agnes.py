#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agnes Image 2.1 Flash 生图实现（迁移自 image_client._agnes_image_generate）。

要点（与旧实现逐行等价，行为零变化）：
- 同步式：POST /images/generations → data[0].{url|b64_json}。
- size 档位(1K/2K/3K/4K) + ratio（如 "2K:9:16"）；ratio 在 body.ratio。
- image 在 extra_body（不在顶层）；多图合成传数组。
- 本地图自动转 data URI（无需公网 URL）。
- ctx 逐调用覆盖 api_key/api_base/model（新协议能力）。
"""
import base64 as _b64
from pathlib import Path as _P

from . import register_image
from .image_base import ImageProvider, ImageGenError, _image_request, _image_api_config
from ecommerce_video import config


def parse_image_size(size: str) -> tuple:
    """解析生图尺寸：'2K:9:16' → ('2K','9:16')；'1024x1024' → 原样。"""
    if ":" in size:
        parts = size.split(":")
        if len(parts) == 3 and parts[0].upper() in ("1K", "2K", "3K", "4K"):
            return parts[0].upper(), parts[1] + ":" + parts[2]
    return size, None


@register_image
class AgnesImageProvider(ImageProvider):
    """Agnes Image 2.1 Flash：文生图/图生图/多图合成。"""

    id = "agnes-image"
    display_name = "Agnes Image 2.1 Flash"
    aliases = ("agnes",)  # 历史名，同族实现

    def generate(self, prompt: str, ref_images: list, size: str, ctx: dict) -> str:
        base = (_image_api_config(ctx, "api_base", config.IMAGE_API_BASE)
                or "https://apihub.agnes-ai.com/v1").rstrip("/")
        api_key = _image_api_config(ctx, "api_key", config.IMAGE_API_KEY)
        # 尺寸解析：IMAGE_SIZE 可写 "2K:9:16"（档位:比例）或 "1024x1024"
        size_val, ratio = parse_image_size(size)
        body = {"model": _image_api_config(ctx, "model", config.IMAGE_MODEL)
                or "agnes-image-2.1-flash",
                "prompt": prompt, "size": size_val}
        if ratio:
            body["ratio"] = ratio
        if ref_images:
            # 本地图 → data URI（无需公网 URL）；多图合成传数组
            imgs = []
            for r in ref_images:
                if str(r).startswith(("http://", "https://", "data:")):
                    imgs.append(str(r))
                else:
                    p = _P(r)
                    if not p.exists():
                        raise ImageGenError(f"参考图不存在: {r}")
                    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".webp": "image/webp"}.get(p.suffix.lower(), "image/jpeg")
                    imgs.append(f"data:{mime};base64,{_b64.b64encode(p.read_bytes()).decode()}")
            body["extra_body"] = {"image": imgs}
        data = _image_request("POST", base + "/images/generations", api_key, json=body)
        if isinstance(data, dict):
            d = data.get("data") or []
            if isinstance(d, list) and d:
                item = d[0]
                if item.get("url"):
                    return item["url"]
                if item.get("b64_json"):
                    return f"__b64__:{item['b64_json']}"
        raise ImageGenError(f"Agnes 无法解析生图结果: {str(data)[:200]}")
