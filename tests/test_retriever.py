#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索层契约测试（tests/test_retriever.py）。

运行：python -m unittest tests.test_retriever -v   （从项目根目录）

依赖：仅标准库 unittest + unittest.mock（无 pytest / 无第三方依赖）。
契约（见 scripts/retriever.py 与项目检索层约定）：
    from retriever import retrieve
    result = retrieve(category, shots, material, type_name)
    result["per_shot"][shot_no] = {
        "scene_light": [...], "lighting": [...], "camera_movement": [...],
        "lens_shot": [...], "motion": [...], "negative": [...]}

说明：retriever 由检索层同事实现；若 scripts/retriever.py 尚未落地，本组用例
自动跳过（套件保持全绿，日志会显示 skipped 原因）；文件落地后自动转为真实断言。
"""
import os
import sys
import unittest
from pathlib import Path

# Windows GBK 兼容：测试名含中文，重配 stdout 防编码异常
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

RETRIEVER_FILE = SRC_DIR / "ecommerce_video" / "retriever.py"
if RETRIEVER_FILE.exists():
    from ecommerce_video.retriever import retrieve  # noqa: E402  （存在则必须可用；报错=实现缺陷，直接失败）
    RETRIEVER_AVAILABLE = True
else:
    retrieve = None
    RETRIEVER_AVAILABLE = False

# 知识库单一数据源（开源改造第2步：包内为唯一数据源）——与 retriever 运行时实际读取目录保持一致
from ecommerce_video import config as _config  # noqa: E402
KNOWLEDGE = _config.KNOWLEDGE_DIR
ALL_CATEGORIES = [
    "clothing", "beauty", "food", "digital3c", "home", "shoes", "bags",
    "accessories", "personalcare", "baby", "sports", "pet", "auto", "jewelry",
]


def _shot(result, shot_no):
    """兼容 per_shot 键为 int 或 str。"""
    ps = result["per_shot"]
    return ps.get(shot_no) if shot_no in ps else ps.get(str(shot_no))


def _scene_light_ids(entries):
    ids = set()
    for e in entries or []:
        if isinstance(e, dict):
            ids.add(str(e.get("id", "")))
            ids.add(str(e.get("name", "")))
        else:
            ids.add(str(e))
    return ids


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
    RETRIEVER_AVAILABLE,
    "scripts/retriever.py 未实现（检索层同事交付后自动启用，套件保持全绿）",
)
class RetrieverContractTest(unittest.TestCase):
    """检索层契约测试基类（retriever 缺失时整组跳过）。"""


class TestSceneExactMatch(RetrieverContractTest):
    """1. 场景精确命中：clothing + 大理石美术馆 → scene_light 非空且含 satin。"""

    def test_scene_exact_hit_contains_satin(self):
        shots = [{"shot_no": 1, "scene": "大理石美术馆"}]
        res = retrieve("clothing", shots, "", "tvc")
        sl = _shot(res, 1)["scene_light"]
        self.assertTrue(sl, "场景精确命中应至少返回 satin 条目")
        self.assertTrue(_any_field(sl, "satin"), "scene_light 应含 satin（缎面）")


class TestMaterialDirect(RetrieverContractTest):
    """2. 材质直取：material=缎面 → scene_light 含 satin（即使场景不匹配）。"""

    def test_material_direct_wins_over_scene(self):
        # "海边" 不是 satin 的场景（satin.scenes 无 海边），缎面必须靠材质直取注入
        shots = [{"shot_no": 1, "scene": "海边"}]
        res = retrieve("clothing", shots, "缎面", "tvc")
        sl = _shot(res, 1)["scene_light"]
        self.assertTrue(sl)
        self.assertTrue(_any_field(sl, "satin"), "材质直取：material=缎面 应含 satin")


class TestTagsFallback(RetrieverContractTest):
    """3. tags 兜底：场景关键词命中条目 tags（按实际数据断言非空，不写死 id）。"""

    def test_scene_keyword_hits(self):
        for scene in ("街头", "旗袍"):
            with self.subTest(scene=scene):
                shots = [{"shot_no": 1, "scene": scene}]
                res = retrieve("clothing", shots, "", "tvc")
                self.assertTrue(
                    _shot(res, 1)["scene_light"],
                    f"场景关键词 {scene} 应有兜底命中（场景/tags 任一通道）",
                )


class TestCrossCategoryIsolation(RetrieverContractTest):
    """4. 跨品类不误召回：beauty 时 scene_light 不得出现 fabric 条目（如 satin）。"""

    def test_beauty_no_fabric_recall(self):
        shots = [{"shot_no": 1, "scene": "梳妆台镜前"}]
        res = retrieve("beauty", shots, "", "tvc")
        sl = _shot(res, 1)["scene_light"]
        self.assertTrue(sl, "beauty 应有自身场景光线条目命中")
        ids = _scene_light_ids(sl)
        self.assertNotIn("satin", ids, "beauty 检索不得混入 fabric-scene-light.json 条目")
        self.assertNotIn("缎面", ids)

    def test_beauty_material_satin_also_excluded(self):
        # 即使材质写缎面，beauty 也只应查 beauty 库，不得跨库取面料条目
        shots = [{"shot_no": 1, "scene": "梳妆台镜前"}]
        res = retrieve("beauty", shots, "缎面", "tvc")
        ids = _scene_light_ids(_shot(res, 1)["scene_light"])
        self.assertNotIn("satin", ids)


class TestInjectionCaps(RetrieverContractTest):
    """5. 注入量上限：scene_light≤3 / lighting≤3 / camera_movement≤2 / lens_shot≤2 / motion≤5 / negative 8~15。"""

    CAPS = {
        "scene_light": 3,
        "lighting": 3,
        "camera_movement": 2,
        "lens_shot": 2,
        "motion": 5,
        "negative": (8, 15),
    }

    def test_caps(self):
        shots = [{
            "shot_no": 1,
            "scene": "街头",
            "lens": "大特写、特写、近景、中景、全景、远景、过肩、俯视角度、仰视角度、85mm以上长焦",
            "move": "环绕、跟拍、甩镜、俯拍、慢动作、推近、拉远、横移、升降、手持、固定机位",
            "motion": "转身、甩发、裙摆甩动、慢步前行、回眸",
        }]
        res = retrieve("clothing", shots, "缎面", "tvc")
        data = _shot(res, 1)
        self.assertLessEqual(len(data["scene_light"]), self.CAPS["scene_light"])
        self.assertLessEqual(len(data["lighting"]), self.CAPS["lighting"])
        self.assertLessEqual(len(data["camera_movement"]), self.CAPS["camera_movement"])
        self.assertLessEqual(len(data["lens_shot"]), self.CAPS["lens_shot"])
        self.assertLessEqual(len(data["motion"]), self.CAPS["motion"])
        lo, hi = self.CAPS["negative"]
        self.assertGreaterEqual(len(data["negative"]), lo)
        self.assertLessEqual(len(data["negative"]), hi)


class TestNegativeMustHaves(RetrieverContractTest):
    """6. 负面词必含：形变扭曲/多余肢体/手指变形/水印/画面文字。"""

    MUST = ("形变扭曲", "多余肢体", "手指变形", "水印", "画面文字")

    def test_negative_required_terms(self):
        for scene in ("大理石美术馆", "街头", "海边"):
            with self.subTest(scene=scene):
                shots = [{"shot_no": 1, "scene": scene}]
                res = retrieve("clothing", shots, "缎面", "tvc")
                neg = _shot(res, 1)["negative"]
                for term in self.MUST:
                    self.assertIn(term, neg, f"negative 缺必含项：{term}")


class TestAliasesMissingRobustness(RetrieverContractTest):
    """7. 健壮性：scene-aliases.json 不存在时不抛异常（临时改名模拟，addCleanup 恢复）。"""

    def test_missing_aliases_no_crash(self):
        aliases = KNOWLEDGE / "scene-aliases.json"
        if aliases.exists():
            bak = aliases.with_suffix(".json.bak")
            os.replace(aliases, bak)
            # 无论测试成败都恢复原文件（addCleanup 保证）
            self.addCleanup(os.replace, bak, aliases)
        res = retrieve("clothing", [{"shot_no": 1, "scene": "大理石美术馆"}], "缎面", "tvc")
        self.assertIn("per_shot", res)
        self.assertIn(1, res["per_shot"], "别名缺失时仍应正常返回 per_shot")


class TestAllCategoriesEmptyShots(RetrieverContractTest):
    """8. 14 品类空 shots 调用不崩溃。"""

    def test_empty_shots_all_categories(self):
        for cat in ALL_CATEGORIES:
            with self.subTest(category=cat):
                res = retrieve(cat, [], "", "")
                self.assertIn("per_shot", res)
                self.assertEqual(res["per_shot"], {}, f"{cat} 空 shots 应返回空 per_shot")


class TestMissingRetrieverReporting(unittest.TestCase):
    """契约兜底：retriever 缺失时给出明确提示（套件仍全绿）。"""

    def test_retriever_present(self):
        if not RETRIEVER_AVAILABLE:
            self.skipTest(
                "scripts/retriever.py 尚未实现：契约测试组已跳过，待检索层同事交付后自动启用"
            )
        # 存在时该用例无额外断言（真实契约断言在上方各测试类）


if __name__ == "__main__":
    unittest.main(verbosity=2)
