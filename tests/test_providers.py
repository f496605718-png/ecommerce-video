#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider 协议测试（战役2：接口开放化质量保障）。

运行：python -m unittest tests.test_providers -v   （从项目根目录）

契约（见 scripts/providers/__init__.py、base.py、agnes.py）：
    list_providers() -> [id...]（含别名）；get_provider(id, capabilities=None) -> 实例
    能力注入：get_provider 未显式传 capabilities 时自动读 knowledge/models.json 对应条目
    agnes._frames_for_duration(duration)（8n+1 规则，≤441）；_ratio_to_wh(ratio)
    base._extract_url / VideoProvider.extract_url：递归提取 metadata.url / url 等键

约束：全部用例仅本地逻辑（读本地 models.json / mock 请求），
      绝不发起真实网络调用——末尾有"禁网哨兵"用例兜底。
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

from ecommerce_video.providers import get_provider, list_providers  # noqa: E402
from ecommerce_video.providers.base import VideoGenError, VideoProvider, _extract_url  # noqa: E402
from ecommerce_video.providers.agnes import _frames_for_duration, _ratio_to_wh  # noqa: E402


class TestRegistry(unittest.TestCase):
    """1. 注册表：list_providers() 含 seedance-2.0 / agnes-video / custom 及别名。"""

    def test_list_providers_contains_required(self):
        ids = list_providers()
        for required in ("seedance-2.0", "agnes-video", "custom"):
            self.assertIn(required, ids, f"注册表缺少 provider: {required}")

    def test_list_providers_contains_aliases(self):
        # 别名与注册名同族注册（seedance/agnes 为历史名）
        ids = list_providers()
        for alias in ("seedance", "agnes"):
            self.assertIn(alias, ids, f"注册表缺少别名: {alias}")

    def test_get_provider_returns_instance(self):
        p = get_provider("seedance-2.0")
        self.assertIsInstance(p, VideoProvider)
        self.assertEqual(p.id, "seedance-2.0")
        self.assertIsInstance(p.capabilities, dict)


class TestCapabilityInjection(unittest.TestCase):
    """3. 能力注入：未显式传 capabilities 时按 models.json 对应条目装载。"""

    def test_seedance25_ref_images_30(self):
        # models.json 'seedance-2.5' → ref_images=30（2.5 与 2.0 同族端点、能力不同）
        p = get_provider("seedance-2.5")
        self.assertEqual(p.capabilities["ref_images"], 30)

    def test_agnes_video_ref_images_1(self):
        p = get_provider("agnes-video")
        self.assertEqual(p.capabilities["ref_images"], 1)

    def test_explicit_capabilities_override(self):
        # 显式传入 capabilities 时优先于 models.json（第三方接入可自行注入）
        p = get_provider("seedance-2.0", {"ref_images": 7, "duration_max": 20})
        self.assertEqual(p.capabilities["ref_images"], 7)
        self.assertEqual(p.capabilities["duration_max"], 20)

    def test_unknown_provider_raises(self):
        # 未知 id → 抛 VideoGenError（含清晰提示，绝不静默）
        with self.assertRaises(VideoGenError):
            get_provider("no-such-model-xyz")


class TestAgnesFrameLogic(unittest.TestCase):
    """4. agnes 帧数逻辑：_frames_for_duration 按 8n+1 规则，≤441。"""

    def test_frames_10s(self):
        self.assertEqual(_frames_for_duration(10), 241)

    def test_frames_18s(self):
        self.assertEqual(_frames_for_duration(18), 433)

    def test_frames_overlong_capped_at_441(self):
        # 超长（如 100s）→ 帧数 cap 到 441（Agnes 硬性上限）
        self.assertEqual(_frames_for_duration(100), 441)
        self.assertEqual(_frames_for_duration(999), 441)

    def test_frames_always_8n_plus_1(self):
        # 规则性质：任何合法时长得到的帧数都满足 8n+1 且在 [1, 441]
        for d in (1, 3, 7, 10, 18, 25, 40, 100):
            frames = _frames_for_duration(d)
            self.assertEqual((frames - 1) % 8, 0, f"duration={d} 帧数应满足 8n+1")
            self.assertGreaterEqual(frames, 1)
            self.assertLessEqual(frames, 441)


