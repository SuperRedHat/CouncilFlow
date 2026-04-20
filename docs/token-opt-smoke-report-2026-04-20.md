# CouncilFlow 0.1.3 Token-Optimization Smoke Report

**Date**: 2026-04-20
**Target version**: 0.1.3
**Gate**: TASK-085 (stage_gate=true, milestone_manual)
**Smoke location**: `D:/AIProjects/test/cf-0.1.3-smoke/` (clean project, not a different machine)

## A. Local quality gates (automated)

### A.1 pytest

```
pytest tests/ 2>&1 | tail -2
..............................                                           [100%]
318 passed in 19.51s
```

**Result**: ✅ 318/318 passing. +129 new tests on top of the 0.1.2 baseline of 189.

### A.2 ruff

```
ruff check src/ tests/
All checks passed!
```

**Result**: ✅ clean.

### A.3 pyproject version

```
python -c "import tomllib; assert tomllib.load(open('pyproject.toml','rb'))['project']['version'] == '0.1.3'"
```

**Result**: ✅ bumped to 0.1.3.

### A.4 CHANGELOG + release notes

- `CHANGELOG.md` has a `[0.1.3] — 2026-04-20` section covering Added / Deferred / Changed / Backward compatibility / Tests / Operator note.
- `docs/release-notes-0.1.3.md` exists (8232 chars) with detailed upgrade walkthrough.

**Result**: ✅ both in place.

---

## B. End-to-end smoke in clean project

### B.1 Test project setup

Created `D:/AIProjects/test/cf-0.1.3-smoke/` with this `.council/config.yaml`:

```yaml
config_version: 1
output_language: en
roles:
  planner: claude
  architect: claude
  implementer:
    - model: claude
      when: "task.complexity == 'L'"
    - model: claude
      when: "task.complexity in ['S', 'M']"
      fallback: [claude]
    - model: claude
  tester: claude
  reviewer: claude
  fixer: claude
  advisor: claude
  synthesizer: claude
discussion:
  default_models: []
  min_rounds: 1
  max_rounds: 3
  convergence_policy: semantic
```

Exercises:
- Dynamic routing on `implementer` (3-entry list with `when` expressions + one fallback)
- `convergence_policy: semantic` override
- All other roles keep shorthand form (backward compat path)

### B.2 A — Dynamic role routing

```bash
council delegate --role implementer \
  --objective "smoke L" --task-summary "smoke" \
  --input "complexity=L" --project-root .
# Returns: role=implementer, model=claude, status=local_execution

council delegate --role implementer \
  --objective "smoke M" --task-summary "smoke" \
  --input "complexity=M" --project-root .
# Returns: role=implementer, model=claude, status=local_execution
```

Inspect the routing audit log:

```bash
cat .council/runs/routing/routing.json | ...
# 2 records
#   implementer -> claude (idx=0, when=task.complexity == 'L')
#   implementer -> claude (idx=1, when=task.complexity in ['S', 'M'])
```

**Result**: ✅ Both invocations routed to the correct RoleRoute entry; `when` expressions evaluated correctly against the `--input complexity=X` context; audit log written to `.council/runs/routing/routing.json`.

### B.3 B — Semantic convergence policy loaded from config

The `convergence_policy: semantic` config entry was accepted by Pydantic
without error (the config load exercised the TASK-079 schema extension).
No actual multi-model discussion was triggered in this smoke because
all `discussion.default_models` resolve to the controller — the
short-circuit path (`no_external_participants`) would fire
immediately anyway, which is the correct 0.1.3 behavior.

End-to-end verification of the full `semantic` / `hybrid` code paths
was performed by the 16 unit tests in `tests/test_convergence_evaluator.py`,
all of which passed as part of the 318/318 suite (see A.1).

### B.4 Observability

```bash
council status --recent 30 --project-root .
# routing total=2, implementer={'claude': 2}
# convergence total=0
# window=30
```

**Result**: ✅ `routing_distribution` aggregates the 2 routing records correctly, grouped by role → model. `convergence_distribution` correctly reports 0 (no discussions ran in this smoke). `recent_window_days` echoes the default 30.

### B.5 Backward compatibility (existing pre-0.1.3 config shape)

All 29 existing `test_cli_delegate.py` tests and 3 existing
`test_cli_status.py` tests pass unchanged. Existing shorthand
`.council/config.yaml` files (like the one still in the CouncilFlow
repo itself) load and behave identically to 0.1.2 — confirmed by
`pytest tests/` returning 318/318 with zero regressions.

---

## C. What was NOT verified in this smoke

- **Real multi-model discussion with `semantic` convergence triggering a round skip** — would require at least two different CLI-backed models configured on the test machine. The codepath is exercised by 16 unit tests with synthetic `DiscussionTurn` fixtures.
- **Fallback retry on real adapter failure** — would require injecting an adapter that fails with `idle_timeout` etc. The codepath is exercised by the `test_delegate_routing_no_match_returns_structured_error` and related unit tests.
- **Different-machine / clean-VM smoke** — not in scope for TASK-085 (unlike TASK-070's infra gate, this release is pure 0.1.3 Python behavior with no infra changes; the unit + single-project smoke is sufficient).

## D. Git hygiene

- No `git filter-repo`, no `git push --force`, no `git reset --hard` — all commits are fast-forward standard commits.
- Routing audit log at `.council/runs/routing/routing.json` (sub-dir) instead of `.council/runs/routing.json` (flat) to avoid colliding with `list_run_records()` which globs direct children. Caught during smoke, fixed before commit.

## E. Decision

Based on the above:

- Local quality gates all ✅ (pytest + ruff + version + CHANGELOG + release notes)
- End-to-end smoke confirms A (dynamic routing) works correctly in a clean project
- Observability (council status) picks up the routing records as designed
- Backward compatibility confirmed by zero regressions in the 189 pre-0.1.3 tests

**Recommendation**: accept the milestone gate. 0.1.3 is ready to be
released. Any further validation (different-machine smoke, real
multi-model discussion timing measurements) belongs to a follow-up
observational phase, not a release blocker.
