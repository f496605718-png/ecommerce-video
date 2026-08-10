#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力感知模块（战役2：让 models.json 的能力参数从"文档映射"变为"运行时生效"）。

作用：
  - get_model_capability()：运行时读取 knowledge/models.json，按 provider_id 返回模型能力；
  - validate_job()：按模型能力校验单个生成任务（时长/参考图/分辨率/中文提示词/多参考图）；
  - flow_adjustments()：返回流程适配建议，供 prompt_engine / batch_generate 动态适配。

设计约束：
  - 只读本地 knowledge/models.json（json 标准库直接读，无网络、无第三方依赖）；
  - provider 匹配：先精确匹配 id；"seedance" 等前缀做家族兼容（seedance-2.0/seedance/seedance-2.5 均属 seedance 系）；
  - 模型缺失 / 文件缺失 / 字段为空 → 一律降级为保守默认值，绝不抛异常、绝不崩流程；
  - Windows GBK 控制台兼容（stdout/stderr 统一 UTF-8）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------- Windows GBK 兼容：控制台输出统一 UTF-8 ----------
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ---------- 配置加载（包式导入：src 布局下统一走 ecommerce_video 包） ----------
try:
    from ecommerce_video import config as _cfg
except Exception:
    _cfg = None  # 配置不可用时全部走内置默认，不影响本模块可用性

# ---------- 保守默认能力（找不到模型 / 字段为空时的兜底） ----------
_DEFAULT_CAPS = {
    "ref_images": 1,               # 参考图上限：未知时最保守取 1
    "duration_min": 1,             # 最短时长（秒）
    "duration_max": 10,            # 最长时长（秒）
    "resolutions": ["480p"],       # 支持分辨率：未知时只认最低档
    "image_to_video": False,       # 是否支持图生视频
    "chinese_prompt": "未知",      # 中文提示词支持度：原生优 / 一般 / 未知
    "multi_ref_supported": False,  # 是否支持多参考图
    "consistency_strength": "未知",  # 一致性能力描述
}
_MODELS_JSON = "models.json"       # knowledge 目录下的模型能力文件名


# =====================================================================
# 内部工具
# =====================================================================
def _knowledge_dir() -> Path:
    """返回 knowledge 目录：优先 config.KNOWLEDGE_DIR，否则按脚本位置推算。"""
    if _cfg is not None:
        kd = getattr(_cfg, "KNOWLEDGE_DIR", None)
        if kd:
            return Path(kd)
    # src 布局：knowledge 随 package-data 打进包内（src/ecommerce_video/knowledge）
    return Path(__file__).resolve().parent / "knowledge"


def _default_provider() -> str:
    """返回当前生效的视频 provider：config.VIDEO_PROVIDER → models.json default_model → seedance-2.0。"""
    if _cfg is not None:
        p = (getattr(_cfg, "VIDEO_PROVIDER", "") or "").strip().lower()
        if p:
            return p
    # config 不可用时，尝试读 models.json 的 default_model 作为兜底
    try:
        data = json.loads((_knowledge_dir() / _MODELS_JSON).read_text(encoding="utf-8"))
        dm = (data.get("default_model") or "").strip().lower()
        if dm:
            return dm
    except Exception:
        pass
    return "seedance-2.0"  # 产品默认（与 config 默认一致）


def _load_models() -> tuple:
    """读取并缓存 models.json。返回 (models 列表 或 None, 警告信息)。

    - 文件缺失 / JSON 损坏 / 结构不符 → (None, 警告)，调用方降级默认。
    - 只读一次并缓存，避免每次查询都重读磁盘。
    """
    if _LOADED.get("models") is not None or _LOADED.get("failed"):
        return _LOADED["models"], _LOADED["warning"]
    path = _knowledge_dir() / _MODELS_JSON
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        models = raw.get("models") if isinstance(raw, dict) else None
        if not isinstance(models, list) or not models:
            _LOADED["failed"] = True
            _LOADED["warning"] = f"{path} 中 models 为空或不是列表"
            return None, _LOADED["warning"]
        _LOADED["models"] = models
        _LOADED["warning"] = ""
        return models, ""
    except FileNotFoundError:
        _LOADED["failed"] = True
        _LOADED["warning"] = f"模型能力文件缺失：{path}"
        return None, _LOADED["warning"]
    except (json.JSONDecodeError, OSError) as e:
        _LOADED["failed"] = True
        _LOADED["warning"] = f"模型能力文件解析失败：{path}（{e}）"
        return None, _LOADED["warning"]


