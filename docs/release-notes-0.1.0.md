# CouncilFlow 0.1.0 — Release Notes

**Released:** 2026-04-19
**Tag:** `v0.1.0`
**Install:** `pip install councilflow` (optional OpenAI advisor:
`pip install 'councilflow[openai]'`)

## What is CouncilFlow?

CouncilFlow is a CLI-first, local-first sidecar for multi-model collaboration.
A single controller — Codex CLI, Claude Code CLI, or Gemini CLI — stays in
charge of a project's workflow and calls `council discuss`, `council delegate`,
or `council synthesize` when another model should weigh in. Everything
persists under `.council/` in the repo so the workflow is reproducible and
auditable offline.

## Highlights

- **Three-controller parity.** Works the same way under Codex CLI, Claude
  Code CLI, and Gemini CLI. Detection picks the right controller from env
  signals; `controller_override` in `.council/config.yaml` pins it
  deterministically.
- **Route-first hard contract.** Every `delegate` / `discuss` call returns a
  structured `local_execution` / `delegated` / `error` status. The controller
  never executes until routing says so.
- **Sidecar isolation.** Each delegation materializes an isolated workspace
  (git worktree by default). Baseline-driven diff means only the sidecar's
  own edits come back. `writable_globs` is deny-by-default, and a hardened
  set of protected paths (`.claude/state`, `.council/state.json`,
  `.workflow-core`, per-controller skills) is snapshotted and restored if a
  delegated role touches them.
- **MCP role policy.** `architect`, `planner`, and `synthesizer` keep MCP;
  execution roles (`implementer`, `tester`, `reviewer`, `fixer`, `advisor`)
  run with a worktree-local empty MCP config so the host's `project-manager`
  cannot silently write workflow state from a delegated subprocess.
- **Two-hour budget for long stages.** Provider total timeout is 7200 s, and
  the new `council delegation wait <id>` subcommand lets controllers poll
  `record.json` from a non-blocking shell when their own command timeout is
  shorter than the real work.
- **Structured failure kinds everywhere.** `adapter_missing`,
  `guardrail_violation`, `recursive_workflow_violation`, `wait_timeout`,
  `environment_not_ready`, `permission_blocked`, `total_timeout`, etc., so
  skills can branch on cause instead of pattern-matching stderr.
- **Tested.** 189 pytest cases plus a 27-scenario live smoke harness
  (`.smoke/full_live_smoke.py`).

## Upgrade / install

```bash
pip install councilflow==0.1.0

# Optional OpenAI advisor for the `gpt` family
pip install 'councilflow[openai]==0.1.0'
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4o-mini  # optional override
```

Existing project root:

```bash
council status   # bootstraps .council/config.yaml on first run
```

## Command reference

| Command | Purpose |
| --- | --- |
| `council version` | Show the installed version. |
| `council status` | Print current controller, language, and recent run records. |
| `council discuss "<question>" --controller-position "<stance>" [--models ...]` | Multi-model discussion with explicit controller stance. |
| `council delegate --role <role> --objective "..." --task-summary "..."` | Route a role stage; returns `local_execution` or `delegated`. |
| `council synthesize --artifact a --artifact b` | Combine artifacts into a single synthesis. |
| `council delegation wait <id> --timeout 7200` | Poll `.council/delegations/<id>/record.json` until completed / failed / timeout. |

See `docs/integration.md` for the workflow-failure report protocol, the
sidecar isolation contract, and the full provider / adapter map.

## Breaking changes

None — this is the initial release.

## Known limitations

- Real-CLI HTTP smoke runs are manual (the packaged harness stays offline).
- Non-Windows `mklink /J` dependency-symlink behaviour is covered by unit
  tests but not the packaged live smoke.
- MCP policy on CLIs that ignore worktree-local settings still relies on the
  post-execution guardrail as a backstop. When a delegated subprocess does
  trigger that guardrail, the stage exits with
  `error_kind=guardrail_violation` and the workflow state is restored.

## Credits

Co-authored by Claude Opus 4.7 (1M context) under the `project-next`
workflow and verified against:

- Full pytest: 189 / 189 green
- `ruff check .`: clean
- Live smoke (`.smoke/full_live_smoke.py`): 27 / 27 green
- Full smoke report: `docs/full-smoke-report-2026-04-19.md`
