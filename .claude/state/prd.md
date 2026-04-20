# CouncilFlow

## 1. 产品名称
**CouncilFlow**

## 2. 产品定位
`CouncilFlow` 是一个 **CLI-first、本地优先、主控感知** 的多模型协作 sidecar 工具，给 Codex / Claude Code / Gemini CLI 用，主控感知 + 按需调用其他模型参与讨论、分工执行、结果收敛。

（§1-§30 保留 git 历史中的原文，摘要见 commits ef61ba1 及之前的 .claude/state/prd.md）

## 31. 变更记录（2026-04-20，工作流 token 效率优化轮）

本阶段引入 Dynamic Role Routing + Semantic Convergence + 基线测量工具 + council status 观测。完整内容见 git 历史 0.1.3 发布前的 PRD 版本（commits 26259e5 及之前）。

关键产出：
- PRD §31.2 动态角色路由（`RoleRoute` + `RoleMapping` list form + 受限 `when` 表达式 + fallback 链）
- PRD §31.3 语义收敛（`convergence_policy` + `min_rounds_by_topic` + `convergence_trace`）
- PRD §31.6 明确排除项：link folding / sidecar 分层 / artifact schema / session 复用 / turn merging / delta handoff
- 78+15 → 93 tasks done，版本 0.1.3 发布

## 32. 变更记录（2026-04-20，0.1.4 Claude Variant 路由补丁）

0.1.3 发布后验证中发现：`resolve_adapter_model` 的白名单只支持 `codex` / `claude` / `gemini-<variant>` / `gpt-<variant>` / `o1-<variant>`，**遗漏 `claude-<variant>`**。结果是用户配置 `tester: claude-haiku` 会在 config 加载时被 `validate_model_name` 直接拒掉。这使得 PRD §31.2 宣传的"按角色下沉便宜 Claude 子型号省 $"对 Claude 主控用户**实际上不 work**，而 Claude 是最常见主控。

**这个缺口也埋在 0.1.3 的 `default-config.yaml` 注释 Example 1 里**：该示例就写了 `claude-haiku`，用户照抄会直接报错。

### 32.1 产品要求

1. **Claude variant 路由必须真实生效**：`claude-haiku` / `claude-sonnet` / `claude-opus` / `claude-3-5-haiku` / `claude-3-5-sonnet` / `claude-4-5-sonnet` 等 variant 名必须：
   - 通过 `validate_model_name` 白名单
   - 在 `cli/delegate.py::get_provider_adapter` 被路由到 `ClaudeCodeCliAdapter(model=<variant>)`
   - adapter 在调 Claude Code CLI 时透传 `--model <variant>` flag

2. **对标 Gemini variant 已有实现**：Claude 路径完全 mirror Gemini 的 `gemini-<variant>` 路径（2026-04-17 已落地）：
   - `GeminiCliAdapter.model_name` 固定 `"gemini"`，`gemini_variant` 进 metadata → Claude adapter 同构：`model_name="claude"`，新增 `claude_variant` 进 metadata
   - Gemini adapter 构造 `--model <variant>` flag → Claude adapter 同构

3. **短名别名必须保留 variant 信息**：`haiku` / `sonnet` / `opus` 映射到 `claude-haiku` / `claude-sonnet` / `claude-opus`（保留 variant），**不是**映射到 `claude`（丢失 variant）。现有 `claude-3-5-sonnet → claude` 这类会吞掉 variant 的 MODEL_ALIASES 条目需要改为保留 variant。

4. **向后兼容硬红线**：
   - `claude` 简写语义完全不变（不加 `--model` flag，由 Claude Code CLI 自己选 default model）
   - 0.1.3 现有所有配置零修改继续工作
   - Gemini / OpenAI variant 路径 0 改动
   - 93 个历史 done 任务零回改

5. **安全**：Claude variant 名字必须通过白名单（`claude-` 前缀 + 别名表）；不接受任意字符串如 `claude-evil`

6. **发布策略**：0.1.3 → 0.1.4 **patch bump**（非 minor）。理由：没有新协议 / 新 CLI 参数 / 新配置字段，只是补齐 0.1.3 已公开 feature 的实现缺口。

### 32.2 明确不涉及
- Claude Code CLI 本身的 model 别名语义：我们只透传 `--model <name>`，Anthropic CLI 自己解析
- 任何 workflow / 阶段机 / discuss 协议变动
- Skills 的 SKILL.md 内容（当前"动态角色路由 0.1.3+"说明是通用的，不需要改 AutoSkills）
- 新的 CLI 命令 / 新的 config schema 字段

### 32.3 阶段 gate
仅 1 个最终 milestone gate（TASK-099）：在 `D:/AIProjects/test/cf-0.1.4-smoke/` clean 项目下跑 `council delegate --model claude-haiku` 和动态路由 claude 变体的端到端测试，确认 `--model haiku` 到达 Claude CLI 子进程。完整 pytest + ruff 全绿。

本节补齐 §31.2 的 feature，并 supersede 0.1.3 "claude 无 variant 支持"的隐含限制。
