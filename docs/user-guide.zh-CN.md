# CouncilFlow 中文使用文档

## 1. 这是什么

`CouncilFlow` 是一个 **CLI-first、本地优先、主控感知** 的多模型协作 sidecar。

它的目标不是替代你当前正在使用的 AI，而是给当前主控模型增加两类能力：

1. 让主控在需要时拉其他模型一起讨论。
2. 让主控把适合的角色任务委派给别的模型执行。

当前支持的三种主控环境是：

- `Codex`
- `Claude Code`
- `Gemini CLI`

一句话理解：

> 你继续在当前主控里工作，`CouncilFlow` 只在需要跨模型讨论或跨模型委派时介入。

---

## 2. 核心概念

### 2.1 主控

主控就是你当前所在的 AI 环境。

例如：

- 你在 `Codex` 里执行命令，那么当前主控是 `codex`
- 你在 `Claude Code` 里执行命令，那么当前主控是 `claude`
- 你在 `Gemini CLI` 里执行命令，那么当前主控是 `gemini`

主控负责：

- 理解当前任务
- 决定是否需要讨论
- 决定是否需要委派
- 最终综合结果

### 2.2 角色

`CouncilFlow` 不是直接把任务绑死到某一个模型上，而是先定义角色，再由你把角色映射到模型。

内置角色有 8 个：

- `planner`
- `architect`
- `implementer`
- `tester`
- `reviewer`
- `fixer`
- `advisor`
- `synthesizer`

### 2.3 sidecar 何时触发

只有两种情况会触发 sidecar：

1. 你显式发起 `discuss`，而且去重后还有非主控模型参与。
2. 某个角色映射到的模型不是当前主控，于是发生 `delegate`。

如果目标模型就是当前主控，系统会直接本地执行，不绕远路。

---

## 3. 安装与环境准备

### 3.1 Python 环境

项目要求：

- `Python 3.13+`

在仓库根目录安装本体：

```powershell
cd D:\project\CouncilFlow
python -m pip install -e .
```

如果你只是本地开发，也可以不安装脚本入口，而是直接用模块方式运行：

```powershell
python -m councilflow.cli.app --help
```

如果你没有做可编辑安装，记得让 Python 能找到 `src/`：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m councilflow.cli.app --help
```

### 3.2 模型 CLI

要想真正跨模型讨论或委派，你的系统里需要安装并可直接调用对应 CLI：

- `codex`
- `claude`
- `gemini`

你可以分别检查：

```powershell
codex --help
claude --help
gemini --help
```

### 3.3 当前内置 provider

当前仓库里已经接好的 provider 是：

- `codex`
- `claude`
- `gemini`

也就是说，`discuss` 和 `delegate` 的真实跨模型主路径目前以这三类 CLI 为主。

虽然配置层允许你写别的字符串，例如 `gpt`，但如果没有对应 adapter，就不能直接拿来做委派或讨论。

---

## 4. 项目级配置

### 4.1 配置文件位置

每个项目都通过项目根目录下的 `.council/config.yaml` 配置行为。

示例路径：

[`D:\project\CouncilFlow\.council\config.yaml`](D:/project/CouncilFlow/.council/config.yaml)

如果项目里还没有这个文件，`CouncilFlow` 会在首次调用时自动创建一份项目本地默认模板。  
这意味着每个项目都可以维护独立的角色分工和讨论策略，而不是共享一份全局运行时配置。

### 4.2 最小配置示例

```yaml
config_version: 1
output_language: zh-CN
roles:
  planner: codex
  architect: codex
  implementer: claude
  tester: gemini
  reviewer: codex
  fixer: claude
  advisor: gemini
  synthesizer: codex
discussion:
  default_models:
    - gemini
  min_rounds: 2
  max_rounds: 3
providers:
  default:
    total_timeout_seconds: 900
    idle_timeout_seconds: null
  claude:
    idle_timeout_seconds: 180
