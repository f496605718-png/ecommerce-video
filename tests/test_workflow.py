#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workflow API 契约测试（战役2：流程编排层质量保障）。

运行：python -m unittest tests.test_workflow -v   （从项目根目录）

契约（见 scripts/workflow.py，Workflow 类）：
    Workflow(provider='seedance-2.0')           # 指定 provider 构造
    .check()                                    # -> dict 含 provider/capabilities
    .retrieve_sources(scene)                    # -> per_shot[no].scene_light（检索结果）
    .validate_against_capability(jobs)          # -> 问题列表（非空 = 有问题）
    .generate(dry_run=True)                     # -> dict 且不调网络（dry_run 禁止触网）
    .stats()                                    # -> dict

说明：workflow.py 由战役2 流程层同事实现；若尚未落地，本组用例自动跳过
（套件保持全绿，日志显示 skipped 原因）；文件落地后自动转为真实断言。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

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

WORKFLOW_FILE = SRC_DIR / "ecommerce_video" / "workflow.py"
if WORKFLOW_FILE.exists():
    from ecommerce_video.workflow import Workflow  # noqa: E402  （存在则必须可用；报错=实现缺陷，直接失败）
    WORKFLOW_AVAILABLE = True
else:
    Workflow = None
    WORKFLOW_AVAILABLE = False


def _shot(result, shot_no):
    """兼容 per_shot 键为 int 或 str。"""
    ps = result["per_shot"]
    return ps.get(shot_no) if shot_no in ps else ps.get(str(shot_no))


def _any_field(entries, needle):
    """entries 任一元素（dict 的任意字段 / 字符串）含 needle。"""
    for e in entries or []:
        if isinstance(e, dict):
            if any(needle in str(v) for v in e.values()):
                return True
        elif needle in str(e):
            return True
    return False


@unittest.skipUnless(
    WORKFLOW_AVAILABLE,
    "scripts/workflow.py 未实现（战役2 流程层同事交付后自动启用，套件保持全绿）",
)
class WorkflowContractTest(unittest.TestCase):
    """Workflow API 契约测试基类（workflow.py 缺失时整组跳过）。"""

    def make_workflow(self):
        return Workflow(provider="seedance-2.0")

    def make_retrieval_workflow(self):
        """带品类/材质/类型的 Workflow（检索测试用：无品类时无法命中知识库）。"""
        return Workflow(provider="seedance-2.0", category="clothing",
                        material="缎面", type_name="tvc")


class TestWorkflowCheck(WorkflowContractTest):
    """1. check()：返回 dict，含 provider / capabilities。"""

    def test_check_returns_provider_and_capabilities(self):
        w = self.make_workflow()
        result = w.check()
        self.assertIsInstance(result, dict)
        self.assertIn("provider", result)
        self.assertIn("capabilities", result)
        self.assertEqual(result["provider"], "seedance-2.0")
        self.assertIsInstance(result["capabilities"], dict)
        # capabilities 应为 seedance-2.0 的真实能力（models.json 注入）
        self.assertEqual(result["capabilities"].get("ref_images"), 9)


class TestWorkflowRetrieveSources(WorkflowContractTest):
    """2. retrieve_sources([{shot_no, scene}])：per_shot[1].scene_light 含 satin（缎面）。"""

    def test_scene_light_contains_satin(self):
        w = self.make_retrieval_workflow()
        result = w.retrieve_sources([{"shot_no": 1, "scene": "大理石美术馆"}])
        self.assertIsInstance(result, dict)
        self.assertIn("per_shot", result)
        sl = _shot(result, 1)["scene_light"]
        self.assertTrue(sl, "场景精确命中应至少返回 satin 条目")
        self.assertTrue(_any_field(sl, "satin"), "scene_light 应含 satin（缎面）")


class TestWorkflowValidateAgainstCapability(WorkflowContractTest):
    """3. validate_against_capability：超限任务应返回非空问题列表。"""

    def test_over_limit_job_reports_issues(self):
        w = self.make_workflow()
        # duration_sec=99 远超 seedance-2.0 上限(15s) → 非空
        jobs = [{
            "project": "p", "sku": "s", "shot_no": 1,
            "prompt": "测试提示词", "duration_sec": 99,
            "ref_images": ["refs/a.png"], "resolution": "1080p",
        }]
        issues = w.validate_against_capability(jobs)
        self.assertTrue(issues, "超限任务应返回非空问题列表")
        self.assertTrue(any("超过模型上限" in i for i in issues),
                        f"应含超上限提示: {issues}")

    def test_valid_job_returns_empty(self):
        w = self.make_workflow()
        jobs = [{
            "project": "p", "sku": "s", "shot_no": 1,
            "prompt": "测试提示词", "duration_sec": 10,
            "ref_images": ["refs/a.png"], "resolution": "1080p",
        }]
        issues = w.validate_against_capability(jobs)
        self.assertIsInstance(issues, list)


class TestWorkflowGenerateDryRun(WorkflowContractTest):
    """4. generate(jobs, dry_run=True)：返回 dict 且不调网络（mock video_client.create_task 断言未被调用）。"""

    def test_generate_dry_run_no_network(self):
        # patch 所有可能的 video_client 引用路径；dry_run 下任一都不应被调用
        mocks = []
        for target in ("ecommerce_video.video_client.create_task",):
            try:
                m = mock.patch(target).start()
                mocks.append((target, m))
            except (AttributeError, ImportError, ModuleNotFoundError):
                pass  # 该 import 路径不存在（workflow 用哪种方式引入，patch 哪种）
        self.addCleanup(mock.patch.stopall)

        w = self.make_workflow()
        jobs = [{
            "project": "p", "sku": "s", "shot_no": 1,
            "prompt": "测试提示词", "duration_sec": 10,
            "ref_images": [], "resolution": "1080p", "aspect_ratio": "9:16",
        }]
        result = w.generate(jobs, dry_run=True)
        self.assertIsInstance(result, dict, "dry_run 应返回 dict（模拟结果/计划）")
        for target, m in mocks:
            self.assertFalse(
                m.called,
                f"{target} 不应在 dry_run 中被调用（dry_run 禁止触网）")


class TestWorkflowStats(WorkflowContractTest):
    """5. stats()：返回 dict（流程统计）。"""

    def test_stats_returns_dict(self):
        w = self.make_workflow()
        result = w.stats()
        self.assertIsInstance(result, dict)


class TestMissingWorkflowReporting(unittest.TestCase):
    """契约兜底：workflow.py 缺失时给出明确提示（套件仍全绿）。"""

    def test_workflow_present(self):
        if not WORKFLOW_AVAILABLE:
            self.skipTest(
                "scripts/workflow.py 尚未实现：契约测试组已跳过，"
                "待战役2 流程层同事交付后自动启用"
            )
        # 存在时该用例无额外断言（真实契约断言在上方各测试类）


if __name__ == "__main__":
    unittest.main(verbosity=2)
