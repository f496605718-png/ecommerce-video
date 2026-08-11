#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成单元规划器（P3，开放选项）。

背景：视频模型接入是开放的（VideoProvider 注册表），各模型能力/时长上限不一，
**没有统一"合并/切分"规则**。本模块把提交策略的决策权交给用户：

- 策略 `strategy`（用户决定）：
    - `"per-shot"`（默认）：一镜一提交——最稳，行为与旧版完全一致（零变化）
    - `"merge"`：合并提交——累积时长 ≤ 上限的多镜提示词合并为一条提交（AI 融合
      成连贯动作描述，镜头转场自然）；总时长超上限时，由 AI 在语义断点切分
      （如 9s+5s），AI 不可用时退化为贪心累积切分
- 上限 `max_seconds`（用户决定，默认 config.UNIT_MAX_SECONDS=10）：
    实际生效值 = min(用户值, 模型 duration_max)（查 models.json 能力）
- 输出 units 与 jobs 同构（含 prompt/negative_prompt/ref_images/duration_sec/
  version_count/project/sku/category），可直接走既有 import → confirm → run 链路

用法：
    python -m ecommerce_video.cli plan-units jobs.json -o units.json --strategy merge --max 10
    # 默认 --strategy per-shot：等价于原样透传（用于把 jobs 规整为 units 格式）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import config

_MERGE_SYSTEM = (
    "你是视频分镜合并专家。把多条分镜提示词合并成【一条连贯的单镜头视频提示词】：\n"
    "1. 必须保留\"与参考图完全一致\"的 L1 锚定表述\n"
    "2. 动作按时间顺序衔接，镜头转场自然（不写镜头编号、不写\"第几镜\"）\n"
    "3. 不改变商品外观描述；全中文；只输出提示词正文，不要解释"
)

_SPLIT_SYSTEM = (
    "你是视频分镜切分专家。把一组分镜切成若干段，每段总时长不超过给定上限：\n"
    "切分点选在语义断点（场景切换/动作段落边界），不要切在连续动作中间。\n"
    "只输出 JSON：{\"groups\": [[镜号,...],[镜号,...]]}，不要解释"
)


def resolve_max_seconds(max_seconds: int | None, capabilities: dict | None = None) -> int:
    """生效上限 = min(用户值, 模型 duration_max)；用户缺省用 config.UNIT_MAX_SECONDS。"""
    user = max_seconds or config.UNIT_MAX_SECONDS
    cap_max = None
    if capabilities:
        cap_max = capabilities.get("duration_max")
        try:
            cap_max = int(cap_max) if cap_max else None
        except (TypeError, ValueError):
            cap_max = None
    if cap_max:
        return max(1, min(user, cap_max))
    return max(1, user)


def _shot_duration(job: dict, default: int = 10) -> int:
    try:
        return max(1, int(job.get("duration_sec") or default))
    except (TypeError, ValueError):
        return default


def _merge_prompt_llm(prompts: list[str]) -> str:
    """LLM 融合多镜提示词为一条连贯描述；失败抛异常（调用方兜底拼接）。"""
    from ecommerce_video.prompt_engine import call_llm
    numbered = "\n".join(f"[分镜{i + 1}] {p}" for i, p in enumerate(prompts))
    return call_llm(_MERGE_SYSTEM, numbered).strip()


def _split_groups_llm(jobs: list[dict], max_seconds: int) -> list[list[dict]] | None:
    """LLM 判定切分点（返回分镜分组）；任何异常返回 None（调用方走贪心兜底）。"""
    try:
        from ecommerce_video.prompt_engine import call_llm
        shot_lines = "\n".join(
            f"镜号{j.get('shot_no')} 场景[{j.get('scene', '')}] 时长{j.get('duration_sec', 10)}s"
            for j in jobs)
        raw = call_llm(_SPLIT_SYSTEM, f"上限 {max_seconds}s。\n{shot_lines}")
        start, end = raw.find("{"), raw.rfind("}")
        groups = json.loads(raw[start:end + 1]).get("groups", [])
        by_no = {str(j.get("shot_no")): j for j in jobs}
        result: list[list[dict]] = []
        for g in groups:
            part = [by_no[str(n)] for n in g if str(n) in by_no]
            if not part:
                return None
            if sum(_shot_duration(j) for j in part) > max_seconds:
                return None  # 超限 → 兜底
            result.append(part)
        if sum(len(g) for g in result) != len(jobs):
            return None
        return result
    except Exception:
        return None


