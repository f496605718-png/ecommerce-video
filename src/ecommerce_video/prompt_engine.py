#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 提示词生成引擎：分镜参数 →(每镜精准素材+元提示词+LLM)→ jobs.json。

v2.0 调用层改造（战役1）：素材从"全量注入"改为"每镜精准注入"——
  - 词源检索统一走 retriever.retrieve()（scripts/retriever.py，契约见下），
    引擎不再 glob 全量读知识库、不再把 4000-6000 字素材一次性塞给 LLM；
  - 元提示词结构：头部（全局一次）+ 【规则区】7条硬约束 + 分镜总览 + 每镜素材区（逐镜注入）+ 输出要求；
  - 整片元提示词长度目标 ≤2500字×镜数（原来 4000-6000 字全量注入）。

retriever 契约：
    from retriever import retrieve
    result = retrieve(category, shots, material, type_name)
    result["per_shot"][shot_no] = {"scene_light":[...≤3], "lighting":[...≤3],
        "camera_movement":[...≤2], "lens_shot":[...≤2], "motion":[...≤5], "negative":[...8-15]}
    result["meta"] = {...}   # 调试用（品类/场景文件/镜数）
  （M11 风格特征词不在 retriever 契约内，由本引擎做一次定向读取注入头部，见 _style_dna_words）

说明：本文件为 Workflow API 的提示词层实现，cmd_* 函数供 cli.py 统一入口路由调用。

用法（CLI 统一入口，推荐）：
  ecommerce-video gen storyboard.json -o jobs.json   # 生成（需 LLM key）
  ecommerce-video dry storyboard.json                # 干跑：只输出组装好的元提示词（调试用）
  ecommerce-video validate jobs.json                 # 校验生成的 jobs.json（规则检查）
（旧入口 `python -m ecommerce_video.prompt_engine <cmd>` 保留兼容，推荐改用 ecommerce-video）

