#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉识别客户端：调用多模态语言模型（默认 Agnes 2.5 Flash）识别参考图。

用途（03 流程阶段 B1）：
  - 识别图片类型（白底/多角度/使用佩戴/细节特写/场景/其他）
  - 提取商品特性（品类/主色/材质推断/关键细节 + 品类字段）
  - 输出结构化 JSON 报告，供用户确认

适配：Agnes 2.5 Flash（OpenAI 兼容 chat/completions，image_url 输入）。
本地图片自动转 base64 data URI（无需公网 URL）。
"""
import base64
import json
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
from ecommerce_video import config

# 固定识别指令模板（阶段 B1：类型/特性/置信度/质量）
RECOGNITION_PROMPT = """你是电商商品图识别专家。识别这张商品参考图，输出 JSON（不要解释）：

{
  "image_type": "白底商品图|多角度展示图|使用佩戴图|细节特写图|场景概念图|生活随拍|其他",
  "image_type_confidence": "高|中|低",
  "category": "品类名",
  "primary_color": "主色描述",
  "material_inference": {"value": "材质推断", "confidence": "高|中|低", "basis": "推断依据(光泽/质感/纹理)"},
  "key_details": "logo/标签/接口/图案等关键细节",
  "quality": {"clear": true, "occluded": false, "watermark": false, "note": "质量备注"}
}

要求：
- material_inference 是重点，必须给出推断依据
- 无法判断的字段写 null，不要编造
"""


class VisionError(Exception):
    pass


def image_to_data_uri(path: str) -> str:
    """本地图片 → base64 data URI（Agnes 支持；避免公网 URL 依赖）。"""
    p = Path(path)
    if not p.exists():
        raise VisionError(f"图片不存在: {path}")
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(p.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def recognize_image(image_path: str, extra_instructions: str = "") -> dict:
    """识别单张参考图，返回结构化结果。extra_instructions 可追加品类字段要求。"""
    if not config.VISION_API_KEY:
        raise VisionError("未配置 VISION_API_KEY（视觉识别），请补 .env 或走人工模式")
    prompt = RECOGNITION_PROMPT + (f"\n额外要求：{extra_instructions}" if extra_instructions else "")
    payload = {
        "model": config.VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_to_data_uri(image_path)}},
            ],
        }],
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    url = config.VISION_API_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {config.VISION_API_KEY}", "Content-Type": "application/json"}
    proxies = {"http": config.HTTP_PROXY, "https": config.HTTP_PROXY} if config.HTTP_PROXY else None
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=config.API_TIMEOUT, proxies=proxies)
        if resp.status_code in (401, 403):
            raise VisionError(f"鉴权失败({resp.status_code})：检查 .env 中 VISION_API_KEY")
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except VisionError:
        raise
    except Exception as e:
        raise VisionError(f"识别请求失败: {e}")
    return _parse_json(content)


def _parse_json(text: str) -> dict:
    """提取 LLM 返回中的 JSON（容忍代码块/杂文）。"""
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise VisionError(f"识别结果不是合法 JSON: {text[:200]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python vision_client.py <图片路径>")
        sys.exit(1)
    print(json.dumps(recognize_image(sys.argv[1]), ensure_ascii=False, indent=2))
