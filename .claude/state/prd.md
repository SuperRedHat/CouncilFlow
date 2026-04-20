# CouncilFlow

## 1. 产品名称
**CouncilFlow**

## 2. 产品定位
`CouncilFlow` 是一个 **CLI-first、本地优先、主控感知** 的多模型协作 sidecar 工具。

它不是浏览器产品，不是本地后端平台，也不是一个新的 AI 聊天前台。
它的目标是：**增强当前主控 AI 的工作能力，让 Codex、Claude Code 或 Gemini CLI 在需要时能够丝滑地调用其他模型参与讨论、分工执行和结果收敛。**

一句话定义：

> `CouncilFlow` 是给 `Codex`、`Claude Code` 和 `Gemini CLI` 使用的多模型协作 sidecar，当前会话里的主控 AI 负责总体流程，`CouncilFlow` 只在需要其他模型参与时被调用。

## 3. 项目背景与问题定义
当前个人 AI 开发工作流存在几个明显问题：

1. 不同模型各有长处，但在真实开发中切换和配合非常繁琐。
2. 多模型讨论通常靠手工复制粘贴，来回转述成本高，容易丢信息。
3. 一旦做成重后端系统，就容易把时间和 token 浪费在后端、接口、状态同步和工具链问题上，而不是实际开发工作上。
4. 当前已经存在一套可同时服务于 `Codex`、`Claude Code` 和 `Gemini CLI` 的 `project-*` 工作流，这套习惯是宝贵资产，不应被推翻。

因此，新的产品方向不是另起一个复杂平台，而是提供一个**薄而稳**的能力层：
- 继续保留 `project-*` 作为主工作流入口
- 让当前主控模型默认原生执行
- 只在确实需要别的模型参与时，通过 `CouncilFlow` 触发跨模型讨论或任务委派

## 4. 产品目标
`CouncilFlow v1` 只做三件事：

1. **多模型讨论**
   - 支持在开发流程中引入一个或多个额外模型参与讨论
   - 支持多轮讨论与总结
   - 支持用户在讨论中途插入自己的意见

2. **多角色分工**
   - 支持为不同角色配置不同模型
   - 当前主控模型能直接执行属于自己的角色任务
   - 只有非主控角色才通过 `CouncilFlow` 委派给其他模型

3. **最小自动化**
   - 支持讨论、规划、实现、测试、评审、修复这些关键开发活动的最小自动串联
   - 不引入数据库、Web UI、常驻后端等复杂基础设施

## 5. 目标用户
核心用户是像你这样的高频使用多模型进行软件开发的个人开发者或小规模团队成员，特点是：

- 主要在 `Codex app`、`Claude Code` 或 `Gemini CLI` 中工作
- 熟悉 git 仓库工作流
- 希望在不同模型之间分工
- 希望多模型讨论更流畅
- 不希望维护沉重的本地后端或前端系统

## 6. 核心概念

### 6.1 主控
**当前会话所在的 AI，就是当前主控。**

规则：
1. 默认由当前主控直接执行当前步骤。
2. 只有在需要别的模型参与时，才调用 `CouncilFlow`。
3. `CouncilFlow` 不替代主控，只增强主控。

### 6.2 角色
系统定义角色，但**不绑定具体模型**。用户可以按项目、阶段或单次流程自由配置角色对应的模型。

V1 的最小完整角色集合为：`planner` / `architect` / `implementer` / `tester` / `reviewer` / `fixer` / `advisor` / `synthesizer`。

### 6.3 讨论
讨论有两种使用方式：**独立讨论**（`project-discuss`）和**嵌入式讨论**（其它 `project-*` skill 的 `discuss` 参数）。

## 7. 主工作流与产品命令层

### 7.1 开发工作流入口
主要入口：`project-init` / `project-design` / `project-plan` / `project-next` / `project-review` / `project-ask` / `project-change` / `project-status` / `project-resume` / `project-discuss`。

