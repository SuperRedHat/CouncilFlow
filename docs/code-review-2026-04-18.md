# CouncilFlow 全量代码审查报告

- 审查日期：2026-04-18
- 审查范围：`src/councilflow/` 全部 Python 源码、`docs/integration.md`、`docs/release-checklist.md`、PRD、架构文档、`.claude/state/tasks.json` 中剩余 4 个 todo 任务
- 当前进度：48 / 53（91%），1 awaiting_manual（TASK-041），4 todo（TASK-042 / 043 / 044 / 045）
- 审查方式：只读分析，不改代码

> 本报告分四层：**架构层面不合理点** → **潜在 bug 明细** → **可优化项** → **后续任务合理性评估**。每个问题都标注了严重度（🔴高 / 🟠中 / 🟢低）与建议处理方式。

---

## 0. 总体结论

CouncilFlow 的代码质量**高于同阶段原型产品的平均水平**：

- 模块职责划分清晰（cli / controller / providers / handoff / state / models / utils），符合架构文档 §3.1 的设计意图。
- Pydantic 模型覆盖完整，handoff / discussion 全部结构化，没有"一大团 dict 乱飞"。
- 子进程均使用 list-style 参数，未出现 `shell=True` 形式的命令拼接，没有观测到 shell/command injection 风险。
- 关键控制流（snapshot/restore、tester preflight、guardrail）都有对应的单元或集成测试（tests/test_delegation_orchestrator.py 等）。
- 三主控（Codex / Claude / Gemini）的适配点都落在 providers 层，没有把模型特性泄漏到 orchestrator。

但也存在**几处确定性问题**和**若干架构决策尚未收口**的地方，特别是：

1. **默认配置存在两套不一致的真值**（code 里的 `DEFAULT_ROLE_MODELS` 与 `templates/default-config.yaml` 完全不同）。
2. **默认角色 `advisor=gpt` 对应的 provider adapter 未实现**，一旦走默认路径会抛 ProviderError。
3. **`--controller-position` 模式下 `min_rounds` 被强制压为 1**，与 PRD §23.4 承诺的"最小闭环"语义冲突。
4. **sidecar 隔离目前仍是"事后 snapshot / restore"**，在 TASK-042/043/044 完成之前始终是被动防御而非主动隔离，这也是计划中任务的合理出发点。

---

## 1. 设计层面的不合理点

### 1.1 🔴 默认配置存在两套真值，且彼此冲突

- `src/councilflow/models/roles.py:29-38` 中 `DEFAULT_ROLE_MODELS` 给出的默认分工是"codex 偏重规划 / 审查，claude 偏重实现 / 测试，advisor=gpt"。
- `src/councilflow/templates/default-config.yaml:4-12` 中所有 8 个角色都被写成 `claude`。
- 两者通过两条不同路径触达用户：
  - 代码默认（当 `.council/config.yaml` 不存在 **且** 也没有 template 可复制时）→ `RoleMapping()` 字段 default。
  - 模板默认（首次 `ensure_config_exists` 时复制到 `.council/config.yaml`）→ 全 claude。
- 实际运行时 `config/loader.py:30-36` 的 `build_default_config()` 会走 YAML 模板，所以用户拿到的永远是"全 claude"，但代码里 `DEFAULT_ROLE_MODELS` 依旧承诺另一种分工。结果就是：**代码里的默认与实际运行时默认永不一致**。

**建议**：
- 选一个真值源。推荐以 `default-config.yaml` 为准，`RoleMapping` 的字段 default 从模板派生（例如 `load_default_config_text()` 读一次并在测试中校验一致性）。
- 同时把 `models/config.py:RoleMapping.planner` 等显式默认删掉，改为"没有字段 default 时才走模板"的 contract，避免以后再分叉。

---

### 1.2 🔴 `advisor` 默认指向 `gpt`，但 `gpt` 没有 provider adapter

- `models/roles.py:36` 里 `RoleName.ADVISOR: "gpt"`。
- `cli/delegate.py:104-119` 的 `get_provider_adapter` 只识别 `{codex, claude, gemini}`，遇到 `gpt` 会抛 `ProviderError("No provider adapter is registered for model 'gpt'.")`。
- 这条错误路径没被单测覆盖；而且 `ProviderError` 默认 `kind="process_exit"`，分类语义错误（它其实是 configuration_error / adapter_missing）。
- 架构文档 §4.5 里提到过 `OpenAIChatAdapter`，但代码里从未实现，也不在 todo 任务里。

