# CouncilFlow Workflow Integration

## Purpose

This document defines the stable integration contract that `project-*` workflows can rely on when they call `CouncilFlow`.

The key rule is simple:

- `project-*` workflows never rely on hidden shared chat context.
- Every integration step reads an explicit artifact from `.council/`.
- The controller still owns synthesis and workflow continuation.
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
- `project-next`: `implementer -> tester -> [fixer -> tester]* -> synthesizer`

Phase-machine rules:

- Each stage must declare a `role`, `objective`, `task_summary`, required upstream artifacts, and
  expected output.
- The host workflow must not infer permission to keep going; it must react to an explicit route
  result for each stage.
- `verification_commands` and `verification_profile` belong to the `tester` stage. They are stage
  inputs, not an automatic controller-local action after `implementer` finishes.
- If a `tester` stage reports failure, the workflow must enter `fixer` and then return to `tester`
  for re-verification.
- `project-feedback` may close a gate, reopen a task, or create a follow-up fix/review task, but it
  must not silently act as `tester` or `fixer` without a new routed execution stage.

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
council delegate --role tester --objective "<objective>" --task-summary "<summary>" --input verification_commands="pnpm exec vitest run" --required-artifact implementer_result=.council/delegations/del_x/result.md --next-on-success "Continue to synthesis or status update." --next-on-failure "Enter fixer, then rerun tester."
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
- When `council` is available, workflows must not start role work until they receive either
  `data.status = local_execution` or a delegated artifact set.
- Role-driven workflows must interpret `verification_commands` as `tester` inputs and must not let
  the controller run them locally unless the `tester` stage itself returned `local_execution`.
- Tester/fixer loops should use `required_artifacts` and `next_actions_on_*` from the handoff
  package/result contract instead of inferring stage transitions from hidden controller state.
- If a manual gate fails, `project-feedback` should reopen the task or create a follow-up routed
  repair task instead of directly performing fixer/tester work inside the gate-closing workflow.
- If `council delegate` or `council discuss` returns an error, workflows must stop and surface that
  failure instead of silently switching to local execution.

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
7. `project-next` loops through `implementer -> tester -> [fixer -> tester]*` until verification
   succeeds, then hands final synthesis/status updates back to the controller.

This keeps the integration deterministic, inspectable, and portable across Codex, Claude Code, and Gemini CLI.
