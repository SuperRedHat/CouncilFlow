# RFC: CouncilFlow Workflow Token Efficiency Optimization

- **状态**：草案（Draft）
- **作者**：Claude Opus 4.7（主控）+ codex（2026-04-20 discuss 参与）+ 用户（最终决策）
- **日期**：2026-04-20
- **目标版本**：0.1.3
- **关联**：PRD §31 / 架构 §27 / discuss 记录 `.council/discuss/disc_20260420T065559937703Z/summary.md` / backlog `docs/workflow-optimizations-backlog.md`
- **Supersedes**：本 RFC 是当前权威设计文档；落地后如有偏差，以代码行为为准。

---

## 1. 背景与动机

### 1.1 观察到的现象

CouncilFlow 当前工作流（PRD §18 配置优先路由 + §23 discuss 协议 + §26 workflow 硬约束 + §27 reviewer 闭环）在**所有角色路由到同一模型**的场景下（例如 `.council/config.yaml` 全 claude），单次 `/project-next` 或 `/project-change` 要走完 4-5 个阶段机 stage，每个 stage 都强制写 artifact + 下一 stage 强制重读 —— 同一模型在同一会话里被迫"忘了再读"自己刚写的内容。

这产生**可观察但未量化**的 ceremony token 开销。用户在 2026-04-20 提出是否需要优化。

### 1.2 初版设计（Link Folding）的 codex 讨论

2026-04-20 通过 `council discuss` 发起 5 轮跨模型讨论（claude↔codex），评估最初提出的 **link folding** 方案：**在 `council delegate` JSON 输出新增 `chain_context` 字段，让同模型连续 delegation 共享 chain_id，主控跳过重读**。

codex 的实质性质疑（详见 `.council/discuss/disc_20260420T065559937703Z/summary.md`）：

1. `chain_id + path list` **不足以区分代际** — retry / fixer loop / 人工编辑 / 外部进程改写都会让"同一路径"内容变化，只凭路径缓存会复用陈旧内存
2. **30 分钟超时 + 跨 skill 切换只适合做兜底**，主判据应是 session / thread identity、memory_epoch、artifact digest / write_seq
3. `expected_artifacts_in_controller_memory` 命名偏强，容易被实现者当 promise 而不是 hint
4. **复杂度可能放错层**：caller（controller）本来就知道上一阶段状态，塞进 delegate JSON 等于把 controller 本地 cache 复杂度固化到核心协议
5. **"40-60% 节省"是估算，无基线** — 可能被大幅高估
6. 未考虑并行 workflow 场景（同 controller session 交叉执行多个 workflow / task）

基于此，**本 RFC 决定：本轮不做 link folding**。改为：

- **先量化真实 ceremony 成本**（Phase 1，无代码改动）
- **再做更普适的动态路由**（A），直接降低"全同模型"场景的发生概率
- **再做语义收敛**（B），从 discuss 轮次维度降 token
- 等 Phase 1 基线数据产出后再独立评估 link folding 的 ROI

### 1.3 为什么选这两项

| 候选 | 本轮 | 理由 |
|---|---|---|
| Phase 1 基线 | ✅ | 任何后续决策都需要硬数据 |
| A 动态路由 | ✅ | 单点 $ 节省最大（30-60%），完全由用户配置权决定，不破坏现有不变量 |
| B 语义收敛 | ✅ | 讨论场景 token 直接降，复杂度中等，风险低 |
| Link folding | ❌ | 被 codex 指出多个未解决的一致性问题，且未基线就优化是盲目 |
| Sidecar 分层 | ❌ | 属于运行时性能优化（启动时间），不是 token 优化，放 backlog |
| Artifact schema | ❌ | 跨模型一致性收益，非 token 直接相关，放 backlog |
| Session 复用 / Turn merging / Delta handoff | ❌ | 实现复杂度 XL，收益递减，放 backlog |

---

## 2. 目标与非目标

### 2.1 目标

