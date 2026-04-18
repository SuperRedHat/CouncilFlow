# CouncilFlow 全量问题解决方案

- 审查日期：2026-04-18
- 本文件是 `docs/code-review-2026-04-18.md` 的配套方案文档，结构为：
  - **Part A**：三主控共享 skills + MCP 层的新审查发现
  - **Part B**：所有问题（代码层 + skills/MCP 层）的统一解决方案
  - **Part C**：实施顺序、依赖关系与验证计划

> 本次 skills/MCP 审查覆盖：
> - 共享源：`C:\Users\David Zhai\.workflow-core\skills\project-*`
> - 三端目标：`.codex\skills\`、`.claude\skills\`、`.gemini\skills\`
> - 同步/备份脚本：`.workflow-core\scripts\*.ps1`
> - MCP 注册：`.codex\config.toml`、`.gemini\settings.json`、`C:\Users\David Zhai\.claude.json`

---

# Part A：共享 Skills + MCP 层新发现

## A.1 🔴 `.bak` 文件污染了分发链

**现象**：
```text
.workflow-core/skills/project-next/
  ├── SKILL.md
  └── SKILL.md.bak        ← 不该出现在真源里
```
`.bak` 存在于共享源中的 7 个技能（project-init / plan / next / change / feedback / + 2 others），并通过 `sync-skills.ps1` 的 `Copy-Item -Recurse -Force` 整目录复制**同步到了三端所有目标目录**。

三个主控看到的目录形如：
```
.claude/skills/project-next/
  ├── SKILL.md
  └── SKILL.md.bak        ← 无意义噪音
```

**后果**：
- Claude Code / Codex / Gemini 都可能扫描 `.bak` 作为备选技能入口，取决于它们对 frontmatter 的容忍度。
- 即使 CLI 本身不识别 `.bak`，静态审计、文档生成、search 索引都会被污染。
- 用户无法从目录内容判断"这个技能正常版本是哪个"，会怀疑共享源存在分叉。

**严重度**：🔴 R0，直接破坏了 PRD §21（"`.workflow-core\skills\project-*` 继续作为三端共享真源"）。

---

## A.2 🔴 `sync-skills.ps1` 的"备份"逻辑是自毁型

`sync-skills.ps1:33-44` 的关键片段：
```powershell
if ($BackupEnabled -and (Test-Path $targetDir)) {
  $targetFile = Join-Path $targetDir 'SKILL.md'
  if (Test-Path $targetFile) {
    Copy-Item -LiteralPath $targetFile -Destination "$targetFile.bak" -Force   # ← 先备份到 target/SKILL.md.bak
  }
}

if (Test-Path $targetDir) {
  Remove-Item -LiteralPath $targetDir -Recurse -Force                           # ← 连同刚刚的 .bak 一起删掉
}

Copy-Item -LiteralPath $sourceDir -Destination $targetRoot -Recurse -Force     # ← 再把 source（含 .bak）全量复制进来
```

**问题**：
1. 先在 `$targetDir` 内创建 `SKILL.md.bak`，紧接着又 `Remove-Item -Recurse` 掉整个 `$targetDir`。刚创建的备份被自己删掉。
2. 用户 `-CreateBackup` 参数形同虚设；实际出现在目标里的 `.bak` 来自**源目录**的 `.bak`（参见 A.1），不是"对旧版目标做的备份"。
3. 如果真需要回滚，只能依赖 `backup-global-workflow.ps1` 的时间戳快照，而不能靠 `SKILL.md.bak`。

**严重度**：🔴 R0，这是"看起来安全、实际没做任何事"的伪安全机制，长期维护中一旦出错没有回退路径。

---

## A.3 🟠 `.codex\skills` 里存在 `{project-init,project-design,...}` 孤儿目录

**现象**：
```
.codex/skills/{project-init,project-design,project-plan,project-next,project-feedback,project-change,project-review,project-status,project-ask,project-resume}/
```
是一个**字面名称包含花括号和逗号**的单一目录，目录修改时间为 2026-03-13（远早于现有脚本时间），目录为空。

**根因**：某次在 PowerShell 里运行了 Bash 风格的 brace expansion（如 `mkdir {a,b,c}`），PowerShell 不会展开 `{…}`，而是把它当成字面名创建了一个目录。

**为什么一直清不掉**：`sync-skills.ps1:29` 只 iterate `$skillNames`（从源目录读出的合法名），然后 `Remove-Item -LiteralPath $targetDir -Recurse -Force` 只删已知名称下的目录；对这个花括号怪名，脚本从不触碰。

**后果**：
- Codex 扫描 `skills/` 时可能被这个空目录扰动；即便不扰动，它也是长期技术债。
- 它的存在说明**同步脚本没有 orphan 检测能力**，未来任何"技能改名 / 删除"都会在三端留下僵尸目录。

**严重度**：🟠 R1（单体而言低，但暴露了同步机制的系统性缺陷）。

---

## A.4 🔴 `project-next` 仍在用被 PRD §27.5 废弃的 `--input verification_commands` 传参

`project-next/SKILL.md:38`：
```bash
council delegate --role tester \
  --objective "验证当前任务实现" \
  --task-summary "执行 verification_commands / verification_profile" \
  --input verification_profile="<task.verification_profile>" \
  --input verification_commands="<joined verification commands>" \   # ← 问题在这
  ...
