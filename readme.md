# CouncilFlow

> **CLI-first、本地优先、主控感知**的多模型协作 sidecar。
> 让 Codex / Claude Code / Gemini CLI 在需要时丝滑调用别的模型来讨论、分工和收敛。

CouncilFlow 不是浏览器产品、不是后端平台、不是新的 AI 聊天前台。
它给已经在用 Codex CLI、Claude Code CLI 或 Gemini CLI 写代码的人，提供一个**增强主控能力**的薄工具——当前会话里的 AI 还是总指挥，CouncilFlow 只在真的需要别的模型参与时才被拉起。

---

## 它能干什么

1. **多模型讨论** — 把当前主控的初始立场抛给 Claude / Gemini / GPT 评论，主控再综合收敛
2. **多角色分工** — `implementer` 让 Claude 做、`reviewer` 让 Codex 做、`advisor` 让 GPT 做，由配置决定
3. **最小自动化** — 把讨论 / 规划 / 实现 / 测试 / 评审 / 修复串成最小可用闭环，不引入数据库 / Web UI / 常驻后端

核心命令一共四个：

```bash
council discuss     # 发起多模型讨论
council delegate    # 把某个角色任务委派给非主控模型
council synthesize  # 汇总讨论或委派结果
council status      # 查看 sidecar 状态
```

---

## 5 分钟快速上手

### 前置要求