1. **给用户更丰富的模型搭配能力**：允许"tester 用 haiku / architect 用 opus / fallback 到 claude"这类真实配置
2. **让 discuss 更智能收敛**：不再被 `min_rounds=2` 硬轮数拖着跑
3. **产出硬数据**：量化当前 ceremony token 实际占比，为未来优化决策提供基线
4. **完全向后兼容**：现有所有 `.council/config.yaml` 不需要任何修改继续工作
5. **保留配置权**：不硬编码任何"推荐降档"规则；用户的 config 完全决定路由

### 2.2 非目标（本 RFC 明确不做）

1. **Link folding（同模型链路折叠）** — codex 指出协议过早固化 + 缺基线，推迟到 Phase 1 数据产出后重新评估
2. **Sidecar 按角色类型分层** — 是运行时性能优化，不是 token 优化，进 backlog
3. **Artifact 结构化 schema** — 跨模型一致性收益，非本轮核心，进 backlog
4. **Turn merging（同 discussion 内相邻 turn 合并）** — 实现复杂度 L，收益边际，进 backlog
5. **增量 handoff（delta artifact）** — 实现复杂度 XL，需要 artifact 版本追踪，进 backlog
6. **Provider session 复用** — 依赖 CLI 生态不成熟，进 backlog

完整 backlog 参见 `docs/workflow-optimizations-backlog.md`。

---

## 3. codex discuss 关键结论与我方回应

本节完整映射 codex 提出的每个质疑，以及本 RFC 采纳/拒绝/推迟的决策。

### 3.1 采纳（本 RFC 遵循）

| codex 质疑 | 我方回应 |
|---|---|
| "`chain_id + path list` 不足以区分代际" | **采纳**。本轮不做 link folding；未来若做需要 digest/write_seq 级信号 |
| "30 分钟超时只适合兜底" | **采纳**。本轮不涉及；未来 link folding 设计时必须用 session/epoch 作主判据 |
| "复杂度可能放错层" | **采纳**。本轮 A 的动态路由放在 `cli/delegate` + `role_router` 层，不塞 `delegate` JSON 协议字段；遵循 codex "最薄协议 + controller 本地判定"原则 |
| "`expected_artifacts_in_controller_memory` 命名偏强" | **采纳**（仅适用于推迟的 link folding）；本轮 A 的新字段命名（`RoutingDecision` / `ConvergenceDecision`）均为描述性而非承诺性 |
| "40-60% 节省是估算" | **采纳**。本轮 Phase 1（TASK-072/073）就是为了获得硬数据 |
| "未考虑并行 workflow" | **采纳**。本轮 A 的 `routing.json` 落到 `.council/runs/<run_id>/`，天然按 run 隔离；B 的 convergence_evaluator 按 discussion 实例独立判断 |

### 3.2 推迟（留待未来轮次）

| codex 建议 | 未来处理 |
|---|---|
| "先做小 RFC/设计草案和基线测量" | **已做**：本 RFC + TASK-071~073 |
| "字段名改弱（hint 而非 promise）" | 未来 link folding 时按此原则命名 |
| "定义 controller-local sidecar state 的 key 与失效规则" | 未来 link folding RFC 专项设计 |
| "复用现有 hash/diff 实现最小原型" | 未来 link folding 原型阶段 |
| "在同模型链路上测量 reread token 占比、hint 命中率、误命中回退成本" | 等 Phase 1 基线工具落地后可顺便测 |

### 3.3 一致确认（无争议）

| 不变量 | 本 RFC 继续遵守 |
|---|---|
| artifact 继续落盘审计 | ✅ A 的路由决策新增 `routing.json` 也是落盘的 |
| 跨模型 delegated 路径完全不变 | ✅ A 不改 delegated stage 的 provider 启动逻辑 |
| `--required-artifact` 保留作 fallback | ✅ 不改 |
| hint 不是 contract | ✅ A 的 `RoutingDecision.matched_when_expr` 只是审计信息，不改变 caller 行为合约 |
| 遇到任何一次非 local_execution 默认策略保守 | ✅ A 不引入任何"绕过 delegate"的新路径 |

