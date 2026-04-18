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

## 19. 变更记录（2026-04-16，全局安装与备份）
本次变更将 `CouncilFlow` 的交付范围从“仓库内完成并可手动同步”扩展为“可安全安装到三端全局环境”。

新增产品要求：
1. 在覆盖任意全局 `project-*` skill 或 MCP 配置之前，必须先生成可恢复备份。
2. 备份范围至少包括：
   - `C:\Users\David Zhai\.workflow-core\skills\project-*`
   - `C:\Users\David Zhai\.codex\skills\project-*`
   - `C:\Users\David Zhai\.claude\skills\project-*`
   - `C:\Users\David Zhai\.gemini\skills\project-*`
   - `C:\Users\David Zhai\.codex\config.toml`
   - `Claude Code` 的用户级 MCP 配置来源
   - `C:\Users\David Zhai\.gemini\settings.json`
3. 必须提供一键化安装入口，把 `.workflow-core` 中当前确认版 `project-*` skills 安装到 `Codex`、`Claude Code` 与 `Gemini CLI` 的全局目录，而不是依赖手工复制。
4. 必须为当前共享 workflow 所需的 MCP 提供统一安装与校验机制；现阶段至少覆盖 `project-manager`，并优先使用各模型官方 CLI 完成注册。
5. 必须提供可读的安装与回滚说明，使用户在新机器、重装或回退时可以复用同一套流程。
6. `.workflow-core\skills\project-*` 继续作为共享 skill 的唯一源，三端目标目录不再允许长期手工分叉维护。

阶段策略：
1. 先备份，再覆盖。
2. 先完成自动化安装与校验，再进行真实会话 smoke。
3. 任一安装步骤失败时，必须保留完整快照并停止后续覆盖。

## 20. 变更记录（2026-04-17，共享 discuss 工作流补齐）
本次变更聚焦 `.workflow-core` 共享 `project-*` skills 与 `CouncilFlow` discuss 能力之间尚未闭环的缺口，目标是让共享 workflow 真正达到 PRD 中承诺的讨论能力覆盖范围。

新增产品要求：
1. 共享 skill 源必须新增独立的 `project-discuss`，作为不绑定具体开发阶段的正式讨论入口。
2. `project-init`、`project-ask`、`project-next` 必须补齐对显式 `discuss <model>` 或 `discuss <model1,model2>` 的说明与调用约定，不再只由 `project-design`、`project-plan`、`project-change`、`project-review` 零散支持。
3. 所有共享 skill 在引用 discuss 产物时，必须遵循 `CouncilFlow` 的真实 artifact 契约：
   - 优先使用 `council discuss` 返回的 `data.summary_path`
   - 或读取 `.council/discuss/<discussion_id>/summary.md`
   - 不再引用不存在的 `.council/discuss/latest/summary.md`
4. 共享 skill 文案必须明确说明 discuss 为显式可选能力，而不是默认总会触发的隐藏步骤。
5. 本次变更完成后，`.workflow-core\skills\project-*` 中的共享定义应再次成为 `Codex`、`Claude Code` 与 `Gemini CLI` 的一致真源，不允许三端继续长期存在 discuss 相关文案漂移。

范围说明：
1. 本次变更只补齐共享 workflow 层，不扩展新的产品 CLI 命令，也不改变 `CouncilFlow` 本体的 provider 行为。
2. 本次变更完成后，需要重新同步共享 skills 到 `C:\Users\David Zhai\.codex\skills`、`C:\Users\David Zhai\.claude\skills` 与 `C:\Users\David Zhai\.gemini\skills`。

## 21. 变更记录（2026-04-17，Claude commands 包装层）
本次变更聚焦 `Claude Code` 的 slash 命令展示兼容性。在不改变共享 workflow 真相源的前提下，为 `Claude Code` 增加一层**可生成、可回滚、可重新安装**的 commands 包装层。