### 7.2 产品内部命令层
`council discuss` / `council delegate` / `council synthesize` / `council status`。

## 8. discuss 参数与讨论协议

### 8.1 适用范围
`project-init` / `project-design` / `project-plan` / `project-next` / `project-review` / `project-ask` / `project-change` 均支持 `discuss` 参数。

### 8.2-8.9
- 默认不启动多模型讨论；只有显式 `discuss <model>` 才启动
- 与主控相同模型自动忽略或提醒
- 当主控 + 1 个额外模型时，最多 5 轮，可提前结束
- 流程：主控 framing → 外部模型首轮 → 可选交叉回应 → 用户插话 → 最终综合
- 输出字段：`question` / `participants` / `key_options` / `agreements` / `disagreements` / `recommended_decision` / `open_questions` / `next_step`
- 去重后无额外模型不调用 sidecar

## 9. 角色执行规则
1. 默认由当前主控执行步骤
2. 角色映射到主控则直接原生执行
3. 只有映射到非主控模型时才调用 `CouncilFlow`

## 10. 命名与语言规则
CLI 命令、role 名称、参数名、配置键名、skill 名称统一英文；输出默认中文（`zh-CN`），可切换。

## 11. 本地状态与文件结构
V1 使用本地文件作为权威状态。建议目录：
```text
.council/
├─ config.yaml
├─ state.json
├─ plans/
├─ discuss/
├─ delegations/
├─ runs/
├─ transcripts/
└─ artifacts/
```

## 12. 技术方向
主语言 Python；CLI 交互；YAML/JSON/Markdown 状态存储；优先接官方 CLI，API 作为 advisor 路径。

## 13. 核心功能列表（Must / Should / Could Have）
详见历史版本。

## 14. 非功能性要求
简单、稳定、透明、可恢复、可配置、三主控兼容、低干扰。

## 15. 验收标准
V1 完成时，三主控均可使用；discuss / delegate / project-discuss 工作正常；状态可从 `.council/` 恢复；共享 skills 同步覆盖三端。

## 16. 约束与假设
继续使用 `project-*` 作工作流；`CouncilFlow` 不沿用旧产品方向；主控支持 Codex / Claude Code / Gemini CLI；不追求平台能力，只追求协作主路径稳定。

## 17. 结论
`CouncilFlow` 的最终定位不是"另一个 AI 平台"，而是一个服务于三主控的、主控感知的、多模型协作 sidecar CLI。

## 18-30. 历史变更记录

§18-§30 的历史变更记录内容过长，**详见 git 历史中的先前版本**（commits `ef61ba1` 及之前）。主要内容摘要：
- §18 (2026-04-16): Gemini CLI 从可选讨论角色提升为产品级主控
- §19 (2026-04-16): 全局安装与备份
- §20 (2026-04-17): 共享 discuss 工作流补齐
- §21 (2026-04-17): Claude commands 包装层
- §22 (2026-04-17): 自动角色分发与项目级默认配置
- §23 (2026-04-17): discuss 协议升级（initial_position + min_rounds 引入）
- §24 (2026-04-17): workflow 强制路由硬约束
- §25 (2026-04-17): provider 活跃度监控与流式执行
- §26 (2026-04-17): 全技能自动化阶段机与全链路硬约束
- §27 (2026-04-18): reviewer 闭环与 tester 预检强化
- §28 (2026-04-18): sidecar isolation 与非递归委派
- §29 (2026-04-18): code-review 综合修复批次（34 条修复清单）
- §30 (2026-04-19): 分发与安装（AutoSkills 独立仓库 + bootstrap + LICENSE + readme 重写）

## 31. 变更记录（2026-04-20，工作流 token 效率优化轮）