---

## 4. 设计原则：最薄协议 + controller 本地判定

这是本 RFC 的核心架构约束，也是 codex 讨论的主要产出。

### 4.1 什么是"最薄协议"

协议层（`council delegate` / `council discuss` 的公共输入输出）**只加载最少的新语义**。具体到本轮：

| 新增 | 协议层 or controller 本地 |
|---|---|
| `RoleRoute` schema（model + when + fallback） | **协议层**（`.council/config.yaml` schema） |
| 路由命中决策 | **controller 本地**（`role_router.resolve()` 返回 `RoutingDecision`，不改变 `council delegate` 对 caller 的 JSON 输出） |
| `convergence_policy` 字段 | **协议层**（config schema） |
| 收敛判定逻辑 | **controller 本地**（`convergence_evaluator.evaluate()`，不改变 `council discuss` 对 caller 的 JSON 输出） |

**协议层变化**：仅 YAML schema 扩展，**不改 `council delegate` / `council discuss` 的输出 JSON shape**。

### 4.2 什么是"controller 本地判定"

路由决策 / 收敛判断的**执行位置**在 CouncilFlow 控制平面（Python 进程），不跨出到外部 caller（skill runtime / 用户 CLI）。这带来的好处：

1. **演进便宜**：未来想改路由算法 / 收敛语义 → 改 Python 代码就行，不用动协议
2. **安全边界清晰**：`when` 表达式在 Python 进程内用受限 AST 求值器评估，不让任何外部输入触碰 eval
3. **审计落盘不变**：`RoutingDecision` 仍然写 `.council/runs/<id>/routing.json`，审计链完整

### 4.3 原则对本轮设计的约束

- A 动态路由：**不**新增 `council delegate` 的输入/输出字段；仅 config schema 扩展 + 内部 router 模块
- B 语义收敛：**不**新增 `council discuss` 的命令行参数；仅 config schema 扩展 + 内部 evaluator 模块（summary.md 新增 `convergence_trace` 字段只是审计信息）

---

## 5. A 动态角色路由协议层改动面

### 5.1 RoleMapping 字段类型扩展

**当前**：

```yaml
roles:
  implementer: claude   # str
```

**扩展后**：

```yaml
# 简写（保留向后兼容，语义不变）
roles:
  implementer: claude

# 等价的完整形式
roles:
  implementer:
    - model: claude

# 动态路由（新能力）
roles:
  implementer:
    - model: claude
      when: "task.complexity in ['L']"
    - model: claude-haiku
      when: "task.complexity in ['S', 'M']"
      fallback: [claude, gemini]
```

### 5.2 `RoleRoute` Pydantic 模型

```python
class RoleRoute(BaseModel):
    model: str                          # 必填，model 白名单内
    when: str | None = None             # 受限表达式；None 表示总是匹配
    fallback: str | list[str] | None = None  # adapter 失败时的降级链
```

### 5.3 `when` 表达式语法

**允许的 AST 节点**：`Compare` / `BoolOp (And, Or)` / `UnaryOp (Not)` / `Name` / `Constant` / `Attribute (仅 task.<field> 一层)` / `List` / `Tuple`。

**允许的操作符**：`==` / `!=` / `<` / `<=` / `>` / `>=` / `in` / `not in` / `and` / `or` / `not`。

**严格禁止**：`Call` / `Subscript (除 List/Tuple 字面量内)` / `Import` / `Assign` / `Lambda` / `FunctionDef` / `ClassDef` / `__<dunder>__` 访问。

**已知危险表达式必须被拒**：`__import__('os')` / `task.__class__` / `[x for x in range(10)]` / `open('/etc/passwd')` / `lambda: None` / `eval(...)` / `subprocess.run(...)` 等。

### 5.4 fallback 语义

- `fallback` 仅在 **primary adapter 调用失败**（process_error / idle_timeout / total_timeout / adapter_missing）时按序列尝试
- **不**在"质量不满意"等主观场景触发降档
- 每次 fallback 尝试记录到 `.council/runs/<run_id>/routing.json`

