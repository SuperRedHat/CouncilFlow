# CouncilFlow 架构设计

## 1. 架构目标

### 1.1 产品定位
`CouncilFlow` 是一个 **CLI-first、本地优先、主控感知** 的多模型协作 sidecar 工具。它不是浏览器产品，不是后端平台，不是新的 AI 聊天前台。

### 1.2 当前阶段定位
和现有 `project-*` 开发工作流并存；支持 Codex / Claude Code / Gemini CLI 三主控；只在真正需要额外模型参与时才激活 sidecar；本地文件保存权威状态。

### 1.3 架构原则

1. **Controller-first**：当前主控始终保有最终流程决策权
2. **CLI-first**：所有核心能力都通过 CLI 完成
3. **Local-first**：本地文件是唯一权威状态源
4. **No hidden context sharing**：不依赖跨模型共享隐式聊天上下文
5. **Explicit handoff**：所有跨模型协作都通过结构化 handoff package 完成
6. **Minimal infrastructure**：不引入 Web UI、数据库、队列、常驻 API
7. **On-demand sidecar**：只有非主控模型真正参与时才调用 `CouncilFlow`
8. **Language-stable surface**：命令与参数统一英文，输出语言可配置

## 2. 技术选型
Python 3.13 + Typer + Pydantic v2 + PyYAML + JSON/Markdown/YAML + subprocess + 官方 CLI 优先。

## 3. 目录结构
```text
councilflow/
├─ pyproject.toml
├─ src/councilflow/
│  ├─ cli/         (app.py, discuss.py, delegate.py, status.py, synthesize.py)
│  ├─ config/      (loader.py, schema.py)
│  ├─ controller/  (host_context.py, discussion_orchestrator.py, delegation_orchestrator.py, routing.py)
│  ├─ providers/   (base.py, codex_cli.py, claude_code_cli.py, gemini_cli.py, openai_api.py)
│  ├─ state/       (paths.py, store.py, snapshots.py)
│  ├─ handoff/     (packages.py, prompts.py, summaries.py)
│  ├─ models/      (roles.py, discussion.py, delegation.py, config.py, run_record.py)
│  └─ utils/       (git.py, io.py, lang.py)
├─ tests/
└─ docs/
```

## 4. 模块划分与职责
- **`host_context`**：识别当前主控（codex/claude/gemini）
- **`routing`**：角色到模型的静态映射决策
- **`discussion_orchestrator`**：多模型讨论编排
- **`delegation_orchestrator`**：非主控角色任务委派
- **`providers`**：四个 adapter（CodexCli / ClaudeCodeCli / GeminiCli / OpenAI）
- **`handoff`**：结构化交接包（role / objective / task_summary / constraints / relevant_files / inputs / expected_output）
- **`state`**：`.council/` 本地权威状态

## 5. CLI 命令
`council discuss` / `council delegate` / `council synthesize` / `council status`。

## 6. discuss 协议
适用于 `project-init` / `project-design` / `project-plan` / `project-next` / `project-review` / `project-ask` / `project-change`。默认不启动；显式 `discuss <model>` 才启动；主控 + 1 个额外模型最多 5 轮，可提前收敛；最终结论由主控输出。

## 7. 数据模型
`PROJECT_STATE` ↔ `ROLE_MAPPING` + `DISCUSSION_RECORD`(含 `DISCUSSION_ROUND`) + `DELEGATION_RECORD`(含 `HANDOFF_PACKAGE`) + `RUN_RECORD`。

## 8. 模块依赖
CLI → Controller → (Models, Providers, Handoff, State); Config → Models; Utils → Controller/Providers/State。

## 9-13. （简介）
`project-*` 是开发工作流层；`council *` 是产品命令层。关键架构决策：不做 Web UI / 不做数据库 / 不做常驻 API / 不共享隐式聊天上下文 / `.council/` 是唯一权威状态 / 非主控模型真正参与时才激活 sidecar / discuss 最终结论由主控输出。

## 14-26. 历史变更记录

