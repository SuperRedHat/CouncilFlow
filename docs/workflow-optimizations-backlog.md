# CouncilFlow Workflow Optimizations Backlog

> **本文档性质**：未实施的优化点清单。
> **收集日期**：2026-04-20
> **触发**：针对"跨模型上下文设计合理性"评估的副产物（详见讨论记录）。
> **消费方**：CouncilFlow 维护者，作为未来迭代候选项。**本清单中的优化点不代表已规划任务 / 不代表一定会实施 / 不是用户需求，只是一份待评估的技术债与优化机会清单**。

## 使用方式

- 每一项独立可评估 priority 和 impact
- 挑选要做的项时走 `/project-change` 正式登记，别直接拍脑袋开工
- 做完后在本文档对应项后面加 `✅ 2026-MM-DD: 见 TASK-XXX`

---

## 已在排期 / 已实施

- **Link folding 优化**：`local_execution` 链路折叠 —— 2026-04-20 用户确认优先做，走 /project-change 登记中（TASK-ID 待分配）

---

## 优化清单（按 impact 排序）

### A. 动态角色路由（Dynamic Role Routing）

**问题**：`.council/config.yaml` 的 `roles` 当前是静态单选：
```yaml
roles:
  implementer: claude
```

无法表达：
- "优先 codex，失败降级 claude"（fallback）
- "复杂任务 opus，简单任务 haiku"（tier-based）
- "按任务 `complexity` 字段动态选"（task-aware）

**建议设计**：
```yaml
roles:
  implementer:
    - model: codex
      when: "task.complexity == 'L'"
    - model: claude
      when: "task.complexity in ['S', 'M']"
      fallback: gemini
  tester:
    model: claude-haiku  # 简单任务统一便宜模型
```

**收益**：节省 30-60% token 成本（把验证类任务路由到便宜模型），且提升鲁棒性（fallback 机制防止单一 provider 故障阻塞 workflow）。

**风险**：配置 schema 升级需要向下兼容；`when` 表达式需要安全的评估器（不能任意 eval）。

**Priority**: High
**Complexity**: L

---

### B. `min_rounds` 从硬轮数改为语义收敛检查

**问题**：`discussion.min_rounds=2` 的设计是为防"第一轮外部说好就收敛"的橡皮图章场景（PRD §23）。但它过校正了：
- 外部第一轮给出实质反对且论据明确 → 控制器该立即响应并收敛，但仍被强制再跑一轮
- 外部第一轮表达同意无新信息 → 强制再跑一轮的结果基本是复述

**建议设计**：
- 保留 `min_rounds` 字段但默认 1
- 新增 `convergence_policy`：
  ```yaml
  discussion:
    min_rounds: 1
    convergence_policy: semantic   # 可选: strict_count | semantic | hybrid
  ```
- `semantic` 模式下：controller 每轮结束时评估 `introduced_new_info && new_disagreements`，连续 N 轮为 false 才算收敛，不看轮数

**收益**：短决策节省 30-50% 讨论 token；长决策仍能充分展开。

**风险**：语义评估本身需要 LLM 判断 → 引入新的 token 开销；需要明确"无新信息"的判定标准防止永远不收敛。

**Priority**: Medium
**Complexity**: M

---

### C. Sidecar 按角色类型分层隔离

**问题**：当前 `sidecar_isolation` 契约（PRD §28）对所有 delegated 角色都 materialize 工作区、跑 subprocess、diff 导回。对 `advisor`（只求个意见）这种只读分析类角色是高射炮打蚊子。

**建议设计**：在角色上加 `workspace_strategy`：
| 角色 | 类型 | workspace_strategy |
|---|---|---|
| implementer, fixer | 改动型 | `full_isolation` (current default) |
| advisor, architect, planner, synthesizer | 分析型 | `readonly_prompt` (no workspace) |
| tester | 验证型 | `isolated_but_no_import` |
| reviewer | 混合 | `readonly_with_optional_import` |

**收益**：分析类角色 per-call 启动时间从 ~2-3s 降到 ~300ms；节省磁盘 I/O；isolated workspace materialize 的 token 开销（如果是 git worktree 类策略）省下来。

**风险**：需要分类每个角色，文档更新量大；潜在的一致性缺口（如果用户把 advisor 当 implementer 用）。

**Priority**: Medium
**Complexity**: M

---

### D. Artifact 结构化 schema 而非自由 Markdown

**问题**：目前只有 `reviewer` 的 findings 有结构化 schema（`finding_id` / `severity` / `title` / `affected_files` / `rationale` / `required_fix`）。其他角色（architect_result、planner_result、implementer_result 等）都是自由 markdown。

**副作用**：
- 跨模型读取时需要做"语义翻译"（claude 产出的自由 md 喂给 codex 时，codex 要先解析风格）
- 不能机械化消费（比如"列出所有 architect 提到的风险"这类查询无法程序化做）

**建议设计**：所有 role-driven stage 的 artifact 都采用两层结构：
```yaml
# frontmatter: 结构化字段
role: architect
stage_inputs: [prd, ...]
decisions: [...]
risks: [...]
constraints: [...]

---

# body: 自由 markdown（阅读友好）
```

**收益**：跨模型一致性；artifact 可以被其他工具（项目 manager MCP、CI）机械消费。

**风险**：schema 膨胀 → 每个角色一套 schema 维护成本高；自由表达空间变小可能限制灵感。

**Priority**: Medium-Low
**Complexity**: L

