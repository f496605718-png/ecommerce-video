#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ecommerce-video —— 电商 AI 视频工作流 CLI 统一入口（开源改造第 2 步）。

一条命令走天下（替代散乱的 `python -m ecommerce_video.xxx <cmd>` 调用）：

  ecommerce-video check               配置自检（复用 config.check_config + capability）
  ecommerce-video status              任务状态统计
  ecommerce-video init                初始化数据库
  ecommerce-video import <jobs.json>  导入任务
  ecommerce-video confirm <job_key>   发放入场券（确认单全✓）
  ecommerce-video confirm-all <project>   项目内全部任务批量发放入场券
  ecommerce-video run [--limit N]     批量生成（串行，可多次跑）
  ecommerce-video gen <sb.json> [-o jobs.json]   AI 提示词生成（prompt_engine，需 LLM key）
  ecommerce-video dry <sb.json>       元提示词干跑（不调 LLM，调试用）
  ecommerce-video validate <jobs.json>    校验生成的 jobs.json（规则检查）
  ecommerce-video kbcheck [--strict] [<file>]   知识库校验（validate_kb）

行为约定（迁移红线：CLI 行为零变化）：
  - 本文件只做 argparse 路由，不重写任何业务逻辑；各子命令逻辑保留在
    batch_generate / prompt_engine / validate_kb 的 cmd_* / main 中；
  - 输出文本 / 退出码与旧入口 `python -m ecommerce_video.batch_generate <cmd>`、
    `python -m ecommerce_video.prompt_engine <cmd>`、`python -m ecommerce_video.validate_kb`
    完全一致（正常调用路径）。