```

### 4.3 如何指定不同角色使用哪一种模型

这就是你最常用的配置入口。

例如上面的配置表示：

- 规划和架构交给 `codex`
- 实现交给 `claude`
- 测试交给 `gemini`
- 评审仍然留在 `codex`

系统在运行时会先看当前主控是谁，再看该角色映射到谁：

- 如果角色目标模型 = 当前主控，直接本地执行
- 如果角色目标模型 != 当前主控，自动进入 `delegate`

例如你当前在 `Codex` 里：

- `planner: codex` -> 本地执行
- `reviewer: codex` -> 本地执行
- `implementer: claude` -> 委派给 Claude
- `tester: gemini` -> 委派给 Gemini

这里有一个关键语义：

- 有 `CouncilFlow` 时，`.council/config.yaml` 是自动分发真相源
- 主控不会因为“自己也能做”就默认抢着本地执行
- 只有当目标角色最终解析到当前主控，或 `council` 根本不可用时，才会本地执行

也就是说，这个配置文件不是“建议”，而是项目级自动路由规则。

### 4.4 如何设置默认 discuss 模型

`discussion.default_models` 用来决定：当你调用 `council discuss` 或 `project-discuss` 时，如果**没有显式指定模型**，系统默认邀请谁参与讨论。

例如：

```yaml
discussion:
  default_models:
    - gemini
    - claude
  max_rounds: 4
```

表示：

- 不写 `--models` 时，默认先邀请 `gemini` 和 `claude`
- 不写 `--min-rounds` 配置时，新项目默认至少完成一轮“主控回应外部意见”的闭环
- 不写 `--max-rounds` 时，默认最多讨论 4 轮

如果其中某个模型正好和当前主控重复，`CouncilFlow` 仍会正常做归一化、去重和短路提醒。

### 4.5 模型别名

当前系统会对常见模型名做归一化。

例如下面这些会被识别为相同控制器或同一路由：

- `claude`
- `claude-code`
- `claude code`

以及：

- `gemini`
- `gemini-cli`
- `gemini-1.5-pro`
- `gemini-1.5-flash`
- `gemini-2.0-flash`

这意味着你可以在配置里写更具体的 Gemini 版本名，但路由层仍会把它视为 Gemini 体系。

### 4.6 controller_override

如果当前环境没有被自动识别出来，可以在配置里显式写：

```yaml
controller_override: codex
```

可选值：

- `codex`
- `claude`
- `gemini`

这个字段主要用于：

- 特殊 shell 环境
- 测试环境
- 无法可靠读到主控环境变量时的兜底

### 4.7 provider 运行窗口

`providers` 配置块用来控制 sidecar 子进程的执行窗口，特别适合长时间推理但仍持续输出事件的模型。

常用字段有两个：

- `total_timeout_seconds`
  - 总墙钟时间上限
  - 防止进程无限挂住
- `idle_timeout_seconds`
  - 失活超时
  - 只有在 provider 长时间没有新的显式输出、日志或事件时才触发

当前默认策略是：

- `providers.default.total_timeout_seconds = 900`
- `providers.default.idle_timeout_seconds = null`
- `providers.claude.idle_timeout_seconds = 180`

含义是：

- 所有 provider 默认最长可跑 15 分钟
- 对仍走一次性 blocking 路径的 provider，不启用全局 idle timeout，避免误杀
- 对已切到流式事件监控的 `Claude`，如果连续 180 秒没有新事件输出，才判定失活

如果你的项目里 `Claude` 经常需要更长的持续思考窗口，可以这样调：

```yaml
providers:
  default:
    total_timeout_seconds: 1200
    idle_timeout_seconds: null
  claude:
    idle_timeout_seconds: 300
