# 电商AI视频工作流 · 安装使用手册

> 给拿到发布包/安装包的人看。按步骤操作即可开始使用。
> 适用：Windows / macOS / Linux（需 Python 3.9+）
> 当前版本：v1.5.0（src 布局，`pip install` 可装）

---

## 一、安装（约 2 分钟）

### 方式一：pip 安装（推荐）

```bash
pip install ecommerce-video
```

> 说明：当前以发布包 / editable 安装为准（`pip install -e .` 亦可）。发布到公开 PyPI 后可直接 `pip install ecommerce-video`；在此之前请使用方式二或源码包。

### 方式二：发布包 zip

```bash
# 1. 解压发布包
unzip ecommerce-ai-video-workflow-v1.5.0.zip
cd ecommerce-ai-video-workflow-v1.5.0

# 2. 安装（自动装依赖 requests / python-dotenv）
pip install .

# 3. 初始化数据库
ecommerce-video init

# 4. 配置密钥：复制 .env.example 为 .env，填入你的 API Key（没有就先跳过，之后可补）
#    - VISION_API_KEY    视觉识别用（多模态，OpenAI 兼容）
#    - VIDEO_PROVIDER    视频生成模型（默认 seedance-2.0，可换 custom 等）
#    - {PROVIDER大写}_API_KEY  对应模型的密钥（如 CUSTOM_API_KEY / SEEDANCE_API_KEY）

# 5. 验证配置
ecommerce-video check
```

> Windows 双击方式：在文件夹地址栏输入 `cmd` 回车，再执行上述命令。
> 跑 Python/CLI 若中文乱码，先执行 `chcp 65001` 或设 `PYTHONIOENCODING=utf-8`。

---

## 二、快速开始（第一个视频）

```bash
# 0. 无密钥先体验（不调任何外部 API）
ecommerce-video dry demo_storyboard.json     # 元提示词干跑：看每镜词源怎么注入
ecommerce-video validate demo_jobs.json      # 规则校验：L1 锚定/全中文/负面词红线
ecommerce-video kbcheck                      # 知识库校验：35 文件 Schema 全部通过
ecommerce-video check                        # 配置自检（缺什么会明确列出）

# 1. 写分镜参数（demo_storyboard.json 为样例；格式见 02-分镜表模板.md）
#    每镜只需填：场景/灯光/镜头/运镜/动作/材质动态

# 2. AI 生成提示词（需 LLM Key：TEXT_LLM_API_KEY 或 VISION_API_KEY）
ecommerce-video gen demo_storyboard.json -o jobs.json

# 3. 导入任务（job 需含 project/sku/category；gen 输出需补这三个字段；
#    可直接导入的完整样例：demo_jobs_full.json）
ecommerce-video import demo_jobs_full.json

# 4. 发放入场券 → 生成（run 需真实 API Key，缺失会前置拦截）
ecommerce-video confirm-all demo
ecommerce-video run --limit 5

# 5. 看结果
ecommerce-video status     # 状态统计
# 视频在 output/videos/ 下
```

---

## 三、完整业务流程（对客户）

```
① 客户给商品参考图 + 需求
② 收集商品信息（02 模板信息卡）→ 识别确认（03 流程 B）
③ 类型推荐（六维打分）→ 客户选定
④ 细节确认单（客户确认后=入场券）→ confirm
⑤ AI 写提示词 → 批量生成 → 质检 → 交付
```

详细话术与确认流程见 `04-客户问答话术与确认流程.md`，逻辑规则见 `03-视频提示词问答与细节确认逻辑.md`。

## 四、换视频模型

**custom 零代码接入（主路径，任意 OpenAI 兼容接口）**：编辑 `.env`：