本次变更基于对 codex 的 5 轮 discuss（记录：`.council/discuss/disc_20260420T065559937703Z/summary.md`）与对工作流 token 成本的深度分析，启动一轮**面向 token 效率**的优化迭代。目标是在**不牺牲交付质量与审计可回放性**的前提下，给用户更丰富的模型搭配能力与更智能的讨论收敛策略。

明确排除：**link folding（同模型链路折叠）** — 尽管 2026-04-19 曾讨论过这个优化，但基于 codex 的反馈（缺少基线数据 / generation 一致性缺失 / 过早协议化），决定本轮不做，留给基线数据产出后再评估。

### 31.1 Phase 1：RFC + 基线测量（不改 Python 源码）

**动机**：在任何代码改动前，先建立"当前 token 成本实际分布"的硬数据。防止基于估算（如"40-60% 节省"）做出错误的优化决策。

新增产品要求：
1. 必须撰写一份 RFC 草案 `docs/rfc-workflow-token-optimization.md`，定义本轮优化目标、非目标、codex discuss 的关键结论、以及"最薄协议 + controller 本地判定"这一指导原则
2. 必须实现独立可运行的基线测量工具 `scripts/measure_ceremony_tokens.py`，分析 `.council/delegations/` 下的 artifact 产出 token 使用报告
3. 必须对当前仓库跑一次真实基线，产出 `docs/ceremony-baseline-<date>.md`，作为 Phase 2 决策依据
4. Phase 1 不引入任何 Python 源码改动；所有交付物都是 docs 或 standalone script

### 31.2 Phase 2（A）：动态角色路由

**动机**：当前 `.council/config.yaml` 的 `roles.<role>: <model>` 是静态单选，无法表达"tester 用便宜模型 / architect 用强模型 / fallback 链 / 按 task 复杂度动态路由"这些真实需求。限制了用户在质量与成本之间做精细权衡的能力。

新增产品要求：
1. **扩展 `RoleMapping` schema**：每个角色的 value 允许是 `str`（简写兼容）或 `list[RoleRoute]`（动态路由）
2. **`RoleRoute` 模型**：`model: str`（目标模型），`when: str | None`（受限表达式），`fallback: str | list[str] | None`（失败降级链）
3. **向后兼容硬红线**：现有所有简写格式的 `.council/config.yaml` 必须 0 修改继续生效；`roles.implementer: claude` 等价于 `[{model: claude}]`
4. **安全红线**：`when` 表达式必须用**受限 AST 求值器**，严禁任意 `eval()`、函数调用、属性链深度超过 1 层、import；仅支持 `==`/`!=`/`in`/`not in`/`and`/`or`/`not`/基本比较 + `task.<field>` 一层访问
5. **路由引擎**：`src/councilflow/controller/role_router.py` 按配置顺序尝试 `when` 条件，首个命中即返回；所有路由决策日志落 `.council/runs/<run_id>/routing.json` 作审计
6. **fallback 语义**：primary adapter 调用失败时按 `fallback_chain` 顺序重试；仅在"adapter 无法启动 / 返回 process_error"等结构化失败时触发，不在"质量不满意"等主观场景降档
7. **配置权在用户**：**禁止**硬编码任何"推荐降档"规则；`templates/default-config.yaml` 保持简写默认（全主控），在注释里以 example 形式展示动态路由用法，但**不**默认启用
8. **新增错误类**：`RoutingNoMatchError`（`kind="routing_no_match"`）带 role + task_context 摘要，可结构化向 caller 上报

### 31.3 Phase 3（B）：语义 min_rounds 收敛

**动机**：当前 `discussion.min_rounds=2` 是硬轮数（PRD §23 引入，防首轮橡皮图章）。但它对"外部首轮就给出明确且论据充分的反馈"和"外部首轮确实无新信息"两类场景都强制再跑一轮，产生无价值 token 消耗。