```

---

## 5. 当前默认角色映射与默认讨论策略

如果你没有写 `.council/config.yaml`，系统会使用默认映射：

- `planner -> codex`
- `architect -> codex`
- `implementer -> claude`
- `tester -> claude`
- `reviewer -> codex`
- `fixer -> codex`
- `advisor -> gpt`
- `synthesizer -> codex`

默认讨论策略是：

- `discussion.default_models = []`
- `discussion.min_rounds = 2`（新生成项目模板）
- `discussion.max_rounds = 5`

这表示如果你不配置默认讨论模型，又没有显式传 `--models`，系统会返回结构化提示，告诉你当前没有额外讨论参与者可用。

如果你已经有自己的偏好，建议总是明确写入项目配置，而不是依赖默认值。

---

## 6. CLI 命令总览

`CouncilFlow` 的底层命令分为 4 个：

- `council discuss`
- `council delegate`
- `council status`
- `council synthesize`

如果已经通过 `pip install -e .` 安装过脚本入口，可以直接这样用：

```powershell
council status
```

如果你在本地源码开发环境中，也可以这样用：

```powershell
python -m councilflow.cli.app status
```

下面的示例默认都使用模块方式。

---

## 7. `council status`

### 7.1 用途

查看当前项目的：

- 当前主控
- 输出语言
- 最近一次 discussion
- 最近一次 delegation
- 当前 `.council/state.json` 摘要

### 7.2 示例

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
$env:CODEX_SHELL = '1'
python -m councilflow.cli.app status --project-root .
```

### 7.3 典型返回

返回结构统一是：

```json
{
  "data": { ... },
  "error": null,
  "meta": { ... }
}
```

其中常见字段包括：

- `data.current_controller`
- `data.output_language`
- `data.recent_discussion`
- `data.recent_delegation`

---

## 8. `council discuss`

### 8.1 用途

让当前主控和一个或多个额外模型进行结构化讨论。

### 8.2 示例

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
$env:CODEX_SHELL = '1'
python -m councilflow.cli.app discuss `
  "Should we use a tiny standard-library backend or a framework?" `
  --models claude,gemini `
  --max-rounds 2 `
  --project-root .
```

如果你已经在项目配置里写了默认讨论模型，也可以不传 `--models`：

```powershell
python -m councilflow.cli.app discuss `
  "Should we split this feature into phases first?" `
  --project-root .
```

### 8.3 讨论规则

- 主控永远会参与
- `--models` 里只写额外模型
- 不写 `--models` 时，会读取项目级 `discussion.default_models`
- 在独立 CLI fallback 模式下，`CouncilFlow` 可以自行生成主控的 `initial_position`
- 外部模型会围绕这版主控立场发表评论，而不是各自从零起草方案
- 在交互式主控里，推荐由当前主控先本地写一句简短 `initial_position`，再通过 `--controller-position` 传给 `council discuss`；summary 产出后由宿主 workflow 继续综合，避免同模型自嵌套
- 只有达到 `discussion.min_rounds` 之后，系统才允许提前收敛
- 不写 `--max-rounds` 时，会读取项目级 `discussion.max_rounds`
- 去重后如果没有非主控模型，sidecar 不会启动
- “主控 + 1 个额外模型”最多 5 轮
- 满足收敛条件时可提前结束

### 8.4 同模型 discuss 的行为

如果你当前主控是 `codex`，然后你写：

```powershell
python -m councilflow.cli.app discuss "..." --models codex --project-root .
```

系统不会真的发起跨模型讨论，而是返回提醒。

如果你写：

```powershell
python -m councilflow.cli.app discuss "..." --models codex,claude --project-root .
```

系统会自动忽略重复的 `codex`，只让 `claude` 参与。

### 8.5 讨论产物

讨论结果会落盘到：

- `.council/discuss/<discussion_id>/summary.md`

返回 JSON 里也会给出：

- `discussion_id`
- `participants`
- `initial_position`
- `current_controller_position`
- `min_rounds`
- `summary_path`
- `recommended_decision`
- `next_step`
- `controller_mode`

---

## 9. `council delegate`

### 9.1 用途

把某个角色任务交给非主控模型执行。

### 9.2 基于角色映射自动选择模型

例如你当前配置中：

- `implementer: claude`
- `tester: gemini`

如果你在 `Codex` 主控下执行：

```powershell
python -m councilflow.cli.app delegate `
  --role implementer `
  --objective "Implement the first version of the feature." `
  --task-summary "Build the smallest working slice." `
  --project-root .