### 5.5 错误语义

新增 `RoutingNoMatchError`：

```json
{
  "error": {
    "kind": "routing_no_match",
    "role": "implementer",
    "task_context_summary": {...},
    "tried_routes": [...]
  }
}
```

---

## 6. B 语义 min_rounds 收敛协议层改动面

### 6.1 Discussion schema 扩展

```yaml
discussion:
  default_models: codex
  max_rounds: 5
  min_rounds: 2
  # 本轮新增（向后兼容）
  convergence_policy: strict_count  # 默认，现有行为
  # 或
  # convergence_policy: semantic
  # 或
  # convergence_policy: hybrid
  # min_rounds_by_topic:
  #   architecture: 2
  #   review: 1
  #   clarification: 1
```

### 6.2 三种模式的语义

| 模式 | 收敛条件 |
|---|---|
| `strict_count`（默认） | 现行 PRD §23 逻辑不变。`completed_rounds >= min_rounds` 且外部表态一致 OR 达到 `max_rounds` |
| `semantic` | 连续 N 轮（默认 N=1）`introduced_new_info == false && no_new_disagreements`；`min_rounds` 保留作硬底线 |
| `hybrid` | 从 question 关键词推断 topic（`architecture` / `review` / `clarification` / `other`），按 `min_rounds_by_topic` 取刚性底线；底线内走 `strict_count`，底线后切 `semantic` |

### 6.3 `ConvergenceDecision` 数据模型

```python
class ConvergenceDecision(BaseModel):
    converged: bool
    reason: str                    # "no_new_info" / "max_rounds" / "external_agreed" / ...
    next_action: Literal["continue", "converge", "max_rounds_reached"]
```

### 6.4 `convergence_trace` artifact 字段

Discussion summary artifact 新增（非破坏性）：

```markdown
## Convergence Trace

- Round 1: continue (reason: min_rounds=2 not yet reached)
- Round 2: converge (reason: no_new_info && no_new_disagreements)
```

### 6.5 不变量

- 无外部参与者时的 short-circuit 逻辑完全不变
- `--controller-position` 本地立场入口完全不变
- 外部模型围绕 `initial_position` 评论的协议完全不变（PRD §23 要求）

---

## 7. 向后兼容硬红线

以下所有**必须**满足，否则视为实现不合格：

### 7.1 Config 层

- [ ] 现有 `.council/config.yaml` **任何字段** 0 修改继续加载
- [ ] `roles.implementer: claude` 简写加载后等价于 `roles.implementer: [{model: claude}]`
- [ ] 不带 `convergence_policy` 字段的 config 默认为 `strict_count`
- [ ] 不带 `min_rounds_by_topic` 的 config 行为与当前一致

### 7.2 CLI 层

- [ ] `council delegate` 的输入参数 shape 不变
- [ ] `council delegate` 的输出 JSON shape 不变（`data.status` / `data.role` / `data.model` / `data.via_sidecar` / `data.reason` 等既有字段不变）
- [ ] `council discuss` 的输入参数 shape 不变
- [ ] `council discuss` 的输出 JSON shape 仅新增 `convergence_trace`（通过 summary.md），不改既有字段
- [ ] `--model` CLI override 优先级最高（用户显式指定永远胜出）

### 7.3 行为层

- [ ] 现有 config 下跑 `/project-next` → 所有 delegate 调用返回的 status / model 与 0.1.2 完全一致
- [ ] 现有 config 下跑 `/project-ask discuss` → discussion 轮数与 ended_reason 与 0.1.2 完全一致
- [ ] 整个 67+11 = 78 个 done 任务**零回改**（不动 commit、不改 verification_commands）

### 7.4 文件系统层

- [ ] 现有 `.council/delegations/` 结构不变（路径 / 文件名 / 内容模板）
- [ ] 现有 `.council/discuss/` 结构不变（summary.md 新增 convergence_trace 段属非破坏性）
- [ ] **新增** `.council/runs/<run_id>/routing.json`（路由审计，独立文件）

