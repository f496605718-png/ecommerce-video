#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow.py —— 电商 AI 视频全流程 Python API 入口（战役2：接口开放化）。

设计目标：
  - 把「识别 → 检索词源 → 提示词生成 → 能力校验 → 批量生成」整条流水线封装为
    纯 Python API（Workflow 类），开源后第三方可嵌入自己的系统；
    CLI（scripts/prompt_engine.py / scripts/batch_generate.py）只是本 API 的薄壳。
  - 本模块不解析命令行、不依赖 argparse；方法签名清晰、有中文 docstring 与类型注解。
  - 确认门（识别报告 / 确认单）**不内置强制** —— 由调用方决定何时放行；
    正式流程建议：recognize → 人工确认 → generate_prompts → validate_against_capability
    → 人工确认 → generate。

用法示例：
    from workflow import Workflow
    w = Workflow(project="projA", sku="sku1", category="clothing",
                 material="缎面", type_name="tvc", provider="seedance-2.0")
    w.check()                                    # 配置自检（接单前）
    w.recognize(["refs/sku1_white.png"])         # 阶段1：识别（供人工确认）
    w.retrieve_sources([{"shot_no": 1, "scene": "大理石美术馆"}])   # 阶段2：词源
    result = w.generate_prompts(storyboard)      # 阶段3：{"jobs": [...], "issues": [...]}
    w.validate_against_capability(result["jobs"])  # 阶段4：能力拦截（空=通过）
    w.generate(result["jobs"], version_count=2)  # 阶段5：入队生成（确认门由调用方决定）
    w.stats()                                    # 工具：任务/素材库统计

依赖（scripts/ 下既有模块，全部只读复用）：
    config / capability / retriever / prompt_engine / video_client / vision_client / db
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

# Windows GBK 兼容（与 scripts/ 其他模块一致）
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import config
from ecommerce_video import capability
from ecommerce_video import db
from ecommerce_video import retriever
from ecommerce_video import video_client
from ecommerce_video import vision_client
from ecommerce_video.logging_utils import get_logger

# 结构化日志（战役3）：输出到 stderr，不污染 CLI stdout；级别由 VIDEO_LOG_LEVEL 可调
logger = get_logger("workflow")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # src 布局：上上级=src，再上一级=项目根