```

系统会自动把这个任务交给 `claude`，因为你没显式传 `--model`，它会从 `roles` 里查。

### 9.3 显式覆盖目标模型

如果你希望临时覆盖角色映射，可以加 `--model`：

```powershell
python -m councilflow.cli.app delegate `
  --role implementer `
  --model gemini `
  --objective "Prototype the page quickly." `
  --task-summary "Only sketch the first working version." `
  --project-root .
```

### 9.4 本地短路

如果目标模型和当前主控相同，系统不会真的启动 sidecar。

例如当前主控是 `codex`，而 `reviewer: codex`，那么：

```powershell
python -m councilflow.cli.app delegate `
  --role reviewer `
  --objective "Review this change." `
  --task-summary "Look for risks and missing tests." `
  --project-root .
```

返回会是：

- `status = local_execution`
- `via_sidecar = false`
- 这代表当前 workflow 已经拿到显式本地执行许可，此时主控才允许继续自己做这项角色工作

### 9.5 委派产物

每次成功委派至少会产出：

- `.council/delegations/<delegation_id>/handoff.yaml`
- `.council/delegations/<delegation_id>/result.md`
- `.council/delegations/<delegation_id>/record.json`

这些文件分别用于：

- `handoff.yaml`：结构化交接包
- `result.md`：目标模型返回的结果
- `record.json`：此次委派的机器可读记录

当 sidecar 路径真实发生时，CLI 返回里会明确给出：

- `status = delegated`
- `delegation_status = completed`
- `via_sidecar = true`

这几个字段的含义是：

- `delegated`：说明 workflow 已完成真实委派，后续应读取 `.council/delegations/...` 产物继续
- `local_execution`：说明该角色最终解析到当前主控，workflow 可以继续本地执行
- `error`：说明委派失败，workflow 应停止并报告失败，不能因为主控“也会做”就偷偷跳过 sidecar

当返回 `error` 时，现在还会附带 `error_kind`，常见值包括：

- `idle_timeout`
- `total_timeout`
- `process_exit`
- `os_error`

这样你可以更快区分：

- 是真的跑太久了
- 还是 provider 很久没有任何新输出
- 还是 CLI 自己报错退出

### 9.6 常见参数

- `--role`
- `--model`
- `--objective`
- `--task-summary`
- `--constraint`
- `--relevant-file`
- `--expected-output`
- `--project-root`

---

## 10. `council synthesize`

### 10.1 用途

把已有的 discussion 或 delegation 产物再拼成一个统一视图，方便主控继续处理。

### 10.2 示例

```powershell
python -m councilflow.cli.app synthesize `
  --artifact .council/discuss/disc_xxx/summary.md `
  --artifact .council/delegations/del_xxx/result.md `
  --project-root .
