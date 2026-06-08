# CouncilFlow Workflow Integration

## Purpose

This document defines the stable integration contract that `project-*` workflows can rely on when they call `CouncilFlow`.

The key rule is simple:

- `project-*` workflows never rely on hidden shared chat context.
- Every integration step reads an explicit artifact from `.council/`.
- The controller still owns workflow continuation and persistence, but substantive role work must
  flow through explicit routed stages first.
- Project-local `.council/config.yaml` is the routing source of truth when `CouncilFlow` is available.

## Supported Controllers

`CouncilFlow` now treats these environments as first-class controllers:

- `codex`
- `claude`
- `gemini`

Controller detection contract:

- `Codex` is detected from `CODEX_SHELL`, `CODEX_THREAD_ID`, or `CODEX_INTERNAL_ORIGINATOR_OVERRIDE`.
- `Claude Code` is detected from `CLAUDECODE`, `CLAUDE_CODE`, `CLAUDE_CODE_SHELL`, `CLAUDE_SHELL`, or `CLAUDECODE_SHELL`.
- `Gemini CLI` is detected from `GEMINI_CLI`, `GEMINI_CLI_SESSION`, or `GEMINI_CLI_IDE_PID`.
- When no host signal is available, workflows may fall back to `.council/config.yaml` with `controller_override`.

## Project-Local Config Contract

When `project-*` workflows call `CouncilFlow`, they should assume the target project owns a local
`.council/config.yaml`.

Rules:

- If the file is missing, `CouncilFlow` materializes a project-local default template on first use.
- `roles.*` defines automatic delegation targets for execution roles.
- `discussion.default_models` defines the default extra discuss participants when workflows omit
  `--models`.
- `discussion.min_rounds` defines the minimum number of critique/respond rounds that must complete
  before early convergence is allowed.
- `discussion.max_rounds` defines the default round budget when workflows omit `--max-rounds`.
- `providers.default.total_timeout_seconds` defines the maximum wall-clock budget for a provider
  subprocess.
- `providers.default.idle_timeout_seconds` defines the inactivity timeout used by stream-aware
  providers when they stop emitting visible events.
- Provider-specific overrides such as `providers.claude.idle_timeout_seconds` may tighten or relax
  runtime windows for a single model family without changing the project-wide default.
- Local-only execution is a fallback for `council`-missing environments or explicit
  `local_execution` responses, not the default routing strategy.

## Workflow Taxonomy And Allowed No-Route Exceptions

`CouncilFlow` now assumes every `project-*` workflow falls into one of four categories:

- `read_only`
  - `project-status`
  - `project-resume`
- `gate_close`
  - `project-feedback`
- `discussion`
  - `project-discuss`
  - embedded `discuss` inside other `project-*` workflows
- `role_driven`
  - `project-init`
  - `project-design`
  - `project-plan`
  - `project-change`
  - `project-ask`
  - `project-review`
  - `project-next`

Allowed no-route exceptions are a strict whitelist:

- `read_only` workflows never take execution roles, so they do not call `delegate`.
- Pure `gate_close` steps only write back manual acceptance or reopen/create follow-up tasks, so
  they do not take execution roles either.
- Every `discussion` or `role_driven` step must treat `CouncilFlow` as a hard prerequisite when the
  tool is available.

This means the controller may only skip routing when:

- the workflow is truly read-only or gate-closing, or
- the stage already received `status = local_execution`, or
- `council` is genuinely unavailable and the workflow is entering an explicit controller-only
  fallback.

## Role-Driven Phase Machines

Every `role_driven` workflow should be modeled as an explicit stage machine instead of a single
"controller does the rest" step.

Recommended minimum stage machines:

- `project-init`: `planner -> synthesizer`
- `project-design`: `architect -> synthesizer`
- `project-plan`: `planner -> synthesizer`
- `project-change`: `architect -> planner -> synthesizer`
- `project-ask`: `advisor -> synthesizer`
- `project-review`: `reviewer`
- `project-next`: `implementer -> tester -> reviewer -> [fixer -> tester -> reviewer]* -> synthesizer`

Phase-machine rules:

- Each stage must declare a `role`, `objective`, `task_summary`, required upstream artifacts, and
  expected output.
- The host workflow must not infer permission to keep going; it must react to an explicit route
  result for each stage.
- `data.status = local_execution` means the active controller may perform only that current stage
  locally.
- `data.status = delegated` means the host must first read the emitted artifacts for that stage
  before continuing to the next stage.
- `error.status = error` means the workflow must stop and report the failure instead of silently
  absorbing the stage into the controller.
- `verification_commands` and `verification_profile` belong to the `tester` stage. They are stage
  inputs, not an automatic controller-local action after `implementer` finishes.
- `tester` should treat verification as a two-part contract: preflight first, then command
  execution. The preflight result should explicitly state whether the sidecar is ready and whether
  the workspace and required commands are available before any verification command is attempted.
  Since 0.1.1 the CouncilFlow preflight no longer probes Claude Code's per-project `permissions.allow`
  — see **Permission and approval model per CLI** below for why and the trust posture that replaces
  it.
- `tester` artifacts should distinguish `verification_failed` and `environment_not_ready` instead of
  collapsing both into a generic test failure. (`permission_blocked` was the third discriminator
  before 0.1.1; it has been removed from the preflight path.)
- `reviewer` is a first-class stage. A passing tester result does not authorize task completion on
  its own; the workflow still needs an explicit reviewer artifact to confirm the implementation is
  semantically acceptable.
- `project-next` must not move into synthesis, status updates, or commit creation after tester
  passes alone. It may do so only after both `tester` and `reviewer` explicitly pass.
- If a `tester` stage reports failure, the workflow must enter `fixer` and then return to `tester`
  for re-verification.
- If a `reviewer` stage reports findings, the workflow must enter `fixer` and then return to both
  `tester` and `reviewer`.
- `project-feedback` may close a gate, reopen a task, or create a follow-up fix/review task, but it
  must not silently act as `tester` or `fixer` without a new routed execution stage.
- Controller-owned save/log/status updates happen only after the routed role stages have completed;
  they are not a license to skip `planner`, `architect`, `advisor`, `reviewer`, or `synthesizer`
  stages when those stages belong to the current workflow.

## Supported Entry Points

### `project-discuss`

Standalone discussion should call:

```bash
council discuss "<question>" --models claude,gpt
council discuss "<question>" --models gemini,codex
council discuss "<question>"
```

