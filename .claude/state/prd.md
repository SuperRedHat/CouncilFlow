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

例如：
- 如果当前在 `Codex` 中执行工作流，那么 `Codex` 是当前主控
- 如果当前在 `Claude Code` 中执行工作流，那么 `Claude Code` 是当前主控
- 如果当前在 `Gemini CLI` 中执行工作流，那么 `Gemini CLI` 是当前主控

规则：
1. 默认由当前主控直接执行当前步骤。
2. 只有在需要别的模型参与时，才调用 `CouncilFlow`。
3. `CouncilFlow` 不替代主控，只增强主控。

### 6.2 角色
系统定义角色，但**不绑定具体模型**。
用户可以按项目、阶段或单次流程自由配置角色对应的模型。

V1 的最小完整角色集合为：

- `planner`
- `architect`
- `implementer`
- `tester`
- `reviewer`
- `fixer`
- `advisor`
- `synthesizer`

角色含义：
- `planner`：任务拆解与执行顺序规划
- `architect`：架构设计、边界与技术路线判断
- `implementer`：代码实现
- `tester`：测试设计、执行与失败分析
- `reviewer`：代码评审与风险识别
- `fixer`：基于评审或测试结果修复问题
- `advisor`：给建议，不直接承担主要执行责任
- `synthesizer`：收敛讨论结果并输出最终结论

### 6.3 讨论
讨论有两种使用方式：

1. **独立讨论**
   - 通过 `project-discuss`
   - 不绑定某个具体步骤
   - 适合架构讨论、路线选择、问题排查

2. **嵌入式讨论**
   - 通过 `discuss` 参数嵌入到其它 `project-*` skill 中
   - 例如：`project-design discuss claude`
   - 含义：当前主控在执行 `project-design` 前，先和 `claude` 讨论，再由主控收敛并继续当前流程

## 7. 主工作流与产品命令层

### 7.1 开发工作流入口
V1 中，用户的主要入口仍然是现有 `project-*` 工作流，而不是手动输入大量 `council` 命令。

主要入口包括：
- `project-init`
- `project-design`
- `project-plan`
- `project-next`
- `project-review`
- `project-ask`
- `project-change`
- `project-status`
- `project-resume`
- 新增：`project-discuss`

### 7.2 产品内部命令层
`CouncilFlow` 自身提供一组英文 CLI 命令，供主控调用，也允许高级用户直接使用。

建议命令集：
- `council discuss`
- `council delegate`
- `council synthesize`
- `council status`

其中：
- `council discuss`：发起多模型讨论
- `council delegate`：把某个角色任务交给非主控模型执行
- `council synthesize`：汇总多个模型输出为可继续使用的结果
- `council status`：查看当前 sidecar 运行状态和最近结果

这些命令默认应被视为：
- **主控内部调用的底层命令**
- 而不是普通用户日常主入口

## 8. discuss 参数与讨论协议

### 8.1 discuss 参数适用范围
以下技能应支持 `discuss` 参数：
- `project-init`
- `project-design`
- `project-plan`
- `project-next`
- `project-review`
- `project-ask`
- `project-change`

示例：
- `project-design discuss claude`
- `project-plan discuss claude,gpt`
- `project-next discuss gemini`

### 8.2 discuss 触发规则
1. 默认不启动多模型讨论。
2. 只有显式写了 `discuss <model>` 或 `discuss <model1,model2>` 才启动。
3. 如果没有指定额外模型，则按当前主控单模型执行。
4. 如果指定了额外模型，则在当前步骤前触发讨论，由主控收敛结果并继续该步骤。

### 8.3 与当前主控相同模型的讨论
如果用户指定的讨论模型与当前主控相同，则系统应给出明确提醒，而不是静默继续。

例如：
- 当前主控为 `codex`
- 用户输入：`project-design discuss codex`

预期行为：
- 不启动跨模型讨论
- 提示用户：
  - 当前指定模型与主控相同
  - 如果希望进行多模型讨论，请指定不同模型

如果输入：
- `project-design discuss codex,claude`

预期行为：
- 自动忽略与主控重复的 `codex`
- 只让 `claude` 参与
- 可选提示：已忽略与当前主控相同的模型

### 8.4 参与者规则
一次 discuss 至少包含：
- 当前主控
- 一个或多个额外模型
- 可选的人类用户输入

