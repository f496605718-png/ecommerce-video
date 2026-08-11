#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量生成主程序：确认单入场 → 队列 → 逐镜生成 → 落盘 → 状态更新。

用法（CLI 统一入口，推荐）：
  ecommerce-video init            # 初始化数据库
  ecommerce-video import <jobs.json>   # 导入分镜任务（pending）
  ecommerce-video confirm <job_key>    # 发放入场券（确认单全✓）
  ecommerce-video confirm-all <project>  # 批量发放入场券
  ecommerce-video run [--limit N]  # 从队列取任务生成（串行，可多次跑）
  ecommerce-video status          # 状态统计
  ecommerce-video check           # 配置自检（接单前必跑）
（旧入口 `python -m ecommerce_video.batch_generate <cmd>` 保留兼容，推荐改用 ecommerce-video）

jobs.json 格式（分镜表参数化导出）：
[
  {"project":"projA","sku":"sku1","shot_no":1,"category":"clothing",
   "prompt":"...七要素拼装后的中文提示词...","negative_prompt":"...",
   "ref_images":["refs/sku1_white.png","refs/sku1_detail.png"],
   "duration_sec":10,"version_count":2}
]
说明：本文件为 workflow.Workflow API 的 CLI 薄壳（战役2 接口开放化），
      数据库/队列/生成/校验逻辑全部走 workflow.py；
      CLI 统一入口见 cli.py（ecommerce-video 命令），cmd_* 函数供其路由调用。
"""
import sys

# Windows 控制台 GBK 兼容：emoji/中文输出不卡死
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import config
from ecommerce_video.logging_utils import get_logger

# 结构化日志（战役3）：输出到 stderr，不影响 CLI 用户可见 stdout
logger = get_logger("batch")


# ---------- CLI（薄封装：逻辑走 workflow.Workflow，输出格式与旧版完全一致） ----------
def cmd_init(w):
    r = w.init()
    logger.info(f"init：初始化数据库完成，状态={r}")
    print("状态:", r)


def cmd_import(w, jobs_path: str):
    n = w.import_jobs(jobs_path)
    logger.info(f"import：从 {jobs_path} 导入 {n} 条任务")
    print(f"导入 {n} 条任务（重复 key 已更新）")


def cmd_confirm(w, job_key: str):
    w.confirm(job_key)
    logger.info(f"confirm：入场券已发放 {job_key}")
    print(f"入场券已发放: {job_key}")


def cmd_confirm_all(w, project: str):
    n = w.confirm_all(project)
    logger.info(f"confirm-all：项目 {project} 共 {n} 条发放入场券")
    print(f"项目 {project} 共 {n} 条已全部发放入场券")


def cmd_run(w, limit: int = 5):
    logger.info(f"run：开始执行（limit={limit}）")
    r = w.run(limit)
    if r.get("missing"):
        logger.error(f"run：配置缺失，禁止入队生成：{r['missing']}")
        print("❌ 配置缺失，禁止入队生成：")
        for m in r["missing"]:
            print("  -", m)
        print("请补 .env 后重试（见 CONFIG.md）。")
        sys.exit(1)
    if r.get("empty"):
        logger.warning("run：队列为空（无 confirmed 任务）")
        print("队列为空（无 confirmed 任务）。先 import + confirm。")
    else:
        logger.info(f"run：完成（成功 {len(r.get('done', []))} 个，失败 {len(r.get('failed', []))} 个）")


def cmd_reset(w, project: str):
    """P6：项目残留任务复位（running/failed → pending），中断/异常后的续传入口。"""
    n = w.reset(project)
    logger.info(f"reset：项目 {project} 复位 {n} 条（running/failed → pending）")
    print(f"项目 {project} 已复位 {n} 条任务为 pending（可重新 run 续传）")


def cmd_status(w):
    r = w.stats()
    logger.info(f"status：任务统计 {r['jobs']}，素材库 {r['assets']}")
    print("状态统计:", r["jobs"])
    for j in r["failed"]:
        logger.warning(f"status：失败任务 {j['job_key']} → {(j['status_detail'] or '')[:80]}")
        print("  失败:", j["job_key"], "→", (j["status_detail"] or "")[:80])


def cmd_check(w):
    r = w.check()
    if r["missing"]:
        logger.warning(f"check：配置缺失项 {r['missing']}")
        print("⚠️ 配置缺失项：")
        for m in r["missing"]:
            print("  -", m)
    else:
        logger.info("check：配置自检通过（视觉识别就绪）")
        print("✅ 配置自检通过（视觉识别就绪）")
    print(f"视频模型: {config.VIDEO_PROVIDER} / {config.VIDEO_MODEL} / key={config.mask_key(config.VIDEO_API_KEY)}")


if __name__ == "__main__":
    from ecommerce_video.workflow import Workflow  # 薄壳入口：CLI 只做参数解析与输出

    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    w = Workflow()
    logger.info(f"batch_generate：执行命令 {cmd}")
    if cmd == "init":
        cmd_init(w)
    elif cmd == "import" and len(args) >= 2:
        cmd_import(w, args[1])
    elif cmd == "confirm" and len(args) >= 2:
        cmd_confirm(w, args[1])
    elif cmd == "confirm-all" and len(args) >= 2:
        cmd_confirm_all(w, args[1])
    elif cmd == "run":
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 5
        cmd_run(w, limit)
    elif cmd == "status":
        cmd_status(w)
    elif cmd == "check":
        cmd_check(w)
    else:
        print(__doc__)