```

**问题**：
- PRD §27.5 明确："`verification_commands` 需要保持结构化，而不是在 workflow 中被拼接成单条 `&&` shell 字符串"。
- Python 侧 CLI 有 `--verification-command`（可重复的 list 参数），对应 `HandoffPackage.verification_commands: list[VerificationCommand]`。
- 这个 skill 却教主控把多条命令 join 成一条字符串用 `--input` 传，然后依赖 `handoff/packages.py::_coerce_verification_commands` 的 **legacy `&&` 拆分兜底**——正是代码审查 §2.5 建议要加 DeprecationWarning 并删掉的路径。
- 换句话说：**skill 教出来的用法和 PRD 反着来**，同时把产品最想淘汰的路径变成默认。

**严重度**：🔴 R0，skill 文案直接违反 PRD，且让 tester 阶段的"逐条命令 exit_code / stderr / blocked 状态"契约失效。

---

## A.5 🟠 MCP 服务器路径硬编码在至少 5 个位置

`C:/Users/David Zhai/.claude/mcp-project-manager/dist/index.js` 这个绝对路径同时出现在：

| 位置 | 作用 |
|------|------|
| `.codex\config.toml` | Codex mcp server 注册 |
| `.gemini\settings.json` | Gemini mcp server 注册 |
| `C:\Users\David Zhai\.claude.json`（per-project） | Claude Code mcp server 注册 |
| `install-global-workflow.ps1:12` | 装机脚本里的 `$projectManagerArgs` |
| `restore-global-workflow.ps1`（间接） | 通过 manifest 还原 |

**问题**：
1. 用户如果把 `mcp-project-manager` 挪到别处（比如拆到独立 repo），至少 3 个脚本 / 配置要同步改。
2. `install-global-workflow.ps1` 用硬编码覆盖三个 CLI 的注册，但没有**先校验脚本里的路径是否还存在**——一旦路径不存在，三端同时装错。
3. PRD §19.3 期望"MCP 安装优先通过官方 CLI 完成"，而实际上 Gemini 的注册是直接改 settings.json 的（install 脚本写 JSON），混合了两种策略。

**严重度**：🟠 R1，当前单机单用户尚可容忍，但换机 / 多机时极易翻车。

---

## A.6 🟠 Gemini 的 `trust: true` + YOLO + sidecar 非隔离三重叠加

`.gemini/settings.json`：
```json
"mcpServers": {
  "project-manager": {
    "command": "node",
    "args": [".../mcp-project-manager/dist/index.js"],
    "trust": true                ← Gemini 不会对该 MCP 再做 approval 提示
  }
}
```
`install-global-workflow.ps1:97`：
```powershell
$arguments = @('mcp', 'add', '-s', 'user', '--trust', 'project-manager', ...)   ← 装机就默认 --trust
```
`providers/gemini_cli.py:68`：
```python
return ["gemini", "--approval-mode", "yolo", ...]                               ← Gemini CLI 子进程也是 YOLO
```

再叠加代码审查 §1.3 指出的"sidecar 目前仍跑在主项目根目录"，这套组合让 Gemini 在任何 delegated stage 都具备"不 prompt、不隔离、可访问 MCP、可调用任意工具"的最大权限。

**风险**：
- Gemini 作为外部参与者时，理论上可以调用 `project-manager` MCP 改 PRD / 架构 / 任务状态。guardrail 只拦 `.claude/state` 和 `.council/state.json`，**不拦 `project-manager` MCP 调用**。
- `--approval-mode yolo` 放大了 Gemini 自主使用内置工具（search / file-read / shell）的可能性。

**严重度**：🟠 R1。在 TASK-042/043/044 隔离方案落地前，这条是"代价最低、收益最大"的加固面。

---

## A.7 🟢 部分 skill 的标题层级混乱

- `project-review/SKILL.md`：
  - "### 第二步：逐文件审查" 下**只有一行标题**，紧接着"### 多模型协作 (可选)"是平级 H3（作为第二步的兄弟节点而非子节点），然后"检查维度：..."一行属于谁读者没法判断。
- `project-change/SKILL.md`：
  - 在"3. 先进入 architect 阶段"编号列表项里，穿插了"### 多模型协作 (可选)"H3——**打断了有序列表的编号连续性**，Markdown 渲染后数字会重置为 1。
- `project-plan/SKILL.md`：
  - "## 第三步：任务清单"是 H2，但前面 "### 多模型协作 (可选)" 又是 H3。整个技能既有有序列表也有 H2/H3 混用，从顶部扫下来会觉得结构跳。

**严重度**：🟢 R2，不影响功能，但降低 skill 可读性，未来新协作者会误解结构。

---

## A.8 🟠 所有 skill 都说"停止 workflow 并报告失败"，但没定义"报告"的结构

每个技能末段都出现类似语句：
```text
如果 council delegate 返回错误、缺少 handoff/result artifact，或无法完成调用，
则停止当前 workflow 并报告失败
```

**问题**：
- 没有约定报告的最小字段（`workflow_id`? `failed_stage`? `error_kind`? `route_result`? `fallback_attempted`?）。
- 没有约定报告的载体（stdout Markdown? MCP `add_log`? 独立 JSON 文件?）。
- 于是三端主控各自发挥："codex 可能在 stdout 简述失败" / "claude 可能 add_log" / "gemini 可能只是中止" —— 同样的失败在三端得到不同的可观察产物。
- 真实 smoke（TASK-041 / TASK-045）想验证"过程正确"的时候，没有统一证据面可比对。

**严重度**：🟠 R1。对"不可静默绕过" PRD §24.3/§24.7 要求是短板。

---

## A.9 🟠 `sync-skills.ps1` 不清理 orphan skills

当源目录里**删除**某个 skill，脚本不会删三端的对应目录。它只会 iterate 源里"还存在的" skill 名做覆盖。被删掉的 skill 在三端继续保留僵尸版本，直到有人手动清理。

A.3 的花括号怪目录就是这条缺陷的具体后果之一。

**严重度**：🟠 R1。

---

## A.10 🟢 Claude Code 的 MCP 配置存在 per-project 重复，没有 user 级单一真源

`C:/Users/David Zhai/.claude.json` 是 Anthropic Claude Code 的 per-user 存储文件，里面对**每个打开过的项目**都写一份 `mcpServers`（本地文件里 `mcpServers` 出现 14 次，`.claude.json` 共 ~1000 行）。

- `install-global-workflow.ps1::Ensure-ClaudeProjectManager` 使用 `claude mcp add -s user` 明确注册到 user scope；但多数情况下 Claude Code 运行时读的是 project scope（当前 cwd 下的 `.claude.json`）。
- 结果：user scope 有一份 project-manager，每个项目 scope 也可能各存一份。长时间后，配置容易出现 user vs project 的不一致（例如 user scope 指向新路径，某个旧项目的 project scope 还指向老路径）。

**严重度**：🟢 R2（偏信息），但值得在集成文档里点明"Claude Code 的 MCP 真源是 per-project `.claude.json`"。

---

## A.11 🟢 `project-feedback` 没有描述 milestone gate 的分支行为

`project-feedback/SKILL.md` 只说了"通过 / 有问题"两条分支，但 PRD 的任务状态机里还有：

- `acceptance_mode = milestone_manual` + `stage_gate=true` 的正向通过需要额外记录"阶段收口说明"。
- 里程碑通过后，是否要求立即进入下一个阶段 gate？

skill 对此只有一句"`milestone_manual` 的通过反馈应额外记录阶段收口说明"，缺少具体行为与对应的 `project-manager` MCP 调用顺序（`update_task_status` → `add_log` → 是否需要 `create_tasks` 开新阶段？）。

**严重度**：🟢 R2。

---

## A.12 🟢 `project-init` / `project-plan` 在"项目目录未确定"时的路由文案模糊

`project-init/SKILL.md:35`：
> "如果项目目录还未确定，只允许继续做需求澄清；一旦目录确定，planner 阶段就重新受 route-first 约束"

- "项目目录还未确定"的判定方式没讲（是 MCP `get_project_info` 返回空？是某个环境变量？）。
- "只允许继续做需求澄清"和"进入 planner 阶段"的边界不清。
- 对新手主控容易退化成"永远先在本地澄清完才 route"的漏洞路径。

**严重度**：🟢 R2。

---

# Part B：所有问题的统一解决方案

> 编号规则：`B.x`，其中 `x` ≤ 22 对应代码审查文档问题，`x` ≥ 23 对应本轮新增。每个方案包含：根因、修复（含代码/配置片段）、边界、验证方式。

---

## B.1 🔴 修复默认配置双真源（对应 §1.1）

**根因**：`models/config.py::RoleMapping` 的字段 default 与 `templates/default-config.yaml` 各自一份默认值。

**方案**：把代码侧默认改为从模板派生。

```python
# src/councilflow/config/loader.py

from functools import lru_cache

@lru_cache(maxsize=1)
def _cached_default_payload() -> dict[str, Any]:
    raw = yaml.safe_load(load_default_config_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("default-config.yaml must deserialize to a mapping.")
    return raw

def default_role_mapping_payload() -> dict[str, str]:
    return dict(_cached_default_payload().get("roles", {}))
```

```python
# src/councilflow/models/config.py

from councilflow.config.loader import default_role_mapping_payload

class RoleMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 移除所有字段的 literal default，改为 model_validator
    planner: str
    architect: str
    implementer: str
    tester: str
    reviewer: str
    fixer: str
    advisor: str
    synthesizer: str

    @model_validator(mode="before")
    @classmethod
    def apply_defaults_from_template(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        template = default_role_mapping_payload()
        merged = {**template, **value}
        return merged
```

**新增测试**：
```python
# tests/test_config_defaults_consistency.py
def test_default_role_mapping_matches_template():
    from councilflow.models.config import RoleMapping
    from councilflow.config.loader import default_role_mapping_payload
    mapping = RoleMapping.model_validate({})
    for role, model in default_role_mapping_payload().items():
        assert getattr(mapping, role) == model
```

**边界**：
- 现有 `DEFAULT_ROLE_MODELS: dict[RoleName, str]` 字典保留一段时间作为"程序查询默认"的便捷 API，但内部也改为调用 `default_role_mapping_payload()`。
- `models/roles.py` 里原来的字典常量加 deprecation 注释：下版本删。

**验证**：`python -m pytest tests/test_config_defaults_consistency.py tests/test_config_loader.py`。

---

## B.2 🔴 `advisor=gpt` 没有 adapter（对应 §1.2）

**根因**：默认配置把 `advisor` 映射到 `gpt`，但 `get_provider_adapter` 只认识 `{codex, claude, gemini}`，且 `OpenAIChatAdapter` 从未实现。

**短期方案（R0，1 个 commit）**：
1. 修改 `templates/default-config.yaml` 和 `DEFAULT_ROLE_MODELS`：
   ```yaml
   # templates/default-config.yaml
   roles:
     ...
     advisor: gemini     # 或 claude，取用户偏好
     ...
   ```
2. 同步修 `models/roles.py::DEFAULT_ROLE_MODELS[RoleName.ADVISOR]` → `ControllerName.GEMINI.value`。
3. 增加 `normalize_model_name` 的主动拒绝逻辑：未知模型名（normalize 后不在 `{codex, claude, gemini}` 且无 alias 映射）在 `RoleMapping.normalize_models` 里 raise `ValueError`。

**长期方案（R1，独立任务）**：新增 `OpenAIChatAdapter` 覆盖 API 型 advisor。

```python
# src/councilflow/providers/openai_api.py  (新文件)

from __future__ import annotations
import os
from typing import Any

from councilflow.models.config import ProviderRuntimeSettings
from councilflow.providers.base import (
    ProviderError, ProviderRequest, ProviderResponse,
    default_runtime_settings,
)

class OpenAIChatAdapter:
    """API-only advisor adapter. Requires OPENAI_API_KEY in env."""
    model_name = "gpt"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        runtime: ProviderRuntimeSettings | None = None,
    ) -> None:
        self.model = model
        self.runtime = runtime or default_runtime_settings()

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        # 延迟 import 避免 openai 成为硬依赖
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(
                "openai SDK is not installed. Install with: pip install openai",
                kind="environment_not_ready",
            ) from exc

        client = OpenAI(timeout=self.runtime.total_timeout_seconds)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": request.prompt}],
            )
        except Exception as exc:
            raise ProviderError(str(exc), kind="process_exit") from exc

        content = response.choices[0].message.content or ""
        return ProviderResponse(
            model="gpt",
            content=content,
            metadata={"openai_model": self.model, "usage": response.usage.model_dump()},
        )