If `--models` is omitted, `CouncilFlow` reads `discussion.default_models` from the project's local
`.council/config.yaml`.

When the caller is an interactive controller workflow such as `project-discuss` or embedded
`project-* discuss`, it should first produce a concise local controller position and pass it via
`--controller-position` so `CouncilFlow` does not spawn a same-controller subprocess just to
simulate the controller's first turn.

Expected persisted artifact:

- `.council/discuss/<discussion_id>/summary.md`

Expected machine-readable contract:

- `discussion_id`
- `artifact_kind = discussion_summary`
- `summary_path`
- `question`
- `participants`
- `initial_position`
- `current_controller_position`
- `min_rounds`
- `recommended_decision`
- `open_questions`
- `next_step`

### Embedded `discuss`

Embedded flows such as:

```text
project-design discuss claude
project-plan discuss claude,gpt
project-next discuss gemini
```

must follow the same pattern:

1. Invoke `council discuss`
   - Use `--models` only when the user explicitly chose participants
   - Otherwise omit `--models` and let the project-local config decide the default participants
2. Let the current controller generate a concise local `initial_position`
3. Pass that position into `council discuss --controller-position "<initial_position>"`
4. Let external models critique that position
5. Wait for the summary artifact
6. Read the summary artifact from disk
7. Continue the main `project-*` step with the controller's own synthesis, rather than nesting the same controller through a subprocess

### Delegation

Delegation-oriented workflow steps should call:

```bash
council delegate --role implementer --model claude --objective "<objective>" --task-summary "<summary>"
council delegate --role reviewer --model gemini --objective "<objective>" --task-summary "<summary>"
council delegate --role implementer --objective "<objective>" --task-summary "<summary>"
council delegate --role tester --objective "<objective>" --task-summary "<summary>" --input verification_commands="pnpm exec vitest run" --required-artifact implementer_result=.council/delegations/del_x/result.md --next-on-success "Enter reviewer after tester passes." --next-on-failure "Enter fixer, then rerun tester."
council delegate --role reviewer --objective "<objective>" --task-summary "<summary>" --required-artifact implementer_result=.council/delegations/del_impl/result.md --required-artifact tester_result=.council/delegations/del_test/result.md --next-on-success "Enter synthesis/status update only after reviewer passes." --next-on-failure "Enter fixer, then rerun tester and reviewer."
```

If `--model` is omitted, `CouncilFlow` reads the target model from the project's local role mapping.

Expected route outcomes:

- `data.status = "delegated"`: a real sidecar delegation happened, `via_sidecar = true`, and the
  workflow must read the emitted artifacts before continuing.
- `data.status = "local_execution"`: the role resolves to the active controller, `via_sidecar =
  false`, and the workflow may continue locally.
- `error.status = "error"`: routing or execution failed; the workflow must stop and report the
  failure instead of silently falling back to controller-only execution.
- `error.error_kind`: the provider failure class (`idle_timeout`, `total_timeout`, `process_exit`,
  or `os_error`) so the host can distinguish a long-running sidecar from a broken invocation.

Expected persisted artifacts:

- `.council/delegations/<delegation_id>/handoff.yaml`
- `.council/delegations/<delegation_id>/result.md`

Expected machine-readable contract:

- `artifact_kind = delegation_handoff`
- `status = delegated`
- `delegation_status = completed`
- `via_sidecar = true`
- `handoff_path`
- `result_path`
- `handoff_schema.id`
- `handoff_schema.role`
- `handoff_schema.objective`
- `handoff_schema.task_summary`
- `handoff_schema.constraints`
- `handoff_schema.relevant_files`
- `handoff_schema.inputs`
- `handoff_schema.required_artifacts`
- `handoff_schema.verification_commands`
- `handoff_schema.tester_preflight`
- `handoff_schema.review_findings`
- `handoff_schema.fixer_input_sources`
- `handoff_schema.execution_guardrails`
- `handoff_schema.next_actions_on_success`
- `handoff_schema.next_actions_on_failure`
- `handoff_schema.expected_output`

## Consumption Rules

- The workflow must treat disk artifacts as the source of truth.
- The workflow must not assume provider-specific hidden memory.
- The controller decides whether a discussion or delegation result is accepted, retried, or ignored.
- Missing artifacts should be treated as failed or incomplete execution.
- Provider timeouts should be interpreted using `error_kind`, rather than assuming all failures are
  the same kind of timeout.
- Same-controller discuss requests should not trigger sidecar execution.
- Same-controller delegate requests should return explicit `local_execution` instead of starting a sidecar.
- Artifacts created under a Gemini-controlled session must remain consumable by Codex and Claude workflows.
- When `council` is unavailable, workflows may fall back to local controller-only execution, but this
  fallback should be explicit in the calling workflow rather than treated as the primary path.
- Route/discuss failures and a missing `council` command are different cases: only the latter may
  trigger an explicit controller-only fallback, while the former must stop the workflow.
- When `council` is available, workflows must not start role work until they receive either
  `data.status = local_execution` or a delegated artifact set.
- Role-driven workflows must interpret `verification_commands` as `tester` inputs and must not let
  the controller run them locally unless the `tester` stage itself returned `local_execution`.
- Tester/fixer loops should use `required_artifacts` and `next_actions_on_*` from the handoff
  package/result contract instead of inferring stage transitions from hidden controller state.
- Fixer stages should also consume explicit `review_findings` and `fixer_input_sources` artifacts,
  rather than relying on free-form controller prose to describe what broke.
- Delegated stages should honor `execution_guardrails`: by default they must not create git commits
  or modify workflow state files such as `.claude/state/**` and `.council/state.json` unless the
  contract explicitly allows it.
- If a manual gate fails, `project-feedback` should reopen the task or create a follow-up routed
  repair task instead of directly performing fixer/tester work inside the gate-closing workflow.
- If `council delegate` or `council discuss` returns an error, workflows must stop and surface that
  failure instead of silently switching to local execution.
- Task status from `project-manager` is now a 7-value enum. `cancelled` and `superseded` are
  **closed-but-not-done** terminal states: they satisfy a DAG predecessor only through the documented
  `getNextTask` semantics (a `superseded` dependency resolves through its replacement chain; a
  `cancelled` dependency *blocks* its dependents and is surfaced, never silently treated as
  satisfied). Closed-but-not-done tasks do **not** contribute to `active_completion_rate` — only
  `done` does. Workflows must not treat `cancelled` / `superseded` as `done`.
