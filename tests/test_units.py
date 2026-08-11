#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成单元规划器测试（P3：开放选项——一镜一提交 / 合并提交+AI切分）。

运行：python -m unittest tests.test_units -v   （从项目根目录）

覆盖：
  - per-shot 透传（行为与旧版一致）
  - merge 合并：总时长 ≤ 上限 → 1 条
  - merge 切分：超限 → 贪心兜底分组（不打断单镜、每段 ≤ 上限）
  - 上限钳制：min(用户值, 模型 duration_max)
  - LLM 融合提示词（mock call_llm）
  - LLM 切分点判定（mock call_llm 返回 groups JSON）与失败兜底
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

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

from ecommerce_video import units  # noqa: E402


def _job(no, dur, prompt=None):
    return {
        "shot_no": no, "project": "p", "sku": "s", "category": "clothing",
        "prompt": prompt or f"镜{no}提示词与参考图完全一致",
        "negative_prompt": "负面词", "duration_sec": dur, "version_count": 1,
    }


JOBS = [_job(1, 3), _job(2, 3), _job(3, 4), _job(4, 2), _job(5, 2)]  # 合计 14s
CAPS = {"duration_max": 18, "duration_min": 1}


class TestPerShot(unittest.TestCase):
    def test_passthrough(self):
        r = units.plan_units(JOBS, strategy="per-shot", capabilities=CAPS)
        self.assertEqual(r["strategy"], "per-shot")
        self.assertEqual(len(r["units"]), 5)
        # 每单元 = 原 job 加 unit_no/shots，prompt 不变
        self.assertEqual(r["units"][0]["prompt"], JOBS[0]["prompt"])
        self.assertEqual(r["units"][0]["unit_no"], 1)
        self.assertEqual(r["units"][0]["shots"], [1])

    def test_max_seconds_respected(self):
        r = units.plan_units(JOBS, strategy="per-shot", max_seconds=7, capabilities=CAPS)
        self.assertEqual(r["max_seconds"], 7)


class TestMerge(unittest.TestCase):
    def test_merge_all_within_cap(self):
        # 上限 14 → 全合并 1 条
        r = units.plan_units(JOBS, strategy="merge", max_seconds=14, llm=False, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 1)
        u = r["units"][0]
        self.assertEqual(u["duration_sec"], 14)
        self.assertEqual(u["shots"], [1, 2, 3, 4, 5])
        # 拼接式提示词（llm=False）
        self.assertIn("镜1提示词", u["prompt"])
        self.assertIn("镜5提示词", u["prompt"])

    def test_split_greedy_when_over_cap(self):
        # 上限 10，总 14s → 贪心切 2 段：1+2+3=10 / 4+5=4
        r = units.plan_units(JOBS, strategy="merge", max_seconds=10, llm=False, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 2)
        self.assertEqual(r["units"][0]["duration_sec"], 10)
        self.assertEqual(r["units"][0]["shots"], [1, 2, 3])
        self.assertEqual(r["units"][1]["duration_sec"], 4)
        self.assertEqual(r["units"][1]["shots"], [4, 5])

    def test_no_split_within_cap_even_llm_off(self):
        r = units.plan_units(JOBS[:2], strategy="merge", max_seconds=6, llm=False, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 1)
        self.assertEqual(r["units"][0]["duration_sec"], 6)

    def test_ref_images_inherited_from_first(self):
        jobs = list(JOBS)
        jobs[0]["ref_images"] = ["composite.png"]
        r = units.plan_units(jobs, strategy="merge", max_seconds=14, llm=False, capabilities=CAPS)
        self.assertEqual(r["units"][0]["ref_images"], ["composite.png"])


class TestCapClamp(unittest.TestCase):
    def test_min_with_model_duration_max(self):
        # 用户给 20，模型上限 18 → 生效 18
        r = units.plan_units(JOBS, strategy="per-shot", max_seconds=20,
                             capabilities={"duration_max": 18})
        self.assertEqual(r["max_seconds"], 18)

    def test_no_model_cap_fallback_user(self):
        r = units.plan_units(JOBS, strategy="per-shot", max_seconds=12, capabilities={})
        self.assertEqual(r["max_seconds"], 12)


class TestLLM(unittest.TestCase):
    def test_llm_merge_prompt(self):
        jobs = JOBS[:2]
        with mock.patch("ecommerce_video.prompt_engine.call_llm",
                        return_value="一条连贯的开箱视频提示词，与参考图完全一致"):
            r = units.plan_units(jobs, strategy="merge", max_seconds=6, llm=True, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 1)
        self.assertEqual(r["units"][0]["prompt"], "一条连贯的开箱视频提示词，与参考图完全一致")

    def test_llm_merge_failure_falls_back_to_concat(self):
        jobs = JOBS[:2]
        with mock.patch("ecommerce_video.prompt_engine.call_llm", side_effect=RuntimeError("boom")):
            r = units.plan_units(jobs, strategy="merge", max_seconds=6, llm=True, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 1)
        self.assertIn("镜1提示词", r["units"][0]["prompt"])
        self.assertIn("镜2提示词", r["units"][0]["prompt"])

    def test_llm_split_groups(self):
        # LLM 判定切分：[[1,2],[3,4,5]] → 6s / 8s（均 ≤ 10）
        with mock.patch("ecommerce_video.prompt_engine.call_llm",
                        return_value='{"groups": [[1, 2], [3, 4, 5]]}'):
            r = units.plan_units(JOBS, strategy="merge", max_seconds=10, llm=True, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 2)
        self.assertEqual(r["units"][0]["shots"], [1, 2])
        self.assertEqual(r["units"][1]["shots"], [3, 4, 5])

    def test_llm_split_invalid_falls_back_greedy(self):
        # LLM 返回超限分组（14s > 10s）→ 判定失败 → 贪心兜底 10s + 4s
        with mock.patch("ecommerce_video.prompt_engine.call_llm",
                        return_value='{"groups": [[1, 2, 3, 4, 5]]}'):
            r = units.plan_units(JOBS, strategy="merge", max_seconds=10, llm=True, capabilities=CAPS)
        self.assertEqual(len(r["units"]), 2)  # 贪心：10s + 4s


if __name__ == "__main__":
    unittest.main()