```

再在 `get_provider_adapter` 与 `get_participant` 里注册 `"gpt"`（参见 B.18 注册表方案）。

**验证**：`python -m pytest tests/test_provider_adapters.py -k "openai or gpt"`（需新增）。

---

## B.3 🔴 tester 角色 preflight 被静默覆盖（对应 §2.1）

**方案**：把"只在 caller 未传时才计算"的逻辑下放到 orchestrator。

```python
# src/councilflow/controller/delegation_orchestrator.py

# 原：
#   if role is RoleName.TESTER:
#       package.tester_preflight = _run_tester_preflight(...)
# 改为：
if role is RoleName.TESTER and package.tester_preflight.status in {"not_requested", "pending"}:
    package.tester_preflight = _run_tester_preflight(
        self.store.paths.project_root,
        target_model=target_model,
        verification_commands=package.verification_commands,
    )
```

**验证**：新增 test case：caller 传 `TesterPreflight(status="passed", permission_status="satisfied")`，orchestrator 不再覆盖。

---

## B.4 🟠 `--controller-position` 下 `min_rounds` 坍缩（对应 §1.4）

**方案**：
1. 移除"默认把 max_rounds 压到 1"的自动降级。
2. 如需保留"本地 initial position 时少跑几轮"的偏好，新增独立配置字段。

```python
# src/councilflow/cli/discuss.py

# 原：
#   effective_max_rounds = max_rounds or config.discussion.max_rounds
#   if normalized_controller_position is not None and max_rounds is None:
#       effective_max_rounds = 1
#   effective_min_rounds = min(config.discussion.min_rounds, effective_max_rounds)
# 改为：
effective_max_rounds = max_rounds or config.discussion.max_rounds
effective_min_rounds = min(config.discussion.min_rounds, effective_max_rounds)
```

3. 更新 `tests/test_cli_discuss.py:307-309`：
```python
# 原：assert payload["data"]["effective_max_rounds"] == 1
# 改：assert payload["data"]["effective_max_rounds"] == config.discussion.max_rounds
# 原：assert payload["data"]["effective_min_rounds"] == 1
# 改：assert payload["data"]["effective_min_rounds"] == config.discussion.min_rounds
```

**边界**：
- 若真的希望"local initial position 时只跑 1 轮"，在 `templates/default-config.yaml` 加一个独立字段：
  ```yaml
  discussion:
    min_rounds: 2
    max_rounds: 5
    max_rounds_when_local_initial_position: 3   # 新字段，默认沿用 max_rounds
  ```
- 但先不加字段，除非有真实场景要求。

**验证**：`python -m pytest tests/test_cli_discuss.py tests/test_discussion_orchestrator.py`。

---

## B.5 🟠 error_kind 命名不统一（对应 §2.2）

**方案**：统一用 `.kind`。

```python
# src/councilflow/controller/discussion_orchestrator.py

