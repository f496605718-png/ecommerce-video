#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频生成客户端（provider 适配层，开放接入）。

对外接口不变（batch_generate 等调用方无感）：
    create_task(prompt, ref_images, duration, resolution, aspect_ratio, negative_prompt) -> task_id
    poll_until_done(task_id, interval, timeout) -> url
    download_video(url, save_path) -> Path
    VideoGenError

内部实现已迁移到 scripts/providers/ 包（统一协议 VideoProvider + @register 注册表）：
本文件只做三件事——
    1. 能力参数装载：读 knowledge/models.json 对应条目（查不到→保守默认 + ctx warning）
    2. 注册表分发：get_provider(config.VIDEO_PROVIDER, capabilities).create_task(...)
    3. 轮询/下载编排（协议约定的 status / extract_url / __direct_url__ 语义）

新增 provider：在 scripts/providers/ 新建模块实现 VideoProvider 并 @register，
无需改动本文件与任何调用方。
"""
import sys
import time
from pathlib import Path

# Windows 控制台 GBK 兼容
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import config
from ecommerce_video.providers import get_provider, list_providers, PROVIDERS  # noqa: F401（PROVIDERS 供诊断/外部检查）
from ecommerce_video.providers.base import (VideoGenError, load_capabilities, download_file,
                                            _request, _auth_headers, _proxies, _extract_url, _URL_KEYS)

# 能力缺失警告只打印一次（防刷屏）
_warned = set()


def _resolve(provider_id: str):
    """装载能力参数 + 取 provider 实例；能力缺失时把 warning 写入 ctx 并提示一次。"""
    ctx = {}
    caps = load_capabilities(provider_id, ctx)
    if ctx.get("warnings") and provider_id not in _warned:
        _warned.add(provider_id)
        for w in ctx["warnings"]:
            print(f"[video_client] 警告: {w}", file=sys.stderr)
    return get_provider(provider_id, caps), ctx


def create_task(prompt: str, ref_images: list, duration: int = 10,
                resolution: str = "1080p", aspect_ratio: str = "9:16",
                negative_prompt: str = "") -> str:
    """创建视频生成任务，返回 task_id（同步返回 URL 时为 __direct_url__:http...）。"""
    provider, ctx = _resolve(config.VIDEO_PROVIDER)
    return provider.create_task(prompt, ref_images, duration, resolution,
                                aspect_ratio, negative_prompt, ctx)


def poll_until_done(task_id: str, interval: int = 10, timeout: int = 900) -> str:
    """轮询任务直到成功/失败/超时，返回视频 URL。"""
    provider, ctx = _resolve(config.VIDEO_PROVIDER)
    if task_id.startswith("__direct_url__:"):  # 同步返回的 URL
        return task_id.split(":", 1)[1]
    waited = 0
    while waited < timeout:
        data = provider.query_task(task_id, ctx)
        status = str(data.get("status", "")).lower()
        if status in ("succeeded", "success", "done", "completed", "finished"):
            url = provider.extract_url(data)
            if url:
                return url
            raise VideoGenError(f"任务成功但未找到视频 URL: {str(data)[:300]}")
        if status in ("failed", "error", "canceled", "cancelled"):
            raise VideoGenError(f"任务失败: {data.get('error') or data.get('message') or str(data)[:200]}")
        # queued/in_progress 继续等待；无 status 字段也等待（部分接口只返回 progress）
        time.sleep(interval)
        waited += interval
    raise VideoGenError(f"任务超时({timeout}s)：task_id={task_id}")


def download_video(url: str, save_path) -> Path:
    """下载视频到 save_path（默认 requests 流式实现，见 providers.base.download_file）。"""
    return download_file(url, save_path)


if __name__ == "__main__":
    print(f"provider 适配层就绪：VIDEO_PROVIDER={config.VIDEO_PROVIDER}, "
          f"model={config.VIDEO_MODEL}, 已注册={list_providers()}")
