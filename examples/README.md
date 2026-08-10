# examples —— 端到端示例

本目录提供一份「分镜 → 提示词任务」的完整可运行示例，方便在**不写代码、不改核心包**的情况下体验整条流水线。

## 与根目录 demo_*.json 的关系

| 文件 | 与根目录 demo 的关系 | 用途 |
|------|----------------------|------|
| `storyboard_sample.json` | 结构对齐 `demo_storyboard.json`（分镜参数表），顶层含 `project` / `sku` / `category` | 喂给 `dry`（无密钥体验）或 `gen`（完整链路） |
| `jobs_sample.json` | 对齐 `demo_jobs_full.json`（可导入任务：每条含 `project` / `sku` / `category`） | 可直接 `validate` 与 `import`，无需先跑 `gen` |

> - 根目录 `demo_storyboard.json` / `demo_jobs.json` / `demo_jobs_full.json` 是项目级演示文件（随发布包一起分发，见 `README.md` 快速开始）；
> - `examples/` 是给使用者的**最小可运行样例**：内容更简短、更容易改造成自己的商品。复制后替换 `project` / `sku` / `sku_desc` / `material` / `model_desc` / `type` / `shots` 即可。
> - `demo_jobs.json` 只含 `shot_no/prompt/negative_prompt`（纯提示词样例，可 `validate` 不能 `import`）；`jobs_sample.json` 与 `demo_jobs_full.json` 一样是**可直接导入**的完整任务样例。

## 链路 A：无密钥体验（不需要任何 API Key）

以下命令全部为本地操作，不调用任何外部模型服务，可放心运行：

```bash
# 1. 配置自检（接单前必跑；缺失项会明确列出，不阻塞）
ecommerce-video check

# 2. 元提示词干跑：不调 LLM，看知识库按镜注入的词源怎么组装
ecommerce-video dry examples/storyboard_sample.json

# 3. 任务规则校验：L1 锚定 / 全中文 / 长度 / 负面词红线（0 问题 = 通过）
ecommerce-video validate examples/jobs_sample.json

# 4. 知识库校验：35 个 JSON 文件逐一 Schema 校验（35/35 通过）
ecommerce-video kbcheck
```

## 链路 B：完整链路（以下命令部分需要真实 API Key）

```bash
# 1. AI 写提示词（需 LLM Key：TEXT_LLM_API_KEY 或 VISION_API_KEY）
#    storyboard 顶层已含 project/sku/category，gen 会自动注入到每条 job，输出可直接 import
ecommerce-video gen examples/storyboard_sample.json -o jobs_sample_out.json

# 2. 导入任务（本地数据库操作，无需密钥；job 需含 project/sku/category）
ecommerce-video import examples/jobs_sample.json

# 3. 发放入场券（确认单全✓，本地数据库操作，无需密钥；sample 为 project 名）
ecommerce-video confirm-all sample

# 4. 批量生成（需真实 API Key：VIDEO_PROVIDER 对应厂商；缺失会前置拦截）
ecommerce-video run --limit 5

# 5. 任务状态统计（无需密钥）
ecommerce-video status
```

> **密钥说明**：`gen` 需要 LLM Key、`run` 需要视频生成厂商 API Key；`import` / `confirm-all` / `status` / `dry` / `validate` / `kbcheck` / `check` 均为本地操作，无需密钥。密钥统一在 `.env` 中配置（见 `CONFIG.md`）。

## 自检

修改 `examples/` 后请确认以下两条通过（本示例已实测通过）：

```bash
ecommerce-video dry examples/storyboard_sample.json     # 元提示词干跑通过
ecommerce-video validate examples/jobs_sample.json      # 0 问题
```
