#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力感知模块测试（战役2：models.json 能力参数运行时生效）。

运行：python -m unittest tests.test_capability -v   （从项目根目录）

契约（见 scripts/capability.py）：
    get_model_capability(provider_id) -> {provider, capabilities, source, warning}
    validate_job(job, capability=None) -> issues 列表（空 = 通过）
    flow_adjustments(capability) -> 流程适配建议 dict

约束：仅读本地 knowledge/models.json，无网络、无第三方依赖。
"""
import sys
import unittest
from pathlib import Path

# Windows GBK 兼容：测试名/skip 消息含中文，stdout/stderr 统一重配 UTF-8（与 scripts/capability.py 同款做法）
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

from ecommerce_video import capability  # noqa: E402


class TestGetModelCapability(unittest.TestCase):
    """1. get_model_capability：按 provider_id 返回模型能力（source 标注来源）。"""

    def test_seedance20_from_models_json(self):
        r = capability.get_model_capability("seedance-2.0")
        self.assertEqual(r["source"], "models.json")
        self.assertEqual(r["provider"], "seedance-2.0")
        self.assertEqual(r["capabilities"]["ref_images"], 9)
        self.assertEqual(r["capabilities"]["duration_max"], 15)
        self.assertEqual(r["capabilities"]["duration_min"], 4)
        self.assertTrue(r["capabilities"]["multi_ref_supported"])

    def test_unknown_falls_back_to_default(self):
        r = capability.get_model_capability("不存在的模型xyz")
        self.assertEqual(r["source"], "default")
        self.assertTrue(r["warning"], "降级时应给出非空 warning 说明")
        self.assertIn("保守默认", r["warning"])
        # 降级能力 = 保守默认（ref_images=1 / duration_max=10）
        self.assertEqual(r["capabilities"]["ref_images"], 1)
        self.assertEqual(r["capabilities"]["duration_max"], 10)

    def test_empty_provider_uses_default(self):
        # provider_id 为空 → 自动取当前 provider（不抛异常，必有返回值）
        r = capability.get_model_capability("")
        self.assertIn(r["source"], ("models.json", "default"))
        self.assertIn("capabilities", r)

    def test_family_prefix_match(self):
        # "seedance" 前缀做家族匹配 → 命中 seedance 系（default_model 优先）
        r = capability.get_model_capability("seedance")
        self.assertEqual(r["source"], "models.json")
        self.assertEqual(r["provider"], "seedance-2.0")
        self.assertEqual(r["capabilities"]["ref_images"], 9)


class TestValidateJob(unittest.TestCase):
    """2. validate_job：按模型能力校验任务，超限给出明确问题。"""

    SEEDANCE_CAPS = None  # 延迟到 setUpClass 装载

    @classmethod
    def setUpClass(cls):
        cls.SEEDANCE_CAPS = capability.get_model_capability("seedance-2.0")["capabilities"]

    def test_duration_over_limit(self):
        # duration_sec=30 > seedance-2.0 duration_max=15
        issues = capability.validate_job({"duration_sec": 30}, self.SEEDANCE_CAPS)
        joined = " | ".join(issues)
        self.assertTrue(any("超过模型上限" in i for i in issues), f"应提示超上限: {joined}")

    def test_duration_below_minimum(self):
        issues = capability.validate_job({"duration_sec": 2}, self.SEEDANCE_CAPS)
        self.assertTrue(any("低于模型下限" in i for i in issues),
                        f"应提示低于下限: {issues}")

    def test_ref_images_over_limit(self):
        # ref_images=10 > seedance-2.0 ref_images=9
        issues = capability.validate_job({"ref_images": ["a"] * 10}, self.SEEDANCE_CAPS)
        self.assertTrue(any("超过模型上限" in i for i in issues),
                        f"应提示参考图超上限: {issues}")

    def test_resolution_not_supported(self):
        issues = capability.validate_job({"resolution": "4K"}, self.SEEDANCE_CAPS)
        self.assertTrue(any("不在支持列表" in i for i in issues),
                        f"应提示分辨率不支持: {issues}")

    def test_multi_ref_not_supported(self):
        # 模型 multi_ref_supported=False + 实际多图 → 需走 S 合成阶段
        caps = {"ref_images": 9, "duration_min": 1, "duration_max": 15,
                "resolutions": ["1080p"], "image_to_video": True,
                "chinese_prompt": "原生优", "multi_ref_supported": False}
        issues = capability.validate_job({"ref_images": ["a", "b"]}, caps)
        self.assertTrue(any("S合成" in i for i in issues),
                        f"应提示需走S合成阶段: {issues}")

    def test_valid_job_passes(self):
        # 全部合规 → 空问题列表
        issues = capability.validate_job({
            "duration_sec": 10, "ref_images": ["a"], "resolution": "1080p",
        }, self.SEEDANCE_CAPS)
        self.assertEqual(issues, [])

    def test_capability_none_uses_current_provider(self):
        # capability=None → 自动取当前 provider 能力，不抛异常
        issues = capability.validate_job({"duration_sec": 10})
        self.assertIsInstance(issues, list)

    def test_full_return_capability_compat(self):
        # 支持直接传 get_model_capability 的完整返回（含 capabilities 键）
        full = capability.get_model_capability("seedance-2.0")
        issues = capability.validate_job({"duration_sec": 30}, full)
        self.assertTrue(any("超过模型上限" in i for i in issues))

    def test_non_dict_job(self):
        issues = capability.validate_job("not-a-dict")
        self.assertTrue(issues, "非 dict 任务应给出问题")


class TestFlowAdjustments(unittest.TestCase):
    """3. flow_adjustments：按能力返回流程适配建议。"""

    def test_seedance20_adjustments(self):
        # 任务中的 'seedance-2.0' 指该模型能力（flow_adjustments 入参契约 = 能力 dict）
        caps = capability.get_model_capability("seedance-2.0")["capabilities"]
        adj = capability.flow_adjustments(caps)
        self.assertEqual(adj["ref_images_limit"], 9)
        self.assertEqual(adj["duration_max"], 15)
        self.assertEqual(adj["duration_min"], 4)
        self.assertFalse(adj["needs_composite"], "seedance-2.0 支持多参考图，无需 S 合成")

    def test_full_return_compat(self):
        # 直接传 get_model_capability 完整返回同样兼容
        adj = capability.flow_adjustments(capability.get_model_capability("seedance-2.0"))
        self.assertEqual(adj["ref_images_limit"], 9)
        self.assertFalse(adj["needs_composite"])

    def test_conservative_default(self):
        # 空能力 → 保守默认（ref_images=1 / needs_composite=True）
        adj = capability.flow_adjustments({})
        self.assertEqual(adj["ref_images_limit"], 1)
        self.assertEqual(adj["duration_max"], 10)
        self.assertTrue(adj["needs_composite"])

    def test_returns_required_keys(self):
        adj = capability.flow_adjustments(capability.get_model_capability("seedance-2.0"))
        for key in ("ref_images_limit", "duration_max", "duration_min",
                    "needs_composite", "chinese_advice", "shot_count_advice"):
            self.assertIn(key, adj, f"flow_adjustments 缺返回键: {key}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