"""
import argparse
import json
import sys
from pathlib import Path

# Windows GBK 兼容（与包内其他模块一致）
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ecommerce_video import batch_generate
from ecommerce_video import prompt_engine
from ecommerce_video import validate_kb
from ecommerce_video.workflow import Workflow

# 兼容 shim（不改 cmd_* 逻辑）：prompt_engine 的 cmd_gen/cmd_dry/cmd_validate 内部引用模块级
# Workflow 名字——旧 `python -m ecommerce_video.prompt_engine` 入口在其 __main__ 块里
# `from ecommerce_video.workflow import Workflow` 注入模块全局后才调用；统一入口直接调 cmd_*，
# 故在此补上同一个全局名，行为与旧入口完全一致。
prompt_engine.Workflow = Workflow


def _workflow():
    """构造 Workflow（与旧 __main__ 薄壳入口一致：无参默认实例）。"""
    from ecommerce_video.workflow import Workflow
    return Workflow()


# ---------- 子命令分发（薄封装：直接调 batch_generate / prompt_engine / validate_kb） ----------
def _cmd_check(args):
    batch_generate.cmd_check(_workflow())


def _cmd_status(args):
    batch_generate.cmd_status(_workflow())


def _cmd_init(args):
    batch_generate.cmd_init(_workflow())


def _cmd_import(args):
    batch_generate.cmd_import(_workflow(), args.jobs)


def _cmd_confirm(args):
    batch_generate.cmd_confirm(_workflow(), args.job_key)


def _cmd_confirm_all(args):
    batch_generate.cmd_confirm_all(_workflow(), args.project)


def _cmd_run(args):
    batch_generate.cmd_run(_workflow(), args.limit)


def _cmd_gen(args):
    # 兼容旧 `gen sb.json -o out.json` 与文档形态 `gen sb.json out.json`；
    # 缺省输出 jobs.json（与旧版一致）
    out = args.output or args.out or "jobs.json"

    # —— P1-3 修复：jobs 注入 project/sku/category（打通 gen→import 主链路）——
    # 优先级：storyboard 顶层字段 > 命令行 --project/--sku/--category；
    # 两者都缺 → 明确中文报错并退出（绝不静默生成无法导入的 jobs）
    sb = json.loads(Path(args.sb).read_text(encoding="utf-8-sig"))
    meta = {
        "project": sb.get("project") or args.project,
        "sku": sb.get("sku") or args.sku,
        "category": sb.get("category") or args.category,
    }
    missing = [k for k, v in meta.items() if not v]
    if missing:
        print("❌ storyboard 与命令行均未提供 project/sku/category（import 必需）：")
        for k in missing:
            print(f"  - {k}")
        print("请在 storyboard 顶层补 {project,sku,category}，或用 --project/--sku/--category 指定")
        sys.exit(1)

    prompt_engine.cmd_gen(args.sb, out)

    # cmd_gen 已按原逻辑写出 jobs（LLM/校验/打印行为不变）；此处只补写三字段
    out_path = Path(out)
    jobs = json.loads(out_path.read_text(encoding="utf-8"))
    for j in jobs:
        if isinstance(j, dict):
            j.update(meta)
    out_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _cmd_dry(args):
    prompt_engine.cmd_dry(args.sb)


def _cmd_validate(args):
    prompt_engine.cmd_validate(args.jobs)


def _cmd_kbcheck(args):
    # validate_kb.main 自带退出码语义（0=通过 / 1=有错 / 2=用法错误），与旧
    # `python -m ecommerce_video.validate_kb` 的 sys.exit(main(...)) 一致
    argv = []
    if args.strict:
        argv.append("--strict")
    if args.file:
        argv.append(args.file)
    sys.exit(validate_kb.main(argv))


def build_parser() -> argparse.ArgumentParser:
    """构建 argparse 子命令解析器（prog 固定为 ecommerce-video，与 console script 一致）。"""
    parser = argparse.ArgumentParser(
        prog="ecommerce-video",
        description="电商 AI 视频工作流 CLI：知识库驱动的提示词引擎 + 开放模型接入 + 批量生成",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    p = sub.add_parser("check", help="配置自检（复用 config.check_config + capability）")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("status", help="任务状态统计")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("init", help="初始化数据库")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("import", help="导入任务（jobs.json）")
    p.add_argument("jobs", metavar="<jobs.json>")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("confirm", help="发放入场券（确认单全✓）")
    p.add_argument("job_key", metavar="<job_key>")
    p.set_defaults(func=_cmd_confirm)

    p = sub.add_parser("confirm-all", help="项目内全部任务批量发放入场券")
    p.add_argument("project", metavar="<project>")
    p.set_defaults(func=_cmd_confirm_all)

    p = sub.add_parser("run", help="从队列取任务生成（串行，可多次跑）")
    p.add_argument("--limit", type=int, default=5, metavar="N")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("gen", help="AI 提示词生成（需 LLM key，prompt_engine）")
    p.add_argument("sb", metavar="<sb.json>")
    p.add_argument("-o", "--output", dest="output", default=None, metavar="jobs.json")
    p.add_argument("out", nargs="?", default=None, metavar="[jobs.json]")
    p.add_argument("--project", default=None, metavar="PROJECT",
                   help="项目标识（storyboard 缺 project 时注入 jobs）")
    p.add_argument("--sku", default=None, metavar="SKU",
                   help="SKU 标识（storyboard 缺 sku 时注入 jobs）")
    p.add_argument("--category", default=None, metavar="CATEGORY",
                   help="品类（storyboard 缺 category 时注入 jobs）")
    p.set_defaults(func=_cmd_gen)

    p = sub.add_parser("dry", help="元提示词干跑（不调 LLM，调试用）")
    p.add_argument("sb", metavar="<sb.json>")
    p.set_defaults(func=_cmd_dry)

    p = sub.add_parser("validate", help="校验生成的 jobs.json（规则检查）")
    p.add_argument("jobs", metavar="<jobs.json>")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("kbcheck", help="知识库 JSON Schema 校验（validate_kb）")
    p.add_argument("--strict", action="store_true", help="严格模式：warning 也报错，退出码 1")
    p.add_argument("file", nargs="?", default=None, metavar="[<file>]")
    p.set_defaults(func=_cmd_kbcheck)

    return parser


def main(argv=None):
    """CLI 统一入口。

    :param argv: 参数列表；None 时取 sys.argv[1:]。返回退出码（0=成功）。
    :note: 个别子命令（kbcheck / run 配置缺失 / gen 缺 key）内部直接 sys.exit，
           与旧入口行为一致（SystemExit 向上传播）。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        # 裸 `ecommerce-video` → 打印帮助（旧版裸调用默认跑 status，统一入口改为帮助更清晰）
        parser.print_help()
        return 0
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