class UnavailableParticipantError(RuntimeError):
    def __init__(self, message: str, *, kind: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind                    # 取代 error_kind

    # 兼容期别名（下个版本删除）
    @property
    def error_kind(self) -> str | None:
        import warnings
        warnings.warn(
            "UnavailableParticipantError.error_kind is deprecated; use .kind",
            DeprecationWarning, stacklevel=2,
        )
        return self.kind
```

同步改所有 raise 点和 persistence：
- `cli/discuss.py:80`：`raise UnavailableParticipantError(str(exc), kind=exc.kind)`
- `controller/discussion_orchestrator.py:267`：`getattr(exc, "kind", None)`

**验证**：全仓 `grep -n error_kind` 确认只剩 DelegationRecord.error_kind（这是序列化字段名，不能改，保持）。

---

## B.6 🟠 Gemini specific 版本 model 名泄漏到 turns（对应 §2.4）

**方案**：
```python
# src/councilflow/providers/gemini_cli.py

class GeminiCliAdapter:
    def __init__(self, model: str | None = None, ...) -> None:
        self.model_name = "gemini"                         # 对外永远是 "gemini"
        self.gemini_variant = model or None                # 具体版本保留为私有字段
        ...

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        result = coerce_run_result(self.runner(self.command, request.prompt))
        metadata = dict(result.metadata)
        if self.gemini_variant:
            metadata["gemini_variant"] = self.gemini_variant
        return ProviderResponse(
            model=self.model_name,                         # 永远归一化为 "gemini"
            content=_strip_runtime_notices(result.content),
            metadata=metadata,
        )
```

**验证**：新增测试：`GeminiCliAdapter(model="gemini-1.5-flash").ask(...).model == "gemini"` 且 `metadata["gemini_variant"] == "gemini-1.5-flash"`。

---

## B.7 🟢 summary.md i18n 化（对应 §1.5）

**方案**：
```python
# src/councilflow/handoff/summaries.py

_SECTION_HEADERS = {
    "zh-CN": {
        "title": "讨论",
        "question": "问题",
        "controller": "主控",
        "participants": "参与者",
        "min_rounds": "最小轮次",
        "rounds_completed": "已完成轮次",
        "ended_reason": "结束原因",
        "initial_position": "初始立场",
        "current_position": "当前主控立场",
        "key_options": "关键选项",
        "agreements": "共识",
        "disagreements": "分歧",
        "recommended_decision": "推荐决策",
        "open_questions": "遗留问题",
        "next_step": "下一步",
    },
    "en": {  # 英文保留原有表述
        "title": "Discussion",
        ...
    },
}

def render_discussion_summary(summary: DiscussionSummary, language: str = "zh-CN") -> str:
    h = _SECTION_HEADERS.get(language, _SECTION_HEADERS["zh-CN"])
    sections = [
        f"# {h['title']} {summary.discussion_id}",
        ...
        f"## {h['initial_position']}",
        summary.initial_position or "- None",
        ...
    ]
    return "\n".join(sections)
```

然后 `DiscussionOrchestrator._persist_summary` 接收一个 `language` 参数，从 `self.config.output_language` 传入。

**验证**：新增测试：渲染 zh-CN summary，断言 "## 初始立场" 出现。

---

## B.8 🟢 `normalize_model_name` 静默降级（对应 §1.6）

**方案**：在 alias 表后增加前缀启发式，并在配置加载期对未识别名 raise。

```python
# src/councilflow/models/roles.py

_PROVIDER_FAMILY_PREFIXES = {
    "claude": ControllerName.CLAUDE.value,
    "gemini": ControllerName.GEMINI.value,
    "gpt":    "gpt",
    "o1":     "gpt",   # o1 系列归到 gpt adapter
    "codex":  ControllerName.CODEX.value,
}

def resolve_provider_family(model: str) -> str | None:
    """Given a normalized model name, return its provider family for runtime overrides."""
    normalized = normalize_model_name(model)
    if normalized in {"codex", "claude", "gemini", "gpt"}:
        return normalized
    for prefix, family in _PROVIDER_FAMILY_PREFIXES.items():
        if normalized.startswith(prefix + "-") or normalized == prefix:
            return family
    return None

def validate_model_name(value: str) -> str:
    normalized = normalize_model_name(value)
    if resolve_provider_family(normalized) is None:
        raise ValueError(
            f"Unknown model '{value}' (normalized='{normalized}'). "
            "Expected one of: codex, claude, gemini, gpt, or a known alias."
        )
    return normalized
```

然后 `RoleMapping.normalize_models`（`models/config.py:31`）改调 `validate_model_name`。`ProviderSettings.for_model` 改用 `resolve_provider_family(model)` 选 override。

**验证**：新增 test：`RoleMapping.model_validate({"planner": "clood"})` raises ValueError。

---

## B.9 🟠 sidecar 隔离主动化（对应 §1.3 与 TASK-042/043/044）

**方案**：按 TASK-042 细化契约字段，再落地 TASK-043、TASK-044。

### B.9.1 TASK-042 的契约字段（建议）

```python
# src/councilflow/models/delegation.py

class IsolatedWorkspace(BaseModel):
    """Sidecar workspace isolation contract."""

    strategy: Literal["copy", "git_worktree", "none"] = "git_worktree"
    include_patterns: list[str] = Field(default_factory=list)   # "src/**", "tests/**"
    exclude_patterns: list[str] = Field(default_factory=lambda: [
        "node_modules/**", "__pycache__/**", ".venv/**",
        ".council/**", ".claude/**", ".workflow-core/**",
    ])
    workspace_path: str | None = None      # 运行时填入：实际 materialized 路径

class ImportManifest(BaseModel):
    """Which changes sidecar is allowed to produce back into main workspace."""

    writable_globs: list[str] = Field(default_factory=list)     # "src/**", "tests/**"
    readonly_artifact_paths: list[str] = Field(default_factory=list)  # 参考文件：PRD / 架构
    max_file_count: int = 200
    max_total_bytes: int = 10 * 1024 * 1024    # 10 MB 上限

class ExecutionGuardrails(BaseModel):
    writable_paths: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(default_factory=lambda: [
        ".claude/state", ".council/state.json",
        ".workflow-core", ".claude/skills", ".codex/skills", ".gemini/skills",
    ])
    allow_commit: bool = False
    allow_workflow_state_write: bool = False
    # 新增：
    isolated_workspace: IsolatedWorkspace = Field(default_factory=IsolatedWorkspace)
    import_manifest: ImportManifest = Field(default_factory=ImportManifest)

class DelegationResult(BaseModel):
    ...
    # 新增：
    workspace_manifest: list["WorkspaceFileChange"] = Field(default_factory=list)
    import_outcome: Literal["none", "applied", "partial", "rejected"] = "none"
    import_rejected_reason: str | None = None

class WorkspaceFileChange(BaseModel):
    path: str
    change_type: Literal["added", "modified", "deleted"]
    byte_size: int
    imported: bool
    rejection_reason: str | None = None
```

### B.9.2 TASK-043 实现（高层伪代码）

```python
# src/councilflow/controller/delegation_orchestrator.py

def _materialize_workspace(self, package: HandoffPackage) -> Path:
    strategy = package.execution_guardrails.isolated_workspace.strategy
    if strategy == "none":
        return self.store.paths.project_root

    workspace_root = self.store.paths.council_root / "workspaces" / package.id
    if strategy == "git_worktree":
        # git worktree add <workspace_root> HEAD
        subprocess.run(
            ["git", "-C", str(self.store.paths.project_root),
             "worktree", "add", str(workspace_root), "HEAD"],
            check=True, capture_output=True,
        )
    elif strategy == "copy":
        # shutil.copytree with ignore patterns
        ...
    return workspace_root

def _import_changes(self, workspace_root: Path, package: HandoffPackage) -> list[WorkspaceFileChange]:
    # 扫描 workspace_root 下相对变化
    # 对每个变化：
    #   1. 比对 import_manifest.writable_globs → 允许？
    #   2. 比对 execution_guardrails.protected_paths → 拒绝
    #   3. 累积 total_bytes 与 file_count 上限检查
    # 导回主工作区
    ...
```

### B.9.3 TASK-044 非递归 guard

```python
# src/councilflow/providers/base.py

_CONTROLLER_ENV_KEYS = (
    "CODEX_SHELL", "CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    "CLAUDECODE", "CLAUDE_CODE", "CLAUDE_CODE_SHELL", "CLAUDE_SHELL", "CLAUDECODE_SHELL",
    "GEMINI_CLI", "GEMINI_CLI_SESSION", "GEMINI_CLI_IDE_PID",
)

def build_sandboxed_env(delegation_id: str) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items()
        if k not in _CONTROLLER_ENV_KEYS
    }
    env["COUNCILFLOW_DELEGATED_STAGE"] = "1"
    env["COUNCILFLOW_DELEGATION_ID"] = delegation_id
    return env
```

```python
# src/councilflow/cli/app.py

def root() -> None:
    """..."""
    if os.environ.get("COUNCILFLOW_DELEGATED_STAGE") == "1":
        # 只允许 version / status；其他命令拒绝
        invoked = sys.argv[1] if len(sys.argv) > 1 else ""
        if invoked not in {"version", "status", "--help", "-h"}:
            typer.echo(json.dumps({
                "data": None,
                "error": {
                    "message": "CouncilFlow refuses to run nested inside a delegated sidecar.",
                    "error_kind": "recursive_workflow_violation",
                    "delegation_id": os.environ.get("COUNCILFLOW_DELEGATION_ID"),
                },
            }))
            raise typer.Exit(code=2)
```

**TASK-043 拆分建议**：如代码审查 §4.3 所述，拆为：
- TASK-043a：materialize + prompt 注入（sidecar 知道 cwd 在 worktree）
- TASK-043b：result manifest + 正向 writable_globs 检查
- TASK-043c：合法变更导回（含冲突处理）

**验证**：
- `pytest tests/test_delegation_orchestrator.py::test_isolated_workspace_strategy_git_worktree`
- `pytest tests/test_cli_delegate.py::test_recursive_council_call_is_blocked`

---

## B.10 🟠 Gemini YOLO 默认关闭（对应 §1.7）

**方案**：
```python
# src/councilflow/providers/gemini_cli.py

class GeminiCliAdapter:
    def __init__(
        self,
        model: str | None = None,
        approval_mode: Literal["default", "auto_edit", "yolo"] = "default",
        ...
    ) -> None:
        self.approval_mode = approval_mode
        ...

def _default_gemini_command(approval_mode: str = "default") -> list[str]:
    resolved = shutil.which("gemini")
    base_args = ["--approval-mode", approval_mode, "--output-format", "text", "-p"]
    if resolved is None:
        return ["gemini", *base_args]
    ...
```

```python
# src/councilflow/models/config.py

class ProviderRuntimeOverrides(BaseModel):
    total_timeout_seconds: float | None = Field(default=None, gt=0)
    idle_timeout_seconds: float | None = Field(default=None, gt=0)
    # 新增：
    approval_mode: Literal["default", "auto_edit", "yolo"] | None = None
```

然后 `cli/delegate.py::get_provider_adapter` 读 `config.providers.gemini.approval_mode`（若有），传给 `GeminiCliAdapter`。

**默认模板**：
```yaml
# templates/default-config.yaml
providers:
  default:
    total_timeout_seconds: 900
    idle_timeout_seconds: null
  claude:
    idle_timeout_seconds: 180
  gemini:
    approval_mode: default     # 不再默认 YOLO