---

## 8. 版本决策：0.1.3

### 8.1 为什么是 0.1.3 而不是 0.2

- SemVer 次版本号代表**新功能 + 向后兼容**
- 本轮无 API 破坏性变更（见 §7 硬红线）
- 主版本号 0.x 表示产品仍处于早期快速迭代期，次版本号递增是自然节奏

### 8.2 为什么不是 0.1.2.1（patch）

- 本轮有新的 Python 源码（3 个新模块：when_eval / role_router / convergence_evaluator）
- 有 config schema 扩展（虽然向后兼容）
- Patch 版本号（0.1.2.1 / 0.1.2.post1）按惯例留给 bugfix，不用于新能力

### 8.3 0.1.3 Release 必备清单

- [ ] CHANGELOG.md 新增 `[0.1.3]` 段，含 `Added` / `Changed` / `Deferred` 三块
- [ ] `docs/release-notes-0.1.3.md` 详述：新能力、不做的事（link folding 推迟 + 理由）、从 0.1.2 升级 checklist
- [ ] pyproject.toml version bump
- [ ] 完整 pytest + ruff 全绿
- [ ] 端到端 smoke（在 `D:/AIProjects/test/` 下 clean 项目）
- [ ] TASK-085 作最终 milestone gate

---

## 9. 实施任务映射

| 阶段 | 任务 | 产出 |
|---|---|---|
| Phase 1 | TASK-071（本文档） / TASK-072 / TASK-073 | RFC + 基线工具 + 基线报告 |
| A 核心 | TASK-074 / TASK-075 / TASK-076 / TASK-077 / TASK-078 | RoleMapping + when_eval + role_router + delegate 接入 + 模板 |
| B 核心 | TASK-079 / TASK-080 / TASK-081 | discussion schema + convergence_evaluator + orchestrator 接入 |
| 收口 | TASK-082 / TASK-083 / TASK-084 / TASK-085 | 观测 + shared skills + integration.md + 0.1.3 发布 |

每个任务有独立的 `acceptance_mode` / `verification_profile` / `verification_commands` / `review_checklist`。详见 `.claude/state/tasks.json`。

---

## 10. 风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| `when_eval` 漏网某个 AST 节点允许任意代码执行 | 中 | 白名单 + 单元测试覆盖已知危险表达式 + code review 硬 checklist |
| 基线测量精度不够 | 低 | 使用 tiktoken 确定性 tokenizer；报告注明假设与不确定性区间 |
| 向后兼容测试覆盖不全 | 中 | TASK-074/077/081 review_checklist 明确要求"现有 config 下行为等价"测试 |
| 0.1.3 升级后用户混淆新 vs 旧配置 | 低 | `templates/default-config.yaml` 保持简写默认；example 仅为注释；release-notes 提供升级 checklist |
| link folding 被推迟但未来需求被遗忘 | 低 | 已收录 `docs/workflow-optimizations-backlog.md` |

---

## 11. 未来工作

本 RFC 完成后，下一个自然迭代点：

1. **分析 Phase 1 基线数据**（TASK-073 产物）决定是否激活 link folding
2. 如果激活，基于 codex 建议写 link folding 专项 RFC（带 digest/write_seq 语义 + memory_epoch + session scope）
3. 观察 A + B 上线后用户的真实配置分布（通过 `council status --recent N` 数据），决定是否需要补充更多路由 pattern（如按时间段路由）
4. Backlog 其他项（C-G）按收益排序，逐项独立 RFC 评估

---

## 12. 参考

- **Discuss 记录**：`.council/discuss/disc_20260420T065559937703Z/summary.md`
- **Backlog**：`docs/workflow-optimizations-backlog.md`
- **PRD §31**：本轮产品要求
- **架构 §27**：本轮架构变更
- **前置 PRD §18 §22 §23 §26 §27**：配置优先路由 / 阶段机 / discuss 协议 / workflow 硬约束 / reviewer 闭环