- **Python 3.13+**
- **[pipx](https://pipx.pypa.io/stable/)**（`pip install --user pipx && pipx ensurepath`）
- 已安装并能跑通以下 CLI 之一：
  - [Codex CLI](https://github.com/openai/codex)
  - [Claude Code CLI](https://docs.claude.com/en/docs/claude-code/overview)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli)
- **GitHub 访问凭据**（PAT 或 SSH key；因为本仓库目前是 private）

### 安装

```bash
pipx install git+https://github.com/SuperRedHat/CouncilFlow.git
```

如果 pipx 报无法访问 GitHub：

```bash
# 方案 A：HTTPS + PAT
pipx install git+https://<your-github-pat>@github.com/SuperRedHat/CouncilFlow.git

# 方案 B：SSH（需要先配好 ssh key）
pipx install git+ssh://git@github.com/SuperRedHat/CouncilFlow.git
```

安装完成后 `council` 命令会自动加入你的 PATH，且独立在自己的 venv 里（不污染系统 Python）。

### 验证

```bash
council status
```

正常应输出当前主控识别结果、项目配置摘要、最近讨论 / 委派记录。如果报错，看 [docs/distribution.md](docs/distribution.md) 的故障排查段。

### 更新

```bash
pipx upgrade councilflow
# 或强制重装最新版
pipx reinstall councilflow
```

---

## 配套工作流：AutoSkills

CouncilFlow 本体只负责 sidecar CLI 能力。真正把 CouncilFlow 串进你日常开发节奏的，是一套配套的 `project-*` 工作流 skills 和 `project-manager` MCP server。这两块放在独立仓库 **[AutoSkills](https://github.com/SuperRedHat/AutoSkills)**（同样是 private）。

装完 CouncilFlow 后，额外跑：

```bash
# Windows (PowerShell)
git clone https://github.com/SuperRedHat/AutoSkills.git
cd AutoSkills
pwsh scripts/bootstrap.ps1

# macOS / Linux
git clone https://github.com/SuperRedHat/AutoSkills.git
cd AutoSkills
bash scripts/bootstrap.sh
```

bootstrap 会：
1. 把 `project-*` skills 同步到 Codex / Claude Code / Gemini 三端
2. 构建 `project-manager` MCP server 并向三端注册
3. 校验三端 `mcp get project-manager` 都可见

完成后你就能在任一主控里用 `/project-init`、`/project-plan`、`/project-next` 这些流程化技能，并在需要时无缝触发 CouncilFlow 讨论或委派。

---

## 常见用法

### 发起一次多模型讨论

```bash
council discuss "这个架构该怎么拆？" \
  --controller-position "我倾向按模块边界拆，因为测试会更独立" \
  --models claude,gemini
```

说明：
- 主控（当前会话 AI）先本地给出 `--controller-position` 初始立场
- CouncilFlow 把立场交给 Claude 和 Gemini 评论，**不是**让它们各自从零起草方案
- 多轮之后由当前主控综合，不再额外调外部模型做最终综合
- 不写 `--models` 时自动读取项目级 `.council/config.yaml` 的 `discussion.default_models`
- **shell 超时恢复（0.1.6+）**：如果调用方 shell 命令超时（多数桌面 CLI 是 3-4 分钟）但 discussion 还没收敛，**不要**直接当失败处理。子进程会继续跑，`summary.md` 最终会落盘。用 `council status | jq -r .data.state.last_discussion_id` 拿到 id，然后 `council discussion wait <id> --timeout 7200` 轮询到完成（详见 `docs/integration.md::Discuss wait`）

### 委派一个实现任务

```bash
council delegate --role implementer \
  --objective "实现 user 注册接口" \
  --task-summary "新增 POST /api/users 端点，带邮箱校验与冲突检测"
```

说明：
- 不传 `--model` 时从 `.council/config.yaml` 的 `roles.implementer` 读取目标模型
- 如果目标模型就是当前主控，返回 `status=local_execution`，意思是"你自己做吧，不用派出去"
- 如果是非主控模型，返回 `status=delegated`，sidecar 在独立工作区完成，产物通过 `.council/delegations/<id>/result.md` 交回

### 查看状态

```bash
council status         # 当前主控 + 最近讨论/委派/语言配置
council discuss list   # 所有讨论记录
council delegation list  # 所有委派记录
```

---

## 项目级配置

每个项目可以有自己的 `.council/config.yaml`，决定角色分工与讨论策略：

```yaml
config_version: 1
output_language: zh-CN
controller_override: null
roles:
  planner: codex
  architect: codex
  implementer: claude
  tester: claude
  reviewer: codex
  fixer: codex
  advisor: gpt
  synthesizer: codex
discussion:
  default_models: claude,gemini
  max_rounds: 5
  min_rounds: 2
```

首次在项目目录调用 `council` 时，如果 `.council/config.yaml` 不存在，会自动从模板创建。

---

## 故障排查与进阶

- **装不上 / PATH 没生效 / pipx 报 EOL Python** → [docs/distribution.md](docs/distribution.md#故障排查)
- **AV 杀软拦截** → [docs/distribution.md](docs/distribution.md#av-误报)
- **讨论跑到一半超时 / idle_timeout** → [docs/integration.md](docs/integration.md#provider-runtime)
- **MCP 没被三端识别** → 先跑 AutoSkills 的 bootstrap，再看 [docs/distribution.md](docs/distribution.md#mcp-注册)
- **想了解 workflow 失败上报协议** → [docs/integration.md](docs/integration.md#workflow-failure-report-protocol)

---

## 开源状态

当前仓库是 **private**。LICENSE 已是 MIT（见 [LICENSE](LICENSE)），将来翻转 public 不需要改任何代码，安装命令也不变。完整的"翻开源步骤清单"在 [docs/distribution.md](docs/distribution.md#开源切换)。

---

## 相关文档

- [docs/integration.md](docs/integration.md) — 集成契约、路由协议、sidecar isolation 契约、workflow failure report 协议
- [docs/distribution.md](docs/distribution.md) — 新电脑安装、开源切换、故障排查
- [docs/user-guide.zh-CN.md](docs/user-guide.zh-CN.md) — 中文用户指南（逐命令详解）
- [CHANGELOG.md](CHANGELOG.md) — 版本变更记录
- [AGENTS.md](AGENTS.md) — 面向 AI 主控的项目工作流约定

---

## License

[MIT](LICENSE) © 2026 SuperRedHat
