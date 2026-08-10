-- 电商AI视频工作流 · 任务数据库 schema
-- 用法：python scripts/db.py init
-- 状态机：pending(分镜已导入) → confirmed(确认单全✓) → queued(已入队) → running(生成中) → done/failed
-- 入场券规则：confirmed 才能入队（03 流程 F 阶段）
-- v1.1：新增素材库字段（qa_status/delivered/sku_info/assets_dir）

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT UNIQUE NOT NULL,          -- 任务唯一键：{project}_{sku}_{shot}，如 projA_sku1_shot03
    project TEXT NOT NULL,                 -- 项目名
    sku TEXT NOT NULL,                     -- 商品/SKU
    shot_no INTEGER NOT NULL,              -- 镜号
    category TEXT NOT NULL,                -- 品类（查 knowledge/profiles 用）
    model TEXT NOT NULL DEFAULT 'seedance-2.0',
    prompt TEXT NOT NULL,                  -- 中文提示词（AI 引擎生成）
    negative_prompt TEXT,                  -- 负面词（三级合并后）
    ref_images TEXT,                       -- 参考图路径列表（JSON 数组字符串）
    duration_sec INTEGER DEFAULT 10,       -- 时长（按模型能力）
    resolution TEXT DEFAULT '1080p',
    aspect_ratio TEXT DEFAULT '9:16',
    status TEXT NOT NULL DEFAULT 'pending',
    status_detail TEXT,                    -- 失败原因/备注
    version_count INTEGER DEFAULT 2,       -- 每镜版本数
    generated_versions INTEGER DEFAULT 0,  -- 已完成版本数
    video_paths TEXT,                      -- 产出视频路径列表（JSON 数组）
    confirm_sheet_ok INTEGER DEFAULT 0,    -- 确认单是否全✓（入场券）
    -- 素材库字段（v1.1）
    qa_status TEXT DEFAULT 'pending',      -- 质检状态：pending/qa_ok/qa_fail
    qa_detail TEXT,                        -- 质检记录（JSON：逐项通过/失败+原因）
    delivered INTEGER DEFAULT 0,           -- 是否已交付投放
    sku_info TEXT,                         -- 商品信息卡 JSON（面料/色值/卖点/人群等，供追溯）
    assets_dir TEXT,                       -- 资产包目录（assets/{project}/{sku}/）
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project, sku);
CREATE INDEX IF NOT EXISTS idx_jobs_qa ON jobs(qa_status);