---

### E. 同 discussion 内多 turn 合并成单次 provider 调用

**问题**：当前 `discussion_orchestrator` 每个 turn 单独启动一次 provider subprocess。一轮典型 discuss（2 min_rounds × 3 参与者 = 6 turns）= 6 次 subprocess 启动（每次 ~1-2s 启动开销 + re-tokenize handoff）。

**建议设计**：
- 检测"同一个参与者在同一个 discussion 中即将连续出现多次"（比如 round 1 和 round 3 都要 gemini 说话）
- 合并成一次 provider 调用，用 multi-turn prompt 表达"先回答 round 1，然后看看 round 2 的反馈，再给 round 3 回答"
- 仅对"同 discussion + 同模型 + 相邻 turn"合并；跨 discussion 不合并（保持审计独立性）

**收益**：启动开销减半到三分之一；prompt cache 命中率提高。

**风险**：provider CLI 对 multi-turn 的支持不统一（Codex/Claude/Gemini CLI 各家接口不同）；discussion 的"逐轮收敛判断"逻辑需要改为"批量回合内判断"。

**Priority**: Low（只有在 discussion 密集使用的项目才明显）
**Complexity**: L

---

### F. 增量 Handoff（Delta Handoff）

**问题**：`project-next` 的 `implementer → tester → reviewer` 链路中：
- `implementer_result.md` 被 tester 读一次 + 被 reviewer 读一次 = 同一个工件 tokenize 2 次
- 如果工件 10k tokens → 浪费 10k tokens

**建议设计**：handoff package 支持"引用前一阶段 artifact + 只传 delta"：
```yaml
required_artifacts:
  implementer_result:
    path: .council/delegations/del_042/result.md
    mode: incremental   # 或 full
    since_commit: abc123  # 仅对 full 的补充
```

- `full` 模式（默认）：完整传
- `incremental` 模式：只传自上次 stage 之后新增的 diff

**收益**：长 artifact 链路可以节省 50-70% 重复读。

**风险**：实现复杂度高（需要 artifact 版本追踪）；增量模式下消费方必须能理解"part of" 语义，否则产生错误理解；provider 不一定支持"已知前半部分" prompt。

**Priority**: Low（收益大但实现复杂；等其他优化先落地）
**Complexity**: XL

---

### G. 跨模型 session 复用（Provider Session Reuse）

**问题**：同一个 gemini 在项目里先当 architect 再当 reviewer → 两次调用完全独立的 subprocess，完全重新读所有上下文。

**事实限制**：三家 CLI（Codex / Claude Code / Gemini）都是每次 subprocess 新起，没有官方 session 持久化机制。

**建议设计**：
- 对于支持 MCP 或 persistent session 的 provider，CouncilFlow 维护一个 session 池
- 同一个项目内，同一个模型的多次调用尽量复用 session
- 用 session ID 落盘到 artifact，支持故障时的恢复

**收益**：长会话内累计节省可观（20-40% for heavy projects）。

**风险**：严重依赖 provider CLI 能力；session 状态管理是经典的分布式系统难题（stale session / race condition）。

**Priority**: Very Low（等 provider CLI 生态成熟再说）
**Complexity**: XL

---

## 评估矩阵

| ID | 优化 | Priority | Complexity | 预估收益 | 已排期 |
|---|---|---|---|---|---|
| Link folding | `local_execution` 链路折叠 | **High** (immediate) | M | **40-60%** ceremony ↓ | 走 /project-change |
| A | 动态角色路由 | High | L | 30-60% cost ↓ | No |
| B | min_rounds 语义化 | Medium | M | 30-50% discuss ↓ | No |
| C | Sidecar 分层 | Medium | M | 启动时间 ↓ | No |
| D | Artifact schema | Medium-Low | L | 跨模型一致性 ↑ | No |
| E | Turn 合并 | Low | L | 20-30% discussion ↓ | No |
| F | 增量 handoff | Low | XL | 50-70% chain read ↓ | No |
| G | Session 复用 | Very Low | XL | 20-40% heavy project ↓ | No |

---

## 不建议做的"优化"

**本节记录看起来像优化但评估后不该做的想法**，防止未来重新提出时做重复评估。

### ❌ 跨模型共享隐式对话上下文

诱惑：让 gemini 能"看见"之前 claude 的对话，省重新 tokenize。
**为什么不做**：违反 `no_hidden_context_sharing` 架构原则（arch §1.3）。可审计性是比 token 效率更核心的属性。当前显式 handoff 的代价是**特性**不是 bug。

### ❌ 让单一角色承担多职（比如 tester + reviewer 合并）

诱惑：tester 和 reviewer 都要读 implementer_result，合并能省一次 tokenize。
**为什么不做**：PRD §27 明确要求 `tester_passed` 和 `review_passed` 是两个独立信号，合并会丢失这个独立验证的价值。token 省了，但质量信号降级。

### ❌ 取消 `.council/delegations/` artifact 落盘

诱惑：local_execution 根本没启动 sidecar，干嘛还写 artifact？
**为什么不做**：artifact 是审计链的一部分。half year 后看的可替换性 > 现在节省的几 KB 磁盘。

---

## 反馈

本 backlog 是 living document。发现新的优化机会或验证了某个优化的实际收益，在对应项末尾加 `**2026-MM-DD note**: ...`。

对优先级的异议欢迎直接 edit 本文件 + commit，不要在 PR description 里单独开一份评估。
