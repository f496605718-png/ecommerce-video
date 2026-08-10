#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retriever.py —— 检索层正式实现（每镜精准素材注入）。

契约（与 tests/test_retriever.py 一致，测试即稳定契约）：
    from retriever import retrieve
    result = retrieve(category, shots, material, type_name)
    result["per_shot"][shot_no] = {
      "scene_light": [...], "lighting": [...], "camera_movement": [...],
      "lens_shot": [...], "motion": [...], "negative": [...]}
    result["matched"][shot_no] = "exact|alias|tags|material|none"   # 每镜命中来源（调试用）
    result["meta"] = {...}

定位与加载策略：
    - 先读 knowledge/index.json 定位文件 → 再按需加载对应品类的
      {category}-scene-light.json（服装 clothing→fabric-scene-light.json）、
      vocab.json、profiles/{category}.profile.json；不全量读入知识库。
    - 任何知识文件缺失均降级（返回空/跳过该源），不抛异常。

匹配规则（四级，优先级从高到低）：
    0 material 材质直取：material 命中条目 name/id/alt（商品属性优先，即使场景不匹配）
    1 exact 场景精确：分镜 scene 与条目 scenes 做「词边界匹配」——
       连续中文字符=一个词块，目标场景词必须落在文本某词块的块首（整块/前缀对齐），
       杜绝跨词误中（如"某随机场景"不得因含"机场/场景"命中"机场/场景"类条目）；
       "大理石美术馆入口" 可命中 scenes=["大理石美术馆"]（词块前缀）。
    2 alias 别名层：scene 命中 scene-aliases.json 的 alias（词边界互相命中）→
       targets 为 scene-light 条目 id 列表 → 直接按 id 从 items 取条目加入结果；
       兼容旧数据：target 非条目 id 时视为知识库场景名，按词边界场景匹配。
       别名文件缺失时静默跳过（降级为无别名，不抛异常）。
    3 tags 兜底：场景关键词命中条目 tags（无场景直接命中时的兜底）。

每镜 matched 值取「实际贡献了至少一个条目」的层级中优先级最高者
（material > exact > alias > tags；全无命中为 none）。

M5 动作按需注入：
    - 读 knowledge/profiles/{category}.profile.json → modules.M5_motion_direction，
      动作数组键兼容 model_actions / actions / food_actions / product_actions；
    - 每条动作含"动作"与"提示词写法"字段；
    - 按 shot.action/motion 与条目"动作"字段的包含关系匹配，取"提示词写法"≤5 条
      （知识库专业写法，非分镜原文切分）；无命中取该品类前 5 条兜底；
    - 动作库缺失/为空时降级返回 []，不抛异常。

注入量上限（契约）：scene_light≤3 / lighting≤3 / camera_movement≤2 / lens_shot≤2 /
motion≤5 / negative 8~15 条且必含通用红线（形变扭曲/多余肢体/手指变形/水印/画面文字）。

