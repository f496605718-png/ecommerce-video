# Changelog

本项目所有值得记录的变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)（pyproject.toml 为唯一真源）。

## [Unreleased] - 2026-08-11

### Added
- **生成单元规划器 `plan-units`**（开放选项，用户决定提交策略）：
  - `per-shot`（默认）：一镜一提交，与旧版行为一致
  - `merge`：≤ 上限的多镜合并为一条提交（AI 融合连贯动作描述）；超限由 AI 在语义断点切分，AI 不可用时贪心兜底
  - 单条上限 = min(用户值 / `UNIT_MAX_SECONDS`=10, 模型 duration_max)
  - 产物与 jobs 同构，可直接走 import → confirm → run 链路
- **`reset <project>` 命令**：中断/异常残留任务复位（running/failed → pending），续传入口
- **http_utils 统一请求重试**：429 指数退避（尊重 Retry-After，上限 300s），接入 providers / prompt_engine / vision_client

### Fixed
- 🔴 **S 合成图未注入 `jobs.ref_images`** → 生成视频完全不包含商品（此前会静默跑成文生视频）；现 `gen` 后自动查找并注入合成图，找不到时明确提示
- 分镜时长未回填 `duration_sec`（每镜固定 10s 与分镜表脱节）
- LLM 请求 120s 读超时（默认超时提至 300s）
- 进程中断后任务残留 `running`（中断自动回滚 pending，可续传）
- `prompt_engine` 直接作为模块函数调用时报 `NameError: Workflow`（模块级导入修复）
- `test_custom_integration` 模块级 `os.environ.update` 污染同进程其他测试（收敛到 setUpClass/tearDownClass 隔离）

### Changed
- `API_TIMEOUT_SECONDS` 默认 120 → 300
- 03 逻辑文档新增 §8.6 生成单元规划、§8.5 合成图回填说明
- 全量测试：125 个用例全绿（含新增 12 个生成单元规划测试）

## [1.5.0] - 2026-08-10

ecommerce-video v1.5.0：开源电商 AI 视频生成工作流——知识库驱动的提示词引擎 + 开放模型接入 + 批量生成。

### 特性摘要
- **开放模型接入**：custom 零代码主路径，兼容 OpenAI 协议的模型可直接接入
- **知识库驱动**：14 品类、35 个 JSON 知识文件程序化校验（kbcheck 35/35 全过）
- **每镜精准注入**：分镜级提示词生成，镜头信息逐镜精准注入
- **全中文提示词体系**
- **CLI 11 个子命令**：check / status / init / import / confirm / confirm-all / run / gen / dry / validate / kbcheck
- **Python API**：Workflow 一键调用
- **测试**：109 + 4 全绿（unittest，GitHub Actions 双 Python 版本）
- **协议**：MIT
- **文档三件套**：README（中英双语）+ ARCHITECTURE + PROVIDERS
- **examples**：端到端示例（jobs / storyboard 样例）

### 安装
见 INSTALL.md / README.md（pip install . 或直接解压发布包使用）。