新增产品要求：
1. `.workflow-core\skills\project-*` 继续作为共享 workflow 的唯一真相源，不允许把业务规则复制到第二套 Claude 专用文档中长期手工维护。
2. `Claude Code` 允许新增一层派生产物：`C:\Users\David Zhai\.claude\commands\project-*.md`，仅用于 slash 命令描述展示和入口适配。
3. 这层 commands 包装文件必须由共享源自动生成，而不是手工散落维护；其内容应明确引用对应的 `C:\Users\David Zhai\.claude\skills\project-*\SKILL.md`。
4. `Codex` 与 `Gemini CLI` 的现有 skill 安装方式不应因此改变；本次变更不得要求另外为它们引入额外包装层。
5. 全局备份、恢复、安装和同步流程必须把 `Claude Code` commands 包装层视为受管产物，保证新机器安装、重复安装和回滚都能恢复到一致状态。
6. 本次变更完成后，`Claude Code` 中的 `project-*` slash 入口描述不应再退回显示 YAML frontmatter 第一行，例如 `--- (user)`。

范围说明：
1. 本次变更不改变 `CouncilFlow` 本体命令语义，只处理共享 workflow 在 `Claude Code` 上的入口适配。
2. 本次变更优先保证“单一真相源 + 自动派生 + 可打包安装”，而不是追求三端物理文件格式完全一致。

修复说明（2026-04-17）：
在真实安装后发现 `Claude Code` 会同时暴露 `.claude\skills\project-*` 与 `.claude\commands\project-*.md`，造成 slash 列表重复和说明错乱。自本次修复起：
1. `Claude Code` 的 `project-*` 运行时入口只保留受管的 `commands` 包装层；
2. `.workflow-core\skills\project-*` 仍是唯一真相源；
3. `Codex` 与 `Gemini CLI` 继续使用各自 `skills` 目录，不受该修复影响。

更正说明（2026-04-17）：
在重新核对 Anthropic 官方当前文档后，确认 `skills` 仍然是 `Claude Code` 推荐的正式路径，`commands` 只是兼容机制。因此上一轮“只保留 commands”的修复方向被撤销，新的交付要求改为：
1. `Claude Code` 恢复为使用 `.claude\skills\project-*\SKILL.md` 作为正式 `project-*` 入口；
2. 已生成的 `.claude\commands\project-*.md` 只视为需要清理的 legacy wrapper，不再作为安装目标；
3. `.workflow-core\skills\project-*` 继续作为三端共享真相源；
4. 为降低 Claude 对 frontmatter 的解析异常风险，共享 `project-*` skills 的 `description` 将统一为更稳定的单行写法。

## 22. 变更记录（2026-04-17，自动角色分发与项目级默认配置）
本次变更聚焦 `config.yaml` 的产品语义修正，目标是把它从“可选路由提示”升级为“项目级自动分发策略”。用户在每个项目目录中的 `.council/config.yaml` 应真正决定角色执行去向和默认讨论参与者，而不是只在手工输入 `--model` 时才偶尔生效。

新增产品要求：
1. **项目级配置成为自动分发真源**：当当前机器已安装并可调用 `CouncilFlow` 时，`project-*` 工作流在进入实现、评审、修复、架构等角色步骤前，必须优先读取当前项目 `.council/config.yaml` 的映射结果，而不是默认让主控先亲自执行。
2. **本地执行从“默认行为”改为“路由结果或降级结果”**：
   - 如果某角色映射到当前主控，则本地执行；
   - 如果某角色映射到非主控模型，则自动委派；
   - 如果当前环境没有安装或无法调用 `CouncilFlow`，才允许退回到“主控直接执行”的降级路径。
3. **讨论默认模型进入项目配置**：为满足用户“即使只写 `/project-discuss` 或 `project-init discuss` 也能自动选模型”的需求，项目配置需要新增一组讨论策略字段，用来承担用户所说的 “discuss 角色” 职责。`project-discuss` 与嵌入式 `discuss` 在未显式给出模型列表时，必须优先使用该项目级默认配置。
4. **`config.yaml` 必须项目本地化**：每个开发项目目录下都应有自己的 `.council/config.yaml`，允许不同项目维护不同的角色分工与讨论策略。
5. **缺失配置时自动补齐**：如果用户在某个项目目录下首次调用 `CouncilFlow` 或依赖它的 `project-*` 工作流，但项目中还没有 `.council/config.yaml`，系统应从 `CouncilFlow` 安装目录内置的默认模板复制一份到项目目录，再继续运行，而不是静默回退到硬编码默认值。
6. **共享 workflow 需要自动遵循配置**：`.workflow-core` 中的 `project-init`、`project-design`、`project-plan`、`project-next`、`project-review`、`project-change`、`project-discuss` 等共享 skills，在 `CouncilFlow` 可用时必须优先采用自动角色分发与默认讨论配置，不再把“主控亲自执行”写成默认主路径。

