#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开放接入（custom / custom-image）实测套件 —— 用本地 mock 证明链路可跑通。

为什么独立成套件、不并入 78 测试主套件：
    - 需要起本地 HTTP mock 服务（线程 + 端口）：主套件是无网络约束的纯本地逻辑；
    - 需要模块级改写环境变量（VIDEO_PROVIDER / API KEY / BASE 等指向 127.0.0.1）：
      主套件各模块在 import 时读取配置，不能混入本套件的 mock 配置；
    - 运行方式（项目根目录，单独跑）：
        python -m unittest tests.test_custom_integration -v

不依赖真实网络：全部请求打向 127.0.0.1 上的 mock 服务（tests/mock_api_server.py）。
不改核心代码：providers/、workflow.py、config.py 等零改动；
    - 环境变量覆盖配置（os.environ 优先于 .env，不碰真实 .env 文件）；
    - 数据库重定向到临时文件（不污染 data/video_jobs.db）；
    - 能力参数用 mock.patch 模拟「已在 models.json 回填能力」的 custom 模型
      （否则 custom 条目全 null → chinese_prompt=未知 会按保守策略拦截所有任务，
      详见 docs/PROVIDERS.md 第五节）。
"""
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ---------- Windows GBK 兼容：控制台输出统一 UTF-8 ----------
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


def _pick_free_port() -> int:
    """取一个当前空闲的本地端口（bind 0 自动分配后释放，供 mock 服务使用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# =====================================================================
# 模块级准备：必须在导入 ecommerce_video 之前设置环境变量
# （config.py 在 import 时读取环境变量；os.environ 优先于 .env，不污染真实 .env）
# =====================================================================
_MOCK_PORT = _pick_free_port()
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="ecom_mock_"))
_MOCK_BASE = f"http://127.0.0.1:{_MOCK_PORT}/v1"

os.environ.update({
    # 视频：custom（OpenAI 兼容）→ 配置键为 CUSTOM_API_KEY / CUSTOM_API_BASE / CUSTOM_MODEL
    "VIDEO_PROVIDER": "custom",
    "CUSTOM_API_KEY": "mock-test-key",
    "CUSTOM_API_BASE": _MOCK_BASE,
    "CUSTOM_MODEL": "mock-video-model",
    # 生图：custom-image → API_KEY/API_BASE 走通用键；MODEL 键为 CUSTOM-IMAGE_MODEL
    "IMAGE_PROVIDER": "custom-image",
    "IMAGE_API_KEY": "mock-test-key",
    "IMAGE_API_BASE": _MOCK_BASE,
    "CUSTOM-IMAGE_MODEL": "mock-image-model",
    # 视觉识别 + 提示词 LLM：都走 mock 的 /v1/chat/completions
    "VISION_API_KEY": "mock-test-key",
    "VISION_API_BASE": _MOCK_BASE,
    "VISION_MODEL": "mock-vision-model",
    "TEXT_LLM_API_KEY": "mock-test-key",
    "TEXT_LLM_API_BASE": _MOCK_BASE,
    "TEXT_LLM_MODEL": "mock-llm-model",
    # 产物与网络：输出到临时目录；关闭代理；本地 mock 无需重试
    "OUTPUT_DIR": str(_TMP_ROOT / "output"),
    "HTTP_PROXY": "",
    "HTTPS_PROXY": "",
    "API_TIMEOUT_SECONDS": "30",
    "API_MAX_RETRIES": "0",
    "API_RETRY_INTERVAL_SECONDS": "1",
})

# 再导入项目代码（此时 config 已读到上面的 mock 配置）
from tests.mock_api_server import MockApiServer  # noqa: E402
from ecommerce_video import capability, config, db  # noqa: E402
from ecommerce_video.providers import get_image_provider, get_provider  # noqa: E402
from ecommerce_video.workflow import Workflow  # noqa: E402


