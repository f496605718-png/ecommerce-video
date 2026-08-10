#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seedance 2.0 / 2.5 实现（字节跳动 / 即梦开放平台）。

端点：POST /api/v1/videos/generation（创建）→ task_id（兼容嵌套 data.task_id/data.id）
      GET  /api/v1/videos/generation/{task_id}（查询）
2.5 与 2.0 同族端点，能力参数不同（2.5：30s/30 图）——由 models.json 按 id 注入 capabilities。
"""
from . import register
from .base import VideoProvider, VideoGenError, _request, _api_config
from ecommerce_video import config


@register
class SeedanceProvider(VideoProvider):
    id = "seedance-2.0"
    display_name = "Seedance 2.0"
    aliases = ("seedance",)  # 历史名，同族实现

    def create_task(self, prompt, ref_images, duration, resolution, aspect_ratio,
                    negative_prompt, ctx):
        body = {"model": _api_config(ctx, "model", config.VIDEO_MODEL),
                "prompt": prompt, "duration": duration,
                "resolution": resolution, "aspect_ratio": aspect_ratio}
        if ref_images:
            body["image"] = ref_images[0]
            if len(ref_images) > 1:
                body["reference_images"] = ref_images[1:]
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        data = _request("POST",
                        _api_config(ctx, "api_base", config.VIDEO_API_BASE).rstrip("/")
                        + "/api/v1/videos/generation",
                        _api_config(ctx, "api_key", config.VIDEO_API_KEY), json=body)
        # task_id 解析：兼容顶层与嵌套 data 两种结构
        for key in ("task_id", "id"):
            if isinstance(data, dict) and data.get(key):
                return str(data[key])
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            d = data["data"]
            for key in ("task_id", "id"):
                if d.get(key):
                    return str(d[key])
        raise VideoGenError(f"无法解析 task_id: {str(data)[:200]}")

    def query_task(self, task_id, ctx):
        data = _request("GET",
                        _api_config(ctx, "api_base", config.VIDEO_API_BASE).rstrip("/")
                        + f"/api/v1/videos/generation/{task_id}",
                        _api_config(ctx, "api_key", config.VIDEO_API_KEY))
        return data.get("data", data) if isinstance(data, dict) else data


@register
class Seedance25Provider(SeedanceProvider):
    """Seedance 2.5：端点同族，能力参数不同（由 models.json 'seedance-2.5' 条目注入）。"""
    id = "seedance-2.5"
    display_name = "Seedance 2.5"
