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

0.1.3 发布后验证中发现：`resolve_adapter_model` 的白名单只支持 `codex` / `claude` / `gemini-<variant>` / `gpt-<variant>` / `o1-<variant>`，**遗漏 `claude-<variant>`**。结果是用户配置 `tester: claude-haiku` 会在 config 加载时被 `validate_model_name` 直接拒掉。0.1.4 补齐 Claude 家族的 variant 路径，完全对标 Gemini 已有实现。93+6 → 99 tasks done，版本 0.1.4 发布。

## 33. 变更记录（2026-04-20，0.1.5 Synthesizer artifact-first + Fallback typo 补丁）

0.1.4 发布后的 cnchess 测试项目暴露两个 0.1.3 已埋下的结构/编码缺陷，0.1.4 没发现也没修：

### 33.1 问题 1：Synthesizer 和 protected-paths 契约不对齐

cnchess 跑 project-design 时，delegated sidecar synthesizer 调 MCP `save_architecture`，MCP 写入落点 `.claude/state/architecture.md` 正好被 `PROTECTED_WORKFLOW_PATHS` 守护，导致 orchestrator 回滚并报 `guardrail_violation`。

根因是跨层契约矛盾：
- MCP policy 层说"synthesizer 允许用 MCP"
- Protected paths 层说"没人可以动 `.claude/state`"
- 两个层都对，但 synthesizer 用了 MCP → 被正确但无用地回滚

### 33.2 问题 2：Fallback chain 字符串 typo

`src/councilflow/cli/delegate.py:149` 的 `_RETRYABLE_FALLBACK_KINDS` 白名单写的是 `"process_error"`，但所有 adapter（base/claude/gemini/codex/openai）实际发的都是 `"process_exit"`。**typo 导致从 0.1.3 上线起，任何 fallback 都不会在子进程失败时触发。** 这是 PRD §31.2 "按角色下沉省 $" 承诺的隐含破损——用户正确配了 fallback 也没用。

### 33.3 产品要求（0.1.5）

1. **Fallback 在 `process_exit` 时必须真 retry**（字符串修正）
2. **Synthesizer 契约对齐到 implementer 的 artifact-first 模式**：
   - sidecar synthesizer 只写 `.council/delegations/<id>/result.md`（既有约定）
   - host 主控读取 artifact 后负责调 MCP `save_architecture` / `save_prd` / `create_tasks` / `add_log`
   - `--allow-workflow-state-write` 保持 opt-in 不变默认；protected-paths 硬红线保留
3. **Skill 协议同步**：project-design / project-plan / project-change 三个 skill（AutoSkills + ~/.workflow-core/skills 两仓 × 三 controller = 9 个副本组合）的 synthesizer 阶段协议更新
4. **向后兼容硬红线**：
   - 0.1.4 现有所有配置零修改继续工作
   - 99 个历史 done 任务零回改
   - Guardrail 默认行为不变
5. **发布策略**：0.1.4 → 0.1.5 **patch bump**。理由：无新协议 / 无新 CLI 参数 / 无新 schema，纯 bug fix + 文档层契约修正

### 33.4 明确不涉及（0.1.5）

- Model 可达性 ping / preflight（显式跳过；failure-then-fallback 已经够用，尤其在修 typo 之后）
- `error_kind=model_unavailable` 新分类（backlog；0.1.5 只修 typo 已经解决 90% 问题）
- Synthesizer 的职责范围（仍是综合多 artifact 产出最终稿，只是落盘方式变）
- 任何 role 的路由优先级 / when 表达式语义

### 33.5 阶段 gate

TASK-106 milestone_manual + stage_gate=true：cf-0.1.5-smoke clean 项目跑 project-design 的 synthesizer 阶段**不再** `guardrail_violation`；fake-adapter 测试证实 fallback 在 `process_exit` 时真 retry。

本节 supersede §31.2 里 fallback 链描述的"fallback 在子进程失败时会 retry"这个隐含承诺——0.1.5 之前该承诺因 typo 并未兑现。