### 8.5 讨论轮次规则
1. 当显式指定了额外模型时，启动多轮讨论。
2. 当讨论场景是“主控 + 1 个额外模型”时：
   - 最多允许 **5 轮**讨论。
3. 这不是强制跑满 5 轮，而是：
   - **最多 5 轮**
   - **满足收敛条件即可提前结束**
4. 不做无限轮讨论。

### 8.6 提前结束规则
如果在某一轮后，额外模型已经明确表示：
- 同意当前方案
- 没有新的实质性补充
- 没有新的异议或风险

那么主控模型可以直接结束讨论，不需要继续跑满剩余轮次。

主控判断收敛时至少参考以下信号：
- 对方模型明确表达认可或无新增意见
- 当前轮只是在重复已有观点
- 用户没有插入新的约束或反驳

### 8.7 讨论流程
建议固定为：

1. **主控 framing**
   - 当前主控先整理问题、上下文、目标、约束
2. **外部模型首轮意见**
   - 每个额外模型独立给出意见
3. **可选交叉回应**
   - 如果有多个模型，允许它们基于彼此摘要再回应一轮或多轮
4. **用户插话**
   - 用户可以在任意轮后补充约束、反驳、缩小范围
5. **最终综合**
   - 由当前主控输出最终结论

### 8.8 输出格式
每次 discuss 最终至少输出：
- `question`
- `participants`
- `key_options`
- `agreements`
- `disagreements`
- `recommended_decision`
- `open_questions`
- `next_step`

### 8.9 sidecar 触发规则
- 如果 discuss 后没有额外模型剩余，则不调用 `CouncilFlow`
- 如果当前步骤目标角色绑定的是当前主控，也不调用 `CouncilFlow`
- `CouncilFlow` 只在“真的有非主控模型参与”时才激活

## 9. 角色执行规则

### 9.1 默认执行规则
1. 默认由当前主控执行步骤。
2. 如果该步骤目标角色绑定的模型就是当前主控，则直接原生执行。
3. 只有当目标角色绑定的是非主控模型时，才调用 `CouncilFlow`。

示例：
- 当前主控是 `Codex`
- `implementer=codex`
  - 直接由 `Codex` 原生执行
- `implementer=claude`
  - 通过 `CouncilFlow` 委派给 `Claude`

### 9.2 默认角色映射（建议）
系统必须支持自由覆盖，但默认推荐如下：

- `planner = codex`
- `architect = codex`
- `implementer = claude`
- `tester = claude`
- `reviewer = codex`
- `fixer = codex`
- `advisor = gpt`
- `synthesizer = codex`

说明：
- `synthesizer` 作为角色概念保留
- 但在 `discuss` 流程中，最终结论默认由**当前主控**输出，而不是额外调用独立模型

## 10. 命名与语言规则

### 10.1 命令与参数语言
以下内容统一使用英文：
- CLI 命令
- role 名称
- 参数名称
- 配置键名
- skill 名称

示例：
- `planner`
- `architect`
- `implementer`
- `discuss`
- `output_language`
- `project-discuss`

### 10.2 skill 命名规则
`project-*` 继续保留英文命名，不新增中文 skill 名。

正式技能集合建议为：
- `project-init`
- `project-design`
- `project-plan`
- `project-next`
- `project-review`
- `project-ask`
- `project-change`
- `project-status`
- `project-resume`
- `project-discuss`

### 10.3 输出语言规则
系统默认输出语言为用户配置语言，初始默认值为：
- `zh-CN`

支持至少：
- `zh-CN`
- `en`

要求：
- 命令和参数始终使用英文
- 最终输出、解释、总结按指定语言返回
- 原始模型回答可保留原文
- `synthesizer` 或主控输出的最终综合结论按目标输出语言生成

## 11. 本地状态与文件结构
V1 使用本地文件作为权威状态，不使用数据库。

建议目录：
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

职责：
- `config.yaml`：角色映射、语言设置、默认讨论策略
- `state.json`：当前流程状态、最近运行结果
- `plans/`：规划产物
- `discuss/`：讨论记录和综合结论
- `delegations/`：委派任务包与结果
- `runs/`：运行日志
- `transcripts/`：完整交互记录
- `artifacts/`：导出的结构化产物

## 12. 技术方向
V1 技术选型建议为：

- 主语言：`Python`
- 交互方式：`CLI`
- 状态存储：`YAML / JSON / Markdown`
- 外部模型接入：
  - 优先接官方 CLI
  - API 作为顾问类补充路径
