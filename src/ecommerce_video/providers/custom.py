#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""custom / OpenAI 兼容实现（第三方模型开放接入的默认落点）。

- 端点：先试 /videos/generations，回退 /images/generations（端点可从 .env 覆盖）。
- 创建响应兼容三种形态：{id} / {task_id} / {data:[{url}]}（后者为同步返回，
  包成已完成任务 __direct_url__:http...）。
- 查询：/videos/generations/{task_id}，失败回退 /images/generations/{task_id}；
  同步 URL 任务直接返回 succeeded。
"""
from . import register
from .base import VideoProvider, VideoGenError, _request, _api_config
from ecommerce_video import config


@register
class CustomProvider(VideoProvider):
    id = "custom"
    display_name = "自定义接入（OpenAI 兼容）"

    def create_task(self, prompt, ref_images, duration, resolution, aspect_ratio,
                    negative_prompt, ctx):
        """custom/OpenAI 兼容接口：images 或 videos 生成端点。"""
        base = (_api_config(ctx, "api_base", config.VIDEO_API_BASE) or "").rstrip("/")
        api_key = _api_config(ctx, "api_key", config.VIDEO_API_KEY)
        body = {"model": _api_config(ctx, "model", config.VIDEO_MODEL),
                "prompt": prompt, "n": 1, "size": f"{resolution}"}
        if ref_images:
            body["image"] = ref_images[0]
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        # 尝试 videos 端点，回退 images 端点
        for ep in ("/videos/generations", "/images/generations"):
            try:
                data = _request("POST", base + ep, api_key, json=body)
                # 兼容 {id} / {data:[{url}]} / {task_id}
                if isinstance(data, dict) and data.get("id"):
                    return str(data["id"])
                if isinstance(data, dict) and isinstance(data.get("data"), list) and data["data"]:
                    # 同步返回 URL 的类型：包成已完成任务
                    return f"__direct_url__:{data['data'][0].get('url', '')}"
                if isinstance(data, dict) and data.get("task_id"):
                    return str(data["task_id"])
            except VideoGenError:
                if ep.endswith("/videos/generations"):
                    continue
                raise
        raise VideoGenError("custom provider 无法创建任务（端点结构未匹配）")

    def query_task(self, task_id, ctx):
        if task_id.startswith("__direct_url__:"):
            return {"status": "succeeded", "url": task_id.split(":", 1)[1]}
        base = (_api_config(ctx, "api_base", config.VIDEO_API_BASE) or "").rstrip("/")
        api_key = _api_config(ctx, "api_key", config.VIDEO_API_KEY)
        try:
            return _request("GET", base + f"/videos/generations/{task_id}", api_key)
        except VideoGenError:
            try:
                return _request("GET", base + f"/images/generations/{task_id}", api_key)
            except VideoGenError:
                return {"status": "failed", "error": "custom provider 查询端点未匹配"}
