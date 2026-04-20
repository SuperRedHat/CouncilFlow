# CouncilFlow 架构设计

## 1. 架构目标 / 核心原则 / 技术选型
（§1-§26 保留 git 历史原文，详见 commits 50e68be 及之前的 .claude/state/architecture.md）

## 27. 变更记录（2026-04-20，工作流 token 效率优化轮）
0.1.3 发布版本的架构。新增 `councilflow.config.when_eval` / `councilflow.controller.role_router` / `councilflow.controller.convergence_evaluator` 三个模块，扩展 `RoleMapping` / `DiscussionSettings` schema。详见 git 历史 commits 4109fd3~26259e5。

## 28. 变更记录（2026-04-20，0.1.4 Claude Variant 路由补丁）

本次架构变更**不新增模块**，**不改协议**。只在 3 个现有模块做最小补齐。详见 CHANGELOG [0.1.4] 和 docs/release-notes-0.1.4.md。

## 29. 变更记录（2026-04-20，0.1.5 Synthesizer artifact-first + Fallback typo 补丁）

本次架构变更**不新增模块**，**不改协议**。纯 bug fix + 文档层契约修正。

### 29.1 改动面

| 模块 | 改动 | 原因 |
|---|---|---|
| `src/councilflow/cli/delegate.py:149` | `_RETRYABLE_FALLBACK_KINDS` 里的 `"process_error"` → `"process_exit"` | 字符串 typo；所有 adapter 实际发 `"process_exit"`，typo 让 fallback 从未触发过 |
| `tests/test_cli_delegate.py` | 新增 `test_fallback_retries_on_process_exit` 回归 | 未来任何人改这个白名单字符串都会撞到测试 |
| `tests/test_synthesizer_artifact_contract.py`（新增） | 新增 e2e 回归：synthesizer 只写 `.council/delegations/<id>/result.md` 时不触发 `guardrail_violation` | 把新契约钉死 |

### 29.2 Skill 协议改动（非代码）

`project-design` / `project-plan` / `project-change` 三个 skill 的 synthesizer 阶段协议对齐到 implementer 的 artifact-first 模式：

| Skill | 旧协议（0.1.4 及以前） | 新协议（0.1.5+） |
|---|---|---|
| project-design | synthesizer sidecar 直接调 `save_architecture` → 触发 guardrail | synthesizer sidecar 只写 result.md；host 主控读后调 `save_architecture` |
| project-plan | synthesizer sidecar 试图调 `save_prd` + `create_tasks` → 触发 guardrail | synthesizer sidecar 只写 result.md；host 主控读后调 `save_prd` + `create_tasks` |
| project-change | synthesizer sidecar 试图调多个 MCP → 触发 guardrail | synthesizer sidecar 只写 result.md；host 主控读后调 `save_architecture` / `save_prd` / `create_tasks` / `add_log` |

位置：AutoSkills (`D:/project/AutoSkills/skills/{claude,codex,gemini}/`) + ~/.workflow-core/skills (`~/.workflow-core/skills/{claude,codex,gemini}/`) 两仓同步。

### 29.3 保持不变

- `PROTECTED_WORKFLOW_PATHS` 默认仍 `(".claude/state", ".council/state.json")`
- `allow_workflow_state_write` 默认仍 `false`
- MCP access policy for roles：`architect`/`planner`/`synthesizer` 保留 MCP（不变），`implementer`/`tester`/`reviewer`/`fixer`/`advisor` worktree-local empty config（不变）
- `RoleMapping` / `RoleRoute` / `role_router` / `convergence_evaluator` / `when_eval` — 零改动
- Claude / Gemini / OpenAI variant 路由 — 零改动
- 0.1.4 adapter 契约 — 零改动

### 29.4 契约对齐

新契约：**synthesizer 的 host-state 写入必须由 host 主控负责，不由 sidecar 直接做**。

对齐到：
- implementer：sidecar 写 `.council/delegations/<id>/result.md` → host 读 → host 基于结果自主决策（是否 commit、是否 update_task_status）

这个模式已经在 project-next 的 implementer/tester/reviewer/fixer 流程里正常工作了 0.1.0 起的所有版本。synthesizer 的偏离是 project-design / project-plan / project-change 三个 skill 隐含假设了"synthesizer 能直写 host state"，而从来没被验证过（因为测试用例中 synthesizer 总是 local_execution，不走 sidecar）。

### 29.5 版本策略

**patch bump**（0.1.4 → 0.1.5）。理由：
- 无新协议、无新 CLI 参数、无新配置 schema
- 纯 bug fix + 文档层契约修正
- 向后兼容：0.1.4 配置不需要任何改动

CHANGELOG 双项：
- **Fixed**: fallback retry typo（`process_error` → `process_exit`）——从 0.1.3 起即存在，0.1.5 首次修复
- **Changed**: synthesizer skill 协议对齐 implementer artifact-first 模式

### 29.6 风险与缓解

1. **Skill 协议改动需要用户更新本地 skills**：本地 `~/.workflow-core/skills` 改过的用户需要 `sync-skills.ps1` 重新同步；发布时在 release-notes 明确提示
2. **Fallback typo 修复可能暴露此前被隐藏的 retry 问题**：某些 adapter 的 `process_exit` 之前不触发 retry，现在会了；如果 retry 逻辑本身有 bug，会显现。新增 TASK-100 回归测试对冲
3. **Synthesizer 契约改动不是强制性的**：用户可以选择继续用旧 skill 协议（虽然会触发 guardrail_violation），或升级到新协议。不是破坏性变更

### 29.7 测试策略

- `tests/test_cli_delegate.py`: 补 process_exit → fallback 真 retry（TASK-100）
- `tests/test_synthesizer_artifact_contract.py`（新增）: synthesizer 不动 `.claude/state` 时 orchestrator 正常返回（TASK-101）
- 回归：现有 342 tests 保持全绿，新增 ≥ 2 tests → 344+

本节不 supersede 任何前序架构，纯粹补齐 §27 `_RETRYABLE_FALLBACK_KINDS` 的 typo，并把 synthesizer 在三个 skill 的协议钉死到 artifact-first。
