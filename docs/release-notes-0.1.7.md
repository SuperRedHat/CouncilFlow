# CouncilFlow 0.1.7 — discussion uncap, delegate validation, default tuning

**Release date:** 2026-05-12
**Type:** Patch release (bug fixes + packaged-default refresh).
**Upgrade path:** `pipx upgrade councilflow`. No skill or
config changes required for existing projects.

## Why this release exists

While running 0.1.6 against `D:/project/simplatform` on 2026-05-12,
three independent issues surfaced in quick succession:

1. A user had set `discussion.max_rounds: 10` in their project's
   `.council/config.yaml` and observed every discussion stopping at
   round 5 with `ended_reason="max_rounds_reached"`. The configured
   ceiling was being silently overridden.
2. The same investigation noticed that
   `tests/test_cli_delegate.py::test_delegate_command_rejects_invalid_input_shape`
   was a long-standing red test on `main` — the CLI was accepting
   malformed `--input` payloads on the local-execution path and
   only validating them once a real sidecar had been resolved.
3. The packaged `templates/default-config.yaml` carried defaults
   that no longer matched how operators actually configure the tool
   on first use (claude in three role slots, empty discuss roster,
   sub-minute timeouts that were too short for real delegations).

None of these break the CLI surface, but together they made first-run
behavior surprising for the simplatform operator and risked the same
surprise for any new project. 0.1.7 closes all three in one patch.

## What changed — user visible

### `council discuss` honors `max_rounds` for one-on-one critiques

Before:

```yaml
# .council/config.yaml
discussion:
  default_models: [claude, codex]
  max_rounds: 10
```

```bash
council discuss "Should we adopt approach A?"
# 5 rounds in, ended_reason=max_rounds_reached, no error.
```

After 0.1.7, the same command runs up to 10 rounds (or terminates
earlier through normal `convergence_evaluator` rules once
`min_rounds` is satisfied and the participants stop introducing new
information).

The clamp lived in
`src/councilflow/controller/discussion_orchestrator.py:108` since
the original multi-model discussion landing (`93af08c`):

```python
allowed_rounds = min(max_rounds, 5) if len(external_models) == 1 else max_rounds
```

