#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ecommerce_video —— 电商 AI 视频生成工作流（开源包入口）。

知识库驱动的提示词引擎 + 开放模型接入 + 批量生成。
安装：pip install ecommerce-video
用法：
    from ecommerce_video import Workflow
    w = Workflow(project="projA", sku="sku1", category="clothing",
                 material="缎面", type_name="tvc", provider="seedance-2.0")
    w.check()
"""
from __future__ import annotations

__version__ = "1.6.0"

from ecommerce_video.workflow import Workflow
from ecommerce_video.providers import get_provider, list_providers, list_image_providers
from ecommerce_video.video_client import VideoGenError
from ecommerce_video.image_client import ImageGenError

__all__ = [
    "Workflow",
    "get_provider",
    "list_providers",
    "list_image_providers",
    "VideoGenError",
    "ImageGenError",
    "__version__",
]