```

**边界**：若 Gemini 真的需要自主改文件（等 TASK-043 worktree 方案落地），再在隔离工作区里临时放 YOLO。

**验证**：`pytest tests/test_provider_adapters.py::test_gemini_default_approval_mode`。

---

## B.11 🟠 verification_commands `&&` legacy 解析加 DeprecationWarning（对应 §2.5）

**方案**：
```python
# src/councilflow/handoff/packages.py

import warnings

def _coerce_verification_commands(
    verification_commands: list[VerificationCommand] | list[str] | None,
    inputs: dict[str, str],
) -> list[VerificationCommand]:
    if verification_commands:
        ...  # 保持

    raw = inputs.get("verification_commands", "").strip()
    if not raw:
        return []

    warnings.warn(
        "Passing verification_commands as a joined string in inputs is deprecated. "
        "Use the structured --verification-command CLI flag (repeatable) instead.",
        DeprecationWarning, stacklevel=3,
    )
    ...  # 现有拆分逻辑保留一个版本
```

下一版本（0.2）直接删 legacy 分支。

---

## B.12 🟢 收敛判据放宽（对应 §2.6）

**方案**：
```python
# src/councilflow/controller/discussion_orchestrator.py

def _round_has_converged(responses: list[ParticipantResponse]) -> bool:
    return all(
        response.supports_current_direction and not response.has_new_information
        for response in responses
    )
    # 移除对 disagreements 与 open_questions 的检查——
    # 它们作为质量信号会保留在 summary.md 里，但不再阻止提前收敛。
```

**验证**：现有 `tests/test_discussion_orchestrator.py::test_converges_when_all_support` 可能需要新增/调整断言。

---

## B.13 🟢 default-config.yaml 用 list 语法（对应 §2.7）

**方案**：
```yaml
# src/councilflow/templates/default-config.yaml
discussion:
  default_models:
    - codex            # YAML list 形式，更符合 Python 端类型
  min_rounds: 2
  max_rounds: 5
```

`DiscussionSettings.normalize_default_models` 保留字符串兼容（有用户已经这么写）。

---

## B.14 🟢 `run_monitored_process` wait 加守卫（对应 §2.8）

```python
# src/councilflow/providers/base.py

try:
    returncode = process.wait(timeout=1)
except subprocess.TimeoutExpired:
    _terminate_process(process)
    try:
        returncode = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        returncode = -1
```

---

## B.15 🟢 `append_run_record` 防冲突（对应 §2.9）

```python
# src/councilflow/state/store.py

def append_run_record(self, kind: str, payload: Mapping[str, Any]) -> Path:
    ensure_council_paths(self.paths)
    record = {...}
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")
    base_name = f"{stamp}-{kind}"
    record_path = self.paths.runs / f"{base_name}.json"
    counter = 1
    while record_path.exists():
        record_path = self.paths.runs / f"{base_name}-{counter}.json"
        counter += 1
    self._write_json(record_path, record)
    return record_path
```

---

## B.16 🟢 `_strip_runtime_notices` 改正则（对应 §2.10）

```python
# src/councilflow/providers/gemini_cli.py

import re

_RUNTIME_NOTICE_PATTERNS = (
    re.compile(r"^YOLO mode is enabled\.$"),
    re.compile(r"^Attempt \d+ of \d+.*$"),       # 只匹配真正的重试提示
)

def _strip_runtime_notices(content: str) -> str:
    cleaned = [
        line for line in content.splitlines()
        if not any(p.match(line) for p in _RUNTIME_NOTICE_PATTERNS)
    ]
    return "\n".join(cleaned).strip()
```

---

## B.17 🟢 inputs 污染（对应 §2.11）

**方案**：`HandoffPackage` 新增 `controller_context` 字段：

```python
# src/councilflow/models/delegation.py

class ControllerContextInfo(BaseModel):
    controller: str
    configured_language: str

class HandoffPackage(BaseModel):
    ...
    controller_context: ControllerContextInfo | None = None
    inputs: dict[str, str] = Field(default_factory=dict)        # 纯用户 inputs
```

`cli/delegate.py` 改为：
```python
result = orchestrator.run(
    ...,
    inputs=structured_inputs,                                    # 不再混进 controller
    controller_context=ControllerContextInfo(
        controller=controller,
        configured_language=config.output_language,
    ),
)
```

---

## B.18 🟠 adapter factory 改注册表（对应 §3.2）

```python
# src/councilflow/providers/registry.py   (新文件)

from collections.abc import Callable
from councilflow.models.config import ProviderRuntimeSettings
from councilflow.providers.base import ProviderAdapter
from councilflow.providers.codex_cli import CodexCliAdapter
from councilflow.providers.claude_code_cli import ClaudeCodeCliAdapter
from councilflow.providers.gemini_cli import GeminiCliAdapter

AdapterFactory = Callable[[str, ProviderRuntimeSettings | None], ProviderAdapter]

def _make_codex(model: str, runtime):
    return CodexCliAdapter(runtime=runtime)

def _make_claude(model: str, runtime):
    return ClaudeCodeCliAdapter(runtime=runtime)

def _make_gemini(model: str, runtime):
    variant = model if model.startswith("gemini-") and model != "gemini-cli" else None
    return GeminiCliAdapter(model=variant, runtime=runtime)

REGISTRY: dict[str, AdapterFactory] = {
    "codex": _make_codex,
    "claude": _make_claude,
    "gemini": _make_gemini,
    # "gpt": _make_openai,                                      # 接 B.2 后启用
}

def resolve_adapter(model: str, runtime=None) -> ProviderAdapter:
    from councilflow.models.roles import resolve_provider_family
    family = resolve_provider_family(model)
    factory = REGISTRY.get(family)
    if factory is None:
        from councilflow.providers.base import ProviderError
        raise ProviderError(
            f"No provider adapter registered for model '{model}' (family={family!r}).",
            kind="adapter_missing",                              # 配合 §2.3
        )
    return factory(model, runtime)
```

`cli/delegate.py::get_provider_adapter` 和 `cli/discuss.py::get_participant` 都改调 `resolve_adapter`。

---

## B.19 🟠 引入 structured logging（对应 §3.1）

```python
# src/councilflow/utils/logging.py   (新文件)

import logging
import os
import sys

def configure_logging() -> None:
    level = logging.DEBUG if os.environ.get("COUNCILFLOW_DEBUG") == "1" else logging.WARNING
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root = logging.getLogger("councilflow")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
```

在 `cli/app.py::main()` 最早调用 `configure_logging()`。然后在 orchestrator、providers、guardrail 点分别 `logger.info(...)`、`logger.debug(...)`。

**关键点**：
- `DelegationOrchestrator.run` 进入 / 退出 / guardrail 触发
- `_run_tester_preflight` 记录每条命令的 availability
- `run_monitored_process` 每 10s 打一次"仍在等待活动信号，已耗 Ns"
- 绝不打 prompt 内容（防信息泄露），只打耗时和字符数

---

## B.20 🟢 Codex / Gemini 流式 runtime 探针（对应 §3.3）

**方案**：作为 TASK-050 新任务独立完成。探针逻辑：
```python
def probe_codex_json_support() -> bool:
    result = subprocess.run(
        ["codex", "--help"], capture_output=True, text=True, timeout=5,
    )
    return "--json" in result.stdout

def probe_gemini_stream_json_support() -> bool:
    result = subprocess.run(
        ["gemini", "--help"], capture_output=True, text=True, timeout=5,
    )
    return "stream-json" in result.stdout
```

启动时缓存结果到 `.council/runtime/providers.json`，根据探针自动切换执行路径。

---

## B.21 🟢 原子写入 config/state（对应 §3.5）

```python
# src/councilflow/state/store.py

import os