```ini
# 视频生成
VIDEO_PROVIDER=custom
CUSTOM_API_KEY=sk-你的密钥
CUSTOM_API_BASE=https://你的网关地址/v1
CUSTOM_MODEL=你的模型名

# 图片生成（合成首帧/概念图，可选）
IMAGE_PROVIDER=custom-image
IMAGE_API_KEY=sk-你的密钥
IMAGE_API_BASE=https://你的网关地址/v1
IMAGE_MODEL=你的生图模型名
IMAGE_SIZE=1024x1024
```

键名规则：`{PROVIDER大写}_API_KEY / _BASE / _MODEL`（如 `CUSTOM_API_KEY`；生图用 `IMAGE_API_KEY/BASE/MODEL/SIZE` 族，详见 `.env.example`）。

**内置 provider**：`VIDEO_PROVIDER=seedance-2.0`（默认）/ `seedance-2.5` / `agnes-video`；`IMAGE_PROVIDER=agnes-image`。

**非兼容厂商（可灵/Runway/Vidu 等签名制）**：按 `docs/PROVIDERS.md` 方式 B 写 provider 类（30–50 行）注册接入。

已登记模型能力参数（`knowledge/models.json`）：seedance-2.0（默认，已验证）/ seedance-2.5（已验证）/ kling / jimeng / runway / vidu / custom / agnes-video-v2.0（后五项 verified=false，接入时复核）。

## 五、目录说明

```
src/ecommerce_video/          # 包主体（src 布局；pip 安装后即包内数据）
├── workflow.py               # Python API 入口（Workflow 类）
├── cli.py                    # 统一命令行（ecommerce-video 11 子命令）
├── retriever.py              # 检索层（每镜精准词源，四级匹配）
├── capability.py             # 模型能力感知（生成前拦截超限）
├── prompt_engine.py          # 元提示词组装 + LLM 调用 + 校验
├── providers/                # 视频协议（seedance/agnes/custom）+ 生图协议（agnes-image/custom-image）
├── knowledge/                # 知识库（35 JSON + schema/ + raw/ + profiles/）← 单一数据源
├── db.py / config.py / validate_kb.py / ...   # 数据库/配置/校验等
tests/                        # 78 主套件 + 4 集成套件（mock server）
docs/                         # PROVIDERS.md / ARCHITECTURE.md
data/                         # 任务数据库（自动生成，SQLite）
output/                       # 生成视频（自动创建）
assets/                       # 素材归档（按 ASSETS.md 规范）
```

> 知识库在**包内**（`src/ecommerce_video/knowledge/`，随安装包一起分发，勿删）；如需自建知识库，设环境变量 `KNOWLEDGE_DIR` 指向你的目录即可覆盖。

## 六、常见问题

| 问题 | 解决 |
|------|------|
| check 报缺 VISION_API_KEY | 填 .env；或确认走人工模式（识别由人工转录） |
| run 拒绝生成报缺密钥 | 按提示补 `{PROVIDER大写}_API_KEY`（防密钥省略设计，故意拦截） |
| gen 报未配置 LLM key | 补 `TEXT_LLM_API_KEY` 或 `VISION_API_KEY`（缺省复用 VISION 配置） |
| import 报 KeyError: project | jobs.json 每条需含 project/sku/category（参考 demo_jobs_full.json） |
| 401/403 | .env 密钥有误或没填对，检查后重试 |
| 生成视频在哪个目录 | output/videos/ |
| 客户确认单怎么管理 | assets/{项目}/{商品}/confirm_sheet.md（ASSETS.md） |
| 知识库被我改了，怎么验证 | `ecommerce-video kbcheck`（35/35 通过） |
| 换模型后能力对不上 | 按模型能力调整分镜（时长/参考图数/分辨率），超限会被 capability 拦截并提示 |

## 七、升级

- **方式一/二**：`pip install -U ecommerce-video` 或替换新版本文件即可；知识库随包更新
- **数据不受影响**：`data/`（任务数据库）和 `assets/`（素材归档）保留；数据库结构升级以 schema.sql 为准，必要时 `ecommerce-video init`（幂等，不丢数据）
- 升级后建议重跑：`ecommerce-video check` + `ecommerce-video kbcheck`
