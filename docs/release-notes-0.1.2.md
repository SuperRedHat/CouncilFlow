# CouncilFlow 0.1.2 — Release Notes

**Released:** 2026-04-19
**Tag:** `v0.1.2`
**Install:** `pip install councilflow==0.1.2`

## What changed in one line

`materialize_workspace` now overlays the host's uncommitted changes
(untracked, modified, and deleted files) onto the sidecar worktree created
by `git worktree add --detach HEAD`, so every delegation phase sees the
same source the controller does — not the last committed snapshot.

## Why

0.1.1 removed the Claude permission preflight and immediately exposed the
deeper issue: a freshly-added `git worktree` at HEAD doesn't include
uncommitted files. In a real chess project workflow, `implementer` imported
the new `board-view` files into the host source, `tester` then spun up its
own worktree, and that worktree checked out HEAD — which didn't contain
the new files. `pnpm exec vitest run tests/unit/features/board-view` saw
empty modules and failed. The controller's only workaround was to commit
the intermediate state before running tester, breaking the "review before
commit" pattern the workflow is supposed to enable.

This is the mirror-image of the TASK-058 fix (baseline-driven diff for
import-back): that one made sidecar → host correct; 0.1.2 makes host →
sidecar correct.

## What gets overlaid

After `git worktree add --detach HEAD` succeeds, CouncilFlow now copies
the following onto the fresh worktree:

| Host state | Overlay action |
| --- | --- |
| Untracked new file (respecting `.gitignore`) | Copy into worktree |
| Modified tracked file | Overlay working-tree content over HEAD version |
| Deleted tracked file (working-tree delete, not yet committed) | Remove from worktree copy of HEAD |
| `.gitignore`d file | Leave out of worktree |
| Path matching `IsolatedWorkspace.exclude_patterns` (e.g. `.claude/**`) | Leave out of worktree |

Order: `.gitignore` is checked first via `git ls-files --others
--exclude-standard`, then `exclude_patterns` is applied on top. Both gates
have to accept a path before it lands in the sidecar.

## Before vs. after (the TASK-007A repro)

Before 0.1.2:

```text
host:  src/features/board-view/*.ts  (untracked)
       tests/unit/features/board-view/*.test.ts  (untracked)
       # controller imports them from the implementer stage.

council delegate --role tester --model claude
  → git worktree add --detach HEAD
  → worktree contains only the last committed files
  → pnpm exec vitest run tests/unit/features/board-view
  → "no test files found" or "empty module" — false negative
```

After 0.1.2:

```text
council delegate --role tester --model claude
  → git worktree add --detach HEAD
  → _overlay_uncommitted_files copies the board-view files in
  → pnpm exec vitest run tests/unit/features/board-view
  → actual tests run, actual results reported
```

## Upgrade

No migration steps. If you were workarounds that involved committing
intermediate state before running `tester` or `reviewer`, you can stop
doing that.

## Tests

- 201 pytest cases (was 191, net +10 from `tests/test_workspace_overlay.py`).
- 29-scenario live smoke (was 27, +2 overlay scenarios S28/S29).
- `ruff check .`: clean.

## Related

- `docs/release-notes-0.1.1.md` — the preflight permission-gate removal
  that made the overlay bug observable.
- `docs/integration.md` — sidecar isolation contract and the new
  "Permission and approval model per CLI" section.

Full notes: `CHANGELOG.md` 0.1.2 entry.