def _atomic_write_text(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
```

所有 `path.write_text(...)` 和 `_write_json` 统一改用 `_atomic_write_text`。同样修 `config/loader.py::dump_config`。

---

## B.22 🟢 `_infer_fixer_input_sources` 白名单（对应 §3.6）

```python
# src/councilflow/handoff/packages.py

_KNOWN_STAGES = {"tester", "reviewer", "implementer", "fixer", "planner", "architect", "synthesizer", "advisor"}

def _infer_fixer_input_sources(required_artifacts: dict[str, str]) -> list[FixerInputSource]:
    sources: list[FixerInputSource] = []
    for label, artifact_path in required_artifacts.items():
        prefix = label.split("_", 1)[0] if "_" in label else ""
        source_stage = prefix if prefix in _KNOWN_STAGES else "upstream"
        sources.append(FixerInputSource(
            label=label, source_stage=source_stage, artifact_path=artifact_path,
        ))
    return sources
```

---

## B.23 🔴 清除共享源里的 `.bak` 文件（对应 A.1）

**执行命令（一次性）**：
```powershell
Get-ChildItem -Path "C:\Users\David Zhai\.workflow-core\skills\" -Recurse -Filter "*.bak" |
    ForEach-Object {
        Write-Output "Removing: $($_.FullName)"
        Remove-Item -LiteralPath $_.FullName -Force
    }
```

然后重跑 `sync-skills.ps1`（见 B.24 修复后的版本）即可把三端的 `.bak` 也清掉。

---

## B.24 🔴 修 `sync-skills.ps1` 的"假备份"逻辑 + `-Exclude *.bak`（对应 A.2）

**新版本 sync-skills.ps1**：
```powershell
param(
  [switch]$CreateBackup = $true
)

$ErrorActionPreference = 'Stop'

$coreRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $coreRoot 'skills'
$claudeCommandRoot = 'C:\Users\David Zhai\.claude\commands'
$targets = @(
  'C:\Users\David Zhai\.codex\skills',
  'C:\Users\David Zhai\.claude\skills',
  'C:\Users\David Zhai\.gemini\skills'
)

# 从共享源读取技能名，过滤掉非 project-* 的误放置目录
$skillNames = Get-ChildItem -Path $sourceRoot -Directory |
  Where-Object { $_.Name -match '^project-[a-z-]+$' } |
  Select-Object -ExpandProperty Name

function Copy-SkillWithoutBak {
  param([string]$SourceDir, [string]$TargetDir)

  # 不要用 Copy-Item -Recurse（会带 .bak），改为 robocopy / 手动 walk
  New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
  Get-ChildItem -Path $SourceDir -Recurse -File |
    Where-Object { $_.Extension -ne '.bak' -and $_.Name -notlike '*.bak' } |
    ForEach-Object {
      $relative = $_.FullName.Substring($SourceDir.Length).TrimStart('\', '/')
      $destination = Join-Path $TargetDir $relative
      $destinationDir = Split-Path -Parent $destination
      New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }
}

function Sync-SharedSkillTargets {
  param(
    [string[]]$ManagedSkillNames,
    [string]$SharedRoot,
    [string[]]$TargetRoots
  )

  foreach ($targetRoot in $TargetRoots) {
    if (-not (Test-Path $targetRoot)) {
      New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
    }

    # 先清理 orphan：目标里但源里不存在的 project-* 技能
    Get-ChildItem -Path $targetRoot -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match '^project-' -and ($ManagedSkillNames -notcontains $_.Name) } |
      ForEach-Object {
        Write-Warning "Removing orphan skill dir: $($_.FullName)"
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
      }

    # 清理异常名目录（如 '{project-...}' 这种 brace expansion 残留）
    Get-ChildItem -Path $targetRoot -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match '[\{\}\,]' } |
      ForEach-Object {
        Write-Warning "Removing malformed dir: $($_.FullName)"
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
      }

    # 同步合法技能
    foreach ($skillName in $ManagedSkillNames) {
      $sourceDir = Join-Path $SharedRoot $skillName
      $targetDir = Join-Path $targetRoot $skillName

      if (Test-Path $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
      }
      Copy-SkillWithoutBak -SourceDir $sourceDir -TargetDir $targetDir
    }

    # 校验：SHA256 比对
    foreach ($skillName in $ManagedSkillNames) {
      $sourceFile = Join-Path (Join-Path $SharedRoot $skillName) 'SKILL.md'
      $targetFile = Join-Path (Join-Path $targetRoot $skillName) 'SKILL.md'
      if ((Test-Path $sourceFile) -and (Test-Path $targetFile)) {
        $src = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
        $tgt = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash
        if ($src -ne $tgt) {
          throw "Hash mismatch for $skillName in $targetRoot (source=$src, target=$tgt)"
        }
      }
    }
  }
}

function Remove-ClaudeLegacyCommandWrappers {
  param([string[]]$ManagedSkillNames, [string]$CommandRoot)
  if (-not (Test-Path $CommandRoot)) { return }
  foreach ($skillName in $ManagedSkillNames) {
    $wrapperPath = Join-Path $CommandRoot ($skillName + '.md')
    if (Test-Path $wrapperPath) { Remove-Item -LiteralPath $wrapperPath -Force }
  }
}

if ($skillNames.Count -eq 0) {
  throw "No project-* skills found in $sourceRoot. Aborting sync."
}

Write-Output "Syncing $($skillNames.Count) skills to $($targets.Count) targets..."
Sync-SharedSkillTargets -ManagedSkillNames $skillNames -SharedRoot $sourceRoot -TargetRoots $targets
Remove-ClaudeLegacyCommandWrappers -ManagedSkillNames $skillNames -CommandRoot $claudeCommandRoot
Write-Output "Shared workflow skills synchronized to Codex, Claude, and Gemini."
```

**要点**：
1. 过滤 `project-*` 白名单：源里不小心放的其他目录不会被同步。
2. 不再 `Copy-Item -Recurse`，改为 file-by-file + 过滤 `.bak`。
3. 同步前**主动清理 orphan**（A.9）和**malformed 目录**（A.3）。
4. 同步后做 SHA256 校验，不一致直接 throw。
5. 移除那条自毁型的 `-CreateBackup` 逻辑（真正的备份由 `backup-global-workflow.ps1` 负责）。

---

## B.25 🟠 清除 `{project-init,...}` 孤儿目录（对应 A.3）

一次性：
```powershell
Remove-Item -LiteralPath 'C:\Users\David Zhai\.codex\skills\{project-init,project-design,project-plan,project-next,project-feedback,project-change,project-review,project-status,project-ask,project-resume}' -Recurse -Force
```
长期：依赖 B.24 的"malformed 目录清理"分支自动处理。

---

## B.26 🔴 `project-next` 改用 `--verification-command` list（对应 A.4）

**修改 `.workflow-core/skills/project-next/SKILL.md` 第 38 行附近**：

原（错的）：
```bash
council delegate --role tester \
  --objective "验证当前任务实现" \
  --task-summary "执行 verification_commands / verification_profile" \
  --input verification_profile="<task.verification_profile>" \
  --input verification_commands="<joined verification commands>" \
  --required-artifact implementer_result="<...>" \
  --next-on-success "若验证通过，进入 reviewer 阶段" \
  --next-on-failure "若验证失败，进入 fixer 阶段"
```

改为：
```bash
council delegate --role tester \
  --objective "验证当前任务实现" \
  --task-summary "执行 verification_commands / verification_profile" \
  --input verification_profile="<task.verification_profile>" \
  --verification-command "<cmd1>" \
  --verification-command "<cmd2>" \
  --verification-command "<cmd3>" \
  --required-artifact implementer_result="<...>" \
  --next-on-success "若验证通过，进入 reviewer 阶段" \
  --next-on-failure "若验证失败，进入 fixer 阶段"