范围说明：
1. 本次变更不仅涉及 `CouncilFlow` Python 本体，还涉及 `.workflow-core` 中的共享 `project-*` skills、集成文档和默认配置模板。
2. 为避免把“执行角色”和“讨论参与者”混成同一语义层，本次设计优先把讨论默认策略建模为项目级 discussion 配置，而不是简单复用现有 execution role 字段。
3. 本次变更完成后，当前文档中所有“默认由当前主控直接执行步骤”的旧表述，均应理解为已被本节 supersede；新语义应为“默认先按项目配置路由，只有工具缺失或显式路由到主控时才本地执行”。

## 23. 变更记录（2026-04-17，discuss 协议升级）
本次变更聚焦 `discuss` 机制本身的讨论质量，目标是把当前更偏“外部咨询 + 主控收敛”的流程升级为更完整的“主控立场 -> 外部评论 -> 主控回应 -> 多轮收敛”协议。

新增产品要求：
1. **主控先给出 `initial_position`**：一旦进入正式 discuss，当前主控必须先基于问题、上下文、约束和当前判断输出一版明确的初始立场，而不是直接把一个裸问题抛给外部模型。
2. **外部模型评论主控立场**：额外参与模型的首轮输出应围绕主控的 `initial_position` 展开，至少对其进行支持、补充、质疑、指出风险或提出替代方案，而不是像独立顾问一样各自从零起草完整方案。
3. **下一轮把外部意见回灌给主控**：多轮 discuss 时，主控下一轮必须显式看到上一轮外部模型对 `initial_position` 的评论摘要，再决定是坚持、修正、收缩还是扩展自己的立场。
4. **增加 `min_rounds`**：在存在额外讨论参与者时，讨论协议必须支持最小轮次控制，避免“第一轮外部模型简单表示同意”就直接提前收敛。只有达到 `min_rounds` 之后，系统才允许走正常的提前收敛判断。
5. **保留 `max_rounds` 但不再与提前结束混淆**：`max_rounds` 继续承担上限保护，而 `min_rounds` 用来保证至少完成一轮“主控回应外部意见”的闭环；两者同时生效。
6. **结构化产物升级**：discussion 的机器可读产物和 summary 需要显式包含：
   - `initial_position`
   - 每轮外部反馈摘要
   - 主控在后续轮次中的回应或修正
   - `min_rounds`
   - 最终是在达到何种条件后结束
7. **无额外参与者时不强行套新协议**：如果 discuss 去重后没有非主控模型参与，仍按现有 warning / short-circuit 行为返回，不为了满足 `min_rounds` 而伪造跨模型回合。

范围说明：
1. 本次变更同时涉及 `CouncilFlow` 本体的 discussion 模型、prompt 协议、orchestrator、CLI 输出、配置 schema，以及与之对应的测试与文档。
2. 本次变更不要求把 discuss 变成无限辩论系统；目标是保证最小闭环质量，而不是追求过度复杂的 debate 框架。
3. 本节覆盖并 supersede 文中所有“外部模型首轮同意即可直接结束”的旧理解；新的产品语义应为：**只要存在额外参与者，至少完成一次主控回应外部意见的闭环后，才允许进入收敛判断。**

## 24. 变更记录（2026-04-17，workflow 强制路由硬约束）
本次变更聚焦共享 `project-*` 工作流的执行纪律，目标是把当前“建议先委派 / 建议先讨论”的软约束，升级为真正影响执行分支的硬约束。否则即使项目级 `.council/config.yaml` 已经声明角色分工，主控仍可能绕过 `CouncilFlow` 直接编码，导致配置失去产品意义。