class Workflow:
    """电商 AI 视频全流程 API（识别 → 词源 → 提示词 → 能力校验 → 批量生成）。"""

    def __init__(self, project: str = "", sku: str = "", provider: str = "",
                 category: str = "", material: str = "", type_name: str = ""):
        """初始化流程上下文。

        :param project:   项目名（job_key 前缀，可后续由 job 自身字段覆盖）
        :param sku:       商品 SKU（job_key 前缀，可后续由 job 自身字段覆盖）
        :param provider:  视频模型 provider_id；空 → config.VIDEO_PROVIDER
                          （能力自动从 knowledge/models.json 读取，缺失降级保守默认）
        :param category:  品类 id（clothing/beauty/food/...）
        :param material:  商品材质（如 缎面；词源检索 material 层直取）
        :param type_name: 视频类型（如 tvc）
        """
        self.project = project or ""
        self.sku = sku or ""
        self.category = (category or "").strip().lower()
        self.material = material or ""
        self.type_name = type_name or ""
        self.provider = (provider or "").strip().lower() or config.VIDEO_PROVIDER
        # 能力自动读取（完整返回含 capabilities/source/warning）
        self.capability = capability.get_model_capability(self.provider)
        self.capabilities = self.capability["capabilities"]

    # =====================================================================
    # 阶段1：识别 / 确认（人工确认门保留给调用方，这里只做编排辅助）
    # =====================================================================
    def recognize(self, image_paths: list, extra_instructions: str = "") -> dict:
        """阶段1：逐张识别参考图 → 合并报告（供人工确认）。

        :param image_paths: 本地图片路径列表
        :param extra_instructions: 追加识别要求（如品类字段）
        :return: {"per_image": {路径: 单图报告}, "merged": 合并商品档案,
                  "errors": {路径: 错误信息}}（单图失败不影响其他图）
        说明：识别报告/确认单为人工确认门，本方法只做编排辅助、不强制确认；
              正式流程建议人工确认 merged 报告后再进入 generate。
        """
        per_image, errors = {}, {}
        for p in image_paths:
            path = str(p)
            try:
                per_image[path] = vision_client.recognize_image(path, extra_instructions)
            except vision_client.VisionError as e:
                errors[path] = str(e)
        return {
            "per_image": per_image,
            "merged": self._merge_recognition(per_image),
            "errors": errors,
        }

    def _merge_recognition(self, per_image: dict) -> dict:
        """把多张图的识别报告合并成一份商品档案（多数决/最高置信度/去重拼接）。"""
        cats, colors, details, types, mats = [], [], [], [], []
        for path, r in per_image.items():
            if not isinstance(r, dict):
                continue
            if r.get("category"):
                cats.append(str(r["category"]))
            if r.get("primary_color"):
                colors.append(str(r["primary_color"]))
            if r.get("key_details"):
                details.append(str(r["key_details"]))
            if r.get("image_type"):
                types.append(str(r["image_type"]))
            mi = r.get("material_inference") or {}
            if isinstance(mi, dict) and mi.get("value"):
                mats.append(mi)

        def most_common(lst: list) -> str:
            c = Counter(lst)
            return c.most_common(1)[0][0] if c else ""

        conf_rank = {"高": 3, "中": 2, "低": 1}
        best = max(mats, key=lambda m: conf_rank.get(str(m.get("confidence", "")), 0), default=None)
        return {
            "category": most_common(cats),
            "primary_color": colors[0] if colors else "",
            "material_inference": {
                "value": best.get("value", ""),
                "confidence": best.get("confidence", ""),
                "basis": best.get("basis", ""),
            } if best else {},
            "key_details": "；".join(dict.fromkeys(d for d in details if d)),
            "image_types": list(dict.fromkeys(types)),
            "image_count": len(per_image),
            "note": "合并报告仅供人工确认；正式流程建议确认后再进入 generate",
        }

    # =====================================================================
    # 阶段2：检索词源
    # =====================================================================
    def retrieve_sources(self, shots: list) -> dict:
        """阶段2：按品类/材质/类型 + 分镜逐镜取精准词源。

        :param shots: 分镜列表（元素含 shot_no/scene/light/lens/move/motion/action）
        :return: {"per_shot": {镜号: {scene_light≤3, lighting≤3, camera_movement≤2,
                  lens_shot≤2, motion≤5, negative 8-15}},
                  "matched": {镜号: "exact|alias|tags|material|none"}, "meta": {...}}
        """
        result = retriever.retrieve(self.category, shots, self.material, self.type_name)
        logger.info(f"检索词源：{len(shots)} 个分镜，命中 {result.get('matched', {})}")
        return result

    # =====================================================================
    # 阶段3：提示词生成（LLM）
    # =====================================================================
    def build_meta_prompt(self, storyboard: dict) -> str:
        """组装元提示词（不调 LLM，供调试 / CLI dry 使用）。"""
        from ecommerce_video.prompt_engine import build_prompt
        return build_prompt(storyboard)

    def generate_prompts(self, storyboard: dict, llm_prompt: str = "") -> dict:
        """阶段3：storyboard → 元提示词(build_prompt) → LLM(call_llm) → jobs → validate_jobs。

        :param storyboard: 分镜剧本（含 category/material/type/shots 等）
        :param llm_prompt: 自定义用户提示词；空则用 build_prompt 组装的元提示词
        :return: {"jobs": [分镜任务列表], "issues": [校验问题列表]}（issues 空=通过）
        :raises RuntimeError: 未配置 LLM key（TEXT_LLM_API_KEY 或 VISION_API_KEY）
        """
        if not (config.TEXT_LLM_API_KEY or config.VISION_API_KEY):
            raise RuntimeError("未配置 LLM key（TEXT_LLM_API_KEY 或 VISION_API_KEY），先补 .env")
        from ecommerce_video.prompt_engine import call_llm, parse_json_response, validate_jobs
        meta = llm_prompt or self.build_meta_prompt(storyboard)
        raw = call_llm("你是严格的 JSON 输出助手，只输出合法 JSON。", meta)
        jobs = parse_json_response(raw)
        issues = validate_jobs(jobs, storyboard)
        logger.info(f"提示词生成完成：{len(jobs)} 个任务，{len(issues)} 个校验问题")
        if issues:
            logger.warning(f"提示词规则校验拦截 {len(issues)} 个问题（前 3 条）：{issues[:3]}")
        return {"jobs": jobs, "issues": issues}

    def validate_prompts(self, jobs: list, storyboard: dict | None = None) -> list:
        """规则校验 jobs（L1 锚定/含英文/外观参数/长度/负面词红线），返回问题列表（空=通过）。"""
        from ecommerce_video.prompt_engine import validate_jobs
        return validate_jobs(jobs, storyboard or {})

    # =====================================================================
    # 阶段4：能力校验（新：生成前按模型能力拦截）
    # =====================================================================
    def validate_against_capability(self, jobs: list) -> list:
        """阶段4：对每个 job 调 capability.validate_job，返回问题列表（空=全通过）。

        校验项（按当前 provider 的 models.json 能力）：
          时长超上限/低于下限、参考图超上限、分辨率不支持、中文提示词支持一般、
          多参考图不支持（需 S 合成）。问题文本带 job_key 前缀（可定位到任务）。
        """
        issues: list = []
        for job in jobs:
            msgs = capability.validate_job(job, self.capability)
            if not msgs:
                continue
            key = self._job_key(job)
            issues.extend(f"{key}: {m}" for m in msgs) if key else issues.extend(msgs)
        if issues:
            logger.warning(f"能力校验拦截 {len(issues)} 条问题（provider={self.provider}）")
        return issues

    # =====================================================================
    # 阶段5：批量生成
    # =====================================================================
    def generate(self, jobs: list, version_count: int = 1, resolution: str = "1080p",
                 aspect_ratio: str = "9:16", limit: int = 5, dry_run: bool = False) -> dict:
        """阶段5：jobs → db.add_job(confirmed) → 队列生成（video_client）→ 落盘 output/videos/。

        :param jobs: 分镜任务列表（prompt/negative_prompt/ref_images/duration_sec/...
                     缺 job_key 时按 project_sku_shotNN 自动生成；缺 version_count/
                     resolution/aspect_ratio 时用本方法参数补齐）
        :param version_count: 每镜生成版本数（job 自带则优先）
        :param resolution: 分辨率（job 自带则优先）
        :param aspect_ratio: 画幅比（job 自带则优先）
        :param limit: 本次从队列取任务上限
        :param dry_run: True 时不调 API、不写库，只打印将执行的命令序列
        :return: {"done": [视频绝对路径], "failed": [{"job_key", "error"}],
                  "dry_run": bool, "planned": [dry_run 时的计划产物路径]}
        说明：
          - 入队前先做能力校验（validate_against_capability），有超限问题 → 拒绝入队，
            记入 failed（error 以「能力校验未通过：」开头）；
          - 通过校验的 jobs 会 add_job(confirmed) 直接发放入场券 —— 确认门由调用方决定：
            正式流程建议先人工确认（识别报告/确认单）再调用本方法；
          - 生成从队列取 confirmed 任务（含历史已确认任务），串行处理最多 limit 条；
          - ref_images 相对路径自动转绝对（复用 batch_generate 既有逻辑）。
        """
        # 1) 能力校验（超限 → 拒绝入队）
        failed, accepted = [], []
        for job in jobs:
            key = self._job_key(job)
            issues = capability.validate_job(job, self.capability)
            if issues:
                reason = "能力校验未通过：" + "；".join(issues)
                failed.append({"job_key": key, "error": reason})
                logger.warning(f"✘ {key} 拒绝入队（{reason}）")
            else:
                accepted.append(job)

        # 2) 入队（confirmed；dry_run 只打印）
        for job in accepted:
            key = self._job_key(job)
            job.setdefault("job_key", key)
            job.setdefault("version_count", version_count)
            job.setdefault("resolution", resolution)
            job.setdefault("aspect_ratio", aspect_ratio)
            if dry_run:
                logger.info(f"   [dry-run] db.add_job({key}) → db.confirm_job({key})（confirmed 入队）")
                continue
            try:
                db.add_job(job)
                db.confirm_job(key)
                logger.info(f"▶ 入队 {key}（能力校验通过，已确认）")
            except Exception as e:
                failed.append({"job_key": key, "error": f"入队失败: {e}"})
                logger.error(f"✘ {key} 入队失败: {e}")

        # 3) 队列生成
        if dry_run:
            result = self._process_batch(accepted, dry_run=True)
            result["dry_run"] = True
            result["failed"] = failed + result["failed"]
            logger.info(f"【dry-run】共规划 {len(accepted)} 条任务、{len(result['planned'])} 个视频文件；"
                        f"未调用任何 API、未写数据库。")
            return result
        queue = db.get_queue()
        if not queue:
            logger.info("队列为空（无 confirmed 任务）。先 import + confirm。")
            return {"done": [], "failed": failed, "dry_run": False, "planned": []}
        batch = queue[:limit]
        logger.info(f"本次处理 {len(batch)} 条（串行，队列剩余 {len(queue) - len(batch)}）")
        result = self._process_batch(batch, dry_run=False)
        result["dry_run"] = False
        result["failed"] = failed + result["failed"]
        logger.info(f"生成完成：成功 {len(result['done'])} 个视频，失败 {len(result['failed'])} 个任务")
        return result

    def run(self, limit: int = 5, dry_run: bool = False) -> dict:
        """从队列取 confirmed 任务生成（CLI `run` 的 API 版；可多次跑，串行处理）。

        :param limit: 本次处理任务数上限
        :param dry_run: True 时不校验视频 key、不调 API、不写库，仅打印提示
        :return: {"done": [...], "failed": [...], "missing": [配置缺失项],
                  "empty": 队列是否为空}
        """
        if dry_run:
            logger.info("【dry-run】不校验视频 key、不调 API、不写数据库（run 的 dry-run 无队列可打印，"
                        "请用 generate(dry_run=True) 预览命令序列）。")
            return {"done": [], "failed": [], "missing": [], "empty": False, "dry_run": True}
        missing = config.check_config(require_video_key=True)
        if missing:
            return {"done": [], "failed": [], "missing": missing, "empty": False}
        queue = db.get_queue()
        if not queue:
            logger.info("run：队列为空（无 confirmed 任务）")
            return {"done": [], "failed": [], "missing": [], "empty": True}
        batch = queue[:limit]
        logger.info(f"本次处理 {len(batch)} 条（串行，队列剩余 {len(queue) - len(batch)}）")
        result = self._process_batch(batch, dry_run=False)
        result["missing"] = []
        result["empty"] = False
        logger.info(f"run 完成：成功 {len(result['done'])} 个视频，失败 {len(result['failed'])} 个任务")
        return result

    def _process_batch(self, batch: list, dry_run: bool = False) -> dict:
        """串行生成一批任务（内部：video_client 调用 + db 状态更新；dry_run 只打印序列）。"""
        done, failed, planned = [], [], []
        for j in batch:
            key = j["job_key"]
            if not dry_run:
                db.mark_running(key)
            logger.info(f"▶ 生成中 {key} ({j.get('category', '')}, {j.get('duration_sec', 10)}s × "
                        f"{j.get('version_count', 1)}版)")
            refs_raw = j.get("ref_images") or []
            # 兼容两种形态：API 调用方直接传 list；db 行内是 JSON 字符串
            if isinstance(refs_raw, str):
                try:
                    refs = json.loads(refs_raw or "[]")
                except (ValueError, TypeError):
                    refs = []
            elif isinstance(refs_raw, list):
                refs = refs_raw
            else:
                refs = []
            # 相对路径转绝对（复用 batch_generate 既有逻辑）
            refs_abs = [str(PROJECT_ROOT / r) if not Path(r).is_absolute() else r for r in refs]
            videos = []
            try:
                for v in range(1, int(j.get("version_count", 1)) + 1):
                    logger.info(f"   版本 {v}/{j.get('version_count', 1)} ...")
                    out = config.VIDEO_DIR / f"{key}_v{v}.mp4"
                    if dry_run:
                        logger.info(
                            f"   [dry-run] video_client.create_task("
                            f"prompt={str(j.get('prompt', ''))[:30]!r}…, "
                            f"ref_images={refs_abs}, duration={j.get('duration_sec', 10)}, "
                            f"resolution={j.get('resolution', '1080p')}, "
                            f"aspect_ratio={j.get('aspect_ratio', '9:16')}, "
                            f"negative_prompt={str(j.get('negative_prompt', ''))[:20]!r}…)")
                        logger.info("   [dry-run] video_client.poll_until_done(task_id) → 视频 URL")
                        logger.info(f"   [dry-run] video_client.download_video(url, {out})")
                        videos.append(str(out))
                        continue
                    task_id = video_client.create_task(
                        prompt=j.get("prompt", ""), ref_images=refs_abs,
                        duration=j.get("duration_sec", 10), resolution=j.get("resolution", "1080p"),
                        aspect_ratio=j.get("aspect_ratio", "9:16"),
                        negative_prompt=j.get("negative_prompt", ""))
                    logger.info(f"   task_id={task_id}，轮询中...")
                    url = video_client.poll_until_done(task_id)
                    video_client.download_video(url, out)
                    videos.append(str(out))
                    logger.info(f"   ✓ 已保存 {out}")
                if dry_run:
                    logger.info(f"   [dry-run] db.mark_done({key}, {videos})")
                    planned.extend(videos)
                else:
                    db.mark_done(key, videos)
                    done.extend(videos)
                    logger.info(f"✔ {key} 完成（{len(videos)} 版）")
            except video_client.VideoGenError as e:
                if not dry_run:
                    db.mark_failed(key, str(e))
                failed.append({"job_key": key, "error": str(e)})
                logger.error(f"✘ {key} 失败: {e}")
            except Exception as e:
                if not dry_run:
                    db.mark_failed(key, f"{type(e).__name__}: {e}")
                failed.append({"job_key": key, "error": f"{type(e).__name__}: {e}"})
                logger.error(f"✘ {key} 异常: {type(e).__name__}: {e}", exc_info=True)
        return {"done": done, "failed": failed, "planned": planned}

    # =====================================================================
    # 工具
    # =====================================================================
    def check(self) -> dict:
        """配置自检（复用 config.check_config + capability 读取）。

        :return: {"ok": bool, "missing": [缺失项], "provider": 生效 provider,
                  "capabilities": {能力 dict}, "capability_source": "models.json|default",
                  "capability_warning": "能力降级说明"}
        """
        missing = config.check_config(require_video_key=False)
        cap = capability.get_model_capability(self.provider)
        logger.info(f"配置自检：ok={not missing}，缺失={missing}，provider={self.provider}，能力来源={cap['source']}")
        return {
            "ok": not missing,
            "missing": missing,
            "provider": self.provider,
            "capabilities": cap["capabilities"],
            "capability_source": cap["source"],
            "capability_warning": cap["warning"],
        }

    def stats(self) -> dict:
        """任务状态统计 + 素材库统计 + 失败任务摘要。

        :return: {"jobs": {状态: 数量}, "assets": {"qa": {...}, "delivered": N},
                  "failed": [{"job_key", "status_detail"}]}
        """
        return {
            "jobs": db.stats(),
            "assets": db.get_assets_stats(),
            "failed": [
                {"job_key": j["job_key"], "status_detail": j.get("status_detail") or ""}
                for j in db.get_jobs(status="failed")
            ],
        }

    # ---- CLI 薄壳辅助（init/import/confirm/confirm-all） ----
    def init(self) -> dict:
        """初始化数据库（幂等），返回状态统计。"""
        db.init_db()
        return db.stats()

    def import_jobs(self, jobs_path: str) -> int:
        """导入 jobs.json（分镜表参数化导出）→ db.add_job（pending），返回导入条数。

        :param jobs_path: jobs.json 路径（job 缺 job_key 时按 project_sku_shotNN 自动生成）
        """
        jobs = json.loads(Path(jobs_path).read_text(encoding="utf-8-sig"))
        n = 0
        for job in jobs:
            job.setdefault("job_key", self._job_key(job) or f"job_{n}")
            db.add_job(job)
            n += 1
        return n

    def confirm(self, job_key: str) -> None:
        """确认单全✓ → 发放入场券（confirmed）。"""
        db.confirm_job(job_key)

    def confirm_all(self, project: str) -> int:
        """项目内全部任务批量发放入场券，返回条数。"""
        jobs = db.get_jobs(project=project)
        for j in jobs:
            db.confirm_job(j["job_key"])
        return len(jobs)

    # =====================================================================
    # 内部工具
    # =====================================================================
    @staticmethod
    def _job_key(job: dict) -> str:
        """生成 job_key：project_sku_shotNN（与 batch_generate import 规则一致）。

        缺项目/SKU 时降级为 shotN；无任何标识字段返回空串。
        """
        project = str(job.get("project") or "").strip()
        sku = str(job.get("sku") or "").strip()
        shot = job.get("shot_no")
        if project and sku:
            base = f"{project}_{sku}"
            if shot is None:
                return base
            try:
                return f"{base}_shot{int(shot):02d}"
            except (TypeError, ValueError):
                return f"{base}_shot{shot}"
        if shot is not None:
            return f"shot{shot}"
        return ""