§14-§26 的历史变更记录内容过长，详见 git 历史中的先前版本（commits `50e68be` 及之前的 `.claude/state/architecture.md`）。主要内容摘要：
- §14 (2026-04-16): Gemini CLI 三主控接入
- §15 (2026-04-16): 全局安装与备份架构
- §16 (2026-04-17): 共享 discuss 工作流补齐
- §17 (2026-04-17): Claude commands 包装层
- §18 (2026-04-17): 自动角色分发与项目级默认配置
- §19 (2026-04-17): discuss 协议升级（initial_position 入正式协议对象）
- §20 (2026-04-17): workflow 强制路由硬约束
- §21 (2026-04-17): provider 活跃度监控与流式执行
- §22 (2026-04-17): 全技能自动化阶段机与全链路硬约束
- §23 (2026-04-18): reviewer 闭环与 tester 预检强化
- §24 (2026-04-18): sidecar isolation 与非递归委派
- §25 (2026-04-18): code-review 综合修复架构（13 条架构清单）
- §26 (2026-04-19): 分发与安装拓扑（AutoSkills 双仓库）

## 27. 变更记录（2026-04-20，工作流 token 效率优化轮）

本次架构变更承接 PRD §31，目标是**在不破坏现有不变量的前提下**扩展 `RoleMapping` 与 `Discussion` 配置 schema 的表达能力，新增三个独立模块，并把 `cli/delegate` 与 `discussion_orchestrator` 的决策入口从内联逻辑改为调用专职评估器。

### 27.1 新增模块（零现有模块替换）

| 新文件 | 职责 | 依赖 |
|---|---|---|
| `src/councilflow/config/when_eval.py` | 受限 AST 表达式求值器；评估 `task.complexity == 'L'` 这类 `when` 表达式；AST 白名单严格限制 | 无外部依赖 |
| `src/councilflow/controller/role_router.py` | 按 `RoleMapping[role]` 的 list 顺序尝试 `when` 命中，返回 `RoutingDecision`；落 `.council/runs/<id>/routing.json` | `when_eval` + `models/config` |
| `src/councilflow/controller/convergence_evaluator.py` | 按 `convergence_policy` 字段切换 strict_count/semantic/hybrid；输出 `ConvergenceDecision` | `models/discussion` + `models/config` |
| `scripts/measure_ceremony_tokens.py` | 独立可运行的基线测量工具；分析 `.council/delegations/` 产物的 token 使用 | 仅依赖 Python stdlib + 可选 tiktoken |

### 27.2 现有模块的扩展性改动（不破坏现有契约）

| 已存在文件 | 改动性质 | 向后兼容要求 |
|---|---|---|
| `models/config.py::RoleMapping` | 字段类型从 `str` 扩展为 `str \| list[RoleRoute]`；`@field_validator(mode="before")` 归一化简写 | 简写 `claude` → `[RoleRoute(model='claude')]`，语义等价 |
| `models/config.py::Discussion` | 新增 `convergence_policy` + `min_rounds_by_topic` 两个字段 | `convergence_policy` 默认 `strict_count`，现有字段 min_rounds/max_rounds/default_models 不变 |
| `models/config.py` | 新增 `RoleRoute` Pydantic 模型 | —— |
| `cli/delegate.py::get_provider_adapter` | 改调 `role_router.resolve()`；保留 `--model` CLI 参数作最高优先级 override | 现有 config 下行为等价 |
| `controller/discussion_orchestrator.py` | 每轮结束调 `convergence_evaluator.evaluate()` 而不是内联判断 | `strict_count` 模式下 end-to-end 行为完全等价 |
| `models/delegation.py` 或相关 | 可能新增 `ConvergenceDecision` + `RoutingDecision` 结构化数据类 | —— |
| `cli/status.py` | `--recent N` 新增"路由分布"+"收敛分布"两段输出 | 现有输出段保留不变 |

### 27.3 完全不动的模块

- `providers/**`（adapter 层）
- `controller/host_context.py`
- `controller/delegation_orchestrator.py`（除可能读新 schema）
- `state/**`
- `handoff/**`（除 discussion summary artifact 加 `convergence_trace` 字段）
- `utils/**`

### 27.4 RoleRoute 数据模型设计