class TestAgnesRatio(unittest.TestCase):
    """5. agnes 宽高比映射：_ratio_to_wh('9:16') == (768, 1152)。"""

    def test_ratio_9_16(self):
        self.assertEqual(_ratio_to_wh("9:16"), (768, 1152))

    def test_ratio_16_9(self):
        self.assertEqual(_ratio_to_wh("16:9"), (1152, 768))

    def test_ratio_unknown_falls_back(self):
        # 未知比例 → 保守默认 9:16
        self.assertEqual(_ratio_to_wh("21:9"), (768, 1152))
        self.assertEqual(_ratio_to_wh(""), (768, 1152))


class TestExtractUrl(unittest.TestCase):
    """6. 基类 URL 提取：_extract_url 递归找 metadata.url / url 等键。"""

    def test_metadata_url_top_level(self):
        # Agnes 特例：metadata.url 优先
        self.assertEqual(
            _extract_url({"metadata": {"url": "https://cdn/x/v.mp4"}}),
            "https://cdn/x/v.mp4")

    def test_metadata_url_nested(self):
        # 深层嵌套也要找到 metadata.url
        data = {"result": {"task": {"metadata": {"url": "https://cdn/n/v.mp4"}}}}
        self.assertEqual(_extract_url(data), "https://cdn/n/v.mp4")

    def test_url_key_recursive(self):
        self.assertEqual(
            _extract_url({"data": {"video_url": "https://cdn/y/v.mp4"}}),
            "https://cdn/y/v.mp4")

    def test_list_recursion(self):
        self.assertEqual(
            _extract_url([{"a": 1}, {"url": "https://cdn/z/v.mp4"}]),
            "https://cdn/z/v.mp4")

    def test_no_url_returns_none(self):
        self.assertIsNone(_extract_url({"status": "queued", "data": {"id": "t1"}}))
        self.assertIsNone(_extract_url([{"status": "failed"}]))

    def test_non_http_url_ignored(self):
        # 非 http/https 字符串不算视频 URL（如 file:// 或占位文本）
        self.assertIsNone(_extract_url({"url": "file:///tmp/v.mp4"}))

    def test_provider_instance_method(self):
        # 实例方法走同一递归逻辑
        from ecommerce_video.providers.agnes import AgnesVideoProvider
        p = AgnesVideoProvider(provider_id="agnes-video")
        self.assertEqual(
            p.extract_url({"metadata": {"url": "https://cdn/a/v.mp4"}}),
            "https://cdn/a/v.mp4")