- 默认不依赖常驻后端

选择 Python 的理由：
- 适合快速实现 CLI
- 易于调用外部 CLI 工具
- 易于处理本地文件状态
- 足以支撑“薄 sidecar”而无需引入服务端复杂度

## 13. 核心功能列表

### Must Have
1. 支持在 `Codex`、`Claude Code` 和 `Gemini CLI` 下工作
2. 当前主控自动识别
3. 支持 `project-discuss`
4. 支持其它 `project-*` skill 使用 `discuss` 参数
5. 支持角色到模型的配置映射
6. 当角色映射到主控时直接原生执行
7. 当角色映射到非主控模型时调用 `CouncilFlow`
8. 支持多模型讨论和最终综合
9. 支持用户在讨论中插入意见
10. 支持本地状态恢复
11. 支持配置输出语言

### Should Have
1. 支持多个模型列表参与 discuss
2. 支持自动忽略与当前主控重复的模型
3. 支持把讨论结果沉淀为结构化文件供后续 skill 使用
4. 支持对实现、测试、评审、修复的最小委派链路
5. 支持高级用户直接调用 `council *` 命令

### Could Have
1. 更细的多轮讨论控制
2. 更丰富的讨论模式（advisor / debate / facilitated）
3. 更强的导出格式
4. 简单 TUI 展示

## 14. 非功能性要求
- **简单**：不引入不必要的系统组件
- **稳定**：默认流程尽可能少依赖额外桥接
- **透明**：每一步是否调用了外部模型必须可见
- **可恢复**：中断后能从本地状态继续
- **可配置**：角色映射和输出语言可改
- **三主控兼容**：同一套工具必须同时适配 Codex、Claude Code 与 Gemini CLI
- **低干扰**：当所有角色都映射到当前主控时，不应触发 sidecar

## 15. 验收标准
V1 完成时，至少满足：

1. 在 `Codex` 中可以将其作为主控工作流使用
2. 在 `Claude Code` 中也可以将其作为主控工作流使用
3. 在 `Gemini CLI` 中也可以将其作为主控工作流使用
4. `project-discuss` 可以发起多模型讨论并得到最终综合结果
5. `project-design discuss claude` 这类嵌入式讨论可以工作
6. 如果用户指定 `discuss` 的模型与当前主控相同，系统会给出正确提醒
7. 当某角色映射到当前主控时，系统不会绕路调用 `CouncilFlow`
8. 当某角色映射到非主控模型时，系统能通过 `CouncilFlow` 发起委派
9. 所有关键状态都能从本地 `.council/` 恢复
10. 默认输出可为中文，且支持切换输出语言
11. 整个系统不依赖数据库、Web UI 或常驻后端
12. `.workflow-core` 的共享 `project-*` skill 源可稳定同步到 `Codex`、`Claude Code` 与 `Gemini CLI`

## 16. 约束与假设
1. 当前项目继续使用现有 `project-*` 作为开发工作流
2. `CouncilFlow` 是新产品本体，不再沿用旧产品方向
3. 第一版正式主控支持：
   - `Codex`
   - `Claude Code`
   - `Gemini CLI`
   - `GPT` 继续作为可选讨论参与者或补充角色
4. 第一版不追求复杂平台能力，只追求多模型协作主路径稳定
5. 只有在非主控模型真正参与时，才启用 sidecar

## 17. 结论
`CouncilFlow` 的最终定位不是“另一个 AI 平台”，而是：

> 一个服务于 `Codex`、`Claude Code` 与 `Gemini CLI` 的、主控感知的、多模型协作 sidecar CLI。

## 18. 变更记录（2026-04-16）
本次变更正式将 `Gemini CLI` 从“可选讨论参与者或补充角色”提升为**产品级主控**支持范围，并要求 `.workflow-core` 的共享 `project-*` skill 源同步覆盖 `Codex`、`Claude Code` 和 `Gemini CLI`。

阶段策略：
1. 允许先完成 `Codex-first` 稳定性硬化，避免 `TASK-008` 在 Claude 配额重置前成为唯一阻塞点。
2. `Gemini CLI` 的主控接入与共享 skill 扩展可以和当前 `Claude Code` release-gate 并行推进。
3. 等 `Claude Code` 配额恢复后，再执行三主控最终 gate 与共享 skill 全量同步验收。

本节覆盖并 supersede 文中所有“仅支持 Codex 与 Claude Code 作为主控”的旧表述。