**建议**（三选一，越往下越激进）：
1. **短期**：把 `DEFAULT_ROLE_MODELS[ADVISOR]` 改成 `codex` 或 `claude` 等现有适配器中存在的值，避免"默认配置 + 默认角色"就能触发运行时错误。
2. **补齐**：在 providers/ 下实现 `OpenAIChatAdapter`（通过官方 SDK 或 OpenAI CLI），注册到 `get_provider_adapter`。
3. **正名**：若明确不支持 gpt，在 `normalize_model_name` 里主动拒绝 `gpt` / `openai`，把错误前置到配置加载期。

---

### 1.3 🟠 sidecar 隔离目前只是"事后 snapshot/restore"，不是真正的隔离

- `controller/delegation_orchestrator.py:206-260` 对 `.claude/state` 与 `.council/state.json` 做 SHA-256 snapshot，执行结束后 detect + restore。
- 这属于**被动防御**：sidecar 仍然运行在主项目根目录内，仍然可以读到 `.claude/state` 的旧内容、读取 `.workflow-core/skills`、读取任意全局配置。它只是"写了会被还原"。
- PRD §28 已经明确"sidecar 默认应被隔离在 workflow 状态面之外，guardrail 只负责兜底"，TASK-042 / 043 正是在补这一缺口。因此**当前缺口是已知且在计划中的**。
- 另外一个细节盲区：`writable_paths` 字段存在（`ExecutionGuardrails.writable_paths`），但 orchestrator 现在**没有正向校验** sidecar 是否只写了 writable_paths 内的文件。即在 TASK-043 落地之前，这是一个"模型规定了、运行时没检查"的隐形契约。

**建议**：
- 先按 TASK-042 的顺序把契约字段（isolated workspace path、writable_paths、readonly artifacts manifest）锁死，再在 TASK-043 里一次性补齐正向检查与导回。不要在 orchestrator 内先加中间态的"writable_paths whitelist 检查"，避免之后要推翻。

---

### 1.4 🟠 `--controller-position` 模式下 `min_rounds` 被强制压为 1，破坏 PRD §23.4

- `cli/discuss.py:154-157`：
  ```python
  effective_max_rounds = max_rounds or config.discussion.max_rounds
  if normalized_controller_position is not None and max_rounds is None:
      effective_max_rounds = 1
  effective_min_rounds = min(config.discussion.min_rounds, effective_max_rounds)
  ```
  当用户同时满足"传了 `--controller-position`" + "没传 `--max-rounds`"时，max_rounds=1、min_rounds 被裁到 1。
- 默认模板 `discussion.min_rounds: 2`（`templates/default-config.yaml:15`），意图是"至少一个完整的主控回应外部意见闭环"。
- 相关测试 `tests/test_cli_discuss.py:307-309` 甚至把 `effective_min_rounds == 1` 作为**预期行为**写入断言。这说明当前实现被当成了产品语义，但它与 PRD §23.4 的"只有达到 min_rounds 之后才允许走正常的提前收敛判断"存在歧义：
  - PRD §19 补充修正："当前主控在宿主工作流中先本地生成简短 `initial_position`" 的意图是避免同控制器 self-nesting，而不是缩短最小轮数。
  - 当前实现把"controller 本地生成 initial_position"与"只允许 1 轮"耦合在了一起，这并不是 PRD 明确要求的。
- 后果：默认 `/project-discuss` 如果依赖 --controller-position（在共享 workflow 中这是推荐路径），只会得到 1 轮讨论。与 `min_rounds=2` 的配置承诺矛盾，用户容易误以为"设置了也不生效"。

**建议**：
1. 把"默认 max_rounds=1"的自动降级移除，默认仍读 `config.discussion.max_rounds`。
2. 如果确实希望"local initial position 模式下默认只跑少一点轮数"，请用独立的字段（例如 `discussion.max_rounds_when_local_initial_position`）显式表达，避免与 `min_rounds` 语义混淆。
3. 同步修改 `tests/test_cli_discuss.py` 里对应断言。

---

### 1.5 🟠 Prompt 和 summary 强制英文输出，与 `output_language=zh-CN` 的产品承诺存在张力

- `handoff/prompts.py:11-108` 里 delegation prompt 的段落 header、指令（"You are the delegated ..."、"Expected Output:" 等）全部英文硬编码。
- `handoff/summaries.py:11-49` 的 summary.md headers（`## Initial Position`、`## Key Options`、`## Agreements` 等）也是英文。
- PRD §10.3 的规则是"命令和参数英文，最终输出按指定语言"，所以**指令体英文、答案体中文**在协议层是正当的。但 `summary.md` 是最终沉淀产物、会被 `project-*` 直接呈现给用户，其 headers 也应该跟随 `output_language`。
- 这是**产品体验层的 rough edge**，不是 bug，但三主控场景下 zh-CN 用户看到一半中文一半英文，会觉得没收口。

**建议**：
- 在 `render_discussion_summary` 里引入一个最小的 i18n table（两套 headers 字符串），按 `summary` 上下文的 language 选择。
- Prompt 内部维持英文指令即可，但在 prompt 末尾的 "Expected Output" 中明确要求模型用 `output_language` 回答。

