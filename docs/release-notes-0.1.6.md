# CouncilFlow 0.1.6 — `council discussion wait` recovery subcommand

**Release date:** 2026-04-21
**Type:** Patch release (closes the asymmetric gap between
`council delegate` and `council discuss` that has existed since 0.1.0).
**Upgrade path:** `pipx upgrade councilflow`; re-sync skills if you
maintain `~/.workflow-core/skills/` manually.

## Why this release exists

Since 0.1.0, `council delegate` has had `council delegation wait <id>`
as a recovery path: when the controller's shell command times out
before the delegation finishes, the caller can poll
`.council/delegations/<id>/record.json` for up to 2 hours instead of
declaring `workflow_failure`. The skill `project-next` made this a
hard prerequisite as part of the timeout protocol.

`council discuss` had no equivalent. Multi-model discussions
(typically 5 rounds × 2-3 critic models = 3-10 minutes) routinely
exceed the 3-4 minute shell command timeout in desktop CLI hosts
(Claude Code / Codex / Gemini). When that happened, the subprocess
kept running and `summary.md` eventually landed at
`.council/discuss/<id>/summary.md`, but the caller had to manually
`ls .council/discuss/` to find it. There was no programmatic recovery
path.

This was masked for a long time because most discussions in the
CouncilFlow dev project itself ran with `controller=claude` and
`models=claude` (effectively local execution, no shell timeout). The
gap surfaced on 2026-04-21 when an SDL project init via Gemini
controller hit it on every `council discuss` call.

## What changed — user visible

### New: `council discussion wait <id>`

```bash
# Caller's normal flow:
council discuss "..." --controller-position "..." --models claude,codex

# If the call above times out at the shell layer (3-4 min typical),
# don't declare failure. Recover:
DISC_ID=$(council status --json --project-root "$ROOT" \
  | jq -r .data.state.last_discussion_id)
council discussion wait "$DISC_ID" --project-root "$ROOT" --timeout 7200

# Read the summary:
cat ".council/discuss/$DISC_ID/summary.md"
```

The recovery path is reliable because
`DiscussionOrchestrator.run()` writes
`state.json::last_discussion_id` within ~50ms of starting, before
any LLM call. So even if the shell killed your `council discuss`
process (which doesn't actually kill the discussion subprocess), the
id is in state.json.

### Naming choice: `discussion` not `discuss`

The new subcommand is `council discussion wait <id>` (noun form),
matching the existing `council delegation wait <id>` pattern. This
preserves `council discuss "question"` (verb form) unchanged — Typer
cannot register both `discuss` as a top-level command and `discuss`
as a sub-app for nested commands.

### Skill protocols updated

Four skills add a hard-prerequisite shell-timeout recovery section:
`project-init`, `project-design`, `project-change`, `project-ask`.
Each of them invokes `council discuss` somewhere in its flow; each
now documents the recovery protocol explicitly. Both
`D:/project/AutoSkills/skills/` and `~/.workflow-core/skills/` are
synced.

## What changed — under the hood

- **`src/councilflow/cli/discuss_wait.py`** (new file, ~280 LOC):
  implements the subcommand, mirrors `cli/delegation.py`'s structure
  but uses dual-condition completion. Module docstring explains the
  shell-timeout vs provider-timeout (7200s) mismatch and the
  rationale for dual conditions.
- **`src/councilflow/cli/app.py`**: registers the new sub-app and
  adds `discussion` to `_ALLOWED_RECURSIVE_SUBCOMMANDS` so
  delegated sidecars can also poll discussion artifacts (read-only,
  matching the `delegation` allowance).
- **`tests/test_cli_discuss_wait.py`** (new file): 8 tests covering
  all 7 error/success scenarios + a `--help` smoke.
- **No changes to `cli/discuss.py`**: the existing
  `council discuss "question"` command is untouched. Audit confirmed
  the `discussion_id` is already written to state.json early enough
  that recovery via `council status --json` is reliable; no need to
  modify discuss.py's stderr behavior.

## Completion contract

Unlike `delegation wait`, where "record.json exists" means
completion, `discussion wait` requires **both**:

1. `record.status == "completed"` — the orchestrator finished its
   convergence loop, AND
2. `summary.md` is present and readable.

Why dual: `DiscussionOrchestrator.run()` writes
`record.json(status="running")` immediately on start, so the
single-condition "record exists is enough" pattern would return
prematurely. The polling loop also tolerates the brief window
between `record.status` flipping to `completed` and `summary.md`
landing on disk (rare write race).

## Error kinds

| `error_kind` | Triggered by |
|---|---|
| `wait_timeout` | Total wait exceeds `--timeout` seconds (default 7200). |
| `discussion_not_found` | `.council/discuss/<id>/` does not exist. |
| `record_corrupt` | `record.json` exists but cannot be parsed. |
| `discussion_failed` | `record.status == "failed"` (e.g. participant unavailable). |
| `summary_missing` | `record.status == "completed"` but `summary.md` is absent or unreadable. |

All non-zero kinds exit code 1 with structured JSON error payload.

## Backward compatibility

- `council discuss "question"` behavior is **completely unchanged**.
- All 110 done tasks across 0.1.0 → 0.1.5 untouched.
- `.council/config.yaml` schemas unchanged.
- `--allow-workflow-state-write` and `PROTECTED_WORKFLOW_PATHS`
  unchanged.
- 0.1.6 skill files reference `council discussion wait`; on a
  0.1.5 CouncilFlow install the call returns "command not found"
  and the caller must fall back to manual recovery — same posture
  as pre-0.1.6.

## Test coverage

- **355 pytest cases** (was 347 at 0.1.5, +8 new):
  `tests/test_cli_discuss_wait.py` covers all 7 scenarios plus
  `--help` smoke. Polling loop verified by `monkeypatch`-ing
  `time.sleep` to inject a record state transition mid-poll.
- `ruff check src/ tests/`: clean.

## Operator guidance

No config migration. Two operational steps worth doing:

1. **Re-sync workflow skills.** If you maintain
   `~/.workflow-core/skills/` manually, copy
   `project-init/SKILL.md`, `project-design/SKILL.md`,
   `project-change/SKILL.md`, `project-ask/SKILL.md` from
   `D:/project/AutoSkills/skills/` — or run `sync-skills.ps1`.
   Skills that stay at 0.1.5 will keep working but won't include the
   shell-timeout recovery protocol; users will continue to manually
   `ls .council/discuss/` after a timeout.

2. **If you noticed `council discuss` hanging then "failing" while
   the artifact actually appeared on disk later** — that was this
   gap. 0.1.6 closes it.

## Known limitations unchanged from 0.1.5

- Real-CLI adapter smoke (live HTTP requests) is manual.
- MCP policy is best-effort on CLIs that ignore worktree-local
  settings; the workspace-import guardrail remains the final
  backstop.
- Skills are not auto-synced on `pipx upgrade` — you still need to
  re-sync manually or via the helper script.

---

See `CHANGELOG.md` `[0.1.6]` for the structured entry,
`docs/integration.md` "Discuss wait (0.1.6+)" for the reference, and
`docs/discuss-wait-smoke-report-2026-04-21.md` for the clean-project
recovery evidence used to accept this milestone.
