# CouncilFlow 架构设计

## 1. 架构目标 / 核心原则 / 技术选型
（§1-§26 保留 git 历史原文，详见 commits 50e68be 及之前的 .claude/state/architecture.md）

## 27. 变更记录（2026-04-20，工作流 token 效率优化轮）
0.1.3 发布版本的架构。新增 `councilflow.config.when_eval` / `councilflow.controller.role_router` / `councilflow.controller.convergence_evaluator` 三个模块，扩展 `RoleMapping` / `DiscussionSettings` schema。详见 git 历史 commits 4109fd3~26259e5。

## 28. 变更记录（2026-04-20，0.1.4 Claude Variant 路由补丁）

本次架构变更**不新增模块**，**不改协议**。只在 3 个现有模块做最小补齐，完全对标 Gemini variant 已落地的路径。

### 28.1 改动面

| 模块 | 改动 | 依据 |
|---|---|---|
| `src/councilflow/models/roles.py` | `resolve_adapter_model` 新增 `claude-` 前缀分支；`MODEL_ALIASES` 调整让 `haiku/sonnet/opus/claude-3-5-*` 等短名映射到保留 variant 的长名（`claude-haiku/claude-sonnet/claude-opus`）而非吞掉 variant 的 `claude` | 同 §25.2 model name 归一化层；对标 `gemini-` / `gpt-` / `o1-` 前缀 |
| `src/councilflow/providers/claude_code_cli.py` | `ClaudeCodeCliAdapter.__init__` 加 `model: str \| None = None`；构造 command 时在 `-p` 前插入 `["--model", variant]`；`ProviderResponse.metadata.claude_variant` 带 variant | 严格对标 `GeminiCliAdapter` §14.2 第 38-57 行 |
| `src/councilflow/cli/delegate.py::get_provider_adapter` | 现有 gemini-variant 特例分支旁新增 claude-variant 特例：`claude-<variant>` 且 `<variant>` 非空非 `claude` 时 → `ClaudeCodeCliAdapter(model=<variant>)` | 参考现有 line ~200 gemini 特例 |

### 28.2 保持不变

- `RoleMapping` / `RoleRoute` / `role_router` / `convergence_evaluator` / `when_eval` — 零改动
- `Discussion` schema + convergence 三模式 — 零改动
- Provider adapter registry / 其他 providers — 零改动
- 所有 workflow skills / 阶段机 / discuss 协议 — 零改动

### 28.3 adapter 契约对齐

Claude adapter 对齐 Gemini adapter 的双字段模式：

| Property | Gemini | Claude (0.1.4+) |
|---|---|---|
| `model_name`（家族归一） | `"gemini"` | `"claude"` |
| variant 存储 | `metadata.gemini_variant` | `metadata.claude_variant` |
| CLI flag 传递 | `--model <gemini_variant>` | `--model <claude_variant>` |
| 简写行为（无 variant） | `model_name=gemini`，不加 `--model` | `model_name=claude`，不加 `--model`（完全等价于 0.1.3） |

这保证 §29.6 的 `ProviderResponse.model` 归一化契约（对外只暴露家族名，不暴露具体 variant 版本号）对 Claude 家族同样生效。

### 28.4 版本策略

- **0.1.4**：patch bump（non-breaking，纯补漏）
- SemVer 理由：没有新协议 / 新命令 / 新字段；完全向后兼容；存在的目的是把 0.1.3 宣传的 Dynamic Role Routing feature 对 Claude 家族真正补齐
- CHANGELOG 标注为 `Added` + `Fixed` 双项：Added Claude variant routing，Fixed 0.1.3 default-config Example 1 的 claude-haiku 现在真能 work

### 28.5 风险与缓解

1. **Claude Code CLI 对 `--model` 的真实别名接受度**：透传机制下完全取决于 Anthropic CLI；smoke 阶段用 `claude --model haiku -p test` 单独验证
2. **MODEL_ALIASES 吞 variant 的历史条目**：现有 `claude-3-5-sonnet → claude` 这类条目需要改为 `claude-3-5-sonnet → claude-sonnet` 保留 variant；测试覆盖现有 alias 测试全绿
3. **Fallback 链行为**：variant 在 fallback 链里的行为已由 0.1.3 机制覆盖，`[claude-haiku, claude, gemini]` 这类混合链路合法

### 28.6 测试策略

- `tests/test_alias_normalization.py`: 补 claude variant 通过 validate + 短名别名映射正确
- `tests/test_claude_adapter.py`（新增）或 test_providers.py: 构造带 model 的 adapter，断言 `--model` 在 command 中
- `tests/test_cli_delegate.py`: 动态路由到 `claude-haiku` 全链路成功
- 回归：现有 318 tests 保持全绿

本节不 supersede 任何前序架构，纯粹补齐 §27.1 `role_router` 下游的 adapter 侧能力缺口。