# custom 模型「已回填」后的能力（模拟用户在 models.json 回填能力参数；
# 不回填时全 null → 保守默认 chinese_prompt=未知 会拦截所有任务）
_MOCK_CUSTOM_CAPS = {
    "ref_images": 1,
    "duration_min": 1,
    "duration_max": 10,
    "resolutions": ["480p", "720p", "1080p"],
    "image_to_video": True,
    "text_to_video": True,
    "chinese_prompt": "原生优",
    "multi_ref_supported": False,
    "need_composite": True,
    "consistency_strength": "未知",
}


class CustomOpenAccessTest(unittest.TestCase):
    """custom 开放接入实测：全部请求走 127.0.0.1 mock，不触真实网络。"""

    @classmethod
    def setUpClass(cls):
        # 1) 启动本地 mock 服务（线程，端口 = 模块级预选端口）
        cls.server = MockApiServer(port=_MOCK_PORT).start()
        # 2) 数据库重定向到临时文件（不污染项目 data/video_jobs.db）
        cls._db_orig = (db.DB_PATH, db.SCHEMA)
        db.DB_PATH = _TMP_ROOT / "data" / "video_jobs.db"
        db.SCHEMA = PROJECT_ROOT / "data" / "schema.sql"  # 沿用真实 schema
        db.init_db()
        # 3) 能力补丁：custom → 按「已回填 models.json」处理；其余模型走原逻辑
        cls._orig_get_cap = capability.get_model_capability

        def fake_get_model_capability(provider_id=""):
            pid = (provider_id or "").strip().lower() or config.VIDEO_PROVIDER
            if pid == "custom":
                return {"provider": "custom",
                        "capabilities": dict(_MOCK_CUSTOM_CAPS),
                        "source": "models.json", "warning": ""}
            return cls._orig_get_cap(provider_id)

        cls._cap_patch = mock.patch("ecommerce_video.capability.get_model_capability",
                                    side_effect=fake_get_model_capability)
        cls._cap_patch.start()
        cls.addClassCleanup(cls._cleanup)

    @classmethod
    def _cleanup(cls):
        """恢复现场：停补丁 → 还原数据库路径 → 停 mock → 删临时目录。"""
        try:
            cls._cap_patch.stop()
        except Exception:
            pass
        db.DB_PATH, db.SCHEMA = cls._db_orig
        try:
            cls.server.stop()
        except Exception:
            pass
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)

    # =================================================================
    # a. custom 视频 provider：创建 + 查询任务
    # =================================================================
    def test_custom_video_provider_create_and_query(self):
        """a. get_provider('custom')：create_task 返回 mock 任务 id；query_task 返回 succeeded+url。"""
        provider = get_provider("custom")
        tid = provider.create_task(
            prompt="模特身穿香槟色缎面吊带连衣裙，在大理石美术馆中转身",
            ref_images=["http://127.0.0.1:1/ref.png"],  # 仅作 JSON 字段，mock 不下载
            duration=5, resolution="1080p", aspect_ratio="9:16",
            negative_prompt="形变扭曲", ctx={})
        self.assertTrue(tid.startswith("mock-task-"), f"应返回 mock 任务 id，实际: {tid}")
        data = provider.query_task(tid, {})
        self.assertEqual(data.get("status"), "succeeded")
        url = provider.extract_url(data)
        self.assertIsNotNone(url, "应从查询结果提取到视频 URL")
        self.assertTrue(url.endswith("/out.mp4"), f"应指向 mock 视频 URL: {url}")

    # =================================================================
    # b. custom-image 生图：生成 + 下载
    # =================================================================
    def test_custom_image_provider_generate_and_download(self):
        """b. get_image_provider('custom-image')：generate 返回 mock url，download 落盘非空。"""
        provider = get_image_provider("custom-image")
        # 文生图：POST /v1/images/generations
        url = provider.generate("香槟色缎面连衣裙商品图", [], "1024x1024", {})
        self.assertTrue(url.endswith("/out.png"), f"应指向 mock 图片 URL: {url}")
        # 有参考图时先试 /images/edits（mock 同样支持）→ 仍返回 url
        url2 = provider.generate("参考图融合测试",
                                 ["http://127.0.0.1:1/ref.png"], "1024x1024", {})
        self.assertTrue(url2.endswith("/out.png"), f"edits 路径应返回 mock URL: {url2}")
        # 下载验证：落盘到本用例临时子目录，断言文件存在且非空
        work = _TMP_ROOT / "case_b"
        work.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        save = provider.download(url, work / "out.png")
        self.assertTrue(save.exists(), "下载文件应存在")
        self.assertGreater(save.stat().st_size, 0, "下载文件不应为空")

    # =================================================================
    # c. Workflow 端到端全链路（核心用例）
    # =================================================================
    @staticmethod
    def _make_storyboard() -> dict:
        return {
            "project": "mockproj",
            "sku": "msku1",
            "category": "clothing",
            "sku_desc": "香槟色缎面吊带连衣裙",
            "material": "缎面",
            "model_desc": "25岁气质优雅亚裔女性",
            "type": "tvc",
            "shots": [
                {"shot_no": 1, "scene": "大理石美术馆", "light": "柔光箱+暖色轮廓光",
                 "lens": "35mm全景", "move": "缓慢推近", "action": "转身360度",
                 "motion": "裙摆甩动液态光泽", "duration": 5},
            ],
        }

    def test_workflow_end_to_end(self):
        """c. Workflow(provider='custom') 全链路：词源→LLM提示词→能力校验→生成→下载（全走 mock）。"""
        w = Workflow(project="mockproj", sku="msku1", category="clothing",
                     material="缎面", type_name="tvc", provider="custom")
        sb = self._make_storyboard()

        # 阶段2：词源检索（本地知识库，无网络）
        src = w.retrieve_sources(sb["shots"])
        self.assertIn("per_shot", src)
        ps = src["per_shot"]
        self.assertTrue(ps.get(1) or ps.get("1"), "镜1 应有词源命中")

        # 阶段3：提示词生成（LLM 走 mock /v1/chat/completions）
        result = w.generate_prompts(sb)
        self.assertEqual(result["issues"], [], f"规则校验应通过: {result['issues']}")
        jobs = result["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertIn("与参考图完全一致", jobs[0]["prompt"])

        # 阶段4：能力校验（custom 已回填能力 → 应全通过）
        issues = w.validate_against_capability(jobs)
        self.assertEqual(issues, [], f"能力校验应通过: {issues}")

        # 阶段5：生成 + 下载（视频走 mock，产物落在临时 OUTPUT_DIR）
        out = w.generate(jobs, version_count=1)
        self.assertEqual(out["failed"], [], f"不应有失败任务: {out['failed']}")
        self.assertEqual(len(out["done"]), 1, f"应产出 1 个视频: {out}")
        video_path = Path(out["done"][0])
        self.assertTrue(video_path.exists(), f"视频文件应存在: {video_path}")
        self.assertGreater(video_path.stat().st_size, 0, "视频文件不应为空")
        self.addCleanup(video_path.unlink, missing_ok=True)

    # =================================================================
    # d. Workflow.recognize：视觉识别走 mock LLM
    # =================================================================
    def test_workflow_recognize_via_mock_llm(self):
        """d. Workflow.recognize：多模态识别走 mock chat/completions，merged 报告可解析。"""
        ref = _TMP_ROOT / "ref_white.png"
        ref.write_bytes(b"fake-png-bytes-for-recognize")
        self.addCleanup(ref.unlink, missing_ok=True)
        w = Workflow(provider="custom", category="clothing")
        result = w.recognize([str(ref)])
        self.assertEqual(result["errors"], {}, f"单图识别不应失败: {result['errors']}")
        merged = result["merged"]
        self.assertEqual(merged["category"], "连衣裙")
        self.assertEqual(merged["primary_color"], "香槟色")
        self.assertEqual(merged["material_inference"]["value"], "缎面")


if __name__ == "__main__":
    unittest.main(verbosity=2)