---

### 1.6 🟢 `normalize_model_name` 对未知模型名静默降级

- `models/roles.py:60-64` 的实现：`MODEL_ALIASES.get(normalized, normalized)`。
- 如果用户在 config 里写了 `clood`、`gpt-4` 这种非法或未映射名，会原样通过 normalize，直到 `get_provider_adapter` 才报错。错误信息离源头很远。
- 三主控的 alias 表是硬编码（`gemini-1.5-flash`、`google-gemini` 等），**新模型版本会失配**。例如未来 `gemini-2.5-pro` 不在表里就被原样返回，`ProviderSettings.for_model` 判断 `normalized in {"codex","claude","gemini"}` 会失败，runtime override 不生效。

**建议**：
- 在 `normalize_model_name` 里把未知值也尽量 fallback 到 provider family（例：以 `gemini-` 前缀开头 → `gemini`、以 `claude-` 开头 → `claude`），或者加一个独立的 `resolve_provider_family(model) -> Literal["codex","claude","gemini"]` 用于 runtime override 路由。
- 也可以把完全未识别的模型拒绝在 config 加载阶段（`RoleMapping.normalize_models` 的 validator），给出一条明确的错误信息。

---

### 1.7 🟢 Gemini 的 YOLO 审批模式写死在默认命令里

- `providers/gemini_cli.py:68-95` 默认带 `--approval-mode yolo`。
- 当前 sidecar 只传纯文本 prompt、不给 Gemini 调用本地工具的 instruction，所以 YOLO 的实际风险有限。
- 但 Gemini CLI 自己也可能在 prompt 诱导下主动使用其内置工具（search / file-read 等）。YOLO 一旦叠加到"在主项目根目录运行"的当前实现上，风险面就被放大了。
- 这与 §1.3 的 sidecar 隔离缺口耦合：在 TASK-042/043 之后若 sidecar 真的跑在隔离工作区里，YOLO 可以接受；在那之前，保留 YOLO 是把安全全部交给"Gemini 不会乱来"这个假设。

**建议**：
- 把 approval-mode 提到 `ProviderRuntimeOverrides` 里作为可调参数；默认改为 `auto_edit` 或 `default`，仅在显式允许时才 YOLO。
- 相关文档（integration.md）也补一行"Gemini 默认不开 YOLO"。

---

## 2. 潜在 Bug 明细

### 2.1 🔴 `tester` 角色时，调用方传入的 `tester_preflight` 被静默覆盖

- `controller/delegation_orchestrator.py:403-408`：
  ```python
  if role is RoleName.TESTER:
      package.tester_preflight = _run_tester_preflight(...)
  ```
  即使调用方在 `run(tester_preflight=...)` 里显式传了一个 TesterPreflight 实例，也会被覆盖。
- 对调用方来说这是"API 参数看起来能传但其实不生效"的 silent override，未来别的组件（例如 project-next skill 直接提供预计算 preflight）会被坑。

**建议**：
- 要么移除 `run(..., tester_preflight=...)` 入参（强制 orchestrator 现算），要么改成"只在 caller 没传时才计算"。推荐前者，签名更干净。

---

### 2.2 🟠 `discussion_orchestrator.run` 捕获到 `ProviderError` 时 `error_kind` 会丢失

- `controller/discussion_orchestrator.py:267`：
  ```python
  "error_kind": getattr(exc, "error_kind", None),
  ```
- 目前的调用链里，`ProviderError` 在 `cli/discuss.py:ProviderDiscussionParticipant.respond` 被包裹为 `UnavailableParticipantError(..., error_kind=exc.kind)`，所以多数情况下确实有 `error_kind`。
- 但如果 `participant.respond` 以任何原因抛 `ProviderError` 而不是 `UnavailableParticipantError`（例如未来有人直接在 participant 内部复用 provider），`getattr(exc, "error_kind", ...)` 会返回 None，然后持久化到 `.council/discuss/<id>/record.json` 时类型分类就丢了。
- 更长远的问题是**error 属性命名不统一**：`ProviderError.kind` vs `UnavailableParticipantError.error_kind`，未来很容易写错。

**建议**：
- 统一命名。推荐把所有错误类都用 `.kind`（与 ProviderError 保持一致），`UnavailableParticipantError.error_kind` 重命名为 `.kind`。
- 或者在基类 `CouncilError` 上强制约定。

---

### 2.3 🟠 `get_provider_adapter` 未注册模型时抛 `ProviderError` 但 `kind` 默认是 `process_exit`

- `cli/delegate.py:119`：
  ```python
  raise ProviderError(f"No provider adapter is registered for model '{model}'.")
  ```