storyboard.json 格式：
{
  "project":"projA","sku":"sku1","category":"clothing",
  "sku_desc":"香槟色缎面吊带连衣裙","material":"缎面","model_desc":"25岁气质优雅亚裔女性",
  "type":"tvc",
  "shots":[
    {"shot_no":1,"scene":"大理石美术馆","light":"柔光箱+暖色轮廓光","lens":"35mm全景",
     "move":"缓慢推近","action":"转身360°","motion":"裙摆甩动液态光泽","duration":10},
    ...
  ]
}
"""
import json
import re
import sys
from pathlib import Path

# Windows GBK 兼容
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import config
from ecommerce_video.workflow import Workflow  # 模块级导入：cmd_gen/cmd_dry/cmd_validate 直接调用时不再 NameError（cli.py 兼容 shim 保留，冗余但无害）

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # src 布局：上上级=src，再上一级=项目根
KNOWLEDGE = config.KNOWLEDGE_DIR
TEMPLATE = Path(__file__).resolve().parent / "prompt_gen_template.md"  # 包内随模板文件一起分发

# 模板内置每镜素材块数量（1-9 镜；超出部分由 build_prompt 按相同格式动态追加）
SHOT_BLOCK_COUNT = 9

# 每镜素材字段：key / 连接符 / 中文名（顺序即模板每镜块内顺序）
_ZONE_FIELDS = [
    ("scene_light", "；", "场景光线"),
    ("lighting", "、", "灯光词"),
    ("camera_movement", "、", "运镜词"),
    ("lens_shot", "、", "镜头词"),
    ("motion", "；", "动作/材质动态写法"),
    ("negative", "、", "负面词"),
]

# 超过 9 镜时的动态追加块（与模板内 1-9 镜块格式完全一致）
_EXTRA_SHOT_TMPL = """### 镜{n} · {label}
- 场景光线（≤3条）：{scene_light}
- 灯光词（≤3个）：{lighting}
- 运镜词（≤2个）：{camera_movement}
- 镜头词（≤2个）：{lens_shot}
- 动作/材质动态写法（≤5条）：{motion}
- 负面词（8-15条）：{negative}
"""


# ---------- 词源提取（调用层：统一走 retriever，不再 glob 全量加载） ----------
def extract_sources(category: str, material: str, type_name: str, shots: list = None) -> dict:
    """按品类/材质/类型/分镜逐镜取词源（每镜精准注入，非全量）。

    内部必须走 retriever.retrieve()；若 scripts/retriever.py 缺失则报清晰错误提示先创建。
    """
    if not shots:
        raise ValueError("storyboard 缺少 shots（至少 1 镜），无法进行每镜精准注入")
    try:
        from ecommerce_video.retriever import retrieve
    except ImportError as e:
        raise RuntimeError(
            "未找到 scripts/retriever.py：本版本（v2.0 每镜精准注入）必须依赖检索层，请先创建 retriever.py。\n"
            "契约：retrieve(category, shots, material, type_name) -> "
            "result['per_shot'][shot_no] = {scene_light≤3, lighting≤3, camera_movement≤2, "
            "lens_shot≤2, motion≤5, negative 8-15}；另含 result['matched'][shot_no] 命中层信息。"
        ) from e
    return retrieve(category, shots, material, type_name)


def _style_dna_words(category: str, type_name: str) -> str:
    """M11 类型风格特征词（头部全局一次性注入）。

    注意：retriever 契约不含该键（其 docstring 明示 type_name 预留、不参与素材组装），
    故此处做一次**定向读取**：只取命中的那一组 style_dna_words 字符串，绝不注入全量。
    """
    cat = (category or "").lower().strip()
    if not cat:
        return ""
    prof_file = KNOWLEDGE / "profiles" / f"{cat}.profile.json"
    try:
        prof = json.loads(prof_file.read_text(encoding="utf-8-sig"))
        seqs = (prof.get("modules", {}).get("M11_type_adaptation", {}) or {}).get("sequences") or []
    except Exception:
        return ""
    for t in seqs:
        if isinstance(t, dict):
            if type_name in str(t.get("type", "")) or type_name in str(t.get("icon", "")):
                return str(t.get("style_dna_words", "") or "")
    return ""


def _lookup_zone(per_shot: dict, shot_no) -> dict:
    """按镜号取该镜词源；容错 int/str 键（retriever 以 shot_no 原类型为键）。"""
    if not per_shot:
        return {}
    candidates = []
    if isinstance(shot_no, str):
        candidates = [shot_no] + ([int(shot_no)] if shot_no.isdigit() else [])
    else:
        candidates = [shot_no, str(shot_no)]
    for key in candidates:
        if key in per_shot:
            zone = per_shot[key]
            return zone if isinstance(zone, dict) else {}
    return {}


def _item_text(v) -> str:
    """素材条目文本归一：字符串直取；字典取 zh→name→prompt_zh→light→text 首个非空字段。

    兼容 retriever 不同版本：新版灯光/运镜/镜头词为 {id,zh} 字典，旧版为字符串；
    场景光线恒为 {name,prompt_zh} 字典（scene_light 单独处理）。
    """
    if isinstance(v, dict):
        for key in ("zh", "name", "prompt_zh", "light", "text"):
            val = v.get(key)
            if val:
                return str(val)
        return ""
    return str(v)


def _zone_value(zone: dict, key: str, join: str) -> str:
    """渲染某镜某字段为一行文本（scene_light 条目为 {name,prompt_zh} 字典，其余为字符串/字典兼容）。"""
    vals = (zone or {}).get(key) or []
    if not vals:
        return "（无匹配，按场景常识自行组织）"
    if key == "scene_light":
        parts = []
        for v in vals:
            if isinstance(v, dict):
                name = str(v.get("name", "") or "")
                prompt = str(v.get("prompt_zh", "") or "")
                parts.append(f"{name}：{prompt}" if name else prompt)
            else:
                parts.append(str(v))
        return join.join(p for p in parts if p)
    return join.join(_item_text(v) for v in vals if _item_text(v))


def _shot_overview(shots: list) -> str:
    """分镜总览：每镜一行（镜号/场景/镜头/运镜/动作/材质动态）。"""
    lines = []
    for s in shots:
        if not isinstance(s, dict):
            continue
        no = s.get("shot_no", "?")
        scene = s.get("scene", "") or ""
        lens = s.get("lens", "") or ""
        move = s.get("move", "") or ""
        action = s.get("action", "") or ""
        motion = s.get("motion", "") or ""
        lines.append(f"- 镜{no}：{scene}｜{lens}｜{move}｜{action}｜{motion}")
    return "\n".join(lines)


def _prune_unused_shot_blocks(tmpl: str, shot_nos: set) -> str:
    """移除模板中未被 storyboard 使用的镜块（按镜号，从"### 镜{n}"到下个块/段落头/结尾）。"""
    for n in range(1, SHOT_BLOCK_COUNT + 1):
        if n in shot_nos:
            continue
        tmpl = re.sub(
            rf"### 镜{n}\b.*?(?=### 镜\d|\n## |\Z)",
            "",
            tmpl,
            flags=re.S,
        )
    return tmpl


def _append_extra_shot_blocks(tmpl: str, shots: list, per_shot: dict) -> str:
    """超过 9 镜 / 非 1-9 整数镜号：按相同格式动态追加素材块（插到"## 输出要求"之前）。"""
    extras = []
    for s in shots:
        if not isinstance(s, dict):
            continue
        no = s.get("shot_no")
        if isinstance(no, int) and 1 <= no <= SHOT_BLOCK_COUNT:
            continue
        if isinstance(no, str) and no.isdigit() and 1 <= int(no) <= SHOT_BLOCK_COUNT:
            continue
        zone = _lookup_zone(per_shot, no)
        extras.append(_EXTRA_SHOT_TMPL.format(
            n=no,
            label=str(s.get("scene", "") or ""),
            scene_light=_zone_value(zone, "scene_light", "；"),
            lighting=_zone_value(zone, "lighting", "、"),
            camera_movement=_zone_value(zone, "camera_movement", "、"),
            lens_shot=_zone_value(zone, "lens_shot", "、"),
            motion=_zone_value(zone, "motion", "；"),
            negative=_zone_value(zone, "negative", "、"),
        ))
    if not extras:
        return tmpl
    return tmpl.replace("## 输出要求", "\n".join(extras) + "\n## 输出要求", 1)


def build_prompt(sb: dict) -> str:
    """组装元提示词（头部全局一次 + 每镜精准注入素材区）。"""
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    shots = sb.get("shots") or []
    if not shots:
        raise ValueError("storyboard 缺少 shots（至少 1 镜），无法进行每镜精准注入")

    sources = extract_sources(
        sb.get("category", ""), sb.get("material", ""), sb.get("type", ""), shots
    )
    per_shot = sources.get("per_shot") or {}

    # 头部（全局一次）
    fills = {
        "category": sb.get("category", ""),
        "sku_desc": sb.get("sku_desc", ""),
        "material": sb.get("material", ""),
        "model_desc": sb.get("model_desc", ""),
        "type": sb.get("type", ""),
        "style_dna_words": _style_dna_words(sb.get("category", ""), sb.get("type", "")),
        "shot_overview": _shot_overview(shots),
    }

    # 每镜素材区（逐镜注入）
    shot_nos = set()
    for s in shots:
        if not isinstance(s, dict):
            continue
        no = s.get("shot_no")
        if isinstance(no, int) and 1 <= no <= SHOT_BLOCK_COUNT:
            shot_nos.add(no)
        elif isinstance(no, str) and no.isdigit() and 1 <= int(no) <= SHOT_BLOCK_COUNT:
            shot_nos.add(int(no))
    for n in range(1, SHOT_BLOCK_COUNT + 1):
        zone = _lookup_zone(per_shot, n)
        fills[f"shot_{n}_scene_label"] = ""
        for key, join, _cn in _ZONE_FIELDS:
            fills[f"shot_{n}_{key}"] = _zone_value(zone, key, join)
    # 镜块标签：取该镜 scene（供 LLM 对应镜号）
    for s in shots:
        if not isinstance(s, dict):
            continue
        no = s.get("shot_no")
        n = int(no) if isinstance(no, str) and no.isdigit() else no
        if isinstance(n, int) and 1 <= n <= SHOT_BLOCK_COUNT:
            fills[f"shot_{n}_scene_label"] = str(s.get("scene", "") or "")

    # 组装：先删未用镜块，再补超限镜块，最后统一替换占位符
    tmpl = _prune_unused_shot_blocks(tmpl, shot_nos)
    tmpl = _append_extra_shot_blocks(tmpl, shots, per_shot)
    for k, v in fills.items():
        tmpl = tmpl.replace("{{" + k + "}}", str(v))
    # 兜底：清掉任何残留占位符（模板与代码不一致时防泄漏给 LLM）
    tmpl = re.sub(r"\{\{[^}]*\}\}", "", tmpl)
    return tmpl


# ---------- LLM 调用（OpenAI 兼容 chat/completions） ----------
def call_llm(system_prompt: str, user_prompt: str) -> str:
    import requests
    from ecommerce_video.http_utils import request_with_retry
    headers = {
        "Authorization": f"Bearer {config.TEXT_LLM_API_KEY or config.VISION_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.TEXT_LLM_MODEL or config.VISION_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
    }
    url = (config.TEXT_LLM_API_BASE or config.VISION_API_BASE).rstrip("/") + "/chat/completions"
    resp = request_with_retry("POST", url, headers=headers, json=body)
    if resp.status_code in (401, 403):
        raise RuntimeError("LLM 鉴权失败：请检查 .env 中 TEXT_LLM_API_KEY/VISION_API_KEY")
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_json_response(text: str) -> list:
    """LLM 可能带 markdown 代码块/前后杂文，提取 JSON 数组。"""
    text = text.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        text = m.group(0)
    return json.loads(text)


# ---------- 结果校验（规则检查，防 LLM 漂移） ----------
def validate_jobs(jobs: list, sb: dict) -> list:
    """返回问题列表；空=通过。"""
    issues = []
    for j in jobs:
        p = j.get("prompt", "")
        if "与参考图完全一致" not in p:
            issues.append(f"shot{j.get('shot_no')}: 缺 L1 锚定（'与参考图完全一致'）")
        if re.search(r"[a-zA-Z]{2,}", p.replace("TVC", "")):
            issues.append(f"shot{j.get('shot_no')}: 含英文词（规则3）")
        if re.search(r"\d+(cm|mm|克|g|斤|#)", p):
            issues.append(f"shot{j.get('shot_no')}: 含外观参数（规则2）")
        if len(p) > 160:
            issues.append(f"shot{j.get('shot_no')}: 提示词过长({len(p)}字>160)")
        if len(p) < 40:
            issues.append(f"shot{j.get('shot_no')}: 提示词过短({len(p)}字<40)")
        neg = j.get("negative_prompt", "")
        for must in ("形变扭曲", "多余肢体", "手指变形", "水印"):
            if must not in neg:
                issues.append(f"shot{j.get('shot_no')}: 负面词缺'{must}'")
    return issues


# ---------- CLI（薄封装：逻辑统一走 workflow.Workflow API，输出格式与旧版完全一致） ----------
def cmd_gen(sb_path: str, out: str):
    sb = json.loads(Path(sb_path).read_text(encoding="utf-8-sig"))
    if not (config.TEXT_LLM_API_KEY or config.VISION_API_KEY):
        print("❌ 未配置 LLM key（TEXT_LLM_API_KEY 或 VISION_API_KEY），先补 .env")
        sys.exit(1)
    w = Workflow(category=sb.get("category", ""), material=sb.get("material", ""),
                 type_name=sb.get("type", ""))
    print("组装元提示词...")
    meta = w.build_meta_prompt(sb)  # 只组装不调 LLM（与旧版打印顺序一致）
    print("调用 LLM 生成...")
    result = w.generate_prompts(sb, llm_prompt=meta)  # 内部 call_llm + validate_jobs
    jobs, issues = result["jobs"], result["issues"]
    if issues:
        print("⚠️ 校验未通过：")
        for i in issues:
            print("  -", i)
        print("（可重跑；如需强制输出加 --force 后续版本）")
        # 仍输出便于人工修正
    out_path = Path(out)
    out_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已生成 {out_path}（{len(jobs)} 镜；问题 {len(issues)} 条）")


def cmd_dry(sb_path: str):
    sb = json.loads(Path(sb_path).read_text(encoding="utf-8-sig"))
    w = Workflow(category=sb.get("category", ""), material=sb.get("material", ""),
                 type_name=sb.get("type", ""))
    print(w.build_meta_prompt(sb))
    # 调试：每镜素材命中层（stderr，不进元提示词，不影响 stdout 输出）
    try:
        src = w.retrieve_sources(sb.get("shots") or [])
        matched = src.get("matched") or src.get("meta") or {}
        if matched:
            print(f"# 素材命中层: {json.dumps(matched, ensure_ascii=False)}", file=sys.stderr)
    except Exception:
        pass


def cmd_validate(jobs_path: str):
    jobs = json.loads(Path(jobs_path).read_text(encoding="utf-8-sig"))
    issues = Workflow().validate_prompts(jobs)
    print("校验结果:", issues if issues else "✅ 全部通过")


if __name__ == "__main__":
    from ecommerce_video.workflow import Workflow  # 薄壳入口：CLI 只做参数解析与输出，逻辑全走 workflow API

    args = sys.argv[1:]
    if args and args[0] == "gen":
        # 支持：gen storyboard.json -o jobs.json | gen storyboard.json jobs.json
        rest = args[1:]
        sb_path = None
        out = "jobs.json"
        i = 0
        while i < len(rest):
            if rest[i] == "-o" and i + 1 < len(rest):
                out = rest[i + 1]
                i += 2
            elif rest[i] == "--output" and i + 1 < len(rest):
                out = rest[i + 1]
                i += 2
            else:
                sb_path = rest[i]
                i += 1
        if sb_path:
            cmd_gen(sb_path, out)
        else:
            print("用法: python scripts/prompt_engine.py gen storyboard.json -o jobs.json")
    elif args and args[0] == "dry" and len(args) >= 2:
        cmd_dry(args[1])
    elif args and args[0] == "validate" and len(args) >= 2:
        cmd_validate(args[1])
    else:
        print(__doc__)
