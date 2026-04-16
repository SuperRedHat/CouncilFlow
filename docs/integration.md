# CouncilFlow Workflow Integration

## Purpose

This document defines the stable integration contract that `project-*` workflows can rely on when they call `CouncilFlow`.

The key rule is simple:

- `project-*` workflows never rely on hidden shared chat context.
- Every integration step reads an explicit artifact from `.council/`.
- The controller still owns synthesis and workflow continuation.

## Supported Entry Points

### `project-discuss`

Standalone discussion should call:

```bash
council discuss --question "<question>" --models claude,gpt
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

## Minimum Integration Flow

1. `project-*` decides whether it needs `discuss` or `delegate`.
2. `CouncilFlow` writes artifacts into `.council/`.
3. `project-*` reads those artifacts explicitly.
4. The controller uses those artifacts to continue the main workflow.

This keeps the integration deterministic, inspectable, and portable across Codex and Claude Code.

