#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logging_utils.py —— 轻量结构化日志模块（战役3：工程化质量：商用产品日志分级）。

纯标准库 logging 实现，零第三方依赖。设计要点：
  1. 日志输出到 **stderr**：绝不污染 stdout —— CLI 的 print 用户可见输出仍在 stdout，
     管道/重定向不受日志干扰；
  2. 统一格式：%(asctime)s | %(levelname)-7s | %(name)s | %(message)s；
  3. 级别可配：setup_logger(level=...) 参数，或环境变量 VIDEO_LOG_LEVEL 覆盖
     （DEBUG/INFO/WARNING/ERROR，非法值回退 INFO，环境变量优先）；
  4. 文件日志可选：环境变量 VIDEO_LOG_FILE=/path/to/app.log 或 setup_logger(log_file=...)
     启用；默认不写文件（零副作用，开源用户按需开启）；
  5. get_logger() 幂等：重复调用返回同一已配置 logger，不重复加 handler。

用法：
    from logging_utils import get_logger
    logger = get_logger("workflow")       # 首次调用自动按默认配置初始化
    logger.info("任务完成：%s", key)       # 信息节点
    logger.warning("校验拦截：%s", reason) # 拦截/降级
    logger.error("生成失败：%s", err)      # 失败/异常
"""
import logging
import os
import sys
import threading
from pathlib import Path

# 统一日志格式（战役3 约定）
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

# 合法级别表（大小写不敏感；WARN 兼容别名）
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# Windows GBK 兼容：stderr 统一 UTF-8 + replace，防止中文日志在 GBK 控制台/管道
# 抛 UnicodeEncodeError（与 scripts/ 其他模块对 stdout 的 reconfiguration 同款做法）
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_configured: set = set()   # 已配置完成的 logger 名（幂等标记）
_lock = threading.Lock()   # 保护 _configured（setup/get 并发安全）


def _resolve_level(level: str) -> int:
    """解析级别：环境变量 VIDEO_LOG_LEVEL 优先，其次参数 level；非法值回退 INFO。"""
    env = os.environ.get("VIDEO_LOG_LEVEL", "").strip().upper()
    raw = env or (level or "").strip().upper()
    return _LEVELS.get(raw, logging.INFO)


def setup_logger(name: str = "ecommerce-video", level: str = "INFO",
                 log_file: str = "", console: bool = True) -> logging.Logger:
    """配置并返回 logger。

    :param name:     logger 名（get_logger(name) 按名取同一实例）
    :param level:    日志级别（DEBUG/INFO/WARNING/ERROR）；环境变量 VIDEO_LOG_LEVEL 可覆盖
    :param log_file: 日志文件路径；为空则看环境变量 VIDEO_LOG_FILE，再空则不写文件
    :param console:  True → 输出到 stderr（默认）；False → 仅写文件
    :return: 已配置的 logging.Logger（幂等：同名重复调用不重复加 handler）
    """
    with _lock:
        logger = logging.getLogger(name)
        if name in _configured:
            return logger
        logger.setLevel(_resolve_level(level))
        # 阻断向 root 传播：避免 root lastResort handler 把 WARNING+ 再打一遍（重复输出）
        logger.propagate = False
        fmt = logging.Formatter(LOG_FORMAT)
        if console and sys.stderr is not None:
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(fmt)
            logger.addHandler(sh)
        file_path = log_file or os.environ.get("VIDEO_LOG_FILE", "").strip()
        if file_path:
            p = Path(file_path)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass  # 目录创建失败不阻塞；文件打开失败由 FileHandler 自行抛错
            fh = logging.FileHandler(str(p), encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        _configured.add(name)
        return logger


def get_logger(name: str = "ecommerce-video") -> logging.Logger:
    """获取已配置的 logger（幂等：首次调用自动按默认配置初始化，重复调用复用）。

    未显式调用 setup_logger 时，用默认配置（INFO / stderr / 不写文件）；
    环境变量 VIDEO_LOG_LEVEL / VIDEO_LOG_FILE 在首次配置时生效。
    """
    if name not in _configured:
        setup_logger(name)  # 锁内二次检查，并发首次调用安全
    return logging.getLogger(name)


__all__ = ["setup_logger", "get_logger", "LOG_FORMAT"]