新增产品要求：
1. **角色型步骤必须先走 `CouncilFlow` 路由**：当 `CouncilFlow` 可用时，任何进入执行角色的 `project-*` skill 都必须先调用对应的 `council delegate --role <role>`，再根据返回结果决定后续动作；主控不得在未调用路由命令前直接开始该角色的工作。
2. **本地执行只能来自显式路由结果**：在已安装 `CouncilFlow` 的环境里，主控本地执行不再是 skill 可自由选择的默认分支；只有在 `council delegate` 返回 `status = local_execution` 时，当前主控才允许继续本地承担该角色。
3. **缺少工具才允许降级**：如果当前机器没有安装、无法调用或明确检测不到 `council` 命令，workflow 才允许退回纯主控本地执行；这种降级必须在输出中明确说明，而不是静默发生。
4. **路由失败应视为 workflow 失败，而不是可接受绕过**：当 `council delegate` 或 `council discuss` 调用失败时，workflow 应如实中止并报告失败原因；不能因为主控“也能做”就直接绕过 sidecar 继续执行。
5. **所有相关共享 skills 都要遵守同一纪律**：至少 `project-next`、`project-review`、`project-change`、`project-design`、`project-plan`、`project-init`、`project-discuss`、`project-ask` 中涉及角色执行或显式 discuss 的部分，都必须把 `CouncilFlow` 调用写成硬前置步骤，而不是“如果愿意可以先调用”的可选建议。
6. **`config.yaml` 的意义是约束分工，不是建议偏好**：项目级 `.council/config.yaml` 应继续作为不同项目的独立真相源；一旦 `CouncilFlow` 可用，主工作流就必须服从该项目配置所定义的分工与默认讨论策略。
7. **验收必须验证“主控不能偷偷跳过”**：新的 workflow 验收不只检查最终能否成功委派，还要检查在真实主控会话里，技能不会在未获得 `local_execution` 前就直接进入本地编码、评审或测试。

范围说明：
1. 本次变更优先修改共享 workflow 契约、集成文档和相关自动化验证；必要时再补充 `CouncilFlow` 本体返回字段或辅助命令，以便主控能稳定判定“允许本地执行”与“必须停下报告失败”。
2. 本节覆盖并 supersede 文中所有“默认由当前主控直接执行步骤”或“主控可按经验直接继续”的旧 workflow 解释；新的产品语义应为：**已安装 `CouncilFlow` 时，先路由、后执行；只有拿到显式路由结果，主控才知道自己能不能继续。**

## 25. 变更记录（2026-04-17，provider 活跃度监控与长时任务容错）
本次变更聚焦非主控 provider 的执行可观察性与长时任务容错，目标是在保持 route-first 硬约束的前提下，让 `Claude Code CLI`、后续的 `Codex CLI` 与 `Gemini CLI` 在长时间推理或产出阶段不再仅凭固定总时长被粗暴判死。

新增产品要求：
1. **provider 超时策略不再只看总时长**：对于支持流式输出或事件输出的 provider，系统需要同时区分：
   - `total_timeout`：防止无限挂起的总上限；
   - `idle_timeout`：只有在长时间无新输出、无新事件、无新进度文本时才视为失活。
2. **优先消费 CLI 已显式暴露的进度信号**：`CouncilFlow` 不需要也不应依赖私有思维链，但应尽可能利用各家 CLI 已公开提供的 stdout/stderr 文本、事件流、partial messages 或状态事件来判断“进程仍在推进”。
3. **Claude provider 先升级为流式监控主路径**：鉴于 `Claude Code CLI` 已支持 `--output-format stream-json` 等实时事件输出，非主控委派和讨论参与中的 `Claude` provider 应优先切换到流式消费模式，而不是继续只依赖 `subprocess.run(..., timeout=...)`。
4. **Codex / Gemini 也要纳入统一 provider 运行抽象**：即便本次只先把 `Claude` 落成活跃度监控，provider 层也应抽象出统一的运行配置与活动心跳概念，避免把 `Codex`、`Gemini` 永久锁死在旧的单次阻塞调用模型上。
5. **失败语义要区分“总超时”和“失活超时”**：结构化错误需要明确告诉宿主 workflow，失败究竟是：
   - 进程活着但总时长超过上限；
   - 长时间无输出/无进度被判定失活；
   - 进程非零退出；
   - 系统级调用失败。
6. **项目级配置需要允许调优 provider 执行窗口**：不同项目、不同模型、不同任务长度差异很大，因此 `.council/config.yaml` 需要支持 provider 相关的执行窗口配置，而不是把超时常量硬编码在安装目录里。
7. **路由硬约束仍然保持**：本次变更的目标是减少误判失败，而不是在 provider 超时后偷偷放开本地绕过；只要 `CouncilFlow` 路由已经启动，宿主 workflow 仍然必须以显式的 `delegated` / `local_execution` / `error` 结果为准。

