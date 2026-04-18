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
  execution. The preflight result should explicitly state whether the sidecar is ready, whether the
  workspace and required commands are available, and whether command permissions are blocked before
  any verification command is attempted.
- `tester` artifacts should distinguish `verification_failed`, `permission_blocked`, and
  `environment_not_ready` instead of collapsing all three into a generic test failure.
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