```

### 10.3 适合的场景

- 你做了一轮 discuss，又做了一轮 delegate
- 想把多个结果拼到一起交给主控综合
- 想把中间产物变得更容易读

---

## 11. `.council/` 目录结构

典型结构如下：

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

各目录用途：

- `config.yaml`：角色映射、语言、controller override
- `state.json`：当前阶段、最近一次运行状态
- `discuss/`：讨论记录和总结
- `delegations/`：委派交接包与结果
- `runs/`：统一运行记录
- `artifacts/`：后续导出产物

这套目录是整个工具的本地权威状态源。

---

## 12. 与 `project-*` 工作流的关系

要区分两层：

### 12.1 开发工作流层

这是你在开发项目时直接对 AI 说的技能：

- `project-init`
- `project-design`
- `project-plan`
- `project-next`
- `project-review`
- `project-change`
- `project-ask`
- `project-status`
- `project-resume`

### 12.2 产品命令层

这是 `CouncilFlow` 自己提供的底层命令：

- `council discuss`
- `council delegate`
- `council status`
- `council synthesize`

关系是：

- `project-*` 是主工作流入口
- `council *` 是被主控调用的底层能力

例如：

- `project-plan discuss claude`
- `project-next discuss gemini`

本质上都是先触发一次 `council discuss`，拿到 `.council` 里的显式产物，再由主控继续主流程。

在新的自动路由语义下：

- 如果 `project-discuss` 或嵌入式 `discuss` 没有显式写模型，默认会读取项目级 `discussion.default_models`
- discuss 仍以 `initial_position` 为核心，但在交互式主控里推荐由主控先本地生成这一步，再通过 `--controller-position` 交给 `CouncilFlow` 分发给外部模型
- 如果 `project-next`、`project-review`、`project-change` 需要执行型角色，默认会优先尝试 `council delegate --role ...`
- 只要 `CouncilFlow` 可用，主工作流必须先拿到显式路由结果；没有 `status = local_execution` 或真实委派产物前，不应直接开始本地编码、评审或测试
- 只有在 `council` 缺失或不可调用时，主工作流才退回纯本地执行

---

## 13. 三主控使用建议

### 13.1 Codex 做主控

适合：

- 结构化工作流推进
- 快速实现和迭代
- 复杂代码库内的连续执行

建议映射：

- `planner = codex`
- `architect = codex`
- `reviewer = codex`
- `implementer = claude`
- `tester = gemini`

### 13.2 Claude Code 做主控

适合：

- 深入解释
- 代码组织和重构推理
- 比较强调文字化分析的场景

如果你以 Claude 做主控，建议把：

- `implementer`
- `reviewer`
- `architect`

中至少一部分映回 Claude，本地执行会更顺手。

### 13.3 Gemini CLI 做主控

适合：

- 快速补充观点
- 做测试/建议类的补位
- 三主控之间的轻量并行

如果用 Gemini 做主控，建议明确配置 `controller_override` 或确保其环境变量能被识别。

---

## 14. 一条推荐的日常使用流程

下面是一条很实用的最小流程。

### 第一步：看状态

```powershell
python -m councilflow.cli.app status --project-root .
```

### 第二步：必要时先讨论

```powershell
python -m councilflow.cli.app discuss `
  "Should we split the feature into backend and frontend first?" `
  --project-root .
```

如果你已经在项目配置里写了默认讨论模型，这一步就不必每次手动指定。

### 第三步：按角色委派

```powershell
python -m councilflow.cli.app delegate `
  --role implementer `
  --objective "Build the first working slice." `
  --task-summary "Implement the backend and the thinnest possible UI." `
  --project-root .
