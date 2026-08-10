#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库 JSON Schema 校验器（战役3 · 工程化质量）

用法：
    python scripts/validate_kb.py             # 校验 knowledge/ 下全部 JSON
    python scripts/validate_kb.py <file>      # 只校验指定文件（相对项目根 / 相对 knowledge/ / 绝对路径均可）
    python scripts/validate_kb.py --strict    # 严格模式：warning 也报错，退出码 1

退出码：
    0 = 通过（有 warning 可容忍）
    1 = 有错误（或 --strict 模式下有 warning）

设计要点：
    1. 纯标准库实现（不依赖 jsonschema 等第三方包），开源即用；
    2. 内置一个极简 JSON Schema 校验器，支持 type/required/properties/items/
       minItems/maxItems/minLength/enum/uniqueItems/additionalProperties；
       未知关键字一律忽略（宽松模式，避免误伤现有数据）；
    3. 按文件名自动匹配 schema（*-scene-light.json / profiles/*.profile.json / 其余查表）；
    4. 除 schema 结构校验外，还做跨字段/跨文件完整性检查（见 check_* 函数）；
    5. Windows GBK 控制台兼容：stdout 强制 UTF-8 + errors=replace，中文不炸。

作者：战役3 · 知识库 schema 校验器
"""

import json
import os
import sys

# ---------- 输出编码兼容（Windows GBK 控制台 / 重定向均不崩溃） ----------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------- 路径常量 ----------
# 知识库单一数据源（开源改造第2步）：与 config.KNOWLEDGE_DIR 同规则——
# 环境变量 KNOWLEDGE_DIR 优先 → 包内 knowledge/（src/ecommerce_video/knowledge，分发即自带）
# → 项目根 knowledge/（源码检出兜底）。根目录不再维护双副本。
try:
    from ecommerce_video import config as _cfg
    _KD = getattr(_cfg, "KNOWLEDGE_DIR", None)
    KNOW_DIR = str(_KD) if _KD else os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "knowledge")
except Exception:
    KNOW_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "knowledge")
SCHEMA_DIR = os.path.join(KNOW_DIR, "schema")                       # schema 目录

# 品类别名 → 对应 scene-light 文件（跨文件检查 b 用）
ALIAS_CATEGORY_FILE = {
    "clothing": "fabric-scene-light.json",
    "beauty": "beauty-scene-light.json",
    "food": "food-scene-light.json",
}

# 精确文件名 → schema 文件名（*scene-light.json 与 *.profile.json 走规则匹配，不在此表）
EXACT_SCHEMA_MAP = {
    "category-profiles.json": "category-profiles.schema.json",
    "types.json": "types.schema.json",
    "vocab.json": "vocab.schema.json",
    "compliance.json": "compliance.schema.json",
    "models.json": "models.schema.json",
    "scene-aliases.json": "scene-aliases.schema.json",
    "index.json": "index.schema.json",
}

# 公共头字段（所有知识库 JSON 都应包含）
COMMON_HEADER = ("schema_version", "updated", "note")


# =====================================================================
# 一、极简 JSON Schema 校验器（标准库实现）
# =====================================================================

def _type_ok(value, type_name):
    """判断 value 是否符合单个类型名。注意：bool 是 int 的子类，需排除。"""
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return True  # 未知类型名：宽松放过


def _path_join(path, key):
    """拼接 JSON 路径用于报错定位。"""
    if not path:
        return "$." + str(key)
    return path + "." + str(key)


def _path_index(path, index):
    """拼接数组下标路径。"""
    if not path:
        return "$[%d]" % index
    return path + "[%d]" % index


def validate_schema(data, schema, path="", errors=None):
    """
    递归校验 data 是否符合 schema（draft-07 子集）。
    支持关键字：type / required / properties / items / minItems / maxItems /
               minLength / maxLength / enum / uniqueItems / additionalProperties(bool 或 schema)。
    未知关键字忽略。错误写入 errors 列表，元素为 (path, message)。
    """
    if errors is None:
        errors = []
    # 非对象 schema（如布尔/非法）直接放过
    if not isinstance(schema, dict):
        return errors

    # ---- type：字符串或数组（多选一） ----
    type_spec = schema.get("type")
    if type_spec is not None:
        allowed = type_spec if isinstance(type_spec, list) else [type_spec]
        if not any(_type_ok(data, t) for t in allowed):
            errors.append((path or "$",
                           "类型错误：期望 %s，实际为 %s" % ("/".join(allowed), type(data).__name__)))
            # 类型不对就不深入子结构，避免级联误报
            return errors

    # ---- enum：枚举值 ----
    if "enum" in schema and data not in schema["enum"]:
        errors.append((path or "$", "值 %r 不在允许的枚举 %s 中" % (data, schema["enum"])))

    # ---- 字符串长度 ----
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append((path or "$", "字符串长度 %d 小于 minLength=%d" % (len(data), schema["minLength"])))
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append((path or "$", "字符串长度 %d 大于 maxLength=%d" % (len(data), schema["maxLength"])))

    # ---- 对象 ----
    if isinstance(data, dict):
        props = schema.get("properties", {})
        # required：必填字段
        for req in schema.get("required", []):
            if req not in data:
                errors.append((path or "$", "缺少必填字段 '%s'" % req))
        # properties：逐个校验已存在字段
        for key, subschema in props.items():
            if key in data:
                validate_schema(data[key], subschema, _path_join(path, key), errors)
        # additionalProperties：false=禁止额外字段；dict=额外字段按该 schema 校验
        ap = schema.get("additionalProperties")
        if ap is not None:
            known = set(props.keys())
            for key in data:
                if key in known:
                    continue
                if ap is False:
                    errors.append((_path_join(path, key), "不允许的额外字段（additionalProperties:false）"))
                elif isinstance(ap, dict):
                    validate_schema(data[key], ap, _path_join(path, key), errors)

    # ---- 数组 ----
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append((path or "$", "数组长度 %d 小于 minItems=%d" % (len(data), schema["minItems"])))
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append((path or "$", "数组长度 %d 大于 maxItems=%d" % (len(data), schema["maxItems"])))
        if schema.get("uniqueItems"):
            seen = []
            dup = None
            for item in data:
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    dup = item
                    break
                seen.append(key)
            if dup is not None:
                errors.append((path or "$", "数组存在重复元素（uniqueItems）：%r" % (dup,)))
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for i, item in enumerate(data):
                validate_schema(item, items_schema, _path_index(path, i), errors)

    return errors


# =====================================================================
# 二、文件发现与 schema 匹配
# =====================================================================

def schema_name_for(relpath):
    """按文件名（相对 knowledge/ 的路径）返回对应 schema 文件名，找不到返回 None。"""
    base = os.path.basename(relpath)
    if base.endswith("-scene-light.json"):
        return "scene-light.schema.json"
    if base.endswith(".profile.json"):
        return "profile.schema.json"
    return EXACT_SCHEMA_MAP.get(base)


def collect_json_files():
    """收集待校验文件（相对 knowledge/ 的路径列表）：顶层 *.json + profiles/*.json，排除 schema/ 目录。"""
    files = []
    for name in sorted(os.listdir(KNOW_DIR)):
        if name.endswith(".json") and os.path.isfile(os.path.join(KNOW_DIR, name)):
            files.append(name)
    prof_dir = os.path.join(KNOW_DIR, "profiles")
    if os.path.isdir(prof_dir):
        for name in sorted(os.listdir(prof_dir)):
            if name.endswith(".json") and os.path.isfile(os.path.join(prof_dir, name)):
                files.append(os.path.join("profiles", name))
    return files


def resolve_input(arg):
    """
    解析命令行传入的文件参数 → 相对 knowledge/ 的路径。
    支持三种写法：相对项目根（knowledge/xxx.json）、相对 knowledge/（xxx.json）、绝对路径。
    找不到返回 None。
    """
    candidates = []
    if os.path.isabs(arg):
        candidates.append(arg)
    else:
        candidates.append(os.path.join(os.getcwd(), arg))
        candidates.append(os.path.join(KNOW_DIR, arg))
    for c in candidates:
        if os.path.isfile(c):
            return os.path.relpath(c, KNOW_DIR)
    return None


# =====================================================================
# 三、单文件级扩展检查（schema 表达不了的跨字段约束）
# =====================================================================

def extra_file_checks(relpath, data):
    """返回该文件额外的 (path, message) 错误列表。"""
    errors = []
    base = os.path.basename(relpath)
    # scene-light 文件：item.group 必须存在于顶层 groups 的某个 key；item.id 全文件唯一
    if base.endswith("-scene-light.json"):
        groups = data.get("groups")
        items = data.get("items")
        if isinstance(groups, dict) and isinstance(items, list):
            seen = set()
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                g = item.get("group")
                if isinstance(g, str) and g not in groups:
                    errors.append((_path_index("$.items", i) + ".group",
                                   "分组 '%s' 不存在于顶层 groups（现有分组：%s）"
                                   % (g, "、".join(sorted(groups.keys())))))
                iid = item.get("id")
                if isinstance(iid, str):
                    if iid in seen:
                        errors.append((_path_index("$.items", i) + ".id",
                                       "条目 id 重复：'%s'" % iid))
                    seen.add(iid)
    return errors


# =====================================================================
# 四、跨文件完整性检查（a~e）
# =====================================================================

def _load(relpath):
    """读取 knowledge/ 下 JSON，返回 (data, error)。"""
    abspath = os.path.join(KNOW_DIR, relpath)
    try:
        with open(abspath, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as exc:
        return None, "读取/解析失败：%s" % exc


def check_a_index_files(errors_by_file, warnings):
    """
    a. index.json 的 files 列表里每个 file 字段对应的文件必须真实存在。
       支持通配模式（如 profiles/*.profile.json → 至少匹配 1 个真实文件）。
    """
    data, err = _load("index.json")
    if err:
        errors_by_file.setdefault("index.json", []).append(("$", err))
        return
    for i, entry in enumerate(data.get("files", [])):
        if not isinstance(entry, dict) or "file" not in entry:
            errors_by_file.setdefault("index.json", []).append(
                (_path_index("$.files", i), "files[%d] 缺少 file 字段" % i))
            continue
        f = entry["file"]
        target = os.path.join(KNOW_DIR, f)
        if "*" in f or "?" in f:
            if not glob_any(target):
                errors_by_file.setdefault("index.json", []).append(
                    (_path_index("$.files", i) + ".file", "通配模式 '%s' 未匹配到任何真实文件" % f))
        elif not os.path.isfile(target):
            errors_by_file.setdefault("index.json", []).append(
                (_path_index("$.files", i) + ".file", "文件不存在：%s" % f))


def glob_any(pattern):
    """判断通配模式是否至少匹配一个文件（延迟 import glob）。"""
    import glob
    return bool(glob.glob(pattern))


def check_b_alias_targets(errors_by_file, warnings):
    """
    b. scene-aliases.json 每个 alias 的 category 若为 clothing/beauty/food，
       targets 的每个 id 必须存在于对应品类 scene-light 文件的 items[].id 中。
    """
    data, err = _load("scene-aliases.json")
    if err:
        errors_by_file.setdefault("scene-aliases.json", []).append(("$", err))
        return
    for i, alias in enumerate(data.get("aliases", [])):
        if not isinstance(alias, dict):
            continue
        cat = alias.get("category")
        targets = alias.get("targets")
        if cat not in ALIAS_CATEGORY_FILE or not isinstance(targets, list):
            continue
        sl_data, sl_err = _load(ALIAS_CATEGORY_FILE[cat])
        if sl_err:
            errors_by_file.setdefault("scene-aliases.json", []).append(
                (_path_index("$.aliases", i), "读取 %s 失败：%s" % (ALIAS_CATEGORY_FILE[cat], sl_err)))
            continue
        valid_ids = set()
        for item in sl_data.get("items", []):
            if isinstance(item, dict) and "id" in item:
                valid_ids.add(item["id"])
        for j, tid in enumerate(targets):
            if tid not in valid_ids:
                errors_by_file.setdefault("scene-aliases.json", []).append(
                    (_path_index("$.aliases", i) + ".targets[%d]" % j,
                     "alias '%s' 的 target '%s' 不存在于 %s 的 items[].id 中"
                     % (alias.get("alias", "?"), tid, ALIAS_CATEGORY_FILE[cat])))


def check_c_default_model(errors_by_file, warnings):
    """
    c. models.json 的 default_model 必须存在于 models[].id 中。
    """
    data, err = _load("models.json")
    if err:
        errors_by_file.setdefault("models.json", []).append(("$", err))
        return
    dm = data.get("default_model")
    ids = [m.get("id") for m in data.get("models", []) if isinstance(m, dict)]
    if dm not in ids:
        errors_by_file.setdefault("models.json", []).append(
            ("$.default_model", "default_model '%s' 不存在于 models[].id（现有：%s）"
             % (dm, "、".join(ids))))


def check_d_profiles_consistency(errors_by_file, warnings):
    """
    d. 14 个 profiles 文件与 category-profiles.json 的 profiles key 一致
       （双向：每个 profile 文件都有对应 key，每个 key 都有对应 profile 文件）。
    """
    cp_data, cp_err = _load("category-profiles.json")
    keys_in_cp = set()
    if cp_err:
        errors_by_file.setdefault("category-profiles.json", []).append(("$", cp_err))
    elif isinstance(cp_data, dict) and isinstance(cp_data.get("profiles"), dict):
        keys_in_cp = set(cp_data["profiles"].keys())

    prof_dir = os.path.join(KNOW_DIR, "profiles")
    cats_in_files = set()
    file_map = {}  # category -> 文件名
    if os.path.isdir(prof_dir):
        for name in sorted(os.listdir(prof_dir)):
            if not name.endswith(".profile.json"):
                continue
            d, e = _load(os.path.join("profiles", name))
            if e:
                errors_by_file.setdefault(os.path.join("profiles", name), []).append(("$", e))
                continue
            cat = d.get("category") if isinstance(d, dict) else None
            if cat is None:
                errors_by_file.setdefault(os.path.join("profiles", name), []).append(
                    ("$", "profile 缺少 category 字段（应与文件名前缀一致）"))
                continue
            cats_in_files.add(cat)
            file_map.setdefault(cat, name)

    # 报告侧：把不一致记到 category-profiles.json 名下（作为被校验文件时可见）
    missing_in_cp = sorted(cats_in_files - keys_in_cp)   # 有 profile 文件但 category-profiles 无 key
    missing_in_files = sorted(keys_in_cp - cats_in_files)  # 有 key 但无 profile 文件
    if missing_in_cp:
        errors_by_file.setdefault("category-profiles.json", []).append(
            ("$.profiles", "存在 profile 文件但 category-profiles.json 缺少对应 key：%s"
             % "、".join(missing_in_cp)))
    if missing_in_files:
        errors_by_file.setdefault("category-profiles.json", []).append(
            ("$.profiles", "category-profiles.json 存在 key 但 profiles/ 下无对应文件：%s"
             % "、".join(missing_in_files)))


# 跨文件检查注册表：{源文件相对路径（触发时校验）: 检查函数}
CROSS_CHECKS = [
    ("index.json", check_a_index_files),
    ("scene-aliases.json", check_b_alias_targets),
    ("models.json", check_c_default_model),
    ("category-profiles.json", check_d_profiles_consistency),  # 触发条件见下方逻辑
]


def run_cross_checks(validated_set, errors_by_file, warnings):
    """
    运行跨文件检查。validated_set：本次实际校验的文件集合（相对 knowledge/ 路径）。
    原则：只有涉及的文件被校验时才跑对应检查，保证单文件模式也有意义。
    """
    # a/b/c：源文件在校验集合里就触发
    for src, fn in CROSS_CHECKS[:3]:
        if src in validated_set:
            fn(errors_by_file, warnings)
    # d：category-profiles.json 或任意 profile 文件被校验时触发
    if "category-profiles.json" in validated_set or any(
            p.endswith(".profile.json") for p in validated_set):
        check_d_profiles_consistency(errors_by_file, warnings)
    # e：scene-light 文件 id 唯一已并入 extra_file_checks（每个 scene-light 文件校验时执行）


# =====================================================================
# 五、主流程
# =====================================================================

def validate_one(relpath, errors_by_file, warnings):
    """校验单个文件：schema 结构 + 单文件扩展检查。返回错误数。"""
    abspath = os.path.join(KNOW_DIR, relpath)
    try:
        with open(abspath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        errors_by_file.setdefault(relpath, []).append(("$", "JSON 解析失败：%s" % exc))
        return 1

    sname = schema_name_for(relpath)
    if sname is None:
        warnings.append("未找到匹配的 schema，跳过结构校验：%s" % relpath)
        return 0
    spath = os.path.join(SCHEMA_DIR, sname)
    if not os.path.isfile(spath):
        errors_by_file.setdefault(relpath, []).append(("$", "schema 文件缺失：%s" % sname))
        return 1
    with open(spath, "r", encoding="utf-8") as f:
        schema = json.load(f)

    errors = []
    validate_schema(data, schema, "$", errors)
    errors += extra_file_checks(relpath, data)
    if errors:
        errors_by_file[relpath] = errors
    return len(errors)


def print_result(relpath, errs, warnings):
    """打印单文件结果行 + 错误详情。"""
    display = os.path.join("knowledge", relpath).replace(os.sep, "/")
    if errs:
        print("❌ %s" % display)
        for path, msg in errs:
            print("     %s : %s" % (path, msg))
    else:
        print("✅ %s" % display)


def main(argv):
    args = [a for a in argv if a != "--strict"]  # 提取 --strict
    strict = len(args) != len(argv)
    files_arg = [a for a in argv if a != "--strict"]

    if len(files_arg) > 1:
        print("用法：python scripts/validate_kb.py [--strict] [<file>]")
        return 2

    # 确定本次校验的文件集合
    if files_arg:
        rel = resolve_input(files_arg[0])
        if rel is None:
            print("❌ 找不到指定文件：%s（应在 knowledge/ 目录下）" % files_arg[0])
            return 1
        validated = [rel]
    else:
        validated = collect_json_files()

    if not validated:
        print("❌ knowledge/ 目录下未发现任何 JSON 文件")
        return 1

    errors_by_file = {}   # relpath -> [(path, message)]
    warnings = []

    # 逐个校验
    for relpath in validated:
        validate_one(relpath, errors_by_file, warnings)

    # 跨文件完整性检查
    run_cross_checks(set(validated), errors_by_file, warnings)

    # 打印结果（按输入顺序）
    print("")
    for relpath in validated:
        print_result(relpath, errors_by_file.get(relpath, []), warnings)

    # 汇总
    total = len(validated)
    failed = sum(1 for r in validated if r in errors_by_file)
    passed = total - failed
    print("")
    print("========== 汇总 ==========")
    print("校验文件：%d 个（✅ %d / ❌ %d）" % (total, passed, failed))
    if warnings:
        print("警告：%d 条（可容忍，--strict 下视为错误）" % len(warnings))
        for w in warnings:
            print("  ⚠ %s" % w)
    if failed:
        print("结果：❌ 存在 %d 个文件未通过，请按上面错误详情修复" % failed)
        return 1
    if strict and warnings:
        print("结果：❌ 严格模式下警告视为错误（%d 条）" % len(warnings))
        return 1
    print("结果：✅ 全部通过" + ("（有 %d 条警告）" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