There was no comment, no test naming it, and no documentation. It
was almost certainly added defensively ("1v1 critique tends to spin
in circles, so cap it"), but it overrode the user's explicit
configuration. Now:

```python
allowed_rounds = max_rounds
required_rounds = min(min_rounds, allowed_rounds)
```

`required_rounds` continues to pull `min_rounds` down to
`allowed_rounds` when the caller passes `min_rounds > max_rounds`,
so that edge case is still safe.

**Behavior implication:** If your project habitually runs
single-external discussions that produce no new agreements, they
will now run to the upper bound. To preserve 0.1.6 behavior
explicitly, set `discussion.max_rounds: 5`.

### `council delegate` rejects malformed `--input` even on local execution

Before:

```bash
council delegate --role tester --objective ... --task-summary ... \
                 --input not-a-pair
echo $?  # 0 — malformed input silently ignored when target == controller
```

After:

```bash
council delegate --role tester --objective ... --task-summary ... \
                 --input not-a-pair
# Error: --input expects KEY=VALUE items, got 'not-a-pair'.
echo $?  # 2
```

Cause: `cli/delegate.py` ran `_parse_key_value_items()` after the
`local_execution` short-circuit. When the resolved target model
matched the active controller, the command returned successfully
*before* the validator ran. Validation moved upstream of route
resolution; the same parsed dict is reused downstream so the
non-local path is unaffected.

This restores the contract asserted by
`tests/test_cli_delegate.py::test_delegate_command_rejects_invalid_input_shape`
which had been a pre-existing red test on `main` since at least
0.1.5.

### `templates/default-config.yaml` defaults refreshed

| Field                                          | 0.1.6 default | 0.1.7 default        |
|------------------------------------------------|---------------|----------------------|
| `roles.implementer`                            | `claude`      | `codex`              |
| `roles.tester`                                 | `claude`      | `codex`              |
| `roles.advisor`                                | `claude`      | `codex`              |
| `discussion.default_models`                    | `[]`          | `[codex, claude]`    |
| `providers.default.total_timeout_seconds`      | `900`         | `90000`              |
| `providers.claude.idle_timeout_seconds`        | `180`         | `18000`              |

The role flips align the packaged template with how most users
configure the project after first run; the timeout bumps recognize
that real delegations (multi-hour implementer runs through Claude
Code, for example) routinely exceeded the previous defaults.

**This only affects projects bootstrapping a fresh
`.council/config.yaml` on 0.1.7+.** Existing projects keep their
committed `.council/config.yaml` untouched.

## What changed — under the hood

- `src/councilflow/controller/discussion_orchestrator.py:108` —
  the one-line clamp removed; the surrounding comment block at
  lines 303–310 also updated to drop the now-stale "only 1 external
  model so max=min(5,max_rounds)" example. (`decec65`)
- `src/councilflow/cli/delegate.py` — both
  `_parse_key_value_items()` calls (for `--input` and
  `--required-artifact`) lifted out of the post-route block and
  placed immediately after `store / config` setup. The downstream
  guardrail-construction code reads the same `structured_inputs` /
  `required_artifacts` dicts; no duplicate parsing. (`77f92ce`)
- `src/councilflow/templates/default-config.yaml` — six field-value
  edits, no schema change. (`c7fee9b`)
- Five test files synced to the new template values:
  `tests/test_config_loader.py` (5 assertions),
  `tests/test_routing.py` (2 assertions, one of them
  `test_route_role_delegates_when_target_differs_from_controller`
  reframed around `controller=CLAUDE` so the "differs → delegated"
  branch is still exercised when every default role is `codex`),
  `tests/test_state_store.py` (3 assertions),
  `tests/test_cli_discuss.py` (1 setup change writing a
  project-local config with `default_models: []` so the
  warn-when-no-defaults path stays covered). (`5ce59c8`)
- `src/councilflow/__init__.py::__version__` re-synced to
  `pyproject.toml`. The runtime string had drifted to `0.1.2` since
  0.1.3 and was missed during every release in between.

## Tests

- `ruff check .` — clean.
- `python -m pytest` — full suite green; no regressions.
- The previously red
  `tests/test_cli_delegate.py::test_delegate_command_rejects_invalid_input_shape`
  is now green via TASK-112.
- The new
  `tests/test_discussion_orchestrator.py::test_single_external_model_discussion_runs_full_max_rounds`
  (renamed from `..._caps_rounds_at_five`) directly exercises
  `max_rounds=9` end-to-end.

## Backward compatibility guarantees

- CLI surface unchanged. No new commands, flags, or options on
  `council discuss`, `council delegate`, `council status`, or any
  subcommand.
- JSON response shapes unchanged on the happy path.
- Existing `.council/config.yaml` files load identically — the
  template default refresh only affects fresh init.
- One **behavior change** worth noting: single-external
  `council discuss` will now run up to `discussion.max_rounds`
  instead of stopping at five. Lower `max_rounds` explicitly if you
  prefer the old ceiling.

## Operator note

```bash
pipx upgrade councilflow
council version  # → 0.1.7
```

No skill files need re-syncing for this release. If you actively
maintain `~/.workflow-core/skills/` or `D:/project/AutoSkills/skills/`,
both stay compatible with 0.1.7 unchanged.

## Commits in this release

```
5ce59c8 test(config): sync test expectations to new default-config.yaml (TASK-113)
77f92ce fix(cli): validate --input/--required-artifact before route short-circuit (TASK-112)
c7fee9b chore(config): tune default-config.yaml roles and provider timeouts
decec65 fix(discussion): remove 5-round hard cap for single external model (TASK-111)
6bee2df Update readme.md
57f002d Fix formatting in AutoSkills section of README
```