范围说明：
1. 本次变更优先覆盖 provider 层、配置 schema、委派/讨论错误语义和相关测试，不要求在这一轮把三家 CLI 全部重写成流式接入。
2. `Claude` 流式监控会作为第一优先级落地；`Codex`、`Gemini` 至少需要在本轮中完成能力评估、抽象兼容和非回归验证。

## 26. 变更记录（2026-04-17，全技能自动化阶段机与全链路硬约束）
本次变更聚焦“所有 `project-*` skills 都必须真正服从项目级分工配置”这一产品语义，目标是把当前仍然存在的半硬约束状态彻底收口成一套**按技能、按阶段、按角色显式路由**的完整自动化工作流。

新增产品要求：
1. **所有 `project-*` skills 必须先被归类，再决定是否允许跳过角色路由**。新的正式分类为：
   - **只读/状态型技能**：`project-status`、`project-resume`，只读取状态，不承担执行角色，因此不需要 `delegate`；
   - **人工 gate / 状态流转型技能**：`project-feedback`，只负责人工验收结果回写、阶段 gate 收口或追加后续任务，除非用户显式要求“继续修复”之类的新执行动作，否则不直接承担代码、测试、评审工作；
   - **执行型技能**：`project-init`、`project-design`、`project-plan`、`project-change`、`project-ask`、`project-review`、`project-next`，都必须拆成显式角色阶段并按阶段路由；
   - **讨论型技能**：`project-discuss` 以及其它技能中的嵌入式 `discuss`，一旦触发就是硬前置，不允许主控绕过。
2. **执行型技能必须定义最小阶段机**。V1 正式阶段机要求至少明确为：
   - `project-init`：`planner -> synthesizer`
   - `project-design`：`architect -> synthesizer`
   - `project-plan`：`planner -> synthesizer`
   - `project-change`：`architect -> planner -> synthesizer`
   - `project-ask`：`advisor -> synthesizer`
   - `project-review`：`reviewer`
   - `project-next`：`implementer -> tester -> [fixer -> tester]* -> synthesizer`
3. **`project-next` 的验证与修复不再默认由主控亲自承担**。任务的 `verification_commands` 与 `verification_profile` 应视为 `tester` 阶段的输入，而不是宿主 workflow 自动在本地执行的默认动作。
4. **测试失败后的修补必须进入 `fixer` 阶段机**。当 `tester` 返回失败结论后，workflow 必须显式进入 `fixer` 路由，再回到 `tester` 复测；主控不得因为“问题不大”而直接本地补丁，除非当前阶段拿到了 `local_execution` 或明确进入 `CouncilFlow` 缺失降级路径。
5. **主控的职责收缩为 orchestrate、读取 artifact、以及在获得显式许可后的本地执行**。也就是说，主控不再因为“自己也能做”就默许接管实现、测试、修复、评审或分析阶段。
6. **每个阶段都必须有显式 artifact 消费契约**。至少要明确：
   - 使用哪个 `role`
   - 需要读取哪些前序 artifact
   - 成功后宿主读取哪个 result/summary artifact
   - 失败时如何停止并上报
7. **允许不走 `delegate` 的情况必须是白名单，而不是默认宽松**。只有以下两类情况允许本地继续而不先委派：
   - 技能本身属于只读/状态流转类型；
   - 该阶段明确拿到 `local_execution`，或当前环境确认不存在/不可调用 `council`。
8. **人工验收技能不直接“帮忙补做”执行工作**。`project-feedback` 在收到“未通过”或“需要修改”时，应优先推动新修复任务或重新打开现有任务，而不是在没有新路由的前提下直接进入本地修复。

范围说明：
1. 本次变更同时影响 `CouncilFlow` 本体的集成契约、`.workflow-core` 共享 `project-*` skills、用户文档、发布清单和自动化验证策略。
2. 本次变更的目标不是把每个技能都变成复杂的编排引擎，而是确保**一旦某个阶段属于执行角色，就必须 route-first**。
3. 本节覆盖并 supersede 当前文档中所有“部分角色已硬约束即可视为 workflow 完整”的旧理解；新的产品语义应为：**只有当每个技能的执行阶段都拥有明确角色归属、显式路由结果和清晰的失败/降级规则时，这套 workflow 才算真正完成。**

