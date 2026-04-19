# CouncilFlow 0.1.1 — Release Notes

**Released:** 2026-04-19
**Tag:** `v0.1.1`
**Install:** `pip install councilflow==0.1.1`

## What changed in one line

The Claude Code adapter now runs delegated subprocesses with
`--dangerously-skip-permissions`, matching the Gemini adapter's long-standing
`--approval-mode yolo`. Claude's per-project `.claude/settings.json::permissions.allow`
is no longer consulted during tester preflight.

## Why

A real project (chess) hit `permission_blocked` because a task's
`verification_commands` weren't pre-seeded into the project's allow-list. The
preflight was doing exactly what the 0.1.0 contract promised, but the
friction was in the wrong place:

- Delegated sidecars already run inside (a) a materialized worktree,
  (b) a deny-by-default writable-glob allow-list,
  (c) DEFAULT_PROTECTED_PATHS snapshot / restore, and
  (d) the role-scoped MCP policy.
- Adding a fifth layer — Claude's own per-command allow-list — didn't catch
  any additional unsafe behavior. It just blocked legitimate tester stages
  until the operator manually kept two declarations (which commands to run
  / which commands may run) in sync across `tasks.json` and
  `settings.json`.
- The Gemini adapter has always bypassed its equivalent gate via
  `--approval-mode yolo`. CouncilFlow now treats Claude the same way, so
  delegating a `tester` stage works identically regardless of which target
  model the config resolves to.

## Explicit trust model

Delegated execution in 0.1.1+ assumes the following four layers are the
enforcing layers:

1. **Isolated workspace** — materialized as a `git_worktree` (or `copy` /
   `none` per `IsolatedWorkspace.strategy`); the sidecar only sees what was
   copied in.
2. **Writable-glob allow-list** — `ImportManifest.writable_globs` is
   deny-by-default; anything the sidecar writes outside the allow-list is
   rejected on import-back.
3. **Protected workflow paths** — `DEFAULT_PROTECTED_PATHS` snapshots the
   host's `.claude/state`, `.council/state.json`, `.workflow-core`, and the
   per-controller skill directories before a stage runs; any mutation is
   rolled back and the stage fails with `error_kind=guardrail_violation`.
4. **MCP role policy** — `architect`, `planner`, `synthesizer` keep MCP
   access; `implementer`, `tester`, `reviewer`, `fixer`, `advisor` get an
   empty worktree-local MCP config so the host's `project-manager` is out of
   reach.

The `--dangerously-skip-permissions` flag name is intentionally loud. If you
can read the output of `ps` / process-explorer you'll see it in the argv
list; that's the psychological cost we chose to pay in exchange for removing
a friction point that was costing more than it protected.

## Codex CLI note

The Codex adapter does **not** force an approval-policy flag. If you
delegate to Codex, make sure your `~/.codex/config.toml::approval_policy`
(or per-project override) does not require interactive approval for
`codex exec` — otherwise a delegated `tester` stage will hang on an
approval prompt the sidecar can't satisfy. Recommended:
`approval_policy = "never"` or `"full-auto"` for machines that are used
primarily as delegation targets.

## Per-CLI summary

| CLI | Approval gate | 0.1.1 default |
| --- | --- | --- |
| Claude Code | `.claude/settings.json::permissions.allow` | `--dangerously-skip-permissions` in `CLAUDE_STREAM_FLAGS` |
| Gemini CLI | `--approval-mode` | `--approval-mode yolo` (unchanged) |
| Codex CLI | `~/.codex/config.toml::approval_policy` | Not forced — user-configured |

## Upgrade

No migration steps. Existing `.claude/settings.json` files keep working;
their `permissions.allow` arrays are simply no longer consulted by
CouncilFlow's preflight. You can delete entries that only existed to satisfy
the old preflight if you want to, but there's no requirement to do so.

## Tests

- 190 pytest cases (was 189); net +1 from replacing the old allow-list
  regression with two positive tests plus an adapter-flag pin.
- `ruff check .`: clean.
- Smoke harness still at 27 scenarios (no behavioral change there).

Full notes: `CHANGELOG.md` 0.1.1 entry.