- `current_focus` returned by `get_project_context` is **auxiliary ops-level state** and may be
  stale (it carries an `is_stale` hint). It is **not** authoritative task state — task `status`
  remains the source of truth. Do not gate routing or completion decisions on `current_focus`.
- Logs now carry a `kind` discriminator (`task_transition` / `ops_event` / `decision` / `note` /
  `workflow_failure` / `focus_update`) plus `event_type`. Consumers must select log entries by
  `kind` / `event_type`, not by parsing the human-readable `message` text.

## Sidecar Isolation Contract

Every delegated stage carries an `execution_guardrails` block with two companion
objects that describe how the sidecar runs and how its results flow back:

- `execution_guardrails.isolated_workspace`:
  - `strategy`: `copy`, `git_worktree`, or `none`.
    - `git_worktree` (default) materializes the current HEAD into a separate worktree
      outside the host project root so sidecar edits cannot collide with the controller.
    - `copy` mirrors explicit include patterns into a temp directory.
    - `none` is reserved for workflow-maintenance tasks that are explicitly allowed to
      modify the host project; it must be an exception, never the default.
  - `include_patterns` / `exclude_patterns`: what ends up inside the sidecar workspace.
    The default exclude list covers `node_modules/**`, `__pycache__/**`, `.venv/**`,
    `.council/**`, `.claude/**`, `.codex/**`, `.gemini/**`, and `.workflow-core/**`
    so the sidecar never sees workflow state or MCP configuration.
  - `workspace_path`: filled in at runtime with the materialized directory location.

- `execution_guardrails.import_manifest`:
  - `writable_globs`: the only paths whose sidecar changes may be imported back into
    the host project (e.g. `src/**`, `tests/**`).
  - `readonly_artifact_paths`: the sidecar may read these but must not modify them.
  - `max_file_count` / `max_total_bytes`: budgets that cap how much content can be
    imported back in a single delegation.

- `execution_guardrails.protected_paths` defaults to `.claude/state`, `.council/state.json`,
  `.workflow-core`, `.claude/skills`, `.codex/skills`, and `.gemini/skills`. Any change
  under these paths is refused even if the sidecar produced one.

- `execution_guardrails.isolated_workspace.dependency_symlinks` lists directories that
  must be exposed inside the sidecar workspace so package-manager verification commands
  (`pnpm exec`, `python -m pytest`, `cargo test`, ...) can resolve their binaries. The
  default set covers `node_modules`, `.venv`, `venv`, `vendor`, `.gradle`, `.cargo`, and
  `target`. On Windows these are mounted as NTFS junctions (`mklink /J`, no admin
  required); on Unix they become `os.symlink(..., target_is_directory=True)` entries.
  The sidecar is expected to treat them as read-only shared references — writing
  through the junction lands in the host project, so guardrail-relying tasks should not
  modify dependency contents. Entries that do not exist under the source are silently
  skipped, so the feature is zero-cost for projects without those ecosystems.

Ordinary code tasks must not override these defaults. Only workflow-maintenance tasks
may relax `allow_workflow_state_write` or extend `writable_paths`; the controller is
responsible for that decision and must justify it in the handoff package.

### Delegation result manifest

A successful `DelegationResult` carries three additional fields that let the controller
decide whether to accept the sidecar output:

- `workspace_manifest: list[WorkspaceFileChange]` — one entry per file the sidecar
  touched (`path`, `change_type ∈ {added, modified, deleted}`, `byte_size`, `imported`,
  optional `rejection_reason`).
- `import_outcome ∈ {none, applied, partial, rejected}` — the net effect on the host
  project. `rejected` requires the controller to stop; `partial` requires it to read
  `rejection_reason` before continuing.
- `import_rejected_reason: str | None` — free-form human-readable explanation used when
  `import_outcome != "applied"`.

These fields are informational in TASK-042 (the contract-only phase); subsequent
isolation work (TASK-043 / TASK-044) makes the orchestrator produce and enforce them.

### Permission and approval model per CLI

Each of the three first-party CLIs has its own gate for letting model-driven
Bash tool calls run. CouncilFlow delegations run inside a materialized
worktree with the full guardrail stack (writable-glob allow-list,
DEFAULT_PROTECTED_PATHS snapshot/restore, MCP role policy, recursion guard,
sandboxed env). Because all four layers already constrain what a sidecar can
touch, CouncilFlow's adapters default to **auto-approve in delegation** for
every CLI. This keeps the three controllers symmetric — you don't need to
know whether the target model happens to be Claude or Gemini before you
schedule a task.

| CLI | Approval gate | How CouncilFlow handles it |
| --- | --- | --- |
| Claude Code | `.claude/settings.json::permissions.allow` array of `Bash(<subject>:*)` entries. Non-interactive `-p` mode without a matching entry refuses the tool call and usually emits a "claims tested but didn't" result. | Adapter appends `--dangerously-skip-permissions` to the default command line (since 0.1.1). The name surfaces the risk intentionally; the actual safety lies in the four guardrail layers above. |
| Gemini CLI | Tool-approval prompts driven by `--approval-mode {default,auto-edit,yolo}`. | Adapter passes `--approval-mode yolo` by default. Same posture as Claude. |
| Codex CLI | User-configured `~/.codex/config.toml::approval_policy` (and project-level overrides). | Adapter does **not** force a policy flag. If you use Codex as a delegation target, make sure your Codex install is configured so `codex exec` can run bash tool calls without an interactive approval (e.g. `approval_policy = "never"` or `"full-auto"`). Otherwise a delegated `tester` stage may hang on an approval prompt the sidecar can't satisfy. |

The tester preflight therefore only checks one thing before handing off to
the sidecar: **does every verification command resolve on PATH?** A missing
`pnpm` or `pytest` still fails fast with `error_kind=environment_not_ready`.
The older `error_kind=permission_blocked` path was removed in 0.1.1.

### Change detection is baseline-driven

After TASK-058 the orchestrator snapshots the workspace's file-level state
right after materialization and diffs the post-provider workspace against
that baseline. It does NOT compare the workspace to the host source tree.
This matters because an earlier delegation may have left uncommitted files
in source: those files were never in the sidecar workspace to begin with
and must never appear in `workspace_manifest` as `deleted`. Empty
`import_manifest.writable_globs` is now a strict deny-all guard — every
legitimate import must list an explicit glob, and the default
`ExecutionGuardrails()` safely rejects every sidecar write.

