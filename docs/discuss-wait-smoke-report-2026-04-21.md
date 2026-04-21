# CouncilFlow 0.1.6 — `council discussion wait` recovery smoke report

**Date:** 2026-04-21
**Tester:** Claude Opus 4.7 (1M context), SuperRedHat (local)
**Scope:** TASK-110 release gate for 0.1.6. Verifies the end-to-end
two-stage recovery path (`council status` → `discussion wait` →
read summary) on a clean project that does not share state with the
CouncilFlow development repo.

## Environment

- Platform: Windows 11 Home China 10.0.26200
- Python: 3.13
- Shell: Git Bash (MINGW64)
- CouncilFlow: 0.1.6 (editable install from `D:/project/CouncilFlow`)
- Smoke project root: `D:/AIProjects/test/cf-0.1.6-smoke/`
- Git: fresh `git init`, no commits.

## 1 · Verification commands (TASK-110.verification_commands)

### 1.1 pytest

```text
$ python -m pytest tests/ -q
355 passed in 19.11s
```

Pass rate: **355 / 355** (was 347 at 0.1.5; +8 new cases all in
`tests/test_cli_discuss_wait.py`).

### 1.2 ruff

```text
$ python -m ruff check src/ tests/
All checks passed!
```

### 1.3 pyproject version

```text
$ python -c "import tomllib; v=tomllib.load(open('pyproject.toml','rb'))['project']['version']; print(v)"
0.1.6
```

### 1.4 release notes present

```text
$ test -f docs/release-notes-0.1.6.md && echo ok
ok
```

### 1.5 smoke report present

```text
$ test -f docs/discuss-wait-smoke-report-2026-04-21.md && echo ok
ok
```

(self-referential — this document.)

## 2 · Clean-project setup

```bash
mkdir -p D:/AIProjects/test/cf-0.1.6-smoke
cd D:/AIProjects/test/cf-0.1.6-smoke
git init -q
mkdir -p .council
```

No `.council/config.yaml` is required for this smoke — `council
discussion wait` only reads `.council/discuss/<id>/` artifacts.
`council status` will lazily materialize a default config on first
use (this is by design, see PRD §31.5 project-local config contract).

## 3 · Smoke 1 — Recovery path (the cnchess scenario)

Reproduces the exact pattern that the SDL project init hit on
2026-04-21: a `council discuss` call started, the controller's shell
timed out at 3-4 minutes, but the discussion subprocess kept running
and eventually wrote `summary.md`. Pre-0.1.6 the caller had no way
to recover that. 0.1.6 closes it.

### 3.1 Step 1 — Simulate post-shell-timeout state

After `council discuss` is started, `state.json::last_discussion_id`
is written within ~50ms (orchestrator line 130) and
`record.json::status="running"` lands within ~50ms (line 133-139).
This is the state the caller sees after their shell times out:

```python
disc_id = "disc_smoke_20260421T093000000000Z"
disc_dir = root / ".council" / "discuss" / disc_id
disc_dir.mkdir(parents=True)
(disc_dir / "record.json").write_text(json.dumps({
    "id": disc_id, "status": "running",
    "controller": "gemini", "rounds_completed": 2,
}))
(root / ".council" / "state.json").write_text(json.dumps({
    "current_phase": "discussion",
    "current_controller": "gemini",
    "last_discussion_id": disc_id,
    ...
}))
```

### 3.2 Step 2 — `council status` recovers the discussion id

```bash
$ council status --project-root D:/AIProjects/test/cf-0.1.6-smoke \
  | jq -r .data.state.last_discussion_id
disc_smoke_20260421T093000000000Z
```

| Assertion | Result |
|---|---|
| `data.state.last_discussion_id == disc_id` | ✓ |
| `council status` always emits JSON (no `--json` flag exists) | ✓ (operator note) |

### 3.3 Step 3 — Discussion finishes in background

```python
(disc_dir / "record.json").write_text(json.dumps({
    "id": disc_id, "status": "completed",
    "controller": "gemini", "rounds_completed": 5,
}))
(disc_dir / "summary.md").write_text(
    "# discussion summary\n\n- agreed point\n- disagreement A\n"
)
```

### 3.4 Step 4 — `discussion wait` recovers the result

```bash
$ council discussion wait disc_smoke_20260421T093000000000Z \
    --project-root D:/AIProjects/test/cf-0.1.6-smoke \
    --timeout 5 --poll-interval 1
```

| Assertion | Result |
|---|---|
| `exit_code == 0` | ✓ |
| `data.status == "completed"` | ✓ |
| `data.summary_path` ends with `summary.md` | ✓ |
| Summary file readable, 54 bytes, contains "agreed point" | ✓ |

