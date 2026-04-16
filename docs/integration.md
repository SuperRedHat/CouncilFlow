# CouncilFlow Workflow Integration

## Purpose

This document defines the stable integration contract that `project-*` workflows can rely on when they call `CouncilFlow`.

The key rule is simple:

- `project-*` workflows never rely on hidden shared chat context.
- Every integration step reads an explicit artifact from `.council/`.
- The controller still owns synthesis and workflow continuation.

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

## Supported Entry Points

### `project-discuss`

Standalone discussion should call:

```bash
council discuss --question "<question>" --models claude,gpt
council discuss --question "<question>" --models gemini,codex
```

Expected persisted artifact:

- `.council/discuss/<discussion_id>/summary.md`

Expected machine-readable contract:

- `artifact_kind = discussion_summary`
- `summary_path`
- `question`
- `participants`
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
2. Wait for the summary artifact
3. Read the summary artifact from disk
4. Continue the main `project-*` step with the controller's own synthesis

### Delegation

Delegation-oriented workflow steps should call:

```bash
council delegate --role implementer --model claude --objective "<objective>" --task-summary "<summary>"
council delegate --role reviewer --model gemini --objective "<objective>" --task-summary "<summary>"
```

Expected persisted artifacts:

- `.council/delegations/<delegation_id>/handoff.yaml`
- `.council/delegations/<delegation_id>/result.md`

Expected machine-readable contract:

- `artifact_kind = delegation_handoff`
- `handoff_path`
- `result_path`
- `handoff_schema.id`
- `handoff_schema.role`
- `handoff_schema.objective`
- `handoff_schema.task_summary`
- `handoff_schema.constraints`
- `handoff_schema.relevant_files`
- `handoff_schema.inputs`
- `handoff_schema.expected_output`

## Consumption Rules

- The workflow must treat disk artifacts as the source of truth.
- The workflow must not assume provider-specific hidden memory.
- The controller decides whether a discussion or delegation result is accepted, retried, or ignored.
- Missing artifacts should be treated as failed or incomplete execution.
- Same-controller discuss requests should not trigger sidecar execution.
- Same-controller delegate requests should return local execution instead of starting a sidecar.
- Artifacts created under a Gemini-controlled session must remain consumable by Codex and Claude workflows.

## Minimum Integration Flow

1. `project-*` decides whether it needs `discuss` or `delegate`.
2. `CouncilFlow` writes artifacts into `.council/`.
3. `project-*` reads those artifacts explicitly.
4. The controller uses those artifacts to continue the main workflow.

This keeps the integration deterministic, inspectable, and portable across Codex, Claude Code, and Gemini CLI.
