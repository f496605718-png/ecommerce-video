# 08-GitHub发布清单 — ecommerce-video v1.5.0

> 用途：ecommerce-video 开源发布执行清单（步骤 E 产出）。每完成一项请把 `[ ]` 改为 `[x]`。
> 版本：v1.5.0 ｜ 日期：2026-08-10 ｜ 发布包：dist/ecommerce-ai-video-workflow-v1.5.0.zip

## 一、仓库初始化

- [x] `git init` 已在项目目录独立执行成功（嵌套于家目录仓库，无冲突）
- [x] 首次提交内容已暂存（`git add -A`，共 140 文件：源码 / knowledge 知识库 / tests / 文档 / CI / examples / data/schema.sql 等）
- [x] .gitignore 已追加两行：`00-项目进度快照.md`、`refs/`（原有规则未动）
- [x] `git status` 人工复核：无 .env / *.db / 00-快照 / refs / output / jobs / dist 等敏感项
- [ ] **待办：配置 git 身份**（当前 user.name / user.email 均未配置，首次提交被 git 拒绝）：
  - `git config --global user.name "你的名字"`
  - `git config --global user.email "you@example.com"`
  - 然后补上首次提交（文件已全部暂存好）：
  - `git commit -m "chore: v1.5.0 发布准备（开源文档/CI/示例/键名修复）"`

## 二、GitHub 建仓步骤（网页操作）

1. 登录 GitHub → 右上角 `+` → **New repository**
2. 仓库名称建议：`ecommerce-video`
3. 可见性：**Public**（开源）或 **Private**（按需），自行选择
4. **不要勾选** README / .gitignore / license 模板（仓库内均已具备，勾选反而冲突）
5. 点击 **Create repository**
6. 关联远程并推送（仓库地址按实际填写）：
   ```bash
   git remote add origin <你的仓库地址>   # 例：https://github.com/<用户名>/ecommerce-video.git
   git push -u origin main
   ```
   （若本机默认分支不是 main：先 `git branch -M main`）

## 三、发布流程（打标签 + GitHub Releases）

1. 打标签并推送：
   ```bash
   git tag v1.5.0
   git push origin v1.5.0
   ```
2. GitHub 仓库页 → **Releases** → **Draft a new release**
3. Choose a tag：选 `v1.5.0`
4. Release title：`v1.5.0`
5. 正文：粘贴第四节 release notes
6. 附件：上传 `dist/ecommerce-ai-video-workflow-v1.5.0.zip`（140 文件，已审计 0 泄漏）
7. 点击 **Publish release**

## 四、Release Notes 模板（v1.5.0，中文）

```markdown
## v1.5.0

ecommerce-video v1.5.0：开源电商 AI 视频生成工作流 —— 知识库驱动的提示词引擎 + 开放模型接入 + 批量生成。

### 特性摘要
- **开放模型接入**：custom 零代码主路径，兼容 OpenAI 协议的模型可直接接入
- **知识库驱动**：14 品类、35 个 JSON 知识文件程序化校验（`kbcheck` 35/35 全过）
- **每镜精准注入**：分镜级提示词生成，镜头信息逐镜精准注入
- **全中文提示词体系**
- **CLI 11 个子命令**：check / status / init / import / confirm / confirm-all / run / gen / dry / validate / kbcheck
- **Python API**：`Workflow` 一键调用
- **测试**：109 + 4 全绿（unittest）
- **协议**：MIT
- **文档三件套**：README（中英双语）+ ARCHITECTURE + PROVIDERS
- **examples**：端到端示例（jobs / storyboard 样例）
- **CI**：GitHub Actions 双 Python 版本（含打包冒烟）

### 安装
见 INSTALL.md / README.md（`pip install .` 或直接解压发布包使用）。
```

## 五、红线自查（发布前必须全过）

- [ ] `.env` 绝不提交（已忽略；`.env.example` 为模板，可提交）
- [ ] `00-项目进度快照.md` 与 `refs/` 已加入 .gitignore（内部文件 / 参考素材，不入库）
- [ ] 发布包 0 泄漏（zip 审计：README×2 / LICENSE / CONTRIBUTING / docs×2 / examples×3 / demo×3 / 01-07 / schema.sql 等 140 文件全部在位；无 .env / .db / .pyc / 00-快照 / output / jobs / refs）
- [ ] release notes 不含任何密钥 / token / 内部地址
- [ ] 全仓 grep 无旧版本号残留（本次升版 8 文件 14 处已全改，确认通过）

## 六、发布后待办

- [ ] `ci.yml` 首次实跑：push 后 GitHub Actions 双 Python 版本跑通（含冒烟脚本 v1.5.0 zip 校验）
- [ ] PyPI 发布评估（可选，需用户决策：是否发布到 PyPI；若发布需补 twine 流程与 PyPI 账号）
- [ ] 关注首个 issue / star，收集 README 使用反馈