class TestCreateTaskLocalLogic(unittest.TestCase):
    """协议请求体组装：mock 掉 _request，验证请求体与 task_id/URL 解析（不触网）。"""

    def test_seedance_task_id_parsing(self):
        with mock.patch("ecommerce_video.providers.seedance._request", return_value={"task_id": "t-123"}):
            from ecommerce_video.providers.seedance import SeedanceProvider
            p = SeedanceProvider(provider_id="seedance-2.0")
            tid = p.create_task("prompt", ["r1"], 5, "1080p", "9:16", "", {})
            self.assertEqual(tid, "t-123")

    def test_seedance_nested_data_id_parsing(self):
        # 兼容嵌套 data.id 结构
        with mock.patch("ecommerce_video.providers.seedance._request", return_value={"data": {"id": "t-456"}}):
            from ecommerce_video.providers.seedance import SeedanceProvider
            p = SeedanceProvider(provider_id="seedance-2.0")
            self.assertEqual(p.create_task("p", [], 5, "1080p", "9:16", "", {}), "t-456")

    def test_agnes_multi_ref_keyframes_mode(self):
        captured = {}

        def fake_request(method, url, api_key, json=None, **kw):
            captured["body"] = json
            return {"video_id": "v-1"}

        with mock.patch("ecommerce_video.providers.agnes._request", side_effect=fake_request):
            from ecommerce_video.providers.agnes import AgnesVideoProvider
            p = AgnesVideoProvider(provider_id="agnes-video")
            refs = ["https://cdn/a.png", "https://cdn/b.png"]  # 多图 → 关键帧模式
            tid = p.create_task("p", refs, 10, "1080p", "9:16", "", {})
            self.assertEqual(tid, "v-1")
            body = captured["body"]
            self.assertEqual(body["num_frames"], 241)
            self.assertEqual(body["frame_rate"], 24)
            self.assertEqual(body["width"], 768)
            self.assertEqual(body["height"], 1152)
            self.assertIn("extra_body", body, "多图应走关键帧模式 extra_body")
            self.assertEqual(body["extra_body"]["mode"], "keyframes")
            self.assertEqual(body["extra_body"]["image"], refs)

    def test_agnes_single_ref_image_field(self):
        captured = {}

        def fake_request(method, url, api_key, json=None, **kw):
            captured["body"] = json
            return {"video_id": "v-2"}

        with mock.patch("ecommerce_video.providers.agnes._request", side_effect=fake_request):
            from ecommerce_video.providers.agnes import AgnesVideoProvider
            p = AgnesVideoProvider(provider_id="agnes-video")
            p.create_task("p", ["https://cdn/a.png"], 10, "1080p", "9:16", "", {})
            self.assertEqual(captured["body"]["image"], "https://cdn/a.png")
            self.assertNotIn("extra_body", captured["body"], "单图不应走关键帧模式")

    def test_agnes_local_image_to_data_uri(self):
        # 本地图自动转 data URI（临时文件，不触网）
        import base64
        import tempfile
        from ecommerce_video.providers.agnes import AgnesVideoProvider
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake-png-bytes")
            path = f.name
        self.addCleanup(Path(path).unlink, missing_ok=True)
        captured = {}

        def fake_request(method, url, api_key, json=None, **kw):
            captured["body"] = json
            return {"video_id": "v-3"}

        with mock.patch("ecommerce_video.providers.agnes._request", side_effect=fake_request):
            p = AgnesVideoProvider(provider_id="agnes-video")
            p.create_task("p", [path], 10, "1080p", "9:16", "", {})
            expect = "data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode()
            self.assertEqual(captured["body"]["image"], expect)

    def test_custom_sync_url_wrapped(self):
        # custom/OpenAI 兼容：同步返回 URL → 包成 __direct_url__:http... 已完成任务
        with mock.patch("ecommerce_video.providers.custom._request",
                        return_value={"data": [{"url": "https://cdn/sync/v.mp4"}]}):
            from ecommerce_video.providers.custom import CustomProvider
            p = CustomProvider(provider_id="custom")
            tid = p.create_task("p", [], 5, "1080p", "9:16", "", {})
            self.assertTrue(tid.startswith("__direct_url__:"))
            res = p.query_task(tid, {})
            self.assertEqual(res["status"], "succeeded")
            self.assertEqual(res["url"], "https://cdn/sync/v.mp4")


class _NoNetworkSentinel:
    """禁网哨兵：任何属性访问都直接失败——防止用例意外发起真实网络调用。"""

    def __getattr__(self, name):
        raise AssertionError(f"禁止网络调用：requests.{name} 被访问（本用例只应走本地逻辑）")


class TestNoNetwork(unittest.TestCase):
    """7. 不调用网络：核心本地逻辑在 requests 被禁用的前提下仍可完成。"""

    def test_local_logic_under_no_network(self):
        with mock.patch("ecommerce_video.providers.base.requests", _NoNetworkSentinel()):
            # get_provider 只读本地 knowledge/models.json（能力注入）
            p = get_provider("seedance-2.0")
            self.assertEqual(p.capabilities["ref_images"], 9)
            # agnes 帧数/比例纯计算
            self.assertEqual(_frames_for_duration(10), 241)
            self.assertEqual(_ratio_to_wh("9:16"), (768, 1152))
            # URL 提取纯递归
            self.assertEqual(
                _extract_url({"metadata": {"url": "https://cdn/x/v.mp4"}}),
                "https://cdn/x/v.mp4")
            # 未注册异常路径同样不触网
            with self.assertRaises(VideoGenError):
                get_provider("no-such-model-xyz")


if __name__ == "__main__":
    unittest.main(verbosity=2)
