# 贡献指南（CONTRIBUTING）

欢迎贡献！本项目是开源产品级工作流，PR 必须满足下面这些纪律才能合入。文档语言以**中文为主**（README.md 中文主文档 + README_EN.md 英文镜像；代码注释/CLI 帮助/日志均为中文）。

---

## 1. 开发环境

```bash
# 推荐：editable 安装（改代码即生效）
pip install -e .[dev]

# 依赖
#   运行时：requests、python-dotenv（见 pyproject.toml）
#   开发：pytest（可选，测试本身零第三方依赖，unittest 直接可跑）
```

- 包布局为 **src 布局**：`src/ecommerce_video/`，新增模块放包内；`tests/` 放测试
- 运行任何命令前先 `chcp 65001`（Windows）或设 `PYTHONIOENCODING=utf-8`，避免中文乱码

## 2. 测试纪律（红线）

项目有两套测试，**跑法固定，不能混**：

```bash
# 主套件 78 用例（tests/ 下 5 个文件，零第三方依赖）
python -m unittest tests.test_workflow tests.test_retriever tests.test_providers tests.test_capability tests.test_kb_integrity -v

# 开放接入集成套件 4 用例（独立跑：本地 mock server 起在 127.0.0.1）
python -m unittest tests.test_custom_integration -v
```

- **两套不能混跑**：集成套件会改写全局环境变量，主套件在 import 时读配置；先跑主套件，再单独跑集成套件
- 任何代码改动必须保证主套件 78 全绿；涉及 providers/模型接入的改动必须再跑集成套件 4 用例
- 新增功能必须带测试（unittest，风格对齐现有 tests/）

## 3. 代码风格

- Python 3.9+；类型注解（`dict`/`list`/`str | None`）必写
- 中文 docstring：每个公开函数/方法说明用途、参数、返回值
- 输出文本全中文；日志走 `logging_utils.get_logger`（stderr，不污染 stdout）
- 不引入新第三方依赖（确有必要先讨论）；不硬编码密钥（一律 `.env`，见 CONFIG.md）
- **禁止手写 if-else 分发 provider**：新增模型 = 新建模块 + 实现基类 + `@register` / `@register_image` 注册（见 docs/PROVIDERS.md）

## 4. 知识库修改规范

- 知识库是**单一数据源**：`src/ecommerce_video/knowledge/`（35 JSON + schema/ + raw/ + profiles/）
- 改任何 JSON 必须**先过 `ecommerce-video kbcheck`**（程序化 Schema 校验），35/35 通过才能提交
- 新增品类 = 新增一个 `profiles/*.profile.json` + 更新 `category-profiles.json` 索引；通用骨架不动
- 知识库内容与代码解耦：不因知识库改动升级包版本号（除非 schema 结构变更）

## 5. PR 流程

1. 从 `main` 开分支，命名如 `feat/xxx`、`fix/xxx`、`docs/xxx`
2. 改动 + 测试 + 更新文档（README 中英镜像同步改；INSTALL/CONFIG/ASSETS 如涉及）
3. 自检清单：
   - [ ] 主套件 78 全绿（集成套件涉及时单独跑 4 用例）
   - [ ] `ecommerce-video kbcheck` 35/35
   - [ ] 无 `scripts/` 旧路径残留（`python scripts/*.py` 用法已废弃，统一走 CLI/API）
   - [ ] 未提交 `.env` / 密钥 / `data/*.db` / 生成产物
4. 提 PR，描述：改了什么、为什么、测试结果

## 6. 其他约定

- 版本号：`pyproject.toml` 中 `version` 为唯一真源；`src/ecommerce_video/__init__.py` 的 `__version__` 保持同步
- 发布包自动排除历史调试脚本（`_*.py` 等）；根目录不留调试残留
- 协议 MIT（见 LICENSE）；提交即代表同意以 MIT 授权
