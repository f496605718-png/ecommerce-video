#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务数据库：SQLite 管理生成任务（状态机：pending→confirmed→queued→running→done/failed）。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime

# src 布局：src/ecommerce_video/db.py → 上上级=src，再上一级=项目根（data/ 保持在项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = PROJECT_ROOT / "data" / "schema.sql"
DB_PATH = PROJECT_ROOT / "data" / "video_jobs.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    print(f"DB 就绪: {DB_PATH}")


def add_job(job: dict) -> int:
    """新增任务（状态 pending）。job 需含：job_key/project/sku/shot_no/category/prompt。"""
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO jobs
               (job_key, project, sku, shot_no, category, model, prompt, negative_prompt,
                ref_images, duration_sec, resolution, aspect_ratio, version_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job["job_key"], job["project"], job["sku"], job["shot_no"], job["category"],
             job.get("model", "seedance-2.0"), job["prompt"], job.get("negative_prompt", ""),
             json.dumps(job.get("ref_images", []), ensure_ascii=False),
             job.get("duration_sec", 10), job.get("resolution", "1080p"),
             job.get("aspect_ratio", "9:16"), job.get("version_count", 2)),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        # 已存在则更新（幂等）
        conn.execute(
            """UPDATE jobs SET prompt=?, negative_prompt=?, ref_images=?, updated_at=? WHERE job_key=?""",
            (job["prompt"], job.get("negative_prompt", ""),
             json.dumps(job.get("ref_images", []), ensure_ascii=False),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job["job_key"]),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM jobs WHERE job_key=?", (job["job_key"],)).fetchone()
        return row["id"]
    finally:
        conn.close()


def confirm_job(job_key: str, ok: bool = True):
    """确认单全✓ → 入场券发放（confirmed）。"""
    conn = connect()
    conn.execute("UPDATE jobs SET confirm_sheet_ok=?, status=?, updated_at=? WHERE job_key=?",
                 (1 if ok else 0, "confirmed" if ok else "pending",
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def mark_queued(job_key: str):
    conn = connect()
    conn.execute("UPDATE jobs SET status='queued', updated_at=? WHERE job_key=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def mark_running(job_key: str):
    conn = connect()
    conn.execute("UPDATE jobs SET status='running', updated_at=? WHERE job_key=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def mark_done(job_key: str, video_paths: list):
    """完成一个版本后调用；全部版本完成才置 done。"""
    conn = connect()
    row = conn.execute("SELECT version_count, generated_versions, video_paths FROM jobs WHERE job_key=?",
                       (job_key,)).fetchone()
    versions = row["generated_versions"] + 1
    paths = json.loads(row["video_paths"] or "[]") + video_paths
    status = "done" if versions >= row["version_count"] else "running"
    conn.execute(
        "UPDATE jobs SET generated_versions=?, video_paths=?, status=?, updated_at=? WHERE job_key=?",
        (versions, json.dumps(paths, ensure_ascii=False), status,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def mark_qa(job_key: str, status: str, detail: str = ""):
    """质检标记：status=qa_ok/qa_fail（素材库 v1.1）。"""
    assert status in ("qa_ok", "qa_fail")
    conn = connect()
    conn.execute("UPDATE jobs SET qa_status=?, qa_detail=?, updated_at=? WHERE job_key=?",
                 (status, detail[:2000], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def mark_delivered(job_key: str):
    """交付标记（素材库 v1.1）。"""
    conn = connect()
    conn.execute("UPDATE jobs SET delivered=1, updated_at=? WHERE job_key=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def set_sku_info(job_key: str, sku_info: dict):
    """商品信息卡入库（A0 阶段）。"""
    conn = connect()
    conn.execute("UPDATE jobs SET sku_info=?, updated_at=? WHERE job_key=?",
                 (json.dumps(sku_info, ensure_ascii=False),
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def get_assets_stats() -> dict:
    """素材库统计：按质检/交付状态。"""
    conn = connect()
    qa = {r["qa_status"]: r["c"] for r in conn.execute("SELECT qa_status, COUNT(*) c FROM jobs GROUP BY qa_status")}
    dlv = conn.execute("SELECT COUNT(*) c FROM jobs WHERE delivered=1").fetchone()["c"]
    conn.close()
    return {"qa": qa, "delivered": dlv}


def mark_failed(job_key: str, detail: str):
    conn = connect()
    conn.execute("UPDATE jobs SET status='failed', status_detail=?, updated_at=? WHERE job_key=?",
                 (detail[:500], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def mark_pending(job_key: str):
    """回到 pending（中断续传用：running/failed → pending，可重新 import+confirm 或由 reset 统一处理）。"""
    conn = connect()
    conn.execute("UPDATE jobs SET status='pending', updated_at=? WHERE job_key=?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_key))
    conn.commit()
    conn.close()


def reset_project(project: str, statuses: tuple = ("running", "failed")) -> int:
    """项目级复位：把指定状态的残留任务重置为 pending（SIGKILL/异常中断后的续传入口）。
    返回受影响行数。"""
    conn = connect()
    marks = ",".join("?" for _ in statuses)
    cur = conn.execute(
        f"UPDATE jobs SET status='pending', updated_at=? WHERE project=? AND status IN ({marks})",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), project, *statuses))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def get_jobs(status: str | None = None, project: str | None = None) -> list:
    """取任务列表（可按状态/项目过滤）。"""
    conn = connect()
    sql = "SELECT * FROM jobs"
    conds, params = [], []
    if status:
        conds.append("status=?")
        params.append(status)
    if project:
        conds.append("project=?")
        params.append(project)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY project, sku, shot_no"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_queue() -> list:
    """可取队列：confirmed 且未完成的（入场券已发放）。"""
    return get_jobs(status="confirmed")


def stats() -> dict:
    conn = connect()
    rows = conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
    conn.close()
    return {r["status"]: r["c"] for r in rows}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_db()
    else:
        init_db()
        print("状态统计:", stats())
