# 素材库管理规范（v1.0）

> 定位：全项目资产（参考图/视频/确认单/质检记录）的统一组织与命名规范。
> 原则：**一商品一资产包**；资产路径入库可追溯；质检/交付状态可统计。
> 配套：data/schema.sql（jobs 表 v1.1 素材库字段）；数据库操作走 CLI 与 Python API（见第 8 节）。

---

## 1. 目录结构

```
assets/
└── {project}/                        ← 项目（客户/品牌）
    └── {sku}/                        ← 商品（一商品一资产包）
        ├── refs/                     ← 参考图（按锚点类型归档）
        │   ├── 01_white.png          ← 白底商品图（外形锚点）
        │   ├── 02_detail.png         ← 细节特写（材质/印花/五金）
        │   ├── 03_onbody.png         ← 使用/佩戴图（动态锚点）
        │   ├── 04_scene.png          ← 场景概念图（环境锚点）
        │   └── ...                   ← 序号_类型.png（≤9张）
        ├── shots/                    ← 生成视频（每镜一目录）
        │   ├── 01/
        │   │   ├── v1.mp4            ← 版本1
        │   │   └── v2.mp4            ← 版本2
        │   ├── 02/
        │   └── ...
        ├── storyboard.json           ← 分镜+提示词（AI 引擎输出，已确认版）
        ├── confirm_sheet.md          ← 细节确认单（入场券归档）
        ├── qa_result.json            ← 质检记录（逐镜逐项）
        └── deliver_package.json      ← 交付清单（选中的终版视频+投放适配）
```

## 2. 命名规范

| 资产 | 命名 | 示例 |
|---|---|---|
| 参考图 | `{序号}_{锚点类型}.{ext}` | `01_white.png`、`02_detail.png` |
| 生成视频 | `{sku}_shot{镜号}_v{版本}.mp4` | `silk_dress_shot01_v1.mp4` |
| 质检通过后 | 同名前缀加 `_QA_OK`（副本，不覆盖原文件） | `silk_dress_shot01_v1_QA_OK.mp4` |
| 确认单 | `confirm_sheet.md`（固定名） | — |
| 分镜 | `storyboard.json`（固定名） | — |
| 质检记录 | `qa_result.json`（固定名） | — |
| 交付清单 | `deliver_package.json`（固定名） | — |

**规则**：文件名全小写+下划线；中文仅用于字段内容不用于文件名；禁止空格（用 `_`）。

## 3. 锚点类型编号（refs 目录）

| 序号 | 类型 | 锚点作用 | 说明 |
|---|---|---|---|
| 01 | white | 外形锚点 | 白底商品图（最重要） |
| 02 | detail | 细节锚点 | 材质/印花/五金/logo 特写 |
| 03 | onbody | 动态锚点 | 使用/佩戴图（服装上身/美妆上脸/3C手持） |
| 04 | scene | 环境锚点 | 场景概念图 |
| 05-09 | 补充 | — | 多角度/平铺等，按需 |

## 4. 数据库字段（jobs 表 v1.1）

| 字段 | 说明 | 取值 |
|---|---|---|
| qa_status | 质检状态 | pending / qa_ok / qa_fail |
| qa_detail | 质检记录 JSON | 逐镜逐项 {check, pass, note} |
| delivered | 交付标记 | 0/1 |
| sku_info | 商品信息卡 JSON | 面料/色值/卖点/人群/场合…（A0 信息卡） |
| assets_dir | 资产包路径 | assets/{project}/{sku}/ |

**检索维度**（db.py 扩展查询）：按 项目 / 品类 / 质检状态 / 交付状态 / 日期。

## 5. 生命周期（与流程衔接）

```
A0 信息卡 → sku_info 入库
B/C/D 确认 → confirm_sheet.md 归档 + confirm_sheet_ok=1
E 生成 → shots/ 落盘 + video_paths 入库
质检 → qa_result.json + qa_status 更新（qa_ok/qa_fail）
交付 → deliver_package.json + delivered=1（选中终版副本 _QA_OK）
```

## 6. 质检记录格式（qa_result.json）

```json
{
  "sku": "silk_dress", "project": "demo", "date": "2026-08-07",
  "model": "seedance-2.0",
  "shots": [
    {"shot_no": 1, "version": "v1", "result": "fail",
     "checks": [
       {"check": "版型三要素", "pass": true},
       {"check": "材质动态", "pass": false, "note": "缎面生成成棉感，缺L3锚定"},
       {"check": "色值", "pass": true}
     ]},
    {"shot_no": 2, "version": "v1", "result": "ok", "checks": []}
  ],
  "summary": {"total": 9, "ok": 6, "fail": 3}
}
```

## 7. 交付清单格式（deliver_package.json）

```json
{
  "sku": "silk_dress", "project": "demo",
  "platforms": [
    {"platform": "抖音", "ratio": "9:16", "duration": "15s",
     "shots": ["silk_dress_shot01_v1_QA_OK.mp4", "silk_dress_shot03_v2_QA_OK.mp4", "..."]},
    {"platform": "信息流", "ratio": "9:16", "duration": "30s", "shots": ["..."]}
  ],
  "delivered_at": "2026-08-07"
}
```

## 8. 配套命令

数据库操作当前没有独立 CLI 子命令，统一走两条真实入口：

**1. 初始化（v1.1 schema，含素材库字段）——CLI：**

```bash
ecommerce-video init
```

**2. 质检 / 交付标记——Python API（包内模块 `ecommerce_video.db`）：**

```python
from ecommerce_video.db import mark_qa, mark_delivered

mark_qa("projA_sku1_shot01", "qa_ok", "质检明细 JSON 或说明")   # status: qa_ok / qa_fail
mark_delivered("projA_sku1_shot01")                            # 交付标记 delivered=1
```

> 注：qa / deliver 为 db.py 的**函数**（`mark_qa(job_key, status, detail)` / `mark_delivered(job_key)`），**没有对应 CLI 子命令**；状态与素材库统计用 `ecommerce-video status`。