## 27. 变更记录（2026-04-18，reviewer 闭环与 tester 预检强化）
本次变更聚焦 `project-next` 的后半段闭环质量，目标是在现有 `implementer -> tester -> [fixer -> tester]* -> synthesizer` 的基础上，补齐正式 `reviewer` 阶段，并把 `tester` 从“只会跑命令”升级为“先做环境/权限预检，再执行结构化验证”的稳定执行者。

新增产品要求：
1. **`project-next` 的正式阶段机升级为 `implementer -> tester -> reviewer -> [fixer -> tester -> reviewer]* -> synthesizer`**。也就是说，`tester` 通过后不能直接视为可收口，而是必须进入显式 `reviewer` 阶段，确认语义缺口、状态机漏洞和契约遗漏是否仍然存在。
2. **`tester_passed` 与 `review_passed` 必须是两个独立信号**。`tester` 的职责是执行 `verification_commands`、读取 `verification_profile` 并给出验证层结论；`reviewer` 的职责是基于实现产物和 tester artifact 做语义复查、风险识别与代码审查。只有两者都通过，任务才允许进入最终综合与状态流转。
3. **测试失败与环境阻塞必须区分**。当 `tester` 因 sidecar 权限、CLI allowlist、依赖缺失或工作区环境未就绪而无法执行时，宿主 workflow 必须把它记录为独立的 `permission_blocked` / `environment_not_ready` 类失败，而不是混同为普通 `verification_failed`。
4. **`tester` 进入执行前必须做最小预检**。至少需要验证：
   - 当前目标模型 sidecar 可启动；
   - 本轮 `verification_commands` 所需命令在目标环境中可执行；
   - 若目标模型对命令执行有显式权限模型（如 `Claude Code`），则需要在 handoff 或预检结果中明确说明所需权限集合。
5. **`verification_commands` 需要保持结构化，而不是在 workflow 中被拼接成单条 `&&` shell 字符串**。这样 `tester` 才能逐条执行、逐条上报，并把“哪一条失败”“哪一条因权限被拦截”明确写进 artifact。
6. **`reviewer` 阶段需要结构化 findings 产物**。当 `reviewer` 发现问题时，至少要输出：
   - `finding_id`
   - `severity`
   - `title`
   - `affected_files`
   - `rationale`
   - `required_fix`
   这样 `fixer` 才能基于结构化 review artifact 工作，而不是只消费一段自由文本。
7. **`fixer` 必须消费明确来源的失败输入**。`fixer` 的输入应至少来自以下两类之一：
   - `tester` 的失败 artifact（命令失败、断言失败、环境阻塞）
   - `reviewer` 的 findings artifact（语义缺口、契约偏差、代码风险）
   不允许宿主 workflow 只凭临时自然语言总结就进入修复。
8. **任务执行角色不得越权修改 workflow 状态文件**。`implementer`、`tester`、`reviewer`、`fixer` 的默认允许修改面应聚焦任务相关代码、测试和任务产物；除非任务本身就是在修改 `CouncilFlow` 的 workflow 状态系统，否则不应在 sidecar 实现结果里混入 `.claude/state/*` 这类项目状态文件。
9. **sidecar 默认不得擅自创建 git commit 或推进任务状态流转**。`implementer`、`tester`、`reviewer`、`fixer` 可以产生代码、测试、review artifact 和修复说明，但最终是否 `git commit`、是否标记任务完成、是否接受产物，必须由宿主 controller 在完成 tester/reviewer 闭环后显式决定。

范围说明：
1. 本次变更同时影响 `CouncilFlow` 本体的 delegation/review artifact 契约、共享 `project-next` skill、集成文档、发布清单与自动化测试。
2. 本次变更的目标是把“测试通过但主控仍需肉眼补审”的隐式流程，升级为正式可路由、可验证、可回放的 reviewer 闭环，而不是让 `tester` 无限膨胀成兼做语义评审的超级角色。
3. 本节覆盖并 supersede 当前文档中所有“tester 通过后即可直接综合收口”的旧理解；新的产品语义应为：**只有当 tester 和 reviewer 都以显式 artifact 给出通过结论时，任务才允许完成流转。**