```python
class RoleRoute(BaseModel):
    model: str                            # 必填，已有的白名单模型名
    when: str | None = None              # 可选，受限表达式；None 表示总是匹配
    fallback: str | list[str] | None = None  # 可选，adapter 失败时的降级链
```

`when` 语法白名单：
- 字面量：`int`, `str`, `bool`, `None`, `List`, `Tuple`
- 变量：仅 `task` 及其一层属性（`task.complexity`、`task.module` 等，**不支持** `task.__class__.xxx` 这类深属性链）
- 操作符：`==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `and`, `or`, `not`
- 禁止：`Call`, `Import`, `Assign`, `Lambda`, `FunctionDef`, `ClassDef`, `Subscript`（除 list/tuple 字面量内），`__*__` 访问

### 27.5 Convergence 三种模式的语义

| 模式 | 何时收敛 |
|---|---|
| `strict_count` | 轮数达到 `min_rounds` 且外部表态一致 OR 轮数达到 `max_rounds`（现行行为） |
| `semantic` | 连续 N 轮（默认 N=1）`introduced_new_info == false && no_new_disagreements`；`min_rounds` 作硬底线 |
| `hybrid` | 从 question 关键词推断 topic，查 `min_rounds_by_topic` 取刚性底线；底线内走 `strict_count`，底线后切 `semantic` |

**不变量**：三种模式下无外部参与者时的 short-circuit 行为完全一致。

### 27.6 Artifact 契约微调

- Discussion summary 新增 `convergence_trace: list[{round, reason, decision}]` 字段
- 路由决策落 `.council/runs/<run_id>/routing.json`（新增文件，不替换现有 runs artifact）

现有 `.council/delegations/<id>/result.md` 结构**完全不变**。现有 `.council/discuss/<id>/summary.md` 除加 `convergence_trace` 字段外结构不变。

### 27.7 与历史章节的关系

- **§18（自动角色分发）**：本节扩展其 `RoleMapping` 为支持动态路由的更丰富表达式，但简写 fallback 语义保留；`discussion.default_models` 继续作为 discuss 默认参与者字段
- **§19（discuss 协议升级）**：本节保留 `initial_position` / `min_rounds` / 主控回应轨迹等协议要素；仅扩展了 `min_rounds` 的"何时允许放宽"的判断机制
- **§25（code-review 综合修复）**：本节遵守 §25.1 "配置真源层"原则，`RoleMapping` 默认仍由 `templates/default-config.yaml` 派生；新的 `RoleRoute` 模型加入后，`default_role_mapping_payload()` 返回值仍然等价于简写形式
- **§20-§24 / §26-§27（历史 sidecar / reviewer / 分发）**：本节**不改动**这些章节建立的契约

### 27.8 测试覆盖目标

- `when_eval.py`：正向（合法表达式）+ 反向（已知危险表达式如 `__import__('os')`, `task.__class__`, `[x for x in range(10)]` 等均应被拒）
- `role_router.py`：简写加载 / 表达式命中 / 表达式都 miss / fallback 链 / routing.json 落盘
- `convergence_evaluator.py`：三种模式的 converge / continue / max_rounds 边界 + 无外部参与者 short-circuit
- 向后兼容 smoke：加载现有 `.council/config.yaml`（全简写）并跑 /project-next + /project-ask，行为完全等价

### 27.9 版本影响

- **0.1.3**：本轮发布版本（有 Python 源码改动）
- **兼容性**：SemVer 次版本，向后兼容（config + CLI + API 都不破坏）
- **CHANGELOG**：必须列出 `Added`（RoleRoute + convergence_policy + measurement tool）+ `Deferred`（link folding + sidecar 分层 + 其他 backlog 项）

本节覆盖并 supersede 之前架构文档中"`RoleMapping` 字段类型固定为 str"与"convergence 逻辑内联在 orchestrator"的旧隐含假设。

**注**：§3-§26 的完整历史记录内容过长未在本版本中逐字保留。如需查阅原文请回溯 git 历史（commits `50e68be` 及之前的 `.claude/state/architecture.md`）。