## Optional: OpenAI (`gpt`) Adapter

CouncilFlow ships an opt-in `OpenAIChatAdapter` that lets the `advisor` role
(or any other role you want to map) resolve to the OpenAI Chat Completions
API. It is *not* part of the base install — enabling it requires two things:

1. Install the extra:

   ```bash
   pip install 'councilflow[openai]'
   ```

2. Set `OPENAI_API_KEY` in the environment where CouncilFlow runs. You can
   also set `OPENAI_MODEL` to override the default `gpt-4o-mini` for a
   specific project.

Once both conditions are met, `roles.advisor: gpt` in `.council/config.yaml`
routes through `OpenAIChatAdapter` just like `codex` / `claude` / `gemini`
roles route through their CLI adapters. If the SDK is missing or the API key
is absent at call time, the delegation fails with a structured
`ProviderError(kind="environment_not_ready")` so the workflow failure report
protocol classifies it correctly.

Specific OpenAI models (e.g. `gpt-4o`, `gpt-4o-mini`, `o1-preview`) are
accepted directly as the model name in config or via `--model`. The adapter
normalizes the family back to `gpt` in `ProviderResponse.model` so downstream
`speaker_model` / `participants` comparisons stay stable.

## MCP Registration via `mcp-manifest.json`

Three-controller MCP registration now flows from a single source of truth:
`C:\Users\David Zhai\.workflow-core\mcp-manifest.json`. Previously the path
to `mcp-project-manager/dist/index.js` was hardcoded in five places
(`install-global-workflow.ps1`, `backup-global-workflow.ps1`,
`restore-global-workflow.ps1`, `.codex/config.toml`, `.gemini/settings.json`),
which meant any move or upgrade of the server required touching every file.

Manifest schema (version 1):

```json
{
  "version": 1,
  "servers": {
    "project-manager": {
      "command": "node",
      "args_template": ["${MCP_HOME}/mcp-project-manager/dist/index.js"],
      "env": { "MCP_HOME": "C:/Users/David Zhai/.claude" },
      "trust": { "codex": false, "claude": false, "gemini": true }
    }
  }
}
```

`${<key>}` placeholders inside `args_template` are expanded against the
server's own `env` block at registration time, so swapping the install
location of the Node-based server is a one-line change in the manifest.

Scripts that consume the manifest:

- **`install-global-workflow.ps1`**: loads the manifest, expands args per
  server, then registers each via `codex mcp add`, `claude mcp add -s user`,
  and `gemini mcp add -s user` (adding `--trust` when `trust.gemini=true`).
  The earlier hardcoded path is gone.
- **`backup-global-workflow.ps1`**: includes `mcp-manifest.json` in the
  timestamped snapshot under `<snapshot>/config/mcp-manifest.json`, alongside
  the Codex / Claude / Gemini config files.
- **`restore-global-workflow.ps1`**: prefers the restored manifest as the
  registration source. The legacy per-snapshot `mcp_servers` path is kept
  as a fallback so backups taken before TASK-050 still restore correctly.

### Claude Code MCP configuration is per-project

Unlike Codex (global `config.toml`) and Gemini (single user `settings.json`),
Claude Code stores its MCP registrations inside `C:\Users\David Zhai\.claude.json`
in one block per project scope plus a user-scope fallback. `claude mcp add
-s user` writes to the user scope, which acts as the default when a project
scope does not override it. If you need different MCP paths per project,
`claude mcp add -s local` inside the project writes a project-scope entry
that wins. The manifest applies to the user-scope fallback only — project
overrides remain under the user's control.

## `project-manager` Task-State Contract

The `project-manager` MCP server is the authoritative store for task status and
project logs. Workflows that read or mutate task state should rely on the
following contract.

### Status enum and the forward state machine

Task status is a 7-value enum: `todo`, `in_progress`, `auto_verified`,
`awaiting_manual_acceptance`, `done`, `cancelled`, `superseded`.

- The forward state machine driven by `update_task_status` is unchanged:
  `todo -> in_progress -> auto_verified -> {done | awaiting_manual_acceptance}`;
  `awaiting_manual_acceptance -> {done | in_progress}`. `done` is a terminal that
  still requires the full verification/review gauntlet.
- `cancelled` and `superseded` are **terminal management states** with no
  outbound edges. They are reachable **only** through the `close_task` tool.
  `update_task_status` now **rejects** them with a "use `close_task`" error — the
  forward state machine cannot reach them.
- **Contract version 1.2.0 (additive over 1.1.0):** the terminal states
  (`done` / `cancelled` / `superseded`) now have exactly **one** audited reverse
  edge — `reopen_task -> {todo | in_progress}`. This is the single documented
  exception to "terminal states have no outbound edges" and **supersedes the
  ADR-001 "no reopen in v1" decision**. Like `close_task`, `reopen_task` is a
  management bypass: it does **not** travel the forward state machine and is not
  a role-driven stage action (see **`reopen_task`** below).

### `close_task` management API

`close_task(id, status, reason, replacement_task_id?)` is the **only** path from
outside the internal forward state machine into `cancelled` / `superseded`. It is
an audited management bypass, not a workflow-stage action.

- `status` may be only `cancelled` or `superseded`. `close_task` can **never** set
  a task to `done` (use the forward state machine for that), and it cannot
  un-complete or reopen a task — it operates only from a **non-terminal** source
  (you cannot close a task that is already `done` / `cancelled` / `superseded`;
  there is no reopen in v1).
- `cancelled` requires `reason`. `superseded` requires `reason` **and**
  `replacement_task_id` (validated: the replacement must exist, not be the task
  itself, not already be closed, and not introduce a replacement-chain cycle).
- `close_task` writes a `task_closed` audit log
  (`kind = task_transition`, `event_type = task_closed`, `source = close_task`).
- `superseded` **rewrites every dependent edge** from the closed task to its
  replacement so the DAG stays runnable. `cancelled` with live dependents instead
  emits an `ops_event` (`event_type = dependents_blocked_by_cancel`) so the
  controller can re-point or close those dependents — there is no silent deadlock.
- **Who calls it:** in normal operation `close_task` is invoked **only** by
  `project-feedback` (a manual-gate rejection that decides to cancel or supersede)
  or by an explicit controller / management decision. Role-driven stages
  (`implementer` / `tester` / `reviewer` / `fixer` / `synthesizer` / `planner` /
  `architect` / `advisor`) do **not** call `close_task`; they report failures and
  leave task state to `project-feedback` / the controller. See also the note in
  the Workflow Failure Report Protocol: a `workflow_failure` log does not
  authorize `close_task`.