```

### 第四步：读取 `.council` 产物继续推进

你可以直接看：

- `.council/discuss/.../summary.md`
- `.council/delegations/.../handoff.yaml`
- `.council/delegations/.../result.md`

然后由当前主控决定下一步：

- 自己实现
- 再委派一轮
- 做 review
- 做 synthesize

---

## 15. 真实烟测示例

仓库中已经包含一个最小真实示例：

[`examples/go-web-smoke`](D:/project/CouncilFlow/examples/go-web-smoke)

它的作用不是做完整围棋规则，而是验证：

- `Codex` 主控下的真实 `discuss`
- `implementer -> claude`
- `tester -> gemini`
- 示例前后端可以跑起来

启动方式：

```powershell
python examples/go-web-smoke/backend/server.py
```

访问：

[http://127.0.0.1:8000](http://127.0.0.1:8000)

它支持：

- 棋盘展示
- 黑白轮流落子
- 已占位置校验
- 重置棋盘

不支持：

- 提子
- 打劫
- 自杀禁手
- 终局计分

这是故意的，因为这个示例服务于工作流烟测，不服务于完整游戏实现。

---

## 16. 常见问题

### 16.1 为什么我明明配了角色，但没有触发 sidecar？

最常见原因有两个：

1. 该角色映射到的正好是当前主控。
2. `discuss` 去重后没有剩下非主控模型。

这都属于预期行为。

### 16.2 为什么我设置了 `implementer: claude`，却还是本地执行？

先看当前主控是不是 `claude`。

如果当前主控本来就是 `claude`，那么 `implementer: claude` 就会本地短路，而不是再委派一次。

### 16.3 为什么 `discuss codex` 没真正发起讨论？

如果当前主控就是 `codex`，那你指定 `codex` 只是在要求主控和自己讨论。

系统会提示你：

- 当前指定模型与主控相同
- 需要指定不同模型才能开始跨模型讨论

### 16.4 为什么配置里写了 `gpt`，但 delegate 可能跑不起来？

因为“配置允许写入”不等于“当前已经有对应 provider adapter”。

当前真实接通的 CLI provider 主要是：

- `codex`
- `claude`
- `gemini`

如果你想让 `gpt` 也成为真实 delegate/discuss 目标，需要后续补 adapter。

### 16.5 Windows 控制台下为什么有时会看到转义字符？

在部分非 UTF-8 控制台环境中，某些模型返回的 emoji 或特殊字符不能直接回显。

当前实现已经做了安全回退：

- 不会因为编码问题直接崩溃
- 必要时会把不兼容字符回退成转义形式

如果你想获得最佳可读性，建议使用 UTF-8 终端。

---

## 17. 排错建议

### 17.1 先看状态

```powershell
python -m councilflow.cli.app status --project-root .
```

### 17.2 看 `.council` 是否有产物

重点检查：

- `.council/discuss/`
- `.council/delegations/`
- `.council/runs/`
- `.council/state.json`

### 17.3 单独验证模型 CLI

```powershell
codex --help
claude --help
gemini --help
```

### 17.4 必要时显式指定主控

```yaml
controller_override: codex
```

### 17.5 在源码环境下记得设置 `PYTHONPATH`

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
```

### 17.6 provider 长时间运行时如何调参

如果你遇到这类错误：

- `error_kind = total_timeout`
- `error_kind = idle_timeout`

优先先分清是哪一种：

- `total_timeout`
  - 说明总执行窗口不够长
  - 提高 `providers.default.total_timeout_seconds`
- `idle_timeout`
  - 说明 provider 太久没有新的显式输出
  - 对流式 provider（当前主要是 `Claude`）提高对应的 `idle_timeout_seconds`

例如：

```yaml
providers:
  default:
    total_timeout_seconds: 1200
    idle_timeout_seconds: null
  claude:
    idle_timeout_seconds: 300
```

---

## 18. 推荐实践

- 总是为每个项目显式写 `.council/config.yaml`
- 把 `.council/config.yaml` 当作项目级自动分发真相源，而不是可有可无的提示文件
- 让最常做主流程控制的模型承担 `planner / architect / synthesizer`
- 把你真正想外包的能力映射出去，例如 `implementer` 或 `tester`
- 把默认讨论参与者写进 `discussion.default_models`，减少每次手动重复写模型
- 把 `.council` 当作显式协作轨迹，而不是临时缓存
- 对重要步骤优先先 `discuss`，再 `delegate`
- 如果 `council` 缺失，再退回主控本地完成；有工具时优先按配置自动路由

---

## 19. 总结

`CouncilFlow` 最适合的使用方式不是“让所有模型同时乱入”，而是：

1. 先明确当前主控
2. 再明确角色映射
3. 只在真正需要时才讨论或委派
4. 让 `.council` 产物成为整个流程的显式中间层

如果你这样使用，它会非常像一个轻量、稳定、可恢复的多模型协作编排层。