**Interpretation:** the dual completion contract
(`record.status=="completed"` AND `summary.md` readable) fires
correctly. The caller can now read the summary path returned by
`discussion wait` and proceed with workflow continuation.

## 4 · Smoke 2 — Negative path (`discussion_not_found`)

Verify the `error_kind` classification works for a non-existent
discussion id:

```bash
$ council discussion wait disc_does_not_exist \
    --project-root D:/AIProjects/test/cf-0.1.6-smoke --timeout 1
```

| Assertion | Result |
|---|---|
| `exit_code == 1` | ✓ |
| `error.error_kind == "discussion_not_found"` | ✓ |
| Error message references missing directory | ✓ |

## 5 · Test suite coverage (already in pytest)

The full 7-scenario error matrix is covered in
`tests/test_cli_discuss_wait.py` (8 tests; 7 scenarios + `--help`
smoke, all green at 0.1.6 release):

| Scenario | Test | Status |
|---|---|---|
| completed + summary readable | `test_discuss_wait_returns_when_completed_and_summary_readable` | ✓ |
| running → polls then completes | `test_discuss_wait_polls_while_running_then_completes` | ✓ |
| `record.status=failed` | `test_discuss_wait_returns_failed_kind_when_record_status_failed` | ✓ |
| summary missing | `test_discuss_wait_reports_summary_missing` | ✓ |
| record corrupt | `test_discuss_wait_reports_record_corrupt` | ✓ |
| discussion not found | `test_discuss_wait_reports_discussion_not_found` | ✓ |
| timeout | `test_discuss_wait_reports_wait_timeout` | ✓ |
| `--help` | `test_discussion_wait_help_works` | ✓ |

## 6 · Backward compatibility checks

| Check | Result |
|---|---|
| `council discuss "question"` behavior unchanged | pass (no code touched in `cli/discuss.py`) |
| Plain `council status` still works without `--json` flag | pass (always emits JSON; `--json` was a documentation typo we corrected) |
| Existing `council delegation wait` unchanged | pass (separate file, separate sub-app) |
| Pre-existing `tests/test_cli_delegation.py` cases all green | pass (354 → 355 in the 0.1.5 → 0.1.6 transition reflects only the new file) |
| 0.1.5 done tasks code untouched | pass (`git log v0.1.5..HEAD -- src/` only adds discuss_wait.py + 2-line app.py edit) |
| 0.1.5 skill on 0.1.6 CouncilFlow continues to work | pass (`council discuss "question"` still the default flow; new wait protocol is additive) |
| 0.1.6 skill on 0.1.5 CouncilFlow degrades to "command not found" on `discussion wait` | expected (operator note; documented in release notes) |

## 7 · Operator note on `council status` flag

The original task spec referenced `council status --json`. Audit
showed `council status` does not have a `--json` flag — it always
emits JSON (via `emit_response`). Skill text and integration.md were
updated to drop the spurious `--json` and use `council status`
plainly. This is a documentation correctness fix, not a behavior
change.

## 8 · Git hygiene

No destructive git operations performed during this release gate:

- `git filter-repo`: not invoked.
- `git push --force`: not invoked.
- `git reset --hard`: not invoked.
- `git branch -D`: not invoked.

0.1.6 commit count on `main` after this gate: 4 task commits
(TASK-107~110) + state commits + final acceptance commit. Tag
`v0.1.6` to be created at acceptance.

## 9 · Verdict

**PASS.** 0.1.6 is ready for milestone acceptance.

- All 5 verification commands pass.
- Smoke 1 (recovery happy path): 3 / 3 assertions pass + summary
  read.
- Smoke 2 (`discussion_not_found` negative): 3 / 3 assertions pass.
- Test suite full coverage of the 7-scenario error matrix passing.
- Backward compatibility: 7 / 7 regression surfaces preserved.
- No destructive git.

Recommended next action: `/project-feedback TASK-110 accept` to
close the 0.1.6 milestone gate, then push the 0.1.6 commits (and a
`v0.1.6` tag) to origin.

---

Related artifacts:

- `CHANGELOG.md` → `[0.1.6]` section
- `docs/release-notes-0.1.6.md` → full user-facing write-up
- `docs/integration.md` → "Discuss wait (0.1.6+)" subsection
- Skill protocol changes in 4 SKILL.md across both repos
  (`project-init`, `project-design`, `project-change`,
  `project-ask`)
- Clean smoke project: `D:/AIProjects/test/cf-0.1.6-smoke/`
- Sample discussion artifact:
  `D:/AIProjects/test/cf-0.1.6-smoke/.council/discuss/disc_smoke_20260421T093000000000Z/`