### Management and batch tools (1.2.0+)

Five tools are now exposed alongside `close_task`. They are all management
APIs, not forward-state-machine actions; the boundary rules from `close_task`
apply unchanged unless noted.

- **`set_task_priority(id, priority)`** — adjust a single task's priority.
  `priority` is a number; higher means more urgent. See **Task priority and
  priority-aware `get_next_task`** below for how it influences scheduling.
- **`update_tasks([{ id, status, notes? }])`** — the **batch** form of
  `update_task_status` for **forward** transitions only. It is per-item with
  **partial success**: each entry is still validated independently against the
  forward state machine, and one rejected item does not roll back the items that
  succeeded. It does **not** accept `cancelled` / `superseded` (use
  `close_tasks` for those), exactly as the single-task `update_task_status`
  rejects them.
- **`close_tasks([{ id, status, reason, replacement_task_id? }])`** — the
  **batch** form of `close_task`. Each entry carries the same per-item contract
  as `close_task` (`status ∈ {cancelled, superseded}`, `reason` required;
  `superseded` also requires a validated `replacement_task_id`) and is validated
  and audited individually.
- **`archive_module(module, reason)`** — bulk-close **every non-terminal task**
  in a module by issuing `close_task(status = cancelled)` for each. Tasks already
  in a terminal state (`done` / `cancelled` / `superseded`) are left untouched.
  This is the management shortcut for retiring a whole module; each cancellation
  is audited like an ordinary `close_task`, and live cross-module dependents are
  surfaced via the same `dependents_blocked_by_cancel` `ops_event`.
- **`reopen_task(id, reason, to_status?)`** — the **audited reverse of
  `close_task`**. It brings a task that is in a **terminal** state
  (`done` / `cancelled` / `superseded`) back to `todo` (default) or
  `in_progress` (`to_status`). `reason` is **required**.
  - It is a **management bypass** that does **not** use the forward state
    machine — it is the only edge out of a terminal state (see the state-machine
    note above; this supersedes ADR-001).
  - Reopening a **`superseded`** task **clears its `replacement_task_id`**.
    However, the dependent edges that `close_task` rewired from the closed task
    onto the replacement at supersede time are **not** auto-restored to the
    reopened task. The audit log **flags** this so the controller can decide
    whether to re-point those dependents manually.
  - It writes an audit log entry mirroring `close_task`
    (`kind = task_transition`, `source = reopen_task`).
  - **Who calls it (same boundary as `close_task`):** in normal operation
    `reopen_task` is invoked **only** by `project-feedback` (e.g. a manual-gate
    decision to revive a previously-closed task) or by an explicit controller /
    management decision. Role-driven stages (`implementer` / `tester` /
    `reviewer` / `fixer` / `synthesizer` / `planner` / `architect` / `advisor`)
    do **not** call `reopen_task`; they report failures and leave task state to
    `project-feedback` / the controller.

### Task priority and priority-aware `get_next_task` (1.2.0+)

- Tasks now carry an optional **`priority?: number`** field (default `0`;
  higher = more urgent), set via `set_task_priority` or at task creation.
- `get_next_task` now returns the **highest-priority runnable `todo`**. Ties on
  priority are broken by **creation order** (oldest first), preserving the
  pre-1.2.0 ordering as the `priority == 0` baseline.
- Priority **never overrides dependency gating**: a higher-priority task whose
  predecessors are not satisfied is still not runnable. Priority only re-orders
  among tasks that are *already* runnable under the existing DAG semantics
  (`cancelled` dependency blocks; `superseded` dependency resolves through its
  replacement chain).

### `get_project_context` (additive, backward compatible)

`get_project_context` now also returns:

- `in_progress_tasks` — the full set of currently in-progress tasks.
- `tasks_summary.metrics` — `{ total_all, active_total, done, cancelled,
  superseded, closed_total, raw_completion_rate, active_completion_rate }`. The
  two rates are distinct: `raw_completion_rate` counts against all tasks, while
  `active_completion_rate` counts `done` against active (non-closed) tasks only;
  `cancelled` / `superseded` do not contribute to `active_completion_rate`.
- `tasks_summary.next_task_blocked_reason` — one of `none`, `all_done`,
  `blocked_in_progress`, `blocked_by_cancelled_dep`.
- `current_focus` — the single-slot ops focus snapshot (or `null`, with an
  `is_stale` hint). Auxiliary ops state only; see Consumption Rules.
- `schema_version`.

It accepts new optional params:

- `context_mode` (`build` | `ops` | `hybrid`) — a **presentation hint only**. It
  must **not** be treated as a filter or permission boundary; the task set is
  identical across all three modes.
- `max_recent_events`.
- `include_full_in_progress`.

The legacy `progress` object is preserved unchanged
(`{ total, done, in_progress, awaiting_acceptance, todo }`) and is now
**additively** extended with the dual-rate metrics fields above.

`get_current_focus` / `set_current_focus` read and write that single-slot ops
focus snapshot (stored in `.claude/state/focus.json`). It is auxiliary ops state,
not task state.

### `add_log` / `get_logs`

- `add_log` now also accepts `kind`
  (`task_transition` | `ops_event` | `decision` | `note` | `workflow_failure` |
  `focus_update`), `event_type`, `tags`, `entities`, and `source`; `task_id` may
  be `null` for a project-level ops event.
- `get_logs` accepts `{ n/limit, kind, event_type, since }` and **filters before
  slicing** (a journal view), so a `kind`/`event_type` filter returns the most
  recent matching entries rather than filtering only within the last `n`.
- `migrate_tasks_schema` is a v0 -> v1, idempotent migration that **never** changes
  task status, backfills log `kind` / `event_type`, and stamps `schema_version = 1`.

### `verification_profile` validation (1.2.0+)

`verification_profile` names are no longer a hardcoded enum baked into the
server. They are now validated **at runtime** against the external policy file
`~/.workflow-core/policies/verification-profiles.json`.

- Adding (or renaming) a profile is an **edit to that JSON file only** — no
  project-manager code change is required, so the profile set is extensible
  without a release.
- An **unknown** profile name is **rejected** when the policy file is present.
- Validation is **lenient only when the file is missing**: with no policy file
  to validate against, any name is accepted (so an unprovisioned environment
  does not hard-fail task creation).

## Workflow Failure Report Protocol