- `ProviderError.__init__` 默认 `kind="process_exit"`（`providers/base.py:58`）。
- 最终进入 `_persist_failure`（`delegation_orchestrator.py:293`），`DelegationRecord.error_kind` 被记为 `process_exit`。
- 这和"进程退出码非 0"是同一个分类，事后调试会误以为 CLI 被 kill 了。

**建议**：
- 明确给出 `kind="adapter_missing"` 或 `kind="configuration_error"`，并在 `providers/base.py:62` 的注释里登记新的 error kind。
- `DelegationOrchestrator._persist_failure` 无需修改（它只是透传 kind）。

---

### 2.4 🟠 Gemini specific 版本的 `ProviderResponse.model` 与 `participants`/`external_models` 不一致

- `providers/gemini_cli.py:36,57`：若 caller 传了 `model="gemini-1.5-flash"`，`self.model_name` 就是 `"gemini-1.5-flash"`，response.model 也是这个值。
- `controller/discussion_orchestrator.py:171`：`speaker_model=response.model`，会把 `"gemini-1.5-flash"` 写进 `DiscussionTurn`。
- 但 `DiscussionRecord.participants` 里记录的是**去重归一化后的** `"gemini"`（来自 `resolve_discuss_models`）。
- 结果：`summary.md` 的 `Participants: codex, gemini`，但 `turns[*].speaker_model: "gemini-1.5-flash"` —— 两处名字不一致，阅读和 downstream 工具按名字比对时会出错。

**建议**：
- 二选一：
  - （简单）`GeminiCliAdapter` 保持 `model_name="gemini"`，把具体版本塞到 `metadata.gemini_model`。
  - （产品友好）同时在 `DiscussionRecord.participants` 里记录版本名，但用 `normalize_model_name` 后的 family 作为 key 做比对。
- 推荐第一种，落地小、一致性强。

---

### 2.5 🟠 `handoff/packages.py::_coerce_verification_commands` 仍保留 `&&` 拆分

- `handoff/packages.py:40-44` 在 caller 没传 `verification_commands` 但传了 `inputs["verification_commands"]` 这种旧格式时，按 `&&` / 换行切分。
- PRD §27.5 明确要求"不再在 workflow 中被拼接成单条 `&&` shell 字符串"，所以这是向后兼容代码。
- 副作用：如果将来有人传了 `bash -c "foo && bar"` 这种合法命令，会被错误拆成 2 条。
- 另外，当下 CLI 唯一的入参路径是 `--verification-command` list，根本触不到这个 legacy 分支；但仍然是测试盲点、潜在陷阱。

**建议**：
- 给 legacy 路径加 DeprecationWarning（保留一个版本），同时打印一条"请迁移到 list 型 --verification-command"。
- 下个版本直接删。

---

### 2.6 🟢 `discussion_orchestrator._round_has_converged` 判定过于严苛

- `controller/discussion_orchestrator.py:443-450`：
  ```python
  return all(
      response.supports_current_direction
      and not response.has_new_information
      and not response.disagreements
      and not response.open_questions
      for response in responses
  )
  ```
- 要求所有参与者"支持方向 + 无新信息 + 无异议 + 无遗留问题"才算收敛。
- 现实中 LLM 被 prompt 要求输出 "open_questions"，几乎总会写点东西（"Do you want X or Y?"）。导致 convergence 几乎永远不触发，除非 prompt 里明确允许它留空。
- 结果：大多数 discuss 会跑到 `max_rounds` 才停，浪费额度。

**建议**：
- 放宽：只要 `supports_current_direction == True` 且 `has_new_information == False`，就接受收敛；把 `open_questions` / `disagreements` 降级为可选质量信号。
- 或者在 prompt 里更明确地要求模型"无剩余问题时 open_questions 必须为空数组 []"。

---

### 2.7 🟢 `default-config.yaml:discussion.default_models` 是字符串而非列表

- 模板写的是 `default_models: codex`（单个字符串），依赖 `DiscussionSettings.normalize_default_models` 的 before-validator 去 split/`normalize`。
- 这在 YAML 里是合法的，但**和 `List[str]` 的 Pydantic 标注不一致**。用户看模板容易学成这种写法，下一次想扩展就会写 `codex,claude` 而不是列表形式。
- 建议把模板里写成 `default_models: [codex]`（YAML list），和 `roles:` 一样缩进，阅读更自然。

---

### 2.8 🟢 `run_monitored_process` 返回前的 `process.wait(timeout=1)` 未被包裹

