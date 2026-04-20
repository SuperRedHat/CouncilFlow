# CouncilFlow 0.1.3 Release Notes

**Release date**: 2026-04-20
**Phase**: Workflow token-efficiency optimization (TASK-071 ~ TASK-085)
**Backward compatibility**: 100% — existing `.council/config.yaml` and workflow state load unchanged.

---

## TL;DR

0.1.3 gives you two new **opt-in** capabilities plus observability, without breaking any existing setup:

- **Dynamic role routing** — per-role ordered routes with `when` expressions and `fallback` chains, letting you say "route `tester` to haiku for S/M tasks, claude for L tasks, gemini if claude is down"
- **Semantic convergence** — multi-model discussions can now stop as soon as the round adds no new info, instead of blindly respecting `min_rounds` count
- **Observability** — `council status --recent 30` summarizes recent routing hits and discussion convergence reasons

Nothing changes if you don't opt in. Existing shorthand configs keep their 0.1.2 behavior.

---

## What's new (the interesting bits)

### 1. Dynamic role routing

**Before** (pre-0.1.3):

```yaml
roles:
  implementer: claude  # always claude, no conditions
```

**After** (0.1.3+, optional):

```yaml
roles:
  implementer:
    - model: claude
      when: "task.complexity in ['L']"
    - model: claude-haiku
      when: "task.complexity in ['S', 'M']"
      fallback: [claude, gemini]
    - model: gemini        # final default when nothing else matches
```

What this buys you:

- **Route cheap tasks to cheap models** — common estimate is 30-50% $ savings when you actually use this (tester + synthesizer + advisor are typical candidates for downsizing)
- **Fallback resilience** — if the primary adapter has an `idle_timeout` / `process_error` / `total_timeout` / `os_error` / `adapter_missing`, `council delegate` auto-tries the fallback chain. Permission / environment / verification failures still exit immediately (those reflect task state, not provider transient failure)
- **Task-aware routing** — `when` can reference `task.complexity` / `task.module` / `task.role` / anything passed via `--input KEY=VALUE`

Safety model: `when` expressions run in a sandboxed AST walker. `__import__('os')`, `task.__class__`, `lambda: None`, `getattr(...)`, f-strings, comprehensions — all rejected. Only comparisons, boolean ops, literals, `task.<single-attr>` access. See `docs/integration.md` "Dynamic Role Routing" section for the full grammar.

### 2. Semantic convergence

**Before** (pre-0.1.3): `discussion.min_rounds=2` was a hard count. Even if round 1 produced unambiguous "we agree, nothing more to add", the orchestrator forced a round 2 that was mostly filler.

**After** (0.1.3+, optional):

```yaml
discussion:
  convergence_policy: semantic   # or "hybrid" / "strict_count"
  min_rounds: 1
  max_rounds: 5
```

With `semantic`: stop as soon as the latest round has `introduced_new_info=False` and no new disagreements. `min_rounds` still acts as a hard floor to prevent first-round rubber-stamp risk.

With `hybrid`: infer a coarse topic from the question keywords (`architecture` / `review` / `clarification` / `other`), and use per-topic floors:

```yaml
discussion:
  convergence_policy: hybrid
  min_rounds_by_topic:
    architecture: 2   # design discussions require at least 2 rounds
    clarification: 1  # factual lookups can stop after round 1
```

All policies preserve the "no external participants → immediate converge" short-circuit.

Every round's decision is now recorded to `DiscussionSummary.convergence_trace` for audit:

```json
"convergence_trace": [
  {"round": 1, "reason": "min_rounds_not_met", "decision": "continue"},
  {"round": 2, "reason": "no_new_info",        "decision": "converge"}
]
```

### 3. Observability

```bash
council status --recent 30
```

Now includes:

- `routing_distribution` — for each role, how many times it was routed to which model over the last N days. Lets you see if your cheap-model routing is actually catching the cases you expected.
- `convergence_distribution` — average rounds completed + count of each `ended_reason` (`converged` / `max_rounds_reached` / etc.). Helps tune `min_rounds` / `max_rounds` empirically.

