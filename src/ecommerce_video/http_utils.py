#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 请求统一重试工具（P5：429 限流指数退避 + 5xx/超时/连接错误有限重试）。

用法：各调用方（providers/base、prompt_engine、vision_client）统一走
`request_with_retry(...)`，避免各自写重试逻辑导致行为不一致（演示中 429 因
固定 5s 间隔重试不足而失败）。

规则：
- 429：指数退避，优先尊重 Retry-After 响应头；默认 30s * 2^n，上限 300s；
  重试次数 = API_429_MAX_RETRIES（默认 3）
- 5xx / 超时 / 连接错误：短退避（API_RETRY_INTERVAL 递增），重试 API_MAX_RETRIES 次
- 4xx（非 429）：不重试，直接返回响应（调用方处理 401/403 鉴权语义）
- 返回：requests.Response（不做 raise_for_status，状态码语义留给调用方）
- 全部重试失败：抛出最后一次异常
"""
from __future__ import annotations

import time

import requests

from ecommerce_video import config


def _proxies():
    return {"http": config.HTTP_PROXY, "https": config.HTTP_PROXY} if config.HTTP_PROXY else None


def request_with_retry(method: str, url: str, *, headers: dict | None = None,
                       json: dict | None = None, timeout: int | None = None,
                       max_retries: int | None = None,
                       retry_429: bool = True) -> requests.Response:
    """带重试的请求（见模块 docstring）。"""
    timeout = timeout or config.API_TIMEOUT
    max_retries = config.API_MAX_RETRIES if max_retries is None else max_retries
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.request(method, url, headers=headers, json=json,
                                    timeout=timeout, proxies=_proxies())
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(min(config.API_RETRY_INTERVAL * (2 ** attempt), 60))
            continue

        if resp.status_code == 429 and retry_429:
            if attempt < config.API_429_MAX_RETRIES:
                wait = _retry_after(resp, attempt)
                time.sleep(wait)
                continue
        elif resp.status_code >= 500:
            if attempt < max_retries:
                time.sleep(min(config.API_RETRY_INTERVAL * (2 ** attempt), 60))
                continue
        return resp  # 2xx / 4xx（含 401/403/429 用尽）→ 交回调用方
    raise last_err if last_err else RuntimeError("请求失败（重试耗尽）")


def _retry_after(resp: requests.Response, attempt: int) -> int:
    """429 等待秒数：优先 Retry-After 头；否则 30s * 2^attempt 指数退避（上限 300s）。"""
    h = resp.headers.get("Retry-After")
    if h and h.isdigit():
        return min(int(h), 300)
    return min(30 * (2 ** attempt), 300)