- `providers/base.py:262`：`returncode = process.wait(timeout=1)` 没有 `try/except subprocess.TimeoutExpired`。
- 理论上进到这一行时 `process.poll() is not None`（line 241 的 break 条件），所以 wait 会立即返回；但如果流已关闭但进程仍未退出（极端场景如进程被 OS 挂起），TimeoutExpired 会抛出并逃逸 finally（reader thread join）后直接上抛到调用方。调用方也没有针对 TimeoutExpired 的专门分类，会变成裸 exception。
- 概率极低，可当作加固项。

**建议**：
- 改为 `try: returncode = process.wait(timeout=1) except subprocess.TimeoutExpired: _terminate_process(process); returncode = process.wait(timeout=2)`；或者直接升级为 `ProviderError(kind="process_exit")`。

---

### 2.9 🟢 `append_run_record` 在同一微秒内可能文件名冲突

- `state/store.py:94-95`：时间戳精度到微秒，`.council/runs/{stamp}-{kind}.json`。
- 理论上两次 append 在同一微秒命中会覆盖前一次记录。概率极低，但"审计 / 可恢复"是产品基线（非功能要求第 4 条"可恢复"），信息丢失的代价大于加一个序列号的代价。

**建议**：
- 要么把毫秒 / 微秒 + 递增计数器拼上，要么在写入前检测已存在就回退 `_1`、`_2`。

---

### 2.10 🟢 `_strip_runtime_notices` 以前缀匹配删行，可能误杀模型输出

- `providers/gemini_cli.py:153-163` 删除以 `"Attempt "` 开头的整行。
- 如果模型答案里出现 "Attempt the following steps..." 这种合法内容，会被整行丢掉。
- 目前 Gemini CLI 的运行时提示确实以这两个前缀输出，但依赖前缀过滤是脆弱的。

**建议**：
- 用更严格的特征（例如固定结尾、完整正则）或请求 Gemini CLI 写进 stderr 后只过 stderr。

---

### 2.11 🟢 `cli/delegate.py` 把 `controller` 与 `configured_language` 塞进 `inputs`，可能与 caller 的结构化 input 冲突

- `cli/delegate.py:192-196`：
  ```python
  inputs={
      "controller": controller,
      "configured_language": config.output_language,
      **structured_inputs,
  }
  ```
- `**structured_inputs` 放在后面，意味着 caller 传入的同名 key 会覆盖 orchestrator 默认的 `controller`。倒过来说，如果 caller 真的需要表达"controller"字段，会把 orchestrator 填入的值覆盖掉。
- 同时 handoff.yaml 里永远出现 `inputs.controller` 和 `inputs.configured_language`，而不是放在专门的 metadata 字段里，会污染 handoff 的语义面。

**建议**：
- 把 `controller` / `configured_language` 放到新的 `HandoffPackage.metadata` 或 `HandoffPackage.controller_context` 字段里，别和用户 inputs 混。

---

### 2.12 🟢 `render_delegation_prompt` 中嵌套 f-string 依赖 Python 3.12+ PEP 701

- `handoff/prompts.py:30-42` 等处有形如：
  ```python
  f"- command_availability: "
  f"{json.dumps(
      package.tester_preflight.command_availability,
      ensure_ascii=False,
  )}"
  ```
- PEP 701（嵌套 f-string）是 Python 3.12 才允许的语法。`pyproject.toml` 的 `requires-python = ">=3.13"` 没问题，但这意味着**任何人不小心把最低版本调回 3.11 就会解析错误**。
- 非 bug，但值得在 CI 里加 `--python-version=3.13` 的 mypy 检查或在贡献文档里注明。

---

## 3. 可优化项

### 3.1 🟠 引入结构化 logging

目前整个 codebase 里**没有任何 logging 调用**，所有调试信息都只能通过 `emit_response` 的 JSON metadata 侧面观察。当三主控环境跑出 sidecar 问题时（超时、guardrail 拦截、JSON 解析失败等），现场几乎没法复盘。

建议：
- 统一用 `logging.getLogger("councilflow.<module>")`，默认 INFO，`COUNCILFLOW_DEBUG=1` 切 DEBUG。
- 关键点：
  - `DelegationOrchestrator.run`：进入 / 退出 / guardrail 触发
  - `run_monitored_process`：每 10s 打一条活动心跳
  - `_parse_stream_json_output`：解析失败时记录前 200 字符
  - Provider subprocess：只打 command、cwd、耗时，不打 prompt 内容（防敏感信息）

---

### 3.2 🟠 Provider adapter 的 factory 应改为注册表

当前 `cli/delegate.py::get_provider_adapter` 和 `cli/discuss.py::get_participant` 是两个重复的 if-elif 分支。每加一个 adapter 要动两处。

建议：
```python
# providers/registry.py
ADAPTER_FACTORIES = {
    "codex": lambda model, runtime: CodexCliAdapter(runtime=runtime),
    "claude": lambda model, runtime: ClaudeCodeCliAdapter(runtime=runtime),
    "gemini": lambda model, runtime: GeminiCliAdapter(
        model=_gemini_specific_model(model), runtime=runtime
    ),
}
```
让 `get_provider_adapter` 和 `get_participant` 共享一份。

