# CouncilFlow 分发与开源切换手册

> 这份文档是 [readme.md](../readme.md) 的深度版本。
> readme 回答"装好后怎么用"，这份文档回答"从零搭起来 / 从私有翻成开源 / 出问题怎么办"。

---

## 目录

- [新电脑安装](#新电脑安装)
- [开源切换](#开源切换)
- [故障排查](#故障排查)

---

## 新电脑安装

完整安装 = **CouncilFlow 本体** + **AutoSkills 配套**，两步。

### 前置要求

| 组件 | 最低版本 | 说明 |
|---|---|---|
| Python | 3.13 | CouncilFlow 本体运行时 |
| pipx | 任意近期版 | 隔离安装 Python CLI |
| Git | 2.30+ | 从 private repo 拉取 |
| Node.js | 20.x LTS+ | 构建 project-manager MCP server |
| PowerShell | 7+ (Windows) | 跑 bootstrap.ps1 |
| bash | 4+ (macOS/Linux) | 跑 bootstrap.sh |
| Codex CLI / Claude Code CLI / Gemini CLI | 最新 | 至少装一个作为主控 |
| GitHub 访问凭据 | PAT 或 SSH key | 两仓库都是 private |

### 第一步：安装 CouncilFlow 本体

```bash
# HTTPS + PAT（推荐）
pipx install git+https://<PAT>@github.com/SuperRedHat/CouncilFlow.git

# 或：HTTPS 不带 PAT，交互输入
pipx install git+https://github.com/SuperRedHat/CouncilFlow.git

# 或：SSH
pipx install git+ssh://git@github.com/SuperRedHat/CouncilFlow.git
```

PAT 需要的权限：只读（`repo` 范围的 read 足够）。

装完后 pipx 会把 `council` 命令加入 PATH。重新打开一个 shell 验证：

```bash
council status
```

### 第二步：安装 AutoSkills 配套

```bash
# 1. 克隆
git clone https://github.com/SuperRedHat/AutoSkills.git
cd AutoSkills

# 2. Bootstrap
pwsh scripts/bootstrap.ps1         # Windows
# 或
bash scripts/bootstrap.sh          # macOS / Linux

# 3. 先试 dry-run 看每一步做什么
pwsh scripts/bootstrap.ps1 -DryRun # Windows
bash scripts/bootstrap.sh --dry-run # macOS / Linux
```

bootstrap 按顺序做：
1. 把用户当前环境的 skills + MCP 注册信息做时间戳快照（便于回滚）
2. 同步 `skills/project-*` 到 `~/.claude/skills/`、`~/.codex/skills/`、`~/.gemini/skills/`
3. 在 `mcp/project-manager/` 下 `npm install && npm run build`
4. 按 `mcp-manifest.json` 向三端注册 MCP server
5. 最后 `codex mcp get project-manager` / `claude mcp get project-manager -s user` / 读 `~/.gemini/settings.json` 做端到端校验

### 验证完整安装

```bash
# CouncilFlow
council status

# MCP server 三端可见
codex mcp get project-manager
claude mcp get project-manager -s user
cat ~/.gemini/settings.json | grep -A5 project-manager

# 任一主控里新开会话调用 /project-status 能响应
```

全部 OK 就完成了。没 OK 去 [故障排查](#故障排查)。

### PAT 怎么配

GitHub 官方文档最准，不要信我写的链接：

- 在 GitHub 头像 → Settings → Developer settings → Personal access tokens 创建
- Classic token 选 `repo` 范围；Fine-grained token 选具体仓库 + `Contents: Read-only`
- 保存 token 到一个安全地方（离开页面就再也看不到）
- git 侧配置：
  ```bash
  # Windows (Credential Manager 会自动存)
  git config --global credential.helper manager

  # macOS (Keychain)
  git config --global credential.helper osxkeychain

  # Linux
  git config --global credential.helper store  # 明文存 ~/.git-credentials，仅在私人机器用
  ```
- 或者用 GitHub CLI：`gh auth login` 按交互提示走完

---

## 开源切换

"翻 public"这个动作本身只是 GitHub 上一次点击。真正要做的是把**可能在 public 之后出问题的东西**提前处理好。

### 有序清单

```
☐ 1. 确认 LICENSE 存在且是 MIT 全文
☐ 2. Git 历史敏感信息审计（TASK-061 的报告）
☐ 3. pyproject.toml 元数据齐全
☐ 4. readme.md 面向外部读者（不假设读者是你本人）
☐ 5. 在 GitHub 上 Settings → Change visibility → Make public
☐ 6. （可选）PyPI 发布
```

### 1. LICENSE 检查

```bash
test -f LICENSE && head -1 LICENSE
```

应该是：

```
MIT License
```

如果不是 → 翻开源前补齐（TASK-060 已经做过）。

### 2. Git 历史审计

看 `docs/git-history-audit-2026-04-19.md`。

- 报告结论是 **NO_FINDINGS** → 直接往下走
- 报告列出 findings → **停下**，和团队决定处置方案。`git filter-repo` 会重写所有 commit SHA，**破坏性**操作，需要：
  - 确认所有协作者都同意
  - 本地先做完整 bare backup：`git clone --mirror . ../councilflow-backup-<date>.git`
  - 跑 `git filter-repo --email-callback ...` 或 `--replace-text secrets.txt`
  - 强推：`git push --force-with-lease --all && git push --force-with-lease --tags`
  - 通知协作者重新 clone

### 3. pyproject.toml 元数据

```bash
python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); p=d['project']; print('license:', p.get('license')); print('authors:', p.get('authors')); print('urls:', p.get('urls'))"
```

TASK-060 已补齐 `license`、`authors`、`urls`。如果翻 public 时有额外字段想补（比如 `classifiers`、`keywords`），在这一步一并做。

### 4. readme.md 外部化检查

- 人名只出现在 Copyright 行，不在正文提 "David" / "我"
- 不引用只有你能看懂的内部 URL / Jira / Notion 链接
- 安装命令中的 PAT / SSH 说明在 public 之后依然有效（HTTPS 不带凭据会走匿名拉取，public repo 就不需要 PAT）

### 5. GitHub 翻转可见性

GitHub 仓库页 → Settings → General → Danger Zone → Change visibility → Make public。

翻完**立即**：

- 再跑一遍 `pipx install git+https://github.com/SuperRedHat/CouncilFlow.git`，不带 PAT，确认匿名 clone 能装上
- `council status` 还能正常输出
- 原本用 PAT 安装的用户**不用动**，老命令继续有效

### 6. （可选）PyPI 发布

翻 public 之后才考虑。步骤：

```bash
# 1. 先去 PyPI 搜 "councilflow"，确认名字还没被抢注
# 2. 本地构建
pip install build twine
python -m build  # 产物在 dist/

# 3. 先发 TestPyPI 过一遍
twine upload --repository testpypi dist/*
pipx install --index-url https://test.pypi.org/simple/ councilflow  # 测试装

# 4. 正式发
twine upload dist/*
```

发完后 `pipx install councilflow` 就能用了。

**如果 `councilflow` 名字被抢了**：
- 换名字（`councilflow-cli`、`councilflow-sidecar` 之类），需要改 pyproject 里 `name` 字段
- 或者申请抢回来（PyPI 对 legitimate use 会考虑，但流程慢）
- 从私有 git 安装的用户不受影响

---

## 故障排查

每一项格式：**症状 → 原因 → 解决**。

### pipx install 失败：`Could not fetch`

**症状**：
```
ERROR: Could not fetch URL https://github.com/SuperRedHat/CouncilFlow.git/
HTTP error 404 while getting ...
```

**原因**：仓库是 private，未提供有效凭据。

**解决**：
- 确认 GitHub 账号对 `SuperRedHat/CouncilFlow` 有 read 权限
- 用 HTTPS + PAT：`pipx install git+https://<PAT>@github.com/...`
- 或配 SSH key，用 `git+ssh://git@github.com/...`
- Windows 下 Credential Manager 有时会缓存过期凭据，先 `git credential-manager erase` 清掉再重试

### pipx install 失败：`ERROR: Package 'councilflow' requires a different Python`

**症状**：
```
ERROR: Package 'councilflow' requires a different Python: 3.11.x not in '>=3.13'
```

**原因**：当前 pipx 默认 Python 低于 3.13。

**解决**：
- 装 Python 3.13+
- 让 pipx 用它：
  ```bash
  pipx install --python python3.13 git+https://github.com/SuperRedHat/CouncilFlow.git
  ```
- 或 `pyenv install 3.13 && pyenv global 3.13`

### `council` 命令找不到（Windows PATH 未生效）

**症状**：新装完，新开终端打 `council` 报 `command not found`。

**原因**：
- pipx 安装目录未加入 PATH
- 当前 shell 读取的是旧 PATH

**解决**：
```bash
pipx ensurepath
# 重启终端或：
. ~/.bashrc   # bash
. ~/.zshrc    # zsh
# Windows PowerShell: 关闭再重开
```

如果 `pipx ensurepath` 也不生效，手动把 `~/.local/bin` 或 `%USERPROFILE%\.local\bin` 加到 PATH。

### AV 误报 / SmartScreen 拦截

**症状**：Windows Defender 或三方杀软把 `council.exe` 或 `npm` 生成的产物当恶意软件删掉；SmartScreen 弹"此应用可能不安全"。

**原因**：
- pipx 使用的 `launcher.exe` 是通用 Python launcher，被某些启发式规则误判
- 自带杀软（尤其国内杀软）对未签名 Python 包装器不友好

**解决**：
- 在杀软白名单里加：
  - `%USERPROFILE%\pipx\`（pipx 的隔离 venv 目录）
  - `%USERPROFILE%\.local\bin\`（council 实际入口）
- SmartScreen 第一次运行时选"更多信息 → 仍要运行"
- 这不是 CouncilFlow 特有问题，任何 Python CLI（poetry、black、httpie）都会踩

### AutoSkills bootstrap 失败：`npm install` 报 `EACCES`

**症状**：macOS/Linux 下 bootstrap.sh 跑到 `npm install` 报权限错。

**原因**：Node.js 用 sudo 装过一次，全局目录权限搞乱了。

**解决**：
- **不要**用 sudo npm install，这是最常见陷阱
- 给 npm 换用户目录：
  ```bash
  mkdir -p ~/.npm-global
  npm config set prefix '~/.npm-global'
  # 加 ~/.npm-global/bin 到 PATH
  ```
- 或直接用 nvm / fnm / volta 管 Node

### AutoSkills bootstrap 失败：`codex mcp add` 找不到命令

**症状**：bootstrap 跑到 MCP 注册时报 `codex: command not found`（或 claude / gemini）。

**原因**：对应的 CLI 没装。

**解决**：
- 你不需要三端都装齐。bootstrap 会**跳过**没装的 CLI，只对装了的那一端做注册
- 如果某端装了但命令不识别，确认 PATH 里能找到：`which codex` / `where claude` / `which gemini`
- 如果 bootstrap 报错退出而不是跳过，升级 bootstrap 脚本（TASK-068 的容错分支）

### `claude mcp get project-manager -s user` 不可见

**症状**：bootstrap 成功结束，但 `claude mcp get project-manager -s user` 报 not found。

**原因**：
- Claude Code CLI 的 MCP 有 per-project 和 per-user 两种 scope
- bootstrap 默认注册到 user scope，但如果你在某个项目目录里跑 `claude mcp get` 未加 `-s user`，它会只看 project scope

**解决**：
- 总是带 `-s user`：`claude mcp get project-manager -s user`
- 或把它加到某个具体项目的 `.claude.json`：`claude mcp add project-manager -s project ...`

### MCP server build 失败：`Cannot find module 'typescript'`

**症状**：bootstrap 在 `npm run build` 报 ts 编译相关错。

**原因**：`node_modules` 没装齐，或 devDependencies 被 `npm install --production` 跳过了。

**解决**：
```bash
cd AutoSkills/mcp/project-manager
rm -rf node_modules dist
npm install   # 不加 --production
npm run build
```

### `council status` 报 `.council/config.yaml missing`

**症状**：在某个项目目录下第一次跑 `council status`，报配置文件缺失。

**原因**：当前版本要求每个项目有自己的 `.council/config.yaml`。

**解决**：
- 用当前项目 CouncilFlow 的**自动补齐**机制：随便跑一条 `council discuss` 或 `council delegate`，CouncilFlow 会自动从模板创建 `.council/config.yaml`
- 或者手动 `mkdir .council && cp <councilflow-install-dir>/templates/default-config.yaml .council/config.yaml`

### 讨论跑到一半报 `idle_timeout`

**症状**：`council discuss` 或 `council delegate` 中途终止，错误 `kind=idle_timeout`。

**原因**：provider 长时间无输出，被判定失活。

**解决**：
- 提高项目级 config：
  ```yaml
  provider_runtime:
    idle_timeout_seconds: 600      # 默认 180，调到 10 分钟
    total_timeout_seconds: 7200    # 默认 3600
  ```
- 或调大全局环境变量：`COUNCILFLOW_IDLE_TIMEOUT=600 council discuss ...`
- 如果是 Claude Code CLI 做 sidecar，确认其 `--output-format stream-json` 可用（新版 CLI 才支持）

### `council delegation wait` 等得过久

**症状**：`council delegate` 返回后 shell 退出，但实际 sidecar 还在跑，不知道怎么等。

**解决**：
```bash
# 从 handoff.yaml 或 stderr 找 delegation_id
council delegation wait <delegation_id> --project-root . --timeout 7200
```

`delegation wait` 是轮询式等 `.council/delegations/<id>/record.json` 出现 `status=completed|failed`。最多等 2 小时。

---

## 相关链接

- [readme.md](../readme.md) — 安装与日常使用简版
- [docs/integration.md](integration.md) — workflow 集成契约、sidecar isolation、failure report protocol
- [docs/user-guide.zh-CN.md](user-guide.zh-CN.md) — 中文用户指南（逐命令）
- [AutoSkills 仓库](https://github.com/SuperRedHat/AutoSkills) — 配套 skills + MCP server
- [pipx 官方文档](https://pipx.pypa.io/stable/)
- [GitHub PAT 管理](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