if __name__ == "__main__":
    logger.info("== Workflow API 自检（dry-run，无网络） ==")
    w = Workflow(provider="seedance-2.0", category="clothing", material="缎面", type_name="tvc")
    ck = w.check()
    logger.info("check: %s | caps ref: %s",
                {k: v for k, v in ck.items() if k != "capabilities"},
                ck["capabilities"].get("ref_images"))
    src = w.retrieve_sources([{"shot_no": 1, "scene": "大理石美术馆"}])
    logger.info("retrieve matched: %s | scene_light[0].id = %s",
                src["matched"], src["per_shot"][1]["scene_light"][0]["id"])
    logger.info("capability issues: %s", w.validate_against_capability(
        [{"duration_sec": 99, "ref_images": ["a"] * 20, "resolution": "8K"}]))
    logger.info("--- generate(dry_run=True) ---")
    w.generate(
        [{"project": "demo", "sku": "s1", "shot_no": 1, "category": "clothing",
          "prompt": "模特身穿缎面连衣裙，在大理石美术馆中转身，裙摆甩动出液态光泽，与参考图完全一致",
          "negative_prompt": "形变扭曲, 多余肢体, 手指变形, 水印, 画面文字",
          "ref_images": ["refs/s1.png"], "duration_sec": 5, "version_count": 1}],
        version_count=1, dry_run=True)