新增产品要求：
1. **扩展 `Discussion` schema**：新增 `convergence_policy: "strict_count" | "semantic" | "hybrid"`（默认 `strict_count` 保证向后兼容）与 `min_rounds_by_topic: dict[str, int] | None`
2. **`strict_count` 模式**：保留现行所有逻辑不变（默认模式，任何现有 config 行为不变）
3. **`semantic` 模式**：使用已有的 `DiscussionTurn.introduced_new_info` 字段（不额外调 LLM），连续 N 轮（默认 N=1）`introduced_new_info=false && no_new_disagreements` 才算收敛；`min_rounds` 保留作硬底线
4. **`hybrid` 模式**：从 question 关键词推断 topic（`architecture` / `review` / `clarification` / `other`），查 `min_rounds_by_topic` 取刚性底线（如 architecture=2，clarification=1），底线内走 strict_count，底线后切 semantic
5. **新增 `ConvergenceDecision` 类**：`converged: bool`、`reason: str`、`next_action`；orchestrator 每轮结束调 evaluator 而不是内联判断
6. **Discussion summary artifact 新增字段**：`convergence_trace: list[{round, reason, decision}]`，提供完整的收敛决策回放
7. **保留现行不变**：无外部参与者时的 short-circuit、`--controller-position` 本地立场入口、外部模型围绕 `initial_position` 评论的协议

### 31.4 观测 + 文档 + 发布

新增产品要求：
1. **观测增强**：`council status --recent N` 输出新增"路由命中分布"（每个 role 命中了哪些 model 几次）+"讨论收敛分布"（平均轮数 + 按收敛原因分布）
2. **共享 skills 文案轻量更新**：在 AutoSkills 的 11 个 `project-*/SKILL.md` 中添加一小段说明"路由结果以 `council delegate` 返回为准，skill 不干预"，但核心业务逻辑不变
3. **`docs/integration.md` 新增章节**："Dynamic Role Routing"（schema + when 语法 + fallback 语义）+"Discussion Convergence Policy"（三种模式行为对比 + convergence_trace artifact 字段）
4. **版本 bump 到 0.1.3**；CHANGELOG 和 release-notes 明确列出：schema 扩展 + 向后兼容保证 + 明确不做的事（link folding 推迟）及理由

### 31.5 阶段 gate

仅 1 个最终 milestone gate（TASK-085）：在 `D:/AIProjects/test/` 下建 clean 测试项目，实际跑 `/project-ask discuss` + `/project-next` 端到端验证 A + B。pytest + ruff 全绿，完整 smoke-report 落盘。

### 31.6 明确不涉及（backlog 留档）

本轮**不做**，放进 `docs/workflow-optimizations-backlog.md` 等未来评估：
- Link folding（等 Phase 1 基线数据 + 小 RFC 再决定）
- Sidecar 分层（按角色类型差异化 isolation）
- Artifact 结构化 schema（取代自由 markdown）
- Provider session 复用（长 discussion 场景才有价值）
- Turn merging（同 discussion 内相邻同模型回合合并）
- Delta handoff（增量 artifact 引用）

### 31.7 不变量总结

- 现有 `.council/config.yaml` 0 修改可用
- `discussion.convergence_policy` 默认 `strict_count`，现有 discussion 行为不变
- 67 + 11 = 78 个已完成任务零回改
- `when` 表达式安全红线（受限 AST 白名单）
- 配置权完全在用户手里：CouncilFlow 不预设任何"推荐降档"
- 审计链完整性：所有路由决策 + 收敛决策都有结构化落盘

本节覆盖并 supersede 文中"RoleMapping 字段类型只能是 str"与"min_rounds 只能按轮数硬计数"两条旧隐含假设。新语义为：**RoleMapping 支持简写与表达式路由两种形态；discussion 可按配置切换 strict_count/semantic/hybrid 三种收敛策略；二者均完全向后兼容**。

**注**：§3-§30 的完整历史变更记录内容过长未在本版本中逐字保留。如需查阅原文请回溯 git 历史（commits `ef61ba1` 及之前的 `.claude/state/prd.md`）。