Data is scanned from `.council/runs/<run_id>/routing.json` and `.council/discuss/<id>/record.json`. Missing directories degrade gracefully to `total_records: 0`.

---

## What's explicitly **not** in 0.1.3

We did a 5-round discussion with codex on 2026-04-20 about "link folding" (same-model `local_execution` chain token deduplication). Codex's critique identified real problems:

1. Current design doesn't distinguish different generations of the same artifact path
2. Time-based staleness ("30 minutes no new delegate") is a weak invalidation signal
3. "40-60% savings" was an estimate, not measured

And our baseline measurement (`docs/ceremony-baseline-2026-04-20.md`) showed ceremony tokens are only **5.0%** of total in the real sample — much lower than the estimate. Upside from link folding alone is at most ~3% of total.

**Decision**: defer link folding. Revisit once we have enough data from Part A / Part B in real use. The analysis and rejected design live in `docs/rfc-workflow-token-optimization.md`.

Also deferred (see `docs/workflow-optimizations-backlog.md`):

- Sidecar tiered isolation (per-role `workspace_strategy`)
- Artifact schema unification
- Provider session reuse
- Discussion turn merging / incremental handoff

---

## Upgrade from 0.1.2

**Zero config changes required.** Run:

```bash
pipx upgrade councilflow
# or, if installed from the private git URL:
pipx install --force git+https://github.com/SuperRedHat/CouncilFlow.git
```

Existing `.council/config.yaml` files load unchanged. `convergence_policy` defaults to `strict_count`, matching pre-0.1.3 behavior byte-for-byte.

**To opt into dynamic routing**, edit your project's `.council/config.yaml` following the examples in:

- `src/councilflow/templates/default-config.yaml` (top comment block with 3 patterns)
- `docs/integration.md` → "Dynamic Role Routing" section
- This release notes file (above)

**To opt into semantic convergence**, add to your `discussion` config:

```yaml
discussion:
  convergence_policy: semantic   # or "hybrid"
  min_rounds: 1                  # still a hard floor
```

---

## Tests and quality gates

- **pytest**: 318/318 passing at release (vs 189/189 at 0.1.2 → added 129 new tests)
- **ruff check src/ tests/**: clean
- **Security**: `when` expression evaluator has 21 "known dangerous expression" test cases that must all be rejected

---

## Smoke test

See `docs/token-opt-smoke-report-2026-04-20.md` for the end-to-end smoke (clean test project in `D:/AIProjects/test/`, real `/project-ask discuss` and `/project-next` invocations).

---

## Commits in this release

Notable:

- `715b20f` docs(rfc): add workflow token-efficiency RFC (TASK-071)
- `d3afaa8` feat(tooling): baseline measurement script (TASK-072)
- `d667929` docs(baseline): run baseline measurement (TASK-073)
- `c33c874` feat(config): extend RoleMapping for dynamic routing (TASK-074)
- `47bffef` feat(config): restricted AST when-expression evaluator (TASK-075)
- `8d28c44` feat(controller): role router engine (TASK-076)
- `54d1e80` feat(cli): wire role_router into delegate (TASK-077)
- `da97893` docs(config): add dynamic-routing examples to template (TASK-078)
- `f03d590` feat(config): DiscussionSettings.convergence_policy (TASK-079)
- `1b371b2` feat(controller): multi-mode convergence evaluator (TASK-080)
- `4109fd3` feat(controller): route discussion convergence through evaluator (TASK-081)
- `b0ed1b6` feat(cli): routing + convergence distribution in council status (TASK-082)
- (AutoSkills) `0f7cddc` docs(skills): note dynamic role routing in 7 skills (TASK-083)
- `8ccbd0c` docs(integration): Dynamic Role Routing + Convergence Policy sections (TASK-084)
- This release commit: TASK-085

---

## Acknowledgments

- codex — 5-round discuss on 2026-04-20 that killed the premature link folding design
- claude (controller) — executed all 15 tasks autonomously via `/project-next`
- User — made the decision to pursue Phase 1 + A + B and skip link folding

---

**Previous release**: [0.1.2](./release-notes-0.1.2.md)
**Upgrade confidence**: High (fully backward compatible, regression green).