Every `role_driven` and `discussion` shared skill must emit the same failure
artifact when `council delegate` or `council discuss` returns an error or when
any declared artifact is missing. Three-controller consistency is the whole
point: a Claude Code failure, a Codex failure, and a Gemini CLI failure must
all look the same to whoever reads the logs.

1. **Emit one single-line JSON object to stdout** before stopping the skill.
   The six required fields:

   | Field | Type | Description |
   |-------|------|-------------|
   | `workflow` | string | Skill name, e.g. `project-next`. |
   | `workflow_failed` | bool | Always `true` in a failure report. |
   | `failed_stage` | string | Role / stage that failed: `implementer`, `tester`, `reviewer`, `fixer`, `synthesizer`, `planner`, `architect`, `advisor`, or `discussion`. |
   | `error_kind` | string | Forwarded from `council` output when available: `idle_timeout`, `total_timeout`, `process_exit`, `os_error`, `permission_blocked`, `environment_not_ready`, `guardrail_violation`, `adapter_missing`, `recursive_workflow_violation`, or `missing_artifact`. |
   | `council_available` | bool | `true` if `council` can be invoked but returned an error; `false` only when `shutil.which("council") is None` or `council version` fails. |
   | `artifact_paths` | object | Best-effort pointers like `{"handoff": ".council/delegations/del_x/handoff.yaml"}`; `null` when nothing is persisted. |
   | `fallback_attempted` | bool | `true` only when `council_available=false` and the skill then ran a controller-only fallback. Otherwise `false`. |
   | `message` | string | Human-readable line summarizing what happened. |

   Example:

   ```json
   {"workflow":"project-next","workflow_failed":true,"failed_stage":"tester","error_kind":"idle_timeout","council_available":true,"artifact_paths":{"handoff":".council/delegations/del_abc/handoff.yaml"},"fallback_attempted":false,"message":"council delegate --role tester returned idle_timeout after 180s"}
   ```

2. **Also call `project-manager` MCP `add_log`** with:
   - `type = "workflow_failure"`
   - `task_id = <current task id if any, otherwise null>`
   - `message = <same text as the JSON "message">`

3. **Do not mutate task status toward `done` / `auto_verified`**. The task
   remains `in_progress` (or whatever it was). Let `project-feedback` or a new
   follow-up task pick the repair route.
   - A `workflow_failure` log does **not** authorize `close_task`. A failed
     workflow leaves the task in its current state; whether to cancel, supersede,
     or repair it is a `project-feedback` / controller decision, not something a
     role-driven stage may perform on its own. Role stages
     (`implementer` / `tester` / `reviewer` / `fixer` / `synthesizer` / `planner`
     / `architect` / `advisor`) report the failure and stop; they never call
     `close_task`.

Classification rule for `council_available`:

- `true` + `error_kind != null` → `council` can be invoked but the call failed
  for a structured reason. Workflow **must stop** and emit the report.
- `false` → `council` was genuinely missing. The skill may run a
  controller-only fallback and set `fallback_attempted=true`; the JSON report
  is still required so the downgrade is auditable.

Shared skills reference this protocol by name in their "注意事项" section; see
any of `project-init`, `project-plan`, `project-next`, `project-review`,
`project-change`, `project-ask`, `project-discuss`, `project-design`, or
`project-feedback`.

## Minimum Integration Flow

1. `project-*` classifies the current step as `read_only`, `gate_close`, `discussion`, or
   `role_driven`.
2. If the step is `discussion`, the active controller generates a local `initial_position` and calls
   `council discuss`.
3. If the step is `role_driven`, the workflow enters the first explicit role stage and calls
   `council delegate --role <stage-role>`.
4. `CouncilFlow` writes artifacts into `.council/`.
5. The host workflow reads those artifacts explicitly before deciding the next stage.
6. The controller may only continue locally when the current stage returned `local_execution`.
7. `project-next` loops through `implementer -> tester -> reviewer -> [fixer -> tester -> reviewer]*`
   until both verification and review succeed; only then may the controller perform final
   synthesis, task-state updates, and commit decisions.

This keeps the integration deterministic, inspectable, and portable across Codex, Claude Code, and Gemini CLI.

---

## Dynamic Role Routing (0.1.3+)

CouncilFlow 0.1.3 extends `.council/config.yaml`'s `roles.*` fields so
that each role can be configured either as the shorthand model string
(pre-0.1.3 behavior) or as an ordered list of `RoleRoute` entries for
dynamic routing. The first entry whose `when` expression evaluates
true (or has no `when`) is chosen; the entry's `fallback` list is the
ordered set of models to try if the primary adapter call fails with a
structured error.

### Schema

```yaml
roles:
  # Shorthand form (equivalent to a single-entry list)
  architect: codex

  # Dynamic routing form: ordered list of RoleRoute entries
  implementer:
    - model: claude
      when: "task.complexity in ['L']"
    - model: claude-haiku
      when: "task.complexity in ['S', 'M']"
      fallback: [claude, gemini]
    - model: gemini            # final default match
```

Field contract on `RoleRoute`:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `model` | `str` | yes | Target model name; validated against the known-model whitelist at config load. |
| `when` | `str \| null` | no | Restricted-AST expression. `null` or missing means "always match". |
| `fallback` | `str \| list[str] \| null` | no | Additional models to attempt if the primary adapter fails with a retryable kind. |

### `when` expression grammar

Evaluated by `councilflow.config.when_eval.evaluate()` in a sandboxed
AST walker. Allowed constructs:

- **Literals**: `str`, `int`, `float`, `bool`, `None`, list/tuple literals
- **Variables**: bare names bound in the evaluation context (`task`, `controller`, ...)
- **Attribute access**: one level deep only, e.g. `task.complexity`, `task.module`
- **Operators**: `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `and`, `or`, `not`

Rejected (raises `WhenExpressionError`):

- Any call: `f()`, `__import__(...)`, `eval(...)`, `subprocess.run(...)`, `getattr(task, "x")`
- `Lambda`, `FunctionDef`, `ClassDef`, `Import`, `Assign`
- `Subscript` outside list/tuple literals: `task["x"]`
- Attribute chains deeper than one level: `task.meta.owner`
- Any name starting with underscore: `task._private`, `task.__class__`, `task.__dict__`
- Comprehensions / generators / f-strings / walrus / ternary / starred

Missing context fields resolve to `None` (no exception). Ordering and
membership operators with `None` operands return `False` rather than
crashing.

### Routing decision and audit trail

`councilflow.controller.role_router.resolve()` returns a
`RoutingDecision` with `primary_model`, `fallback_chain`,
`matched_route_index`, `matched_when_expr`, and a
`tried_routes` list for full audit.

Every decision (successful match or no-match) is appended to
`<project_root>/.council/runs/<run_id>/routing.json` as a JSON array
of records. Each record contains:

- `timestamp` (UTC ISO)
- `role`
- `primary_model` (or `null` for no-match)
- `fallback_chain`
- `matched_route_index`
- `matched_when_expr`
- `tried_routes`: list of `{index, model, when, matched, reason, error}`
- `task_context_summary`
- `error_kind` (only on no-match)

### `routing_no_match` error contract

When no route matches and `--model` was not supplied, `council delegate`
exits with code 1 and emits a structured error:

```json
{
  "data": null,
  "error": {
    "status": "error",
    "error_kind": "routing_no_match",
    "role": "implementer",
    "model": null,
    "tried_routes": [...],
    "task_context_summary": {...},
    "message": "No RoleRoute matched for role `implementer` ..."
  }
}
```

Host workflows should treat `routing_no_match` the same as any other
`council delegate` failure — report via
`Workflow Failure Report Protocol` and stop.

### Provider variants (0.1.4+)

Both the Gemini and Claude adapter families accept a **variant** name on
the `model` field, which the adapter translates to a `--model <variant>`
flag on the underlying CLI subprocess. This is how per-role cost tuning
(e.g. "tester to haiku, architect to opus") actually reaches the CLI.

**Claude variants** (0.1.4+):

| Config value | Normalized to | CLI receives |
|---|---|---|
| `claude` | `claude` | (no `--model` flag, CLI default) |
| `haiku` | `claude-haiku` | `--model haiku` |
| `sonnet` | `claude-sonnet` | `--model sonnet` |
| `opus` | `claude-opus` | `--model opus` |
| `claude-haiku` | `claude-haiku` | `--model haiku` |
| `claude-sonnet` | `claude-sonnet` | `--model sonnet` |
| `claude-opus` | `claude-opus` | `--model opus` |
| `claude-sonnet-4-6` | `claude-sonnet-4-6` | `--model claude-sonnet-4-6` |
| `claude-3-5-sonnet-20241022` | `claude-3-5-sonnet-20241022` | `--model claude-3-5-sonnet-20241022` |

The **`claude-` prefix rule** in `resolve_adapter_model` accepts any
non-empty suffix, so newly released Anthropic model names (e.g. a future
`claude-opus-5` or `claude-sonnet-7-1-20270115`) work without a
CouncilFlow patch. Short aliases (`haiku` / `sonnet` / `opus`) are in the
`MODEL_ALIASES` table and normalize to the family-prefixed form to
preserve variant info.

**Gemini variants** (since 0.1.2, semantics sharpened in 0.1.4):

| Config value | Normalized to | CLI receives |
|---|---|---|
| `gemini` | `gemini` | (no `--model` flag, CLI default) |
| `gemini-1.5-flash` | `gemini-1.5-flash` | `--model gemini-1.5-flash` |
| `gemini-2.5-pro` | `gemini-2.5-pro` | `--model gemini-2.5-pro` |
| `gemini-cli` / `google-gemini` | `gemini` | (no `--model` flag, CLI-name alias) |

Before 0.1.4, a config entry like `gemini-1.5-flash` could collapse to
bare `gemini` via `MODEL_ALIASES`, losing the variant. 0.1.4 removes
those variant-collapsing aliases so the Gemini path behaves consistently
with the newly-added Claude path.

**`ProviderResponse.model`** stays the canonical family name (`claude` /
`gemini`) for both adapters so downstream dedup / speaker_model
comparisons are stable. The specific variant is surfaced via
`metadata.claude_variant` / `metadata.gemini_variant`.

### Synthesizer artifact contract (0.1.5+)

The three workflow skills that run a `synthesizer` stage
(`project-design`, `project-plan`, `project-change`) delegate
synthesizer to a sidecar sub-controller, but **the sidecar must not
write host workflow state directly**. The guardrail backstop
(`PROTECTED_WORKFLOW_PATHS = (".claude/state", ".council/state.json")`)
snapshots those paths before the stage, compares after, and rolls
any change back with `error_kind=guardrail_violation`. So:

- **Sidecar synthesizer only produces markdown (plus JSON fragments
  where appropriate) into
  `.council/delegations/<id>/result.md`.** This is the same
  artifact-first contract used by `implementer` since 0.1.0.
- **Host controller reads `result.md` and drives the MCP writes** via
  `save_architecture` / `save_prd` / `create_tasks` / `add_log`
  **itself**, after user confirmation where the skill calls for it.
- **`--allow-workflow-state-write` remains an opt-in flag** for
  callers who genuinely need sidecar-driven host-state writes
  (unusual; effectively a hard-red-line exemption).

This contract is enforced at the **skill-protocol layer** (the
`council delegate --role synthesizer` invocation explicitly instructs
the sub-controller to produce only artifact) plus the **guardrail
layer** (sidecar MCP writes to protected paths are rolled back).
`tests/test_synthesizer_artifact_contract.py` pins the happy path as
a regression test.

Before 0.1.5, the three skills did not explicitly warn the sidecar to
avoid `save_architecture` / `save_prd` / `create_tasks` — so any
sub-controller that "helpfully" persisted its output via MCP triggered
a `guardrail_violation`. 0.1.5 resolves the ambiguity in the skill
documentation without changing the guardrail.

### Fallback retry semantics

When the primary adapter call fails with one of these kinds,
`cli/delegate.py` automatically retries on the next model in the
fallback chain:

- `adapter_missing`
- `process_exit`
- `idle_timeout`
- `total_timeout`
- `os_error`

Non-retryable kinds (`permission_blocked`, `environment_not_ready`,
`verification_failed`, etc.) exit immediately — they reflect task
state, not provider transient failure. Every fallback attempt is
logged to `routing.json`.

**0.1.5 note on `process_exit`:** between 0.1.3 and 0.1.4 this
whitelist contained the string `process_error`, which no adapter
actually emits — every CLI-subprocess non-zero exit surfaces as
`process_exit`. The typo silently broke fallback for any subprocess
failure across three releases. 0.1.5 fixes the spelling, so
correctly-configured fallback chains start working as documented.
If you noticed fallback "not kicking in" before 0.1.5, this is why.

### `--model` override precedence

The `--model <name>` CLI flag takes the **highest** priority and
bypasses routing entirely. This preserves the legacy CLI behavior for
ad-hoc one-off invocations.

### Discuss wait (0.1.6+)

`council discuss` is synchronous: the controller's shell blocks for
the entire multi-model exchange. Real discussions (5 rounds × 2-3
critic models) routinely run 3-10 minutes, but most desktop CLI
shells time out after 3-4 minutes. Before 0.1.6 there was no way to
recover the discussion result after a shell timeout — the subprocess
kept running and `summary.md` eventually landed, but the caller had
to manually `ls .council/discuss/` to find it. (`council delegate`
had `council delegation wait` for the same problem since 0.1.0;
`council discuss` was the asymmetric gap.)

0.1.6 adds the parallel: **`council discussion wait <discussion_id>
--timeout 7200`**. The naming (noun form `discussion`, mirroring
`delegation`) preserves the existing `council discuss "question"`
verb-form interface unchanged.

#### Recovery protocol (host-controller workflow skills)

```bash
# 1. Try the normal call. If shell times out or returns non-zero:
council discuss "..." --controller-position "..." --models claude,codex