---

### 3.3 🟢 Codex / Gemini 也应接入流式心跳（PRD §25）

PRD §25 已经承认："即便本次只先把 `Claude` 落成活跃度监控，provider 层也应抽象出统一的运行配置"。目前：

- Claude：stream-json + idle_timeout 有效 ✅
- Codex：blocking + 只有 total_timeout ❌
- Gemini：blocking + 只有 total_timeout ❌

Codex CLI 已经有 `codex exec --json`（可产出结构化事件），Gemini CLI 长远有 `--output-format stream-json`。

建议：
- 即使不立即切换，**在 TASK-044 中同时增加一个探针**：检测 Codex/Gemini CLI 版本是否支持流式 flag，能用就用。
- 在 `providers/base.py` 暴露 `run_monitored_process` 的 public 通用接口（当前仍半内部），便于 Codex/Gemini 未来直接复用。

---

### 3.4 🟢 `summary.md` i18n 化

参见 §1.5。代码改动量不大（两套 headers 字典）。

---

### 3.5 🟢 配置加载没有 atomic write

`config/loader.py::dump_config` 直接 `path.write_text(...)`。如果进程在写入中途被 kill，config.yaml 可能被截断。类似问题在 `state/store.py::_write_json` 也存在。

建议：
- 使用 `path.with_suffix(".tmp")` 先写再 `os.replace`。
- 因为 CouncilFlow 是本地单进程工具，不需要 fsync，但 rename 原子性可避免半截文件。

---

### 3.6 🟢 `handoff/packages.py::_infer_fixer_input_sources` 的"下划线前缀即 stage"是魔术行为

```python
source_stage = label.split("_", 1)[0] if "_" in label else "upstream"
```
`tester_result` → `tester`，`implementer_result` → `implementer`，`some_label` → `some`（不一定是 stage）。没有文档，未来读者会困惑。

建议：
- 把 stage 识别做成白名单比对（`{"tester","reviewer","implementer","fixer"}`），不在白名单内的直接 `"upstream"`。
- 或者把 `source_stage` 从 label 推断改为调用方必填。

---

### 3.7 🟢 `_hash_bytes` 用 SHA-256 做改动检测略显重

- `delegation_orchestrator.py:186-189`。workflow 状态文件很小，SHA-256 OK；但若未来 `.claude/state` 下出现大文件，会有 CPU 成本。
- 可改为 `hashlib.blake2b(digest_size=16)` 或直接 `len(content), content[:1024]` 粗校验 + 全量校验。非紧急。

---

### 3.8 🟢 测试文件中对 `effective_min_rounds == 1`（§1.4 bug）的断言需要与产品决策同步

当修复 §1.4 时，`tests/test_cli_discuss.py:308` 的预期也要一起改；不要在不看产品意图的情况下留着这个绿色用例。

---

## 4. 后续任务合理性评估

### 4.1 TASK-041（awaiting_manual_acceptance）— 合理 ✅

"在真实 Codex/Claude/Gemini 主控项目中验证 reviewer 闭环、tester preflight、sidecar 提交保护"。

- 已通过自动化（ruff + 122 pytest + sync-skills），只差真实 smoke。
- acceptance_criteria 四条都是**过程验证**（而不是结果正确），符合 PRD §27.9"release/workflow gate 需要新增 reviewer 回归"。
- 建议 smoke 时同步准备 reproducible scenario，例如：
  - 人为故意给 Claude `settings.json` 去掉某条 Bash(...) 权限，触发 `permission_blocked`。
  - 人为让 sidecar 在 result 里试图修改 `.council/state.json`，观察 restore。
- 没有发现任务设计问题。

---

### 4.2 TASK-042（todo, auto, M）— 建议细化契约后再开工 ⚠️

"扩展 delegation/handoff/result 契约，正式引入 sidecar workspace、导回清单与受保护 workflow 路径默认隔离语义"。

**合理性**：对齐 PRD §28，明确优先契约先行、实现后跟；`files` 只涉及 models / handoff / docs / tests，范围合理。

**建议在动手前先定稿这些契约字段**：
- `HandoffPackage.isolated_workspace`（可选，指向 sidecar 用的临时目录相对根路径？）
- `HandoffPackage.import_manifest`（期望导回的文件路径白名单）
- `HandoffPackage.readonly_artifacts`（sidecar 只读、不应被改动的参考文件列表）
- `DelegationResult.workspace_manifest`（实际发生修改的文件清单 + 新增 / 修改 / 删除标记）
- `DelegationResult.import_outcome`（导回成功 / 部分成功 / 全部拒绝 / 冲突）
- 受保护路径 default 值是否要从 `[".claude/state", ".council/state.json"]` 扩展到 `.workflow-core`、全局 skills 目录等？