_LOADED = {"models": None, "warning": "", "failed": False}  # 模块级缓存


def _normalize_caps(raw: dict) -> tuple:
    """把 models.json 里的能力字段整理成可用 dict（null/空 → 保守默认）。

    返回 (caps, changed_keys)：changed_keys 记录被兜底替换的字段名，用于提示。
    """
    caps = dict(_DEFAULT_CAPS)
    changed = []
    if not isinstance(raw, dict):
        return caps, list(caps.keys())
    for key in caps:
        v = raw.get(key)
        if v is None or v == "":
            if key in raw or key not in raw:
                # 字段缺失或为空 → 用保守默认并记录
                changed.append(key)
            continue
        caps[key] = v
    # resolutions：必须是非空列表，否则默认
    res = raw.get("resolutions")
    if isinstance(res, list) and res:
        caps["resolutions"] = [str(r) for r in res]
    elif "resolutions" in raw:
        changed.append("resolutions")
    # 数值字段兜底：必须为正数
    for key in ("ref_images", "duration_min", "duration_max"):
        v = caps.get(key)
        if not isinstance(v, (int, float)) or v <= 0:
            caps[key] = _DEFAULT_CAPS[key]
            changed.append(key)
    # 布尔字段兜底：无法识别一律按 False（保守）
    for key in ("image_to_video", "multi_ref_supported"):
        if not isinstance(caps.get(key), bool):
            caps[key] = bool(caps.get(key)) if caps.get(key) is not None else False
    # 字符串字段兜底
    for key in ("chinese_prompt", "consistency_strength"):
        v = caps.get(key)
        if not isinstance(v, str) or not v.strip():
            caps[key] = _DEFAULT_CAPS[key]
            changed.append(key)
    return caps, sorted(set(changed))


def _resolve_model(provider_id: str) -> tuple:
    """按 provider_id 在 models.json 中定位模型。返回 (模型 dict 或 None, 警告)。

    匹配规则：
      1) id 精确匹配（大小写不敏感）；
      2) 前缀/家族匹配（len≥3）：seedance → seedance-2.0 / seedance-2.5 均算 seedance 系；
         命中多个时优先返回 default_model，其次列表顺序第一个。
    """
    models, warn = _load_models()
    if not models:
        return None, warn or "模型能力文件不可用"
    pid = (provider_id or "").strip().lower()
    # 1) 精确匹配
    for m in models:
        if str(m.get("id", "")).strip().lower() == pid:
            return m, ""
    # 2) 前缀/家族匹配
    cands = []
    for m in models:
        mid = str(m.get("id", "")).strip().lower()
        if mid and len(pid) >= 3 and (mid.startswith(pid) or pid.startswith(mid)):
            cands.append(m)
    if cands:
        # 家族内优先 default_model（如 seedance 家族命中时优先 seedance-2.0）
        try:
            data = json.loads((_knowledge_dir() / _MODELS_JSON).read_text(encoding="utf-8"))
            default_id = str(data.get("default_model", "")).strip().lower()
        except Exception:
            default_id = ""
        for m in cands:
            if str(m.get("id", "")).strip().lower() == default_id:
                return m, ""
        return cands[0], ""
    return None, f"未找到模型 provider={provider_id!r}"


# =====================================================================
# 对外接口（契约见模块头部）
# =====================================================================
def get_model_capability(provider_id: str = "") -> dict:
    """读 knowledge/models.json，按 provider_id 返回该模型 capabilities。

    - provider_id 为空 → 用 config.VIDEO_PROVIDER（或兜底 seedance-2.0）；
    - 找到 → source="models.json"；字段为空处用保守默认补齐（warning 会说明）；
    - 找不到/文件缺失 → 保守默认 + warning，绝不抛异常。

    返回：{"provider":..., "capabilities":{...}, "source":"models.json|default", "warning":"..."}
    """
    pid = (provider_id or "").strip().lower() or _default_provider()
    model, warn = _resolve_model(pid)
    if model is None:
        return {
            "provider": pid,
            "capabilities": dict(_DEFAULT_CAPS),
            "source": "default",
            "warning": (warn or "未找到模型") + "；已降级为保守默认能力",
        }
    caps, changed = _normalize_caps(model.get("capabilities") or {})
    return {
        "provider": str(model.get("id", pid)),
        "capabilities": caps,
        "source": "models.json",
        "warning": (f"capabilities 字段缺失/为空，已用保守默认补齐：{', '.join(changed)}"
                    if changed else ""),
    }


