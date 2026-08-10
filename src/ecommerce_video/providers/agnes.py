#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agnes Video V2.0 实现。

要点：
- 异步任务式：POST /v1/videos → video_id 轮询；结果 URL 在 metadata.url。
- 时长由 num_frames(8n+1，≤441) + frame_rate(24) 控制。
- 图生视频：单图 image（本地图自动转 data URI）；多图走关键帧模式 extra_body。
- 查询：优先 GET /agnesapi?video_id=，回退 GET /v1/videos/<id>。
"""
import base64 as _b64
from pathlib import Path as _P

from . import register
from .base import VideoProvider, VideoGenError, _request, _api_config
from ecommerce_video import config


def _frames_for_duration(duration: int, frame_rate: int = 24) -> int:
    """duration_sec → num_frames：必须 ≤441 且满足 8n+1 规则（Agnes 硬性要求）。"""
    target = duration * frame_rate
    target = min(target, 441)
    # 最近的 8n+1
    n = round((target - 1) / 8)
    frames = 8 * n + 1
    if frames > 441:
        frames = 441
    return frames


def _ratio_to_wh(ratio: str) -> tuple:
    """宽高比 → width/height（按 720p 量级，服务端会标准化）。"""
    mapping = {
        "9:16": (768, 1152),
        "16:9": (1152, 768),
        "1:1": (1024, 1024),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "2:3": (768, 1152),
        "3:2": (1152, 768),
    }
    return mapping.get(str(ratio), (768, 1152))


@register
class AgnesVideoProvider(VideoProvider):
    id = "agnes-video"
    display_name = "Agnes Video V2.0"
    aliases = ("agnes",)  # 历史名，同族实现

    def create_task(self, prompt, ref_images, duration, resolution, aspect_ratio,
                    negative_prompt, ctx):
        base = (_api_config(ctx, "api_base", config.VIDEO_API_BASE)
                or "https://apihub.agnes-ai.com/v1").rstrip("/")
        frame_rate = 24
        body = {
            "model": _api_config(ctx, "model", config.VIDEO_MODEL) or "agnes-video-v2.0",
            "prompt": prompt,
            "num_frames": _frames_for_duration(duration or 10, frame_rate),
            "frame_rate": frame_rate,
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        # 分辨率/宽高比 → width/height（服务端自动标准化到 480p/720p/1080p 档位）
        w, h = _ratio_to_wh(aspect_ratio or "9:16")
        body["width"] = w
        body["height"] = h
        if ref_images:
            # 图生视频：单图（S 阶段合成首帧后这里就是合成图）；本地图转 data URI
            img = ref_images[0]
            if str(img).startswith(("http://", "https://", "data:")):
                body["image"] = str(img)
            else:
                p = _P(img)
                if not p.exists():
                    raise VideoGenError(f"参考图不存在: {img}")
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp"}.get(p.suffix.lower(), "image/jpeg")
                body["image"] = f"data:{mime};base64,{_b64.b64encode(p.read_bytes()).decode()}"
            if len(ref_images) > 1:
                # 多图 → 关键帧模式
                body["extra_body"] = {"image": [body.pop("image")] + [str(r) for r in ref_images[1:]],
                                      "mode": "keyframes"}
        data = _request("POST", base + "/videos",
                        _api_config(ctx, "api_key", config.VIDEO_API_KEY), json=body)
        # 创建响应：id/task_id/video_id 都有，推荐用 video_id
        for key in ("video_id", "task_id", "id"):
            if isinstance(data, dict) and data.get(key):
                return str(data[key])
        raise VideoGenError(f"无法解析任务 ID: {str(data)[:200]}")

    def query_task(self, task_id, ctx):
        """查询任务：优先 /agnesapi?video_id=，回退 /v1/videos/<id>。"""
        base = (_api_config(ctx, "api_base", config.VIDEO_API_BASE)
                or "https://apihub.agnes-ai.com/v1").rstrip("/")
        api_key = _api_config(ctx, "api_key", config.VIDEO_API_KEY)
        try:
            return _request("GET", base + f"/agnesapi?video_id={task_id}", api_key)
        except VideoGenError:
            return _request("GET", base + f"/videos/{task_id}", api_key)