**复杂度评估**：当前标的 M 可能偏低。契约 + 文档 + 至少 6~8 个新字段的 Pydantic + 测试，更接近 M-L。建议改为 L，以免 TASK-043 因 TASK-042 留遗漏被拖慢。

**acceptance_criteria 补充建议**：
- 增加一条"验证 handoff.yaml 在旧版本 CouncilFlow 读取时仍能 load"（向后兼容）。
- 增加一条"handoff prompt 渲染新字段时 E2E snapshot 保持稳定"。

---

### 4.3 TASK-043（todo, auto, L）— 合理但隐含大量决策 ⚠️

"实现 delegation 的隔离工作区 materialize 与合法变更导回"。`files` 列表里出现了 `src/councilflow/utils/io.py`，当前仓库里**这个文件还不存在**（`utils/` 只有 `lang.py`）。TASK-042 理应在契约里确认这个新模块。

**关键决策未在 tasks.json 中明确**：
1. **materialize 策略**：`shutil.copytree` 整库？`git worktree add`？或者只复制 handoff.relevant_files 里提到的文件 + 依赖（pyproject.toml、锁文件、tests 目录）？
2. **Windows 三主控兼容**：硬链接在 Windows 上受文件系统限制，bind mount / overlayfs 没有。最稳的是 `git worktree` + 过滤。
3. **大仓库性能**：全量复制对 50k+ 文件的仓库（含 node_modules）不可接受。必须有一层过滤。
4. **导回冲突**：如果 sidecar 修改了 `src/foo.py`，但与此同时 controller 也改了同一文件（比如用户在并行编辑），应如何处理？PRD §28.7 提到"若导回失败，宿主应停止并报告"，但"失败"判据是 three-way merge 冲突还是 stat-level 发现两边都动过？
5. **`.gitignore`**：sidecar 产出的 `node_modules/`、`__pycache__/` 等临时文件不应被尝试导回。

**建议**：
- 在 TASK-042 的 `ExecutionGuardrails` 里一起引入 `materialize_strategy: "copy" | "git_worktree" | "file_list"`、`import_filter_globs: list[str]`，把这些决策提前暴露在契约层面。
- `acceptance_criteria` 第 2 条"导回成功路径"应细化为：commit-level（sidecar 自己在隔离 worktree 里 commit，controller 按 merge/cherry-pick 导回）还是 patch-level（sidecar 只写文件，controller 用 diff apply）？
- 复杂度 L 合理，**但强烈建议拆成子任务**：
  - TASK-043a：materialize + prompt 注入（sidecar 知道自己在 worktree）
  - TASK-043b：result manifest + 正向 writable_paths 检查
  - TASK-043c：import（合法变更导回主项目）

---

### 4.4 TASK-044（todo, auto, L）— 合理且必要 ✅

"非递归 runtime guard + 环境剥离"。防止 delegated sidecar 在内部再次调用 `council` / `project-*` / `project-manager` MCP。

**实现要点（建议 task notes 里写下）**：
1. 环境变量剥离：启动 sidecar 子进程前，从 `os.environ` 中删除：
   - `CODEX_SHELL`、`CODEX_THREAD_ID`、`CODEX_INTERNAL_ORIGINATOR_OVERRIDE`
   - `CLAUDECODE`、`CLAUDE_CODE`、`CLAUDE_CODE_SHELL`、`CLAUDE_SHELL`、`CLAUDECODE_SHELL`
   - `GEMINI_CLI`、`GEMINI_CLI_SESSION`、`GEMINI_CLI_IDE_PID`
2. 注入 `COUNCILFLOW_DELEGATED_STAGE=1` + `COUNCILFLOW_DELEGATION_ID=<id>`；CLI 入口在 `cli/app.py` 最早期检测这两个，发现就拒绝 discuss/delegate/synthesize（status 可放行，便于调试）。
3. 在 `providers/base.py` 的 `subprocess.Popen` 调用里显式传 `env=_build_sandbox_env(...)`，不要继承 parent `os.environ`（否则剥离失败）。
4. 新增 `ProviderError.kind = "recursive_workflow_violation"` + `DelegationExecutionError.error_kind` 透传。

**复杂度 L 合理**。`acceptance_criteria` 四条覆盖"剥离 / 递归拦截 / 错误分类 / 测试"，完整。

---

### 4.5 TASK-045（todo, manual, M）— 合理 ✅

"在真实 Codex/Claude/Gemini 主控项目中验证 isolated sidecar workspace、合法变更导回与非递归 guard"。