# 2. Recover the discussion id from project state.
DISC_ID=$(council status --project-root "$ROOT" | jq -r .data.state.last_discussion_id)

# 3. Block until the discussion finishes (default budget 7200s = 2h).
council discussion wait "$DISC_ID" --project-root "$ROOT" --timeout 7200

# 4. Read the summary the wait command pointed at.
cat ".council/discuss/$DISC_ID/summary.md"
```

`DiscussionOrchestrator.run()` writes
`state.json::last_discussion_id` within ~50ms of starting (before any
LLM call), so the `council status` recovery path is reliable
even if the shell timed out very early.

#### Completion contract (dual condition)

Unlike `delegation wait`, which treats "record.json exists" as
completion, `discussion wait` requires **both**:

1. `record.status == "completed"` (the orchestrator finished the
   convergence loop), AND
2. `summary.md` is present and readable.

The dual condition is necessary because
`DiscussionOrchestrator.run()` writes `record.json(status="running")`
on start, so a single-condition check would return prematurely.

#### Error kinds (mirror `delegation wait`)

| `error_kind` | Triggered by |
|---|---|
| `wait_timeout` | Total wait exceeds `--timeout` seconds. |
| `discussion_not_found` | `.council/discuss/<id>/` does not exist. |
| `record_corrupt` | `record.json` exists but cannot be parsed as JSON. |
| `discussion_failed` | `record.status == "failed"` (e.g. participant unavailable). |
| `summary_missing` | `record.status == "completed"` but `summary.md` is absent or unreadable (rare write race). |

All non-zero kinds exit code 1 with a JSON error payload. Happy path
exits 0 with `data.summary_path` for the caller to read.

#### Defaults

- `--timeout`: 7200 seconds (2 hours), matching `delegation wait`.
- `--poll-interval`: 30 seconds.

#### Backward compatibility

- `council discuss "question"` behavior is **completely unchanged**.
  No new flags, no protocol shift.
- 0.1.5 callers that don't use `discussion wait` work exactly as
  before.
- 0.1.6 skill files reference `discussion wait`; on a 0.1.5
  CouncilFlow install the call returns "command not found" and the
  caller must fall back to manual recovery (the same posture as
  pre-0.1.6).

---

## Discussion Convergence Policy (0.1.3+)

`DiscussionSettings.convergence_policy` controls when the orchestrator
decides a multi-model discussion has converged. Evaluation happens in
`councilflow.controller.convergence_evaluator.evaluate()` and is a
pure function over already-computed `DiscussionTurn` fields — it
never calls an LLM.

### Three policies

| Policy | Behavior |
|---|---|
| `strict_count` (default) | Pre-0.1.3 behavior preserved. Converge when `completed_rounds >= min_rounds` AND every external turn in the latest round has `supports_current_direction=True`, `introduced_new_info=False`, no disagreements, no open questions. `max_rounds` caps. |
| `semantic` | Converge when the latest round's external turns show `introduced_new_info=False` AND no new disagreements beyond prior externals. `min_rounds` still acts as a hard floor — the first round cannot short-circuit even if externally agreed. `max_rounds` caps. |
| `hybrid` | Infer a coarse topic from the question text (`architecture` / `review` / `clarification` / `other`). Floor = `max(min_rounds, min_rounds_by_topic.get(topic, min_rounds))`. After the floor, apply `semantic` semantics. |

### `min_rounds_by_topic` usage

```yaml
discussion:
  convergence_policy: hybrid
  min_rounds: 1
  min_rounds_by_topic:
    architecture: 2
    review: 1
    clarification: 1
```

Topic inference is a cheap keyword match (no LLM):

- `architecture` matches questions containing `architect`, `design`, `structure`, `schema`, `topology`
- `review` matches `review`, `critique`, `feedback`, `audit`
- `clarification` matches `what is`, `how does`, `how do`, `clarif`, `explain`, `definition`, `meaning`
- Anything else falls under `other`

### `convergence_trace` artifact field

`DiscussionSummary.convergence_trace` is a list of per-round decision
records written alongside the existing discussion summary artifact:

```json
"convergence_trace": [
  {"round": 1, "reason": "min_rounds_not_met", "decision": "continue"},
  {"round": 2, "reason": "no_new_info",        "decision": "converge"}
]
```

The `reason` field is machine-readable and stable across the three
policies — it is the `ConvergenceDecision.reason` returned by the
evaluator. Values include `min_rounds_not_met`, `max_rounds`,
`awaiting_external_turn`, `external_agreed`, `no_new_info`,
`new_info_or_disagreements_present`, `external_not_yet_converged`,
`no_external_participants`, and
`topic_min_rounds_not_met:<topic>:<floor>` (hybrid only).

### Short-circuit guarantee (all policies)

If the discussion has zero external (non-controller) participants —
typically because `discuss --models` was de-duped against the current
controller — the evaluator converges immediately with
`reason="no_external_participants"`, regardless of policy. This
preserves the pre-0.1.3 short-circuit behavior for trivial discussions.

### Backward compatibility

When `.council/config.yaml` has no `convergence_policy` field, Pydantic
defaults to `"strict_count"`. In that mode, the evaluator's output
matches the legacy `_round_has_converged` check byte-for-byte —
confirmed by full regression across 311+ tests.