```

并在注意事项里明确：
> "**禁止**把多条 verification_commands 用 `&&` 或换行拼成单条字符串传给 `--input verification_commands`。这是 PRD §27.5 已废弃的 legacy 路径，CouncilFlow 会在下版本删除。"

修改后运行 `sync-skills.ps1` 把新版本同步到三端。

---

## B.27 🟠 抽出 MCP 路径到单一配置（对应 A.5）

**方案**：在 `.workflow-core` 引入 `mcp-manifest.json`：

```json
// C:\Users\David Zhai\.workflow-core\mcp-manifest.json
{
  "version": 1,
  "servers": {
    "project-manager": {
      "command": "node",
      "args_template": ["${MCP_HOME}/mcp-project-manager/dist/index.js"],
      "env": {
        "MCP_HOME": "C:/Users/David Zhai/.claude"
      },
      "trust": {
        "codex": false,
        "claude": false,
        "gemini": true
      }
    }
  }
}
```

然后让 `install-global-workflow.ps1` 从 manifest 读取、生成三端配置：

```powershell
$manifest = Get-Content -Path (Join-Path $coreRoot 'mcp-manifest.json') -Raw | ConvertFrom-Json
foreach ($serverName in $manifest.servers.PSObject.Properties.Name) {
  $server = $manifest.servers.$serverName
  $expandedArgs = @()
  foreach ($arg in $server.args_template) {
    $expanded = $arg
    foreach ($envKey in $server.env.PSObject.Properties.Name) {
      $expanded = $expanded.Replace("`${$envKey}", $server.env.$envKey)
    }
    $expandedArgs += $expanded
  }
  # 然后注册到三端
  ...
}
```

**优点**：换机 / 换路径只改 manifest 一处。

---

## B.28（已并入 B.10）

---

## B.29 🟢 skill 标题层级梳理（对应 A.7）

- `project-review/SKILL.md`：把"多模型协作（可选）"从 H3 降级为 H4（`#### 多模型协作 (可选)`），作为"第二步：逐文件审查"的子章节。
- `project-change/SKILL.md`：把"多模型协作（可选）"移出编号列表（放到编号 3 全部讲完后作为独立 `#### 多模型协作 (可选)`子章节）。
- `project-plan/SKILL.md`：把"## 第三步：任务清单"改为 `### 第三步：任务清单`，保持与第一步 / 第二步同级。

---

## B.30 🟠 skill 失败上报统一协议（对应 A.8）

**新增到 `docs/integration.md`**：

```markdown
## 工作流失败上报协议

当任何 `role-driven` 或 `discussion` 步骤因路由错误 / artifact 缺失 / sidecar 失活等原因必须停止时，
主控必须在停止前执行以下三件事：

1. **emit 结构化输出到 stdout**（JSON，一行）：
   ```json
   {
     "workflow": "project-next",
     "workflow_failed": true,
     "failed_stage": "tester",
     "error_kind": "idle_timeout",
     "council_available": true,
     "artifact_paths": { "handoff": ".council/delegations/del_xxx/handoff.yaml" },
     "fallback_attempted": false,
     "message": "council delegate --role tester returned idle_timeout after 180s"
   }
   ```

2. **调用 `project-manager` MCP 的 `add_log`**：
   ```
   type: workflow_failure
   task_id: <current task id if any>
   message: <same as above message>
   ```

3. **不要** `update_task_status(done)` 或 `update_task_status(auto_verified)`。任务保持 `in_progress`。

失败的 `council` 可用性分类（`council_available` 字段）：
- `true` + `error_kind != none`：council 可用但调用失败 → workflow 停止
- `false`：council 不可调用（`shutil.which("council") is None` 或 `council version` 非零退出）→ 允许明确降级
```

然后在每个 skill 的"注意事项"末尾添加一句：
```markdown
- 失败时必须按 `docs/integration.md::工作流失败上报协议` 输出 JSON + `add_log`，再停止 workflow。
```

---

## B.31 🟢 `project-feedback` milestone gate 文案补齐（对应 A.11）

在 `project-feedback/SKILL.md` 第 2 步"用户反馈通过"分支补充：

```markdown
2. 如果用户反馈通过：
   - 调用 `update_task_status(id, "done")`
   - 调用 `add_log`
   - 如果任务 `acceptance_mode == "milestone_manual"` 且 `stage_gate == true`：
     - 在 log 中额外记录 `stage_gate_closed: true` 和本阶段摘要
     - 检查当前阶段内还有无未完成任务；若有，暂不关阶段 gate
     - 若本阶段所有任务都已 done，则把阶段状态标记为 closed（`update_project_info({"current_stage_gate_closed": true})`）
     - 如用户要求立即进入下一阶段，引导到 `$project-next`
   - 提交验收 commit
```

---

## B.32 🟢 `project-init` / `project-plan` 项目目录未确定时的路由文案（对应 A.12）

在 `project-init/SKILL.md` 第 4 步附近补：

```markdown
4. 先进入 `planner` 阶段。
   - **如何判断"项目目录已确定"**：
     - MCP `get_project_info` 返回的 `project_dir` 非空且指向一个实存的目录，视为已确定。
     - 或用户已显式在对话里给出目录路径。
     - 仅当 `set_project_dir` 从未被调用过，且对话中也没有可推断的路径时，才算"未确定"。
   - **项目目录未确定时的行为**：
     - 只允许继续做需求澄清（提问、记录用户答复），**不得开始 PRD 草案撰写**。
     - 主控不得擅自选择一个默认目录去创建 `.council/`。
     - 一旦目录确定（用户确认 / `set_project_dir` 被调用），planner 阶段立即受 route-first 约束，必须 `council delegate --role planner`。
   - ...
```

---

## B.33 🟢 Claude MCP per-project 语义文档化（对应 A.10）

在 `docs/integration.md` 新增一节：

```markdown
## Claude Code MCP 配置

与 Codex / Gemini 不同，Claude Code 的 MCP 注册信息存在 `C:/Users/David Zhai/.claude.json` 这一个文件里，
按 **project scope** 组织，每个曾经打开过的项目都会有自己的 `mcpServers` 块。

用 `claude mcp add -s user` 注册的 user-scope server 是 fallback：
- 进入某个具体项目时，Claude 优先使用该 project 的 `mcpServers`；
- project 未覆盖的 server 才退回 user-scope。

因此，如果 `project-manager` 的路径或 args 需要变更，以下位置都要同步：
- `.codex/config.toml`
- `.gemini/settings.json`
- `.claude.json` 的 user-scope `mcpServers.project-manager`
- `.claude.json` 的**每个 project 块**（如果曾经被 per-project 注册过）

推荐做法：使用 `.workflow-core/mcp-manifest.json`（见 B.27）+ `install-global-workflow.ps1` 重建三端注册，
而不是手工改 `.claude.json`。
```

---

## B.34 🟢 建议新增的任务清单

根据代码审查 §4.6 和本文件 Part A 的发现，建议把以下任务加入 `tasks.json`：

| 建议任务 ID | 标题 | 复杂度 | 依赖 | 对应方案 |
|-------------|------|--------|------|----------|
| TASK-046 | 统一 default-config.yaml 与 DEFAULT_ROLE_MODELS 默认值 | S | — | B.1 |
| TASK-047 | 修复 advisor=gpt 无 adapter 的默认路径 | S | — | B.2（短期） |
| TASK-048 | 修 min_rounds 坍缩 + error_kind 命名统一 + gemini 版本名泄漏 | S | — | B.4 / B.5 / B.6 |
| TASK-049 | 清理共享 skills `.bak` + sync-skills.ps1 重构 + project-next 改 list 参数 | M | — | B.23 / B.24 / B.26 |
| TASK-050 | MCP manifest 抽离 + 三端注册重构 | M | — | B.27 |
| TASK-051 | 引入 structured logging | M | — | B.19 |
| TASK-052 | Codex / Gemini 流式 runtime 探针 + 切换 | L | TASK-044 | B.20 |
| TASK-053 | skill 失败上报协议统一 | S | — | B.30 |
| TASK-054 | skill 结构梳理 + milestone gate / 项目目录未确定的文案补齐 | S | — | B.29 / B.31 / B.32 |
| TASK-055 | （可选）OpenAIChatAdapter 实现，启用 `gpt` advisor | L | TASK-047 | B.2（长期） |

---

# Part C：实施顺序与验证计划

## C.1 分阶段推进建议

下面按"影响面最小 → 最大"、"风险最低 → 最高"排序。同阶段内可并行。

### Phase 0（一次性清理，< 30 分钟）
目标：把共享 skills 层的污染和孤儿彻底清掉。