def _split_groups_greedy(jobs: list[dict], max_seconds: int) -> list[list[dict]]:
    """贪心兜底：按累积时长切分（不打断单镜）。"""
    groups: list[list[dict]] = []
    cur, cur_sum = [], 0
    for j in jobs:
        d = _shot_duration(j)
        if cur and cur_sum + d > max_seconds:
            groups.append(cur)
            cur, cur_sum = [], 0
        cur.append(j)
        cur_sum += d
    if cur:
        groups.append(cur)
    return groups


def plan_units(jobs: list[dict], strategy: str = "per-shot", max_seconds: int | None = None,
               llm: bool = True, capabilities: dict | None = None) -> dict:
    """生成单元规划（开放选项）。

    :param jobs: 分镜任务列表（jobs.json 结构）
    :param strategy: "per-shot"（默认，一镜一提交）| "merge"（合并提交+超限切分）
    :param max_seconds: 单条提交时长上限（默认 config.UNIT_MAX_SECONDS；≤ 模型 duration_max）
    :param llm: 是否允许 LLM 判定切分点/融合提示词（False → 贪心+拼接）
    :param capabilities: 模型能力 dict（models.json）；缺省自动查当前 provider
    :return: {"units": [与 jobs 同构的单元列表], "notes": [说明], "strategy": str,
              "max_seconds": int}
    """
    if capabilities is None:
        from ecommerce_video import capability
        capabilities = capability.get_model_capability(config.VIDEO_PROVIDER)["capabilities"]
    cap = resolve_max_seconds(max_seconds, capabilities)
    notes: list[str] = []

    if strategy != "merge":
        units = [dict(j, unit_no=i + 1, shots=[j.get("shot_no")]) for i, j in enumerate(jobs)]
        notes.append(f"策略 per-shot：一镜一提交，共 {len(units)} 条（与旧版行为一致）")
        return {"units": units, "notes": notes, "strategy": "per-shot", "max_seconds": cap}

    # ---- merge：先按上限切分组 ----
    total = sum(_shot_duration(j) for j in jobs)
    if total <= cap:
        groups = [jobs]
        notes.append(f"总时长 {total}s ≤ 上限 {cap}s：全部合并为 1 条提交")
    else:
        groups = _split_groups_llm(jobs, cap) if llm else None
        if groups is None:
            groups = _split_groups_greedy(jobs, cap)
            notes.append(f"总时长 {total}s > 上限 {cap}s：AI 不可用/超限，按贪心切分为 {len(groups)} 段")
        else:
            notes.append(f"总时长 {total}s > 上限 {cap}s：AI 判定切分为 {len(groups)} 段")

    # ---- 逐组生成单元 ----
    units = []
    for i, group in enumerate(groups):
        first = group[0]
        dur = sum(_shot_duration(j) for j in group)
        if len(group) == 1:
            prompt = first.get("prompt", "")
        else:
            prompts = [j.get("prompt", "") for j in group if j.get("prompt")]
            if llm:
                try:
                    prompt = _merge_prompt_llm(prompts)
                    notes.append(f"单元{i + 1}（{len(group)} 镜合并）提示词由 LLM 融合")
                except Exception:
                    prompt = "；".join(prompts)
                    notes.append(f"单元{i + 1}（{len(group)} 镜合并）LLM 融合失败，已按顺序拼接")
            else:
                prompt = "；".join(prompts)
        unit = dict(first)
        unit.update({
            "unit_no": i + 1,
            "shots": [j.get("shot_no") for j in group],
            "shot_no": first.get("shot_no"),  # job_key 沿用首镜号
            "prompt": prompt,
            "duration_sec": dur,
            "version_count": max(int(j.get("version_count") or 1) for j in group),
            "ref_images": next((j.get("ref_images") for j in group if j.get("ref_images")), []),
        })
        units.append(unit)
    notes.append(f"共 {len(units)} 条提交；单条上限 {cap}s（min(用户值, 模型 duration_max)）")
    return {"units": units, "notes": notes, "strategy": "merge", "max_seconds": cap}


def cmd_plan_units(jobs_path: str, out: str, strategy: str = "per-shot",
                   max_seconds: int | None = None, llm: bool = True):
    """CLI：jobs.json → units.json（open 选项，见模块 docstring）。"""
    jobs = json.loads(Path(jobs_path).read_text(encoding="utf-8-sig"))
    result = plan_units(jobs, strategy=strategy, max_seconds=max_seconds, llm=llm)
    out_path = Path(out)
    out_path.write_text(json.dumps(result["units"], ensure_ascii=False, indent=2), encoding="utf-8")
    for n in result["notes"]:
        print(f"· {n}")
    print(f"已生成 {out_path}（{len(result['units'])} 条提交；上限 {result['max_seconds']}s；"
          f"策略 {result['strategy']}）")