说明：本文件为检索层正式实现，纯本地读取、无网络、无 LLM、无第三方依赖，
确定性输出（Windows/Linux 均可跑，含 Windows GBK stdout 兼容）。
"""
import json
import os
import re
import sys
from pathlib import Path

# Windows GBK 兼容（与 scripts/ 其他模块一致）
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# src 布局：src/ecommerce_video/retriever.py → 上上级=src，再上一级=项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 知识库定位与 config 同规则：env KNOWLEDGE_DIR 优先 → 包内 knowledge/ → 项目根 knowledge/
_PACKAGE_KNOWLEDGE = Path(__file__).resolve().parent / "knowledge"
KNOWLEDGE = Path(os.environ.get("KNOWLEDGE_DIR") or (
    _PACKAGE_KNOWLEDGE if _PACKAGE_KNOWLEDGE.is_dir() else PROJECT_ROOT / "knowledge"))

# 品类 → 场景光线文件（服装=面料库；其余按 {category}-scene-light.json）
CATEGORY_SCENE_FILE = {
    "clothing": "fabric-scene-light.json",
    "beauty": "beauty-scene-light.json",
    "food": "food-scene-light.json",
    "digital3c": "digital3c-scene-light.json",
    "home": "home-scene-light.json",
    "shoes": "shoes-scene-light.json",
    "bags": "bags-scene-light.json",
    "accessories": "accessories-scene-light.json",
    "personalcare": "personalcare-scene-light.json",
    "baby": "baby-scene-light.json",
    "sports": "sports-scene-light.json",
    "pet": "pet-scene-light.json",
    "auto": "auto-scene-light.json",
    "jewelry": "jewelry-scene-light.json",
}

# 注入量上限（契约，tests/test_retriever.py 断言）
CAPS = {
    "scene_light": 3,
    "lighting": 3,
    "camera_movement": 2,
    "lens_shot": 2,
    "motion": 5,
    "negative_max": 15,
}

# 负面词必含红线（通用；与 vocab.json negative_general 同源）
REQUIRED_NEGATIVES = ["形变扭曲", "多余肢体", "手指变形", "水印", "画面文字"]

# M5 动作库键名（不同品类 profile 用不同键，兼容处理）
_M5_ACTION_KEYS = ("model_actions", "actions", "food_actions", "product_actions")

_cache = {}


def _load(name):
    """按需加载 knowledge 下 JSON（缓存防重复读盘）。缺失/损坏返回 None。"""
    if name not in _cache:
        p = KNOWLEDGE / name
        if not p.exists():
            _cache[name] = None
        else:
            try:
                _cache[name] = json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:
                _cache[name] = None
    return _cache[name]


def _load_aliases():
    """场景别名：每次现读不缓存（缺失/恢复不影响结果）。缺失返回 []，不抛异常。"""
    p = KNOWLEDGE / "scene-aliases.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data.get("aliases", []) or []
    except Exception:
        return []


def _scene_items(file_name):
    data = _load(file_name)
    return (data or {}).get("items", []) or []


def _load_profile(category):
    return _load(f"profiles/{category}.profile.json")


# ---------- 词边界匹配 ----------
def _word_blocks(text):
    """连续中文字符=一个词块（非中文视为分隔符）。返回词块列表。"""
    return re.findall(r"[\u4e00-\u9fff]+", str(text or ""))


def _word_hit(target, text):
    """词边界匹配：目标词的任一词块是否落在文本某词块的块首（整块/前缀对齐）。

    判定逻辑：把 target 与 text 都按中文字符连续块切分（连续中文=一个词块，
    非中文为分隔）；若存在 target 的词块 tb 与 text 的词块 w，满足 w.startswith(tb)
    （tb 与 w 整块相等即"以自身开头"），则命中。等价于：目标词必须对齐到文本
    词块的块首边界（字符串开头/分隔符之后），从而：
      - "大理石美术馆入口" 命中 scenes=["大理石美术馆"]（词块前缀 ✓）
      - "某随机场景" 不命中 "场景"、"机场"（词尾/跨词子串不误中 ✓）
    """
    tb = _word_blocks(target)
    if not tb:
        return False
    for t in tb:
        for w in _word_blocks(text):
            if w.startswith(t):
                return True
    return False


# ---------- 匹配 ----------
def _tag_hit(term, item_tags):
    """tags 兜底：分镜场景词命中条目 tags（子串双向包含，tags 为自由关键词）。"""
    for t in item_tags:
        if t and (t in term or term in t):
            return True
    return False


def _alias_items(scene, aliases, items, category):
    """别名层：scene 命中 alias → targets 直取条目（契约实现）。

    判定逻辑：
      1) scene 与 alias 词边界互相命中（_word_hit(alias, scene) 或
         _word_hit(scene, alias)，双向包含）；
      2) 命中的 alias 其 targets 是 scene-light 条目 id 列表 → 直接按 id
         从 items 取条目加入结果（不再把 id 当文本去做场景子串匹配）；
      3) 兼容旧数据：target 非条目 id 时视为知识库场景名，按词边界场景匹配；
      4) 别名条目带 category 且与当前品类不一致时跳过；
      5) 别名文件缺失（aliases=[]）时静默返回 []（降级，不抛异常）。
    """
    by_id = {}
    for it in items:
        iid = it.get("id")
        if iid is not None:
            by_id[str(iid)] = it
    out, seen = [], set()
    for a in aliases:
        alias = str(a.get("alias", "") or "")
        if not alias:
            continue
        acat = str(a.get("category", "") or "").lower()
        if acat and acat != (category or ""):
            continue
        # scene 与 alias 词边界互相命中（alias 展开条件）
        if not (_word_hit(alias, scene) or _word_hit(scene, alias)):
            continue
        for t in (a.get("targets", []) or []):
            t = str(t).strip()
            if not t:
                continue
            if t in by_id:
                # 契约主路径：targets = 条目 id → 直取条目
                it = by_id[t]
            else:
                # 兼容旧数据：target = 知识库场景名 → 词边界场景匹配
                it = None
                for cand in items:
                    if any(_word_hit(t, str(x)) for x in (cand.get("scenes") or [])):
                        it = cand
                        break
            if it is None:
                continue
            iid = it.get("id")
            key = ("id", str(iid)) if iid is not None else ("obj", id(it))
            if key not in seen:
                seen.add(key)
                out.append(it)
    return out


# 每镜命中来源 → 优先级（数值越小越优先）
_SOURCE_RANK = {"material": 0, "exact": 1, "alias": 2, "tags": 3}


def _match_scene_items(scene, material, items, aliases, category):
    """四级匹配：材质直取(material) > 场景精确(exact) > 别名(alias) > tags 兜底(tags)。

    返回 (matched_items, source)：
      - matched_items：按优先级去重排序的条目列表（同层保持命中顺序）；
      - source：每镜命中来源，取「实际贡献了至少一个条目」的层级中优先级最高者
        （material > exact > alias > tags）；无任何命中为 "none"。
    """
    ranked, seen, hit_sources = [], set(), set()

    def add(item, source):
        iid = item.get("id")
        key = ("id", str(iid)) if iid is not None else ("obj", id(item))
        if key in seen:
            return  # 已被更高优先级层加入 → 不再计数该层来源
        seen.add(key)
        ranked.append((_SOURCE_RANK[source], source, item))
        hit_sources.add(source)

    # 0 材质直取：material 命中条目 name/id/alt（商品属性优先，即使场景不匹配）
    if material:
        m = str(material)
        for it in items:
            name = str(it.get("name", "") or "")
            alt = str(it.get("alt", "") or "")
            if m in name or m in str(it.get("id", "")) or name in m or (alt and m in alt):
                add(it, "material")
    # 1 场景精确：分镜 scene 与条目 scenes 词边界匹配（防跨词误中）
    if scene:
        for it in items:
            if any(_word_hit(str(x), scene) for x in (it.get("scenes") or [])):
                add(it, "exact")
    # 2 别名层：scene 命中 alias → targets(id) 直取条目
    if scene:
        for it in _alias_items(scene, aliases, items, category):
            add(it, "alias")
    # 3 tags 兜底：场景关键词命中条目 tags（无场景直接命中时的兜底）
    # 注意参数顺序：_tag_hit(term, item_tags) —— term=场景词，item_tags=条目 tags 列表
    if scene:
        for it in items:
            if _tag_hit(scene, it.get("tags") or []):
                add(it, "tags")

    ranked.sort(key=lambda r: r[0])
    source = "none"
    for s in ("material", "exact", "alias", "tags"):
        if s in hit_sources:
            source = s
            break
    return [it for _, _, it in ranked], source


# ---------- 各维度拼装 ----------
def _pick_lighting(shot, matched):
    """灯光词：优先取命中条目 light 文本中命中的 vocab 灯光词；兜底取 light 原文。≤3。"""
    texts = [str(it.get("light", "") or "") for it in matched] + [str(shot.get("light", "") or "")]
    joined = " ".join(texts)
    vocab = _load("vocab.json") or {}
    picks = []
    for v in vocab.get("lighting", []) or []:
        zh = str(v.get("zh", "") or "")
        if zh and any(seg in joined for seg in zh.split("/") if seg) and zh not in [p["zh"] for p in picks]:
            picks.append({"id": v.get("id", ""), "zh": zh})
    if not picks:
        for it in matched[:CAPS["lighting"]]:
            if it.get("light") and it["light"] not in [p["zh"] for p in picks]:
                picks.append({"id": "", "zh": it["light"]})
    return picks[:CAPS["lighting"]]


def _pick_by_vocab(shot, group, fields, cap):
    """运镜/镜头词：分镜字段文本命中 vocab 词；兜底取字段原文。≤cap。"""
    text = " ".join(str(shot.get(f, "") or "") for f in fields)
    vocab = _load("vocab.json") or {}
    picks = []
    for v in vocab.get(group, []) or []:
        zh = str(v.get("zh", "") or "")
        if zh and any(seg in text for seg in zh.split("/") if seg) and zh not in [p["zh"] for p in picks]:
            picks.append({"id": v.get("id", ""), "zh": zh})
    if not picks:
        for f in fields:
            raw = str(shot.get(f, "") or "").strip()
            if raw and raw not in [p["zh"] for p in picks]:
                picks.append({"id": "", "zh": raw})
    return picks[:cap]


def _m5_actions(profile):
    """取品类 profile 的 M5_motion_direction 动作库数组（兼容四种键名）。"""
    m5 = ((profile or {}).get("modules") or {}).get("M5_motion_direction") or {}
    for key in _M5_ACTION_KEYS:
        arr = m5.get(key) or []
        if arr:
            return [e for e in arr if isinstance(e, dict) and e.get("提示词写法")]
    return []


def _pick_motion(shot, category):
    """动作/材质动态写法：知识库按需注入（M5 动作库）。

    规则：
      - 读 knowledge/profiles/{category}.profile.json → M5_motion_direction
        （键兼容 model_actions/actions/food_actions/product_actions）；
      - 按 shot.action/motion 与条目"动作"字段的包含关系匹配，命中取该条
        "提示词写法"（专业提示词片段，非分镜原文切分），去重后 ≤5 条；
      - 无命中时取该品类动作库前 5 条兜底；
      - 动作库缺失/为空时降级返回 []，不抛异常。
    """
    actions = _m5_actions(_load_profile(category))
    if not actions:
        return []
    raw = " ".join(str(shot.get(f, "") or "") for f in ("action", "motion"))
    hits = []
    for e in actions:
        act = str(e.get("动作", "") or "").strip()
        if act and (act in raw or raw in act):
            hits.append(str(e.get("提示词写法", "") or "").strip())
    if not hits:
        hits = [str(e.get("提示词写法", "") or "").strip() for e in actions]
    out = []
    for h in hits:
        if h and h not in out:
            out.append(h)
    return out[:CAPS["motion"]]


def _build_negative(category, matched):
    """负面词：通用红线(必含) + vocab negative_general + 品类 profile M10(L1/L2) + 命中条目负面词。
    去重后 8~15 条（通用库本身 ≥17 条，故下限恒满足；上限截断）。"""
    vocab = _load("vocab.json") or {}
    pool = [str(n) for n in (vocab.get("negative_general", []) or []) if n]
    prof = _load_profile(category)
    if prof:
        m10 = ((prof.get("modules") or {}).get("M10_negative_prompts", {}) or {})
        for arr_key in ("level1_general", "level2_category"):
            for item in m10.get(arr_key, []) or []:
                if isinstance(item, dict) and item.get("负面词"):
                    pool.append(str(item["负面词"]))
    for it in matched:
        for n in (it.get("negative") or []):
            if n:
                pool.append(str(n))
    out = list(REQUIRED_NEGATIVES)
    seen = set(out)
    for n in pool:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:CAPS["negative_max"]]


def _assemble_shot(category, shot, scene, material, items, aliases):
    """单镜拼装：返回 (该镜素材, 命中来源)。命中来源按四级优先级取最高者。"""
    matched, source = _match_scene_items(scene, material, items, aliases, category)
    scene_light = [
        {"id": it.get("id", ""), "name": it.get("name", ""),
         "scenes": it.get("scenes", []), "light": it.get("light", ""),
         "prompt_zh": it.get("prompt_zh", "")}
        for it in matched[:CAPS["scene_light"]]
    ]
    zone = {
        "scene_light": scene_light,
        "lighting": _pick_lighting(shot, matched),
        "camera_movement": _pick_by_vocab(shot, "camera_movement", ["move"], CAPS["camera_movement"]),
        "lens_shot": _pick_by_vocab(shot, "lens_shot", ["lens"], CAPS["lens_shot"]),
        "motion": _pick_motion(shot, category),
        "negative": _build_negative(category, matched),
    }
    return zone, source


# ---------- 入口 ----------
def retrieve(category, shots=None, material="", type_name=""):
    """检索入口（契约）。

    :param category: 品类 id（clothing/beauty/food/...；未知品类降级为 {category}-scene-light.json，缺失则空）
    :param shots:    分镜列表，元素含 shot_no/scene/light/lens/move/motion/action（可省略）
    :param material: 商品材质（如 缎面；命中则直取对应条目）
    :param type_name: 视频类型（如 tvc；当前用于元信息，后续可接 M11 风格词）
    :return: {"per_shot": {shot_no: {...}}, "matched": {shot_no: "exact|alias|tags|material|none"},
              "meta": {...}}；任何文件缺失均不抛异常
    """
    shots = shots or []
    cat = (category or "").lower()
    aliases = _load_aliases()
    scene_file = CATEGORY_SCENE_FILE.get(cat, f"{cat}-scene-light.json")
    items = _scene_items(scene_file)

    per_shot, matched = {}, {}
    for s in shots:
        if not isinstance(s, dict):
            continue
        shot_no = s.get("shot_no")
        if shot_no is None:
            continue
        scene = str(s.get("scene", "") or "")
        per_shot[shot_no], matched[shot_no] = _assemble_shot(cat, s, scene, material, items, aliases)

    return {
        "per_shot": per_shot,
        "matched": matched,
        "meta": {"category": cat, "scene_file": scene_file, "shots": len(shots)},
    }


if __name__ == "__main__":
    demo = retrieve(
        "clothing",
        [
            {"shot_no": 1, "scene": "大理石美术馆", "lens": "35mm全景", "move": "缓慢推近", "motion": "转身360°、裙摆甩动液态光泽"},
            {"shot_no": 2, "scene": "街头", "lens": "50mm中景", "move": "跟拍", "motion": "自然行走"},
        ],
        "缎面",
        "tvc",
    )
    print(json.dumps(demo, ensure_ascii=False, indent=2))