| 步骤 | 操作 | 对应方案 |
|------|------|----------|
| 0.1 | `Remove *.bak` under `.workflow-core/skills/` | B.23 |
| 0.2 | `Remove {project-init,...}` under `.codex/skills/` | B.25 |
| 0.3 | 用新版 `sync-skills.ps1` 覆盖旧版 | B.24 |
| 0.4 | 跑一次 `sync-skills.ps1`，预期 SHA256 校验全绿，三端无 `.bak` | — |

### Phase 1（R0 产品缺陷修复，1-2 个 commit）
目标：消除"默认配置就会翻车"的场景。

| 步骤 | 对应方案 | 新增测试 |
|------|----------|----------|
| 1.1 | 默认配置双真源统一 | B.1 |
| 1.2 | advisor=gpt 默认改值 + normalize 拒绝未知 | B.2（短期） |
| 1.3 | tester preflight 不再覆盖 caller | B.3 |
| 1.4 | min_rounds 坍缩修复 + 测试断言修正 | B.4 |
| 1.5 | project-next 改 `--verification-command` list | B.26 |

### Phase 2（命名 / 协议统一，2-3 个 commit）
目标：把"看得见的接口"先收齐，便于后续加 logging / registry。

| 步骤 | 对应方案 |
|------|----------|
| 2.1 | error_kind → kind 统一 | B.5 |
| 2.2 | Gemini 版本名泄漏 | B.6 |
| 2.3 | adapter factory 改注册表 | B.18 |
| 2.4 | normalize + validate_model_name | B.8 |
| 2.5 | inputs 污染修复 | B.17 |
| 2.6 | verification_commands legacy 加 DeprecationWarning | B.11 |
| 2.7 | skill 标题层级梳理 + milestone / 项目目录文案 | B.29 / B.31 / B.32 |
| 2.8 | skill 失败上报协议 | B.30 |

### Phase 3（运维 / 安全加固，3-5 个 commit）
目标：长期运行稳定性与可观察性。

| 步骤 | 对应方案 |
|------|----------|
| 3.1 | structured logging | B.19 |
| 3.2 | Gemini YOLO 默认关闭 + config 可调 | B.10 |
| 3.3 | 原子写入 config/state | B.21 |
| 3.4 | `_strip_runtime_notices` 改正则 | B.16 |
| 3.5 | append_run_record 防冲突 | B.15 |
| 3.6 | `_infer_fixer_input_sources` 白名单 | B.22 |
| 3.7 | `run_monitored_process` wait 加守卫 | B.14 |
| 3.8 | MCP 路径 manifest 抽离 | B.27 |
| 3.9 | summary.md i18n | B.7 |
| 3.10 | 收敛判据放宽 | B.12 |
| 3.11 | default_models list 语法 | B.13 |

### Phase 4（架构级，已在 tasks.json 中）
目标：sidecar 真正隔离。

| 步骤 | 对应方案 / 任务 |
|------|-----------------|
| 4.1 | TASK-042 细化契约字段（见 B.9.1） | 代码审查 §4.2 + B.9.1 |
| 4.2 | TASK-043a/b/c 拆分实现 materialize / manifest / import | B.9.2 |
| 4.3 | TASK-044 非递归 guard + 环境剥离 | B.9.3 |
| 4.4 | TASK-045 smoke 验收 | 无需改动，跟进 TASK-043/044 |
| 4.5 | TASK-052：Codex / Gemini 流式 runtime（可选，晚于 4.2） | B.20 |

### Phase 5（可选，长期）
- TASK-055：`OpenAIChatAdapter` 实现（B.2 长期）。
- 其他用户反馈推动的优化。

---

## C.2 验证清单

每个阶段结束时至少运行：

```bash
python -m ruff check .
python -m pytest
& 'C:\Users\David Zhai\.workflow-core\scripts\sync-skills.ps1'
```

- Phase 0 / 1 后额外：
  ```powershell
  # 校验三端无 .bak
  Get-ChildItem "C:\Users\David Zhai\.{codex,claude,gemini}\skills\" -Recurse -Filter "*.bak" |
    Measure-Object | Select-Object -ExpandProperty Count
  # 预期 0
  ```
- Phase 2 后额外：
  ```bash
  grep -rn "error_kind" src/ | grep -v "DelegationRecord\|TesterPreflight"
  # 预期：0 处（除了序列化字段名）
  ```
- Phase 4 后额外（TASK-041 / TASK-045 的 manual smoke）：
  - 在真实 Codex / Claude / Gemini 主控项目里跑 `project-next` 的完整 `implementer → tester → reviewer → fixer → tester → reviewer → synthesizer` 闭环，每一步都观察到结构化失败上报（按 B.30）。
  - 在 delegated sidecar 的 prompt 里让模型调用 `council discuss ...`，观察是否被 TASK-044 guard 拒绝。
  - 手工破坏 `.claude/settings.json` 的权限（删一条 `Bash(pnpm:*)`），观察 tester preflight 是否报 `permission_blocked`。

---

## C.3 关键依赖关系图

```text
Phase 0  →  Phase 1  →  Phase 2  →  Phase 3 (运维) ─┐
                 ↓                                    │
                 └────→ Phase 4（架构隔离）────────→ 发布 gate
```

Phase 4 依赖 Phase 2.3（registry）落地，因为 TASK-044 的 `build_sandboxed_env` 要在所有 adapter subprocess 启动点生效，而 registry 化之后改动更干净。

TASK-052（流式 runtime）依赖 TASK-044，因为要确保流式事件消费不会因为递归 guard 被错误拦截（guard 只拦 council 自身，不拦模型输出）。

---

## C.4 风险与回退

| 改动 | 潜在风险 | 回退方式 |
|------|----------|----------|
| B.24 sync-skills 重构 | 新脚本意外删错 | `backup-global-workflow.ps1` 先跑一次生成快照；出错用 `restore-global-workflow.ps1 <snapshot>` 恢复 |
| B.1 RoleMapping 默认改为从模板加载 | 现有 `.council/config.yaml` 若 extra="forbid" 拒绝未知字段 | 保留 extra="forbid" 不变；既有 config 不受影响（只是 default 行为变了） |
| B.27 MCP manifest | 装机路径大改 | 先在 manifest 中保留旧路径作为兼容，再分阶段迁移 |
| B.9.2 TASK-043 materialize | `git worktree` 在未初始化 repo 时失败 | 探测 `git rev-parse --is-inside-work-tree`；非 git 项目 fallback 到 `copy` 策略 |
| B.10 Gemini YOLO 关闭 | 交互式 prompt 会阻塞 | 只在 sidecar 模式关 YOLO；交互式 CLI 由用户自己决定 |
| B.5 error_kind 重命名 | 外部 consumer 依赖该字段 | 保留 `.error_kind` 属性作为 deprecated 别名至少一个版本 |

---

## C.5 与 project-manager MCP 的对齐

本方案产生的**任何**代码 / skill / config 改动都应：

1. 在 MCP `add_log` 里留下 `review_solution_applied` 类型的日志。
2. 如果新增了任务（TASK-046 ~ TASK-055），通过 `create_tasks` 写入，并填好结构化验收字段（`acceptance_mode`、`verification_profile`、`verification_commands`、`review_checklist`、`stage_gate`）。
3. 涉及架构变更（B.9 系列）须先 `save_architecture` 更新架构文档，再写代码。

---

# 结语

当前的 CouncilFlow + 三端共享 skills + project-manager MCP 系统在**单机单用户**场景下是可用的，但上面暴露出的"默认配置翻车、skill 违反 PRD、同步脚本自毁备份、sidecar 仍能污染 workflow 状态"这四条问题，会在用户换机、让别人试用、或者任何一次 skill 重命名/删除时集中爆发。

建议按 Part C 的 Phase 0 → 1 → 2 → 3 → 4 顺序推进。Phase 0 和 Phase 1 可以在**当天**完成（均为局部修复，无架构风险），Phase 4 则按 TASK-042/043/044/045 的既有节奏走。

如果只能优先处理一件事，那就是 **Phase 0 + B.26（project-next 改 list 参数）**——它们同时修复了最显眼的分发污染和对 PRD §27.5 的当面违反。
