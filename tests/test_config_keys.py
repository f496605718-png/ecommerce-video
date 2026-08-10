#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置键名规范化映射测试（P0-1 修复：provider → 键前缀映射表）。

运行：python -m unittest tests.test_config_keys -v   （从项目根目录）

契约（见 src/ecommerce_video/config.py）：
    provider 名经 _VIDEO_KEY_PREFIX / _IMAGE_KEY_PREFIX 规范化映射为键前缀，例如
    seedance-2.0 → SEEDANCE_API_KEY、custom-image → IMAGE_API_KEY（IMAGE 族）；
    查不到映射时退回原规则（provider 大写），并保留 VIDEO_API_KEY / IMAGE_API_KEY 通用兜底。

约束：config 模块级变量在 import 时求值，故用 mock.patch.dict(os.environ, clear=True)
      + importlib.reload 隔离；reload 时屏蔽 dotenv 二次加载真实 .env；
      每个用例 setUp 快照环境、tearDown 恢复并再次 reload —— 不污染同进程后续测试
      （test_capability/test_custom_integration/test_providers/test_retriever/test_workflow 等）。
"""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Windows GBK 兼容：测试名/skip 消息含中文，stdout/stderr 统一重配 UTF-8（与现有测试同款做法）
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ecommerce_video.config as config  # noqa: E402

# 模块导入即求值后的「原始环境」快照：所有用例跑完后环境必须回到此状态
_PRISTINE_ENV = dict(os.environ)
_PRISTINE_VIDEO_PROVIDER = _PRISTINE_ENV.get("VIDEO_PROVIDER", "seedance-2.0").strip().lower()


def _reload_config() -> "module":
    """reload config；屏蔽 dotenv 以免把真实 .env 值注入 mock 环境（dotenv 缺失时本就无此问题）。"""
    try:
        import dotenv  # noqa: F401
    except ImportError:
        importlib.reload(config)
        return config
    with mock.patch("dotenv.load_dotenv", return_value=None):
        importlib.reload(config)
    return config


def _reload_with(env: dict) -> "module":
    """在隔离环境（clear=True）下 reload config，返回模块引用；退出后环境自动恢复。"""
    with mock.patch.dict(os.environ, env, clear=True):
        return _reload_config()


class _ConfigEnvTestCase(unittest.TestCase):
    """基类：每个用例前快照环境，结束后恢复环境并 reload config（防污染同进程后续测试）。"""

    def setUp(self):
        self._env_snapshot = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_snapshot)
        _reload_config()


class TestVideoKeyMapping(_ConfigEnvTestCase):
    """1. 视频侧：provider 名 → 键前缀映射表生效（P0-1 核心修复）。"""

    def test_seedance20_maps_to_seedance(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0", "SEEDANCE_API_KEY": "xxx"})
        self.assertEqual(c.VIDEO_API_KEY, "xxx")

    def test_seedance25_maps_to_seedance25(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.5", "SEEDANCE25_API_KEY": "xxx"})
        self.assertEqual(c.VIDEO_API_KEY, "xxx")

    def test_custom_maps_to_custom(self):
        c = _reload_with({"VIDEO_PROVIDER": "custom", "CUSTOM_API_KEY": "xxx"})
        self.assertEqual(c.VIDEO_API_KEY, "xxx")

    def test_agnes_video_maps_to_agnes(self):
        c = _reload_with({"VIDEO_PROVIDER": "agnes-video", "AGNES_API_KEY": "xxx"})
        self.assertEqual(c.VIDEO_API_KEY, "xxx")

    def test_kling_maps_to_kling(self):
        c = _reload_with({"VIDEO_PROVIDER": "kling", "KLING_API_KEY": "xxx"})
        self.assertEqual(c.VIDEO_API_KEY, "xxx")

    def test_seedance20_prefers_mapped_over_original_rule(self):
        # 映射键优先于原规则键（SEEDANCE-2.0_API_KEY 是带横线的旧陷阱键，不应优先）
        c = _reload_with({
            "VIDEO_PROVIDER": "seedance-2.0",
            "SEEDANCE_API_KEY": "mapped",
            "SEEDANCE-2.0_API_KEY": "old-rule",
            "VIDEO_API_KEY": "fallback",
        })
        self.assertEqual(c.VIDEO_API_KEY, "mapped")

    def test_seedance20_original_rule_fallback_when_mapped_missing(self):
        # 映射键缺、原规则键在 → 走原规则（向后兼容）
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0", "SEEDANCE-2.0_API_KEY": "old-rule"})
        self.assertEqual(c.VIDEO_API_KEY, "old-rule")

    def test_fallback_video_api_key(self):
        # 只给通用兜底 VIDEO_API_KEY → 生效（当前真实 .env 依赖此兜底）
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0", "VIDEO_API_KEY": "yyy"})
        self.assertEqual(c.VIDEO_API_KEY, "yyy")

    def test_no_key_empty(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0"})
        self.assertEqual(c.VIDEO_API_KEY, "")

    def test_unknown_provider_original_rule(self):
        # 未知 provider（如 future-xyz）→ 退回原规则键生效（保持向后兼容）
        c = _reload_with({"VIDEO_PROVIDER": "future-xyz", "FUTURE-XYZ_API_KEY": "kkk"})
        self.assertEqual(c.VIDEO_API_KEY, "kkk")

    def test_video_api_base_uses_mapped_prefix(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0", "SEEDANCE_API_BASE": "https://s/v1"})
        self.assertEqual(c.VIDEO_API_BASE, "https://s/v1")

    def test_video_api_base_fallback_default_kept(self):
        # 映射/原规则/VIDEO_API_BASE 均缺 → 代码默认值不变
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0"})
        self.assertEqual(c.VIDEO_API_BASE, "https://apihub.agnes-ai.com/v1")

    def test_video_model_uses_mapped_prefix(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0", "SEEDANCE_MODEL": "seedance-2.0"})
        self.assertEqual(c.VIDEO_MODEL, "seedance-2.0")

    def test_agnes_video_model_default(self):
        # agnes-video 未配 MODEL → 默认 agnes-video-v2.0（与 config.__main__ 自检一致）
        c = _reload_with({"VIDEO_PROVIDER": "agnes-video"})
        self.assertEqual(c.VIDEO_MODEL, "agnes-video-v2.0")


class TestImageKeyMapping(_ConfigEnvTestCase):
    """2. 生图侧：custom-image / agnes-image → IMAGE 键族（含兜底向后兼容）。"""

    def test_custom_image_maps_to_image(self):
        c = _reload_with({"IMAGE_PROVIDER": "custom-image", "IMAGE_API_KEY": "zzz"})
        self.assertEqual(c.IMAGE_API_KEY, "zzz")

    def test_agnes_image_maps_to_image(self):
        c = _reload_with({"IMAGE_PROVIDER": "agnes-image", "IMAGE_API_KEY": "zzz"})
        self.assertEqual(c.IMAGE_API_KEY, "zzz")

    def test_image_fallback_key_works(self):
        # 只给 IMAGE_API_KEY 兜底（.env.example 与真实 .env 均依赖）→ 生效
        c = _reload_with({"IMAGE_PROVIDER": "custom-image", "IMAGE_API_KEY": "zzz"})
        self.assertEqual(c.IMAGE_API_KEY, "zzz")

    def test_unknown_image_provider_original_rule(self):
        c = _reload_with({"IMAGE_PROVIDER": "future-img", "FUTURE-IMG_API_KEY": "qqq"})
        self.assertEqual(c.IMAGE_API_KEY, "qqq")

    def test_image_model_original_rule_backward_compat(self):
        # 集成测试依赖的旧用法：custom-image + CUSTOM-IMAGE_MODEL（原规则键）仍生效
        c = _reload_with({
            "IMAGE_PROVIDER": "custom-image",
            "CUSTOM-IMAGE_MODEL": "mock-image-model",
        })
        self.assertEqual(c.IMAGE_MODEL, "mock-image-model")


class TestCheckConfigMessage(_ConfigEnvTestCase):
    """3. check_config 缺失提示用映射后键名（不再出现 SEEDANCE-2.0_API_KEY 这类误导键）。"""

    def test_missing_message_uses_mapped_key(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0"})
        miss = c.check_config(require_video_key=True)
        self.assertTrue(any("SEEDANCE_API_KEY" in m and "视频生成" in m for m in miss),
                        f"应提示 SEEDANCE_API_KEY，实际: {miss}")
        self.assertFalse(any("SEEDANCE-2.0_API_KEY" in m for m in miss),
                         f"不应提示旧陷阱键 SEEDANCE-2.0_API_KEY，实际: {miss}")

    def test_check_config_returns_list_and_passes_with_key(self):
        c = _reload_with({"VIDEO_PROVIDER": "seedance-2.0", "SEEDANCE_API_KEY": "xxx"})
        miss = c.check_config(require_video_key=True)
        # 返回仍是字符串列表（其他模块依赖此契约），且视频 key 已配齐不再报缺失
        self.assertIsInstance(miss, list)
        self.assertTrue(all(isinstance(m, str) for m in miss))
        self.assertFalse(any("视频生成" in m for m in miss))

    def test_unknown_provider_message_uses_original_rule_key(self):
        c = _reload_with({"VIDEO_PROVIDER": "future-xyz"})
        miss = c.check_config(require_video_key=True)
        self.assertTrue(any("FUTURE-XYZ_API_KEY" in m for m in miss))


class TestZZEnvRestored(_ConfigEnvTestCase):
    """4. 污染守卫（类名排序最后）：全部 reload 用例跑完后，环境与 config 恢复初始状态。"""

    def test_env_back_to_pristine(self):
        self.assertEqual(dict(os.environ), _PRISTINE_ENV)

    def test_config_back_to_pristine(self):
        # tearDown 已按快照环境 reload：config 反映原始环境而非最后用例的 mock 值
        self.assertEqual(config.VIDEO_PROVIDER, _PRISTINE_VIDEO_PROVIDER)
        # 兜底行为仍在：未 mock 时 VIDEO_API_KEY 与原始导入一致
        self.assertEqual(config.VIDEO_API_KEY, config.get("VIDEO_API_KEY"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
