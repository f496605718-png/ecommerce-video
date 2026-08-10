#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库完整性测试（战役3 工程化质量：把人工复核固化成自动化测试，防知识库回归）。

覆盖范围（对应人工验证过的战役1结论）：
1. 文件与索引一致性：index.json files[] 指向的文件真实存在（含 profiles/*.profile.json 通配）
2. scene-aliases 引用完整性：category 合法、targets 指向对应品类 scene-light 的 items[].id、覆盖度达标
3. 品类一致性：category-profiles 键集 == 14 品类、每个品类有 profile 文件、modules 含 M1-M11、每个品类有 scene-light 文件
4. models.json 一致性：default_model 存在、capabilities 必需键齐全（未验证值允许 null）、模型在 providers 注册表中存在
5. scene-light 数据质量：id 唯一、必填字段齐全、数量与 index.json item_count 一致
6. 负面词红线：vocab.json negative_general 含 5 个红线词

运行（项目根目录）：
    python -m unittest tests.test_kb_integrity -v

约束：仅标准库、不联网、不改任何 knowledge/ 数据。
"""

import glob
import json
import os
import sys
import unittest

# ---------------------------------------------------------------------------
# 路径与加载工具
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "src")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# 知识库单一数据源（开源改造第2步：包内为唯一数据源，根目录不再复制）
# 与运行时 config.KNOWLEDGE_DIR 同规则：env KNOWLEDGE_DIR → 包内 knowledge/ → 项目根兜底
from ecommerce_video import config as _config  # noqa: E402
KNOWLEDGE = str(_config.KNOWLEDGE_DIR)

# 14 个品类（与 index.json profiles/*.profile.json 条目的 groups 一致）
CATEGORY_IDS = [
    "clothing", "beauty", "food", "digital3c", "home", "shoes", "bags",
    "accessories", "personalcare", "baby", "sports", "pet", "auto", "jewelry",
]

# 每个品类的 scene-light 文件（clothing 特例：fabric-scene-light.json）
CATEGORY_SCENE_LIGHT = {c: f"{c}-scene-light.json" for c in CATEGORY_IDS}
CATEGORY_SCENE_LIGHT["clothing"] = "fabric-scene-light.json"

# scene-aliases 的 category -> 对应 scene-light 文件
ALIAS_SCENE_LIGHT = {
    "clothing": "fabric-scene-light.json",
    "beauty": "beauty-scene-light.json",
    "food": "food-scene-light.json",
}

# 14 个 scene-light 文件的期望条目数（与 index.json item_count 一致；
# 若未来增删条目，需同步修改本表与 index.json，否则测试会失败提示回归）
EXPECTED_SCENE_LIGHT_COUNTS = {
    "fabric-scene-light.json": 30,
    "beauty-scene-light.json": 15,
    "food-scene-light.json": 17,
    "digital3c-scene-light.json": 13,
    "home-scene-light.json": 14,
    "shoes-scene-light.json": 9,
    "bags-scene-light.json": 7,
    "accessories-scene-light.json": 6,
    "personalcare-scene-light.json": 6,
    "baby-scene-light.json": 7,
    "sports-scene-light.json": 8,
    "pet-scene-light.json": 7,
    "auto-scene-light.json": 6,
    "jewelry-scene-light.json": 6,
}

# 11 个模块 key（M1-M11 全）
MODULE_KEYS = [
    "M1_category_profile", "M2_shooting_style_system", "M3_lens_language",
    "M4_lighting_system", "M5_motion_direction", "M6_scene_library",
    "M7_styling_spec", "M8_industry_pitfalls", "M9_qa_standards",
    "M10_negative_prompts", "M11_type_adaptation",
]

# scene-light item 必填字段
ITEM_REQUIRED_FIELDS = ["id", "name", "prompt_zh", "scenes", "light", "tags"]

# 负面词红线（vocab.json negative_general 必须包含）
NEGATIVE_REDLINES = ["形变扭曲", "多余肢体", "手指变形", "水印", "画面文字"]

# models.json 中"文档注册但未实现"的模型 id（不在 providers 注册表中，属规划中的开放接入，
# 接入实现后应从本集合移除；新增文档模型但未实现时需加入本集合）
DOCUMENTED_NOT_IMPLEMENTED_MODELS = {"kling", "jimeng", "runway", "vidu"}

# models.json capabilities 必需键（kling/runway/vidu 等未验证的允许 null，但键必须存在）
REQUIRED_CAPABILITY_FIELDS = [
    "ref_images", "duration_min", "duration_max",
    "resolutions", "chinese_prompt", "multi_ref_supported",
]


def load_json(name):
    """读取 knowledge/ 下的 JSON 文件（UTF-8）。"""
    with open(os.path.join(KNOWLEDGE, name), encoding="utf-8") as fh:
        return json.load(fh)


def scene_light_ids(name):
    """返回 scene-light 文件所有 items[].id 的集合。"""
    return {item["id"] for item in load_json(name)["items"]}


# ---------------------------------------------------------------------------
# 1. 文件与索引一致性
# ---------------------------------------------------------------------------
class TestFileIndexConsistency(unittest.TestCase):
    """index.json files[] 指向的文件必须真实存在。"""

    @classmethod
    def setUpClass(cls):
        cls.index = load_json("index.json")

    def test_索引_files_每个文件真实存在(self):
        """index.json files[] 的每个 file 字段对应文件必须存在于磁盘（含 profiles/*.profile.json 通配）。"""
        for entry in self.index["files"]:
            pattern = entry["file"]
            with self.subTest(file=pattern):
                if "*" in pattern:
                    # 通配条目：至少匹配 1 个文件，且数量与 item_count 一致（防缺 profile 文件）
                    matches = glob.glob(os.path.join(KNOWLEDGE, pattern))
                    self.assertGreater(
                        len(matches), 0,
                        f"通配 {pattern} 未匹配到任何文件",
                    )
                    if pattern == "profiles/*.profile.json":
                        self.assertEqual(
                            len(matches), entry.get("item_count"),
                            f"{pattern} 实际 {len(matches)} 个文件，与 index.json item_count={entry.get('item_count')} 不一致",
                        )
                else:
                    self.assertTrue(
                        os.path.isfile(os.path.join(KNOWLEDGE, pattern)),
                        f"index.json 声明的文件缺失: {pattern}",
                    )

    def test_索引_scene_light_文件都在磁盘上(self):
        """index.json 列出的每个 *-scene-light.json 文件必须真实存在。"""
        indexed = [e["file"] for e in self.index["files"]]
        for name in EXPECTED_SCENE_LIGHT_COUNTS:
            with self.subTest(file=name):
                self.assertIn(name, indexed, f"{name} 未在 index.json files[] 中登记")
                self.assertTrue(
                    os.path.isfile(os.path.join(KNOWLEDGE, name)),
                    f"index.json 声明的 scene-light 文件缺失: {name}",
                )


# ---------------------------------------------------------------------------
# 2. scene-aliases 引用完整性
# ---------------------------------------------------------------------------
class TestSceneAliases(unittest.TestCase):
    """scene-aliases.json 的 category 合法、targets 引用存在、覆盖度达标。"""

    @classmethod
    def setUpClass(cls):
        cls.aliases = load_json("scene-aliases.json")["aliases"]
        cls.alias_ids_by_category = {
            cat: scene_light_ids(fname)
            for cat, fname in ALIAS_SCENE_LIGHT.items()
        }

    def test_别名_category_合法(self):
        """每个 alias 的 category 必须是 {clothing, beauty, food}。"""
        for alias in self.aliases:
            with self.subTest(alias=alias.get("alias"), category=alias.get("category")):
                self.assertIn(
                    alias["category"], ALIAS_SCENE_LIGHT,
                    f"alias '{alias.get('alias')}' 的 category '{alias.get('category')}' 非法",
                )

    def test_别名_targets_id_存在于对应scene_light(self):
        """每个 alias 的 targets 每个 id 必须存在于对应品类 scene-light 文件的 items[].id 中。"""
        for alias in self.aliases:
            cat = alias["category"]
            valid_ids = self.alias_ids_by_category[cat]
            for target in alias["targets"]:
                with self.subTest(
                    alias=alias.get("alias"), category=cat, target=target
                ):
                    self.assertIn(
                        target, valid_ids,
                        f"alias '{alias.get('alias')}' 的 target '{target}' 不存在于 "
                        f"{ALIAS_SCENE_LIGHT[cat]} 的 items[].id 中",
                    )

    def test_别名覆盖度_达标(self):
        """覆盖度红线：clothing >= 15、beauty >= 12、food >= 12。

        注：若未来有意精简别名，需同步修改此处下限并在注释说明原因。
        """
        thresholds = {"clothing": 15, "beauty": 12, "food": 12}
        for cat, minimum in thresholds.items():
            count = sum(1 for a in self.aliases if a["category"] == cat)
            with self.subTest(category=cat, count=count):
                self.assertGreaterEqual(
                    count, minimum,
                    f"{cat} 别名仅 {count} 条，低于覆盖度下限 {minimum}",
                )


# ---------------------------------------------------------------------------
# 3. 品类一致性
# ---------------------------------------------------------------------------
class TestCategoryConsistency(unittest.TestCase):
    """category-profiles.json 与 profiles/ 目录、scene-light 文件的品类一致性。"""

    @classmethod
    def setUpClass(cls):
        cls.category_profiles = load_json("category-profiles.json")
        cls.profile_keys = set(cls.category_profiles["profiles"].keys())

    def test_category_profiles_键集等于14品类(self):
        """category-profiles.json 的 profiles 键集合必须恰好等于 14 个品类 id。"""
        self.assertEqual(
            self.profile_keys, set(CATEGORY_IDS),
            f"profiles 键集与 14 品类不一致："
            f"多余={sorted(self.profile_keys - set(CATEGORY_IDS))} "
            f"缺失={sorted(set(CATEGORY_IDS) - self.profile_keys)}",
        )

    def test_每个品类都有profile文件(self):
        """每个品类 id 都必须有对应的 profiles/{品类}.profile.json 文件。"""
        for cat in CATEGORY_IDS:
            with self.subTest(category=cat):
                self.assertIn(cat, self.profile_keys,
                              f"{cat} 不在 category-profiles.json 的 profiles 中")
                self.assertTrue(
                    os.path.isfile(os.path.join(KNOWLEDGE, "profiles", f"{cat}.profile.json")),
                    f"缺少 profiles/{cat}.profile.json",
                )

    def test_每个profile_modules含M1到M11(self):
        """每个 profile 文件的 modules 必须含 11 个模块 key（M1-M11 全）。"""
        for cat in CATEGORY_IDS:
            profile = load_json(os.path.join("profiles", f"{cat}.profile.json"))
            modules = list(profile.get("modules", {}).keys())
            with self.subTest(category=cat):
                self.assertEqual(
                    modules, MODULE_KEYS,
                    f"{cat}.profile.json 的 modules 缺失或顺序异常：{modules}",
                )

    def test_每个品类都有scene_light文件(self):
        """每个品类都必须有对应 scene-light 文件（clothing -> fabric-scene-light.json 特例）。"""
        for cat in CATEGORY_IDS:
            fname = CATEGORY_SCENE_LIGHT[cat]
            with self.subTest(category=cat, file=fname):
                self.assertTrue(
                    os.path.isfile(os.path.join(KNOWLEDGE, fname)),
                    f"品类 {cat} 缺少 scene-light 文件 {fname}",
                )


# ---------------------------------------------------------------------------
# 4. models.json 一致性
# ---------------------------------------------------------------------------
class TestModelsConsistency(unittest.TestCase):
    """models.json 的 default_model、capabilities 必需键、providers 注册一致性。"""

    @classmethod
    def setUpClass(cls):
        cls.models_data = load_json("models.json")
        cls.models = cls.models_data["models"]
        cls.model_ids = {m["id"] for m in cls.models}

    def test_default_model_存在于models(self):
        """default_model 必须存在于 models[].id 中。"""
        self.assertIn(
            self.models_data["default_model"], self.model_ids,
            f"default_model '{self.models_data['default_model']}' 不在 models[].id 中",
        )

    def test_每个model_capabilities必需键齐全(self):
        """每个 model 的 capabilities 必须含必需键；未验证的（kling/runway/vidu 等）值允许 null，但键必须存在。"""
        for model in self.models:
            caps = model.get("capabilities", {})
            for key in REQUIRED_CAPABILITY_FIELDS:
                with self.subTest(model=model["id"], key=key):
                    self.assertIn(
                        key, caps,
                        f"model '{model['id']}' 的 capabilities 缺少键 '{key}'",
                    )

    def test_模型在providers注册表中存在(self):
        """每个 model id 必须在 scripts/providers/ 注册表中存在；custom 必须已注册。

        未注册但属于"文档注册但未实现"清单的模型（kling/jimeng/runway/vidu），
        视为开放接入规划项，给出说明而不判失败；既未注册又不在清单中则判失败（数据漂移）。
        """
        from ecommerce_video.providers import list_providers

        registered = set(list_providers())

        # custom 是开放接入默认落点，必须已实现注册
        self.assertIn(
            "custom", registered,
            "custom provider 必须在 scripts/providers/ 中已注册",
        )

        implemented, documented_only = [], []
        for model in self.models:
            mid = model["id"]
            # 精确注册 或 注册名是其前缀/别名（如 agnes-video-v2.0 -> agnes-video）
            if mid in registered or any(
                rid in mid for rid in registered if len(rid) > 3
            ):
                implemented.append(mid)
            elif mid in DOCUMENTED_NOT_IMPLEMENTED_MODELS:
                documented_only.append(mid)
            else:
                with self.subTest(model=mid):
                    self.fail(
                        f"model '{mid}' 既不在 providers 注册表中，"
                        f"也不在文档未实现清单 {sorted(DOCUMENTED_NOT_IMPLEMENTED_MODELS)} 中，"
                        f"请实现 provider 或补充文档说明",
                    )

        if documented_only:
            # 说明性输出：文档注册但未实现，不判失败（print 不进 -v 输出会被吞，用 subTest 留痕）
            self.assertEqual(
                sorted(documented_only), sorted(DOCUMENTED_NOT_IMPLEMENTED_MODELS),
                f"文档未实现清单与 models.json 中实际未注册模型不一致：{sorted(documented_only)}",
            )


# ---------------------------------------------------------------------------
# 5. scene-light 数据质量
# ---------------------------------------------------------------------------
class TestSceneLightQuality(unittest.TestCase):
    """scene-light 文件：id 唯一、必填字段齐全、数量与 index.json 一致。"""

    @classmethod
    def setUpClass(cls):
        cls.index_entries = {
            e["file"]: e for e in load_json("index.json")["files"]
        }

    def test_items_id唯一(self):
        """每个 scene-light 文件 items 的 id 必须唯一。"""
        for fname in EXPECTED_SCENE_LIGHT_COUNTS:
            items = load_json(fname)["items"]
            ids = [item["id"] for item in items]
            with self.subTest(file=fname):
                self.assertEqual(
                    len(ids), len(set(ids)),
                    f"{fname} 存在重复 id："
                    f"{[i for i in set(ids) if ids.count(i) > 1]}",
                )

    def test_items必填字段齐全(self):
        """每个 item 必须含 id/name/prompt_zh/scenes/light/tags 字段。"""
        for fname in EXPECTED_SCENE_LIGHT_COUNTS:
            items = load_json(fname)["items"]
            for item in items:
                with self.subTest(file=fname, item_id=item.get("id")):
                    for field in ITEM_REQUIRED_FIELDS:
                        self.assertIn(
                            field, item,
                            f"{fname} 的 item '{item.get('id')}' 缺少必填字段 '{field}'",
                        )

    def test_items数量与index_item_count一致(self):
        """items 数量必须与 index.json 对应条目 item_count 一致，且等于期望值表。"""
        for fname, expected in EXPECTED_SCENE_LIGHT_COUNTS.items():
            actual = len(load_json(fname)["items"])
            indexed = self.index_entries[fname]["item_count"]
            with self.subTest(file=fname, actual=actual, expected=expected):
                self.assertEqual(
                    actual, expected,
                    f"{fname} items 数量 {actual} 与期望 {expected} 不一致（改数据需同步改本表）",
                )
                self.assertEqual(
                    indexed, expected,
                    f"index.json 中 {fname} 的 item_count={indexed} 与期望 {expected} 不一致",
                )


# ---------------------------------------------------------------------------
# 6. 负面词红线
# ---------------------------------------------------------------------------
class TestNegativeRedLines(unittest.TestCase):
    """vocab.json 的 negative_general 必须含红线词。"""

    def test_negative_general_含红线词(self):
        """negative_general 必须包含：形变扭曲/多余肢体/手指变形/水印/画面文字。"""
        negative_general = load_json("vocab.json")["negative_general"]
        for word in NEGATIVE_REDLINES:
            with self.subTest(word=word):
                self.assertIn(
                    word, negative_general,
                    f"negative_general 缺少红线词 '{word}'（完整词表：{negative_general}）",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
