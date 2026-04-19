# CouncilFlow Git 历史敏感信息审计报告

**审计日期**：2026-04-19
**审计范围**：`git log --all`（所有引用可达的 commits）
**总 commits 数**：75
**关联任务**：TASK-061
**执行人**：Claude Opus 4.7 (via `/project-next`)

## 结论

**NO_FINDINGS** — 未发现需要处置的敏感信息。仓库可以安全切换为 public（在完成本轮 /project-change 规划的其他分发准备任务后）。

## 扫描 Pattern 集合

本次审计使用以下正则 pattern，覆盖常见 API key / token / 凭据格式：

| 类别 | 正则 | 目标 |
|---|---|---|
| OpenAI API key | `sk-[A-Za-z0-9_-]{20,}` | `sk-...` 开头的密钥 |
| GitHub PAT (classic) | `ghp_[A-Za-z0-9]{30,}` | GitHub personal access token |
| Google API key | `AIza[0-9A-Za-z_-]{30,}` | Google Cloud / Gemini API key |
| Slack token | `xox[baprs]-[A-Za-z0-9-]{20,}` | Slack bot/user/app token |
| GitLab PAT | `glpat-[A-Za-z0-9_-]{20}` | GitLab personal access token |
| npm automation token | `npm_[A-Za-z0-9]{36}` | npm 自动化 token |
| 密码赋值 | `password\s*[:=]\s*[^*\s]{4,}` | `password=xxx` / `password: xxx` |
| 其他凭据 | `secret_key`, `private_key`, `bearer <20+>` | 常见变量名 / Bearer token |
| 敏感关键字（commit 消息） | `token\|secret\|credential\|password`（不区分大小写） | commit message 中异常出现的关键字 |
| 邮箱 | `[\w.%+-]+@[\w.-]+\.(com\|org\|net\|io\|cn)` | 邮箱，排除已知 git author + Claude co-author |

扫描命令示例：

```bash
git log --all -p | grep -nE 'sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{30,}|xoxb-[A-Za-z0-9-]{20,}'
git log --all --format='%H %s %ae' | grep -iE 'token|secret|credential|password'
git log --all -p | grep -nE 'password\s*[:=]\s*[^*\s]{4,}|secret_key|private_key|bearer\s+[A-Za-z0-9]{20,}'
git log --all --format='%ae' | sort -u
```

## 扫描结果明细

### 1. API Key / Service Token 模式

- `sk-*`（OpenAI）：**0 匹配** ✅
- `ghp_*`（GitHub PAT）：**0 匹配** ✅
- `AIza*`（Google）：**0 匹配** ✅
- `xoxb-/xoxp-/xoxa-/xoxr-/xoxs-`（Slack）：**0 真匹配** ✅
  - 2 条字面文本匹配，均为 commit message 中引用 pattern 自身（§26 变更记录、TASK-061 描述本身），不是真实 token
- `glpat-`（GitLab）、`npm_*`（npm）：**0 匹配** ✅

### 2. Commit 消息关键字

- `token` / `secret` / `credential` / `password`（不区分大小写，在 commit subject 或 author 邮箱中）：**0 匹配** ✅

### 3. 密码/密钥赋值模式

- `password=xxx` / `password: xxx` / `secret_key` / `private_key` / `bearer <token>`：**0 真匹配** ✅
  - 1 条字面文本匹配，为 TASK-061 验收标准中枚举扫描 pattern 自身的描述，不是真实密码

### 4. 作者邮箱

全仓库所有 commits 的 `%ae`（author email）去重后，仅存在一个值：

```
593030970@qq.com
```

此邮箱是 git 配置的 commit author 邮箱。**已是仓库公开元数据**（任何拿到此仓库的人通过 `git log` 即可见），不视为新增暴露面。与 TASK-060 刚补入的 `pyproject.toml authors[0].email` 完全一致。

### 5. 其他邮箱（除 git author 与 Claude co-author noreply 外）

全仓库扫描后除 `593030970@qq.com` 与 `noreply@anthropic.com` 外，仅剩下一类匹配：

```
councilflow@example.com
```

出现位置：测试代码（`tests/...`）中的 git 配置设置，典型如：

```python
subprocess.run(["git", "-C", str(source), "config", "user.email", "councilflow@example.com"])
```

分析：`example.com` 是 RFC 2606 保留域名，专门用于文档和测试，不对应任何真实邮件地址。此处是测试在临时 git repo 上设置占位作者邮箱以便测试 commit 逻辑。**非敏感信息** ✅

### 6. 其他可疑模式

- 未发现任何 `.env`、`.key`、`.pem`、`credentials.json`、`secrets.yaml` 类文件误提交痕迹
- 未发现内部 URL / VPN 地址 / 本地 IP 误提交
- 未发现个人真实身份信息（真名、电话、家庭地址等）泄露
- `C:\Users\David Zhai\...` 类用户家目录路径**存在**于历史 commits 中（源自 `.workflow-core` 相关脚本和 skill 内容），但这属于需要在 TASK-065/066 搬迁阶段处理的"去个人化"问题，不属于 git 历史清洗范畴，且"David Zhai" 并未与任何凭据关联，本身也是 GitHub 用户可公开看到的名字

## 结论与建议

### 是否允许切换为 public？

**是**，从敏感信息角度无阻塞。

### 是否需要执行 `git filter-repo` 等破坏性操作？

**否**。本报告未列出任何需要清洗的 finding。

### 如果将来想要收紧暴露面（可选）

虽然非必要，如果用户希望：
1. **收紧 commit author 邮箱暴露**：可以改用 GitHub 提供的 privacy noreply 格式（如 `<id>+SuperRedHat@users.noreply.github.com`），但这需要对**未来**的 commits 生效，无法改变已有历史；且当前邮箱 `593030970@qq.com` 与 pyproject.toml 已一致，切换会引入历史与 meta 不一致问题
2. **彻底清除历史邮箱**：需要 `git filter-repo --email-callback`，会**重写所有 commits 的 SHA**，破坏性操作。**未经用户显式确认不得执行**

以上均为**可选增强**，不是 open-source 的前置条件。

## 处置决策（待用户确认）

| 选项 | 操作 | 推荐 |
|---|---|---|
| A | 不做任何清洗，直接进入后续分发任务 | ✅ **推荐** |
| B | 使用 `git filter-repo` 切换作者邮箱为 GitHub noreply 格式 | ❌ 非必要，且会重写所有 SHA |
| C | 其他（用户指定） | —— |

## Audit Trail

本报告由自动化扫描工具（`grep` + `git log`）生成，原始扫描命令已在"扫描 Pattern 集合"段落列出，可完整重放。报告提交到仓库作为 TASK-061 的交付物和历史审计痕迹。

**无破坏性操作执行**：本次审计未运行 `git filter-repo`、未执行 `git push --force`、未执行 `git reset --hard`、未修改任何历史 commit。