- 与 TASK-041 同形，只是针对 sidecar 隔离。
- 建议 smoke 时同步跑一个"故意尝试 sidecar 递归"的 negative case：在 delegated prompt 里让模型回答"现在请执行 `council discuss ...`"，观察是否被 TASK-044 的 guard 拦下。
- 没有问题。

---

### 4.6 缺失的任务（建议补充）

1. **TASK-046 候选**：修复 §1.1（默认配置两套真值不一致）——把 `DEFAULT_ROLE_MODELS` 与 `default-config.yaml` 对齐到单一真源。S 复杂度。
2. **TASK-047 候选**：解决 §1.2（`advisor=gpt` 没有 adapter）——短期先改默认值，长期引入 `OpenAIChatAdapter`。S / L 两条路径。
3. **TASK-048 候选**：修复 §1.4（`--controller-position` 模式下 `min_rounds` 被压为 1）与 §2.2（error_kind 命名统一）。S 复杂度。
4. **TASK-049 候选**：引入 structured logging（§3.1）。M。
5. **TASK-050 候选**：Codex / Gemini 的流式 runtime 探针（§3.3），完成 PRD §25 的"统一 provider 运行抽象"。M。

上述五个是"架构已经达成共识、但没人写的尾巴"，建议把 1、2、3 挂在 TASK-042 之前（避免 isolation 阶段再被默认配置坑），4、5 可以放在 TASK-045 之后。

---

## 5. 风险与建议优先级

> 用 R0/R1/R2 表示建议处理时机。

| 等级 | 项目 | 位置 | 建议处理 |
|------|------|------|----------|
| 🔴 R0 | 默认配置两套真值 | §1.1 | 在动 TASK-042 前收口，避免 isolation 工作中踩到 role 默认值切换 |
| 🔴 R0 | `advisor=gpt` 无 adapter | §1.2 | 同上；最低工作量：改默认 |
| 🔴 R0 | tester 角色 preflight 被静默覆盖 | §2.1 | 小改动，可放在 TASK-041 smoke 后的修补 commit |
| 🟠 R1 | `--controller-position` 下 min_rounds 坍缩 | §1.4 | 与共享 skill 开发同步收口 |
| 🟠 R1 | error_kind 属性命名不统一 | §2.2 | 在 TASK-044 中顺带统一（反正那时要新加 `recursive_workflow_violation`） |
| 🟠 R1 | Gemini specific 版本 model 名泄漏 | §2.4 | 独立小 PR |
| 🟠 R1 | sidecar 隔离目前只是事后 restore | §1.3 | 已由 TASK-042/043 覆盖 |
| 🟠 R1 | Gemini YOLO 模式默认开启 | §1.7 | 与 §1.3 一起收口 |
| 🟠 R1 | verification_commands 仍允许 `&&` 拆分 | §2.5 | 加 DeprecationWarning，下版本删 |
| 🟢 R2 | Prompt/Summary 英文 header | §1.5 | 产品体验优化 |
| 🟢 R2 | Provider adapter 注册表 | §3.2 | 代码整洁 |
| 🟢 R2 | 引入 structured logging | §3.1 | 长期运维价值高 |
| 🟢 R2 | 原子写入 config/state | §3.5 | 加固项 |
| 🟢 R2 | 收敛判据过严 | §2.6 | 观察真实使用后决定 |
| 🟢 R2 | append_run_record 微秒冲突 | §2.9 | 非紧急 |
| 🟢 R2 | normalize_model_name 静默降级 | §1.6 | 与 §1.2 一起处理更自然 |

---

## 6. 结语

CouncilFlow 已经走到了"核心路径稳定、进入 isolation / recursion guard 加固"的阶段。本次审查未发现安全级别的严重缺陷，代码整体可读、测试覆盖较为全面，PRD → 架构 → 代码 → 测试的一致性保持得相当好。

**最需要优先处理的是两类"小但重要"的问题**：

1. **产品默认值不一致**（§1.1、§1.2）：这是下一阶段 sidecar isolation 工作之前最值得收口的技术债，因为它会让 `.council/config.yaml` 的语义模糊，直接影响 TASK-042 契约设计里对"哪些角色默认走 sidecar"的讨论。
2. **discuss 协议里 min_rounds 的语义塌陷**（§1.4）：这是产品承诺（PRD §23.4）与当前实现冲突的典型案例；修复代价很小但用户感受差异大。

后续 TASK-042/043/044/045 的设计在结构上是合理的，只是**TASK-042 的契约字段需要先定细**（见 §4.2 的字段清单），否则 TASK-043 会因为"契约没说清具体 materialize 策略"而不得不来回补丁。建议把 TASK-043 拆成 3 个可独立验证的子任务（见 §4.3）。

---

*本报告由代码审查 agent 于 2026-04-18 生成，基于本地 CouncilFlow 仓库的当前 main 分支快照。*