def validate_job(job: dict, capability: dict | None = None) -> list:
    """按模型能力校验单个生成任务，返回问题列表（空列表 = 通过）。

    job 字段：prompt / negative_prompt / ref_images(list) / duration_sec /
              resolution / aspect_ratio / category / shot_no
    capability：可为 get_model_capability() 的完整返回（含 capabilities 键），
                也可直接传 capabilities 子 dict；None 时自动取当前 provider 能力。
    检查项（顺序固定）：
      时长超上限 / 低于下限 / 参考图超上限 / 分辨率不支持 / 中文提示词支持一般 / 多参考图不支持
    """
    issues = []
    if not isinstance(job, dict):
        return ["任务数据不是 dict，无法校验"]
    # 能力解析：None → 当前 provider；完整返回 → 取 capabilities 子 dict
    if capability is None:
        capability = get_model_capability()["capabilities"]
    elif isinstance(capability, dict) and "capabilities" in capability:
        capability = capability["capabilities"]
    caps, _ = _normalize_caps(capability)

    # 1) 时长：超上限 / 低于下限
    dur = job.get("duration_sec")
    if dur is not None:
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            issues.append(f"时长{dur!r}不是有效数字")
            dur = None
        if dur is not None:
            if dur > caps["duration_max"]:
                issues.append(f"时长{dur:g}s超过模型上限{caps['duration_max']:g}s")
            if dur < caps["duration_min"]:
                issues.append(f"时长{dur:g}s低于模型下限{caps['duration_min']:g}s")

    # 2) 参考图数量：超上限
    refs = job.get("ref_images") or []
    if isinstance(refs, str):  # 容错：单个路径字符串也算一张
        refs = [refs]
    if not isinstance(refs, list):
        refs = list(refs) if refs else []
    n_refs = len(refs)
    if n_refs > caps["ref_images"]:
        issues.append(f"参考图{n_refs}张超过模型上限{caps['ref_images']}张")

    # 3) 分辨率：不在支持列表
    res = job.get("resolution")
    if res and caps.get("resolutions"):
        if str(res).strip().lower() not in [r.strip().lower() for r in caps["resolutions"]]:
            issues.append(f"分辨率{res}不在支持列表：{'/'.join(caps['resolutions'])}")

    # 4) 中文提示词支持一般 / 未知 → 建议中英对照确认
    cp = caps.get("chinese_prompt", "未知") or "未知"
    if cp in ("一般", "未知"):
        issues.append("该模型中文提示词支持一般，建议中英对照确认")

    # 5) 不支持多参考图且实际给了多张 → 需走 S 合成阶段
    if caps.get("multi_ref_supported") is False and n_refs > 1:
        issues.append("模型不支持多参考图，需走S合成阶段")
    return issues


def flow_adjustments(capability: dict) -> dict:
    """返回流程适配建议（供 prompt_engine / batch_generate 读取后动态适配）。

    返回：{"ref_images_limit":N, "duration_max":N, "duration_min":N,
          "needs_composite":bool, "chinese_advice":str, "shot_count_advice":str}
    """
    # 兼容完整返回 / 子 dict
    if isinstance(capability, dict) and "capabilities" in capability:
        capability = capability["capabilities"]
    caps, _ = _normalize_caps(capability)
    cp = caps.get("chinese_prompt", "未知") or "未知"
    chinese_advice = "全中文" if "原生" in cp else "建议中英对照"
    dm = caps["duration_max"]
    return {
        "ref_images_limit": caps["ref_images"],
        "duration_max": caps["duration_max"],
        "duration_min": caps["duration_min"],
        "needs_composite": caps.get("multi_ref_supported") is False,
        "chinese_advice": chinese_advice,
        "shot_count_advice": "可做长版" if dm >= 30 else "4-15s用9镜",
    }


# =====================================================================
# 命令行自检入口
# =====================================================================
if __name__ == "__main__":
    print("== 能力感知模块自检 ==")
    for pid in ("seedance-2.0", "seedance", "kling", "不存在的模型xyz"):
        r = get_model_capability(pid)
        print(f"provider={pid!r:20} -> id={r['provider']!r} source={r['source']} "
              f"ref={r['capabilities']['ref_images']} dur=[{r['capabilities']['duration_min']},{r['capabilities']['duration_max']}] "
              f"warn={r['warning']!r}")
    print()
    c = get_model_capability("seedance-2.0")["capabilities"]
    print("flow_adjustments(seedance-2.0):", flow_adjustments(c))
    bad = validate_job({"duration_sec": 30, "ref_images": ["a"] * 10, "resolution": "4K"}, c)
    print("validate_job(超长/超图/超分辨率):", bad)
