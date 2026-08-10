#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 契约测试（P1-3 修复：包级导出 list_image_providers + gen 输出注入三字段）。

运行：python -m unittest tests.test_cli -v   （从项目根目录）

覆盖：
  1. from ecommerce_video import list_image_providers 可用，返回生图注册名列表
  2. cmd_gen 从 storyboard 顶层带出 project/sku/category 注入 jobs（LLM 全 mock，零网络）
  3. cmd_gen 用 --project/--sku/--category 参数注入（storyboard 缺字段时）
  4. 三字段都缺 → 明确报错且退出非零（绝不静默生成无法导入的 jobs）
  5. 注入三字段后的 jobs 通过 validate_jobs 规则校验（复用现有校验函数）

零第三方依赖（unittest + mock）；不真写 data/video_jobs.db（cmd_gen 本身不落库，
本套件也绝不调用 import/run 等数据库命令）；不改任何核心模块。
"""
import contextlib
import io
import json
import sys
import tempfile
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

from ecommerce_video import cli, config  # noqa: E402
from ecommerce_video.prompt_engine import validate_jobs  # noqa: E402


# 假 LLM 响应（纯中文、符合规则校验红线，避免任何网络调用）
FAKE_LLM_JOBS = [
    {
        "shot_no": 1,
        "prompt": "25岁气质温柔女性，酒红色麻花针织衫，与参考图完全一致。旧街道咖啡店场景，暖黄灯光柔和洒落，中景，固定机位。模特倚窗而立，针织纹理在暖光中呈现细腻立体感。暖色调胶片颗粒，复古怀旧氛围。",
        "negative_prompt": "形变扭曲,多余肢体,手指变形,水印,画面文字,皮肤光滑,塑料感,过度磨皮,画面模糊,穿帮",
        "ref_images": ["refs/demo/sku1/01_white.jpg"],
        "duration_sec": 5,
        "version_count": 1,
    },
    {
        "shot_no": 2,
        "prompt": "25岁气质温柔女性，酒红色麻花针织衫，与参考图完全一致。秋日街头场景，黄昏暖光铺洒，全景，跟拍。模特自然行走，针织衫随步伐自然摆动，针织纹理在暖光中呈现立体肌理。暖色调胶片颗粒，复古怀旧氛围。",
        "negative_prompt": "形变扭曲,多余肢体,手指变形,水印,画面文字,皮肤光滑,塑料感,过度磨皮,画面模糊,穿帮",
        "ref_images": ["refs/demo/sku1/01_white.jpg"],
        "duration_sec": 5,
        "version_count": 1,
    },
]


def _make_storyboard(with_fields: bool = True) -> dict:
    """demo_storyboard.json 同构分镜；with_fields=False 时去掉三字段（模拟缺字段场景）。"""
    sb = {
        "sku_desc": "酒红色麻花针织衫",
        "material": "针织毛线",
        "model_desc": "25岁气质温柔的女性",
        "type": "复古胶片风",
        "shots": [
            {"shot_no": 1, "scene": "旧街道咖啡店", "light": "暖黄灯光", "lens": "中景",
             "move": "固定", "action": "倚窗而立", "motion": "针织纹理在暖光中显质感",
             "duration": 5},
            {"shot_no": 2, "scene": "秋日街头", "light": "黄昏暖光", "lens": "全景",
             "move": "跟拍", "action": "自然行走", "motion": "针织衫随步伐自然摆动",
             "duration": 5},
        ],
    }
    if with_fields:
        sb.update({"project": "demo", "sku": "knit_sweater", "category": "clothing"})
    return sb


class ListImageProvidersExportTest(unittest.TestCase):
    """P1-3a：包级导出 list_image_providers（README 承诺的查询入口）。"""

    def test_import_from_package_root(self):
        from ecommerce_video import list_image_providers  # 包级导出（修复前 ImportError）
        names = sorted(list_image_providers())
        for expected in ("custom-image", "agnes-image", "openai", "seedance", "agnes"):
            self.assertIn(expected, names,
                          f"生图注册名应含 {expected}，实际: {names}")

    def test_is_package_level_export(self):
        import ecommerce_video
        self.assertIn("list_image_providers", ecommerce_video.__all__)


class CmdGenFieldInjectionTest(unittest.TestCase):
    """P1-3b：cmd_gen 输出 jobs 注入 project/sku/category（LLM 全 mock，零网络）。"""

    def _run_gen(self, sb: dict, extra_args: tuple = ()) -> list:
        """跑 cli.main(['gen', sb, '-o', jobs, *extra_args])，返回注入后的 jobs 列表。"""
        with tempfile.TemporaryDirectory(prefix="ecom_cli_") as td:
            td = Path(td)
            sb_path = td / "storyboard.json"
            out_path = td / "jobs.json"
            sb_path.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")
            argv = ["gen", str(sb_path), "-o", str(out_path)] + list(extra_args)
            with mock.patch("ecommerce_video.prompt_engine.call_llm",
                            return_value=json.dumps(FAKE_LLM_JOBS, ensure_ascii=False)), \
                 mock.patch.object(config, "TEXT_LLM_API_KEY", "test-key"):
                rc = cli.main(argv)
            self.assertEqual(rc, 0, "gen 应正常退出 0")
            return json.loads(out_path.read_text(encoding="utf-8"))

    def test_storyboard_fields_carried_into_jobs(self):
        """storyboard 顶层含三字段 → 直接带出注入每条 job（LLM 输出被 mock）。"""
        jobs = self._run_gen(_make_storyboard(with_fields=True))
        self.assertEqual(len(jobs), 2)
        for j in jobs:
            self.assertEqual(j["project"], "demo")
            self.assertEqual(j["sku"], "knit_sweater")
            self.assertEqual(j["category"], "clothing")
            # LLM 输出原样保留（证明只补字段、不改提示词）
            self.assertEqual(j["prompt"], FAKE_LLM_JOBS[j["shot_no"] - 1]["prompt"])

    def test_cli_args_injected_when_storyboard_missing(self):
        """storyboard 缺三字段 → --project/--sku/--category 命令行注入。"""
        jobs = self._run_gen(
            _make_storyboard(with_fields=False),
            ("--project", "projX", "--sku", "skuX", "--category", "clothing"),
        )
        self.assertEqual(len(jobs), 2)
        for j in jobs:
            self.assertEqual(j["project"], "projX")
            self.assertEqual(j["sku"], "skuX")
            self.assertEqual(j["category"], "clothing")

    def test_cli_args_fill_partial_missing_fields(self):
        """storyboard 部分缺字段 → 命令行只补齐缺失项（已有字段不被覆盖）。"""
        sb = _make_storyboard(with_fields=False)
        sb["project"] = "projA"  # 只缺 sku/category
        jobs = self._run_gen(sb, ("--sku", "skuB", "--category", "clothing"))
        for j in jobs:
            self.assertEqual(j["project"], "projA")
            self.assertEqual(j["sku"], "skuB")
            self.assertEqual(j["category"], "clothing")

    def test_all_fields_missing_exits_nonzero(self):
        """三字段都缺 → 明确中文报错、退出非零、不生成 jobs 文件。"""
        sb = _make_storyboard(with_fields=False)
        with tempfile.TemporaryDirectory(prefix="ecom_cli_") as td:
            td = Path(td)
            sb_path = td / "storyboard.json"
            out_path = td / "jobs.json"
            sb_path.write_text(json.dumps(sb, ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with mock.patch("ecommerce_video.prompt_engine.call_llm") as fake_llm:
                with contextlib.redirect_stdout(buf):
                    with self.assertRaises(SystemExit) as ctx:
                        cli.main(["gen", str(sb_path), "-o", str(out_path)])
            self.assertNotEqual(ctx.exception.code, 0, "缺字段应退出非零")
            fake_llm.assert_not_called()  # 报错在 LLM 调用之前
            self.assertFalse(out_path.exists(), "不应静默生成 jobs 文件")
            msg = buf.getvalue()
            for field in ("project", "sku", "category"):
                self.assertIn(field, msg, f"报错信息应提示缺 {field}")

    def test_injected_jobs_pass_validate(self):
        """注入三字段后的 jobs 通过 validate_jobs 规则校验（复用现有校验函数）。"""
        jobs = self._run_gen(_make_storyboard(with_fields=True))
        issues = validate_jobs(jobs, _make_storyboard(with_fields=True))
        self.assertEqual(issues, [], f"jobs 应通过规则校验: {issues}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
