# CouncilFlow 0.1.5 — Synthesizer artifact-first + fallback typo fix

**Release date:** 2026-04-20
**Type:** Patch release (closes two 0.1.3-era structural defects
surfaced by integration testing on the cnchess test project).
**Upgrade path:** `pipx upgrade councilflow`; re-sync workflow skills
if you maintain a local copy.

## Why this release exists

cnchess, a smoke test project run from scratch on 2026-04-20, exposed
two defects that slipped past both the 0.1.3 (Dynamic Role Routing)
and 0.1.4 (Claude variant) reviews. Neither is a regression — they
were present from 0.1.3 onward — but neither was noticed until a real
multi-stage workflow actually delegated through sidecars.

### Defect 1 — fallback silently never triggered (typo)

`src/councilflow/cli/delegate.py:149` lists the error-kind whitelist
for "retryable via fallback":

```python
_RETRYABLE_FALLBACK_KINDS: frozenset[str] = frozenset(
    {
        "adapter_missing",
        "process_error",          # ← never emitted by any adapter
        "idle_timeout",
        "total_timeout",
        "os_error",
    }
)
```

But every CouncilFlow adapter (`base`, `claude_code_cli`, `gemini_cli`,
`codex_cli`, `openai_api`) raises `DelegationExecutionError` with
`error_kind="process_exit"` when the CLI subprocess returns non-zero.
`"process_error"` vs `"process_exit"` is a simple string mismatch, so
`_is_retryable_with_fallback()` has been returning `False` for every
subprocess failure since 0.1.3 landed.

Practical effect: users who followed `default-config.yaml` Example 1
and wrote

```yaml
roles:
  tester:
    - model: claude-haiku
    - model: claude-sonnet
      fallback: true
```

got no fallback. The first subprocess failure terminated the
delegation, and `record.json` showed `fallback_attempted: false`
regardless of how many fallback entries were configured.

0.1.5 fixes the spelling in one character. Three regression tests lock
the correct behavior so nobody silently re-introduces the typo.

### Defect 2 — synthesizer delegation hit the protected-paths guardrail

`project-design` (and, by extension, `project-plan` / `project-change`)
delegate a `synthesizer` stage whose job is "combine prior artifacts
into a final document". When that delegation runs in a sidecar
sub-controller, and the sub-controller "helpfully" calls MCP
`save_architecture` to persist its own output, the MCP write lands on
host `.claude/state/architecture.md` — which is in
`PROTECTED_WORKFLOW_PATHS`. The orchestrator snapshots protected paths
before the stage, compares after, and rolls any change back with
`error_kind=guardrail_violation`. Net effect: synthesizer delegation
was completing at the provider layer but getting rolled back at the
guardrail layer, then erroring out.

The fix is structural but low-code: the three workflow skills now
instruct the sub-controller explicitly not to call MCP write tools,
and the skill's host-side persistence step is the explicit driver of
`save_architecture` / `save_prd` / `create_tasks` / `add_log`. This
aligns `synthesizer` with the `implementer` contract already in place
since 0.1.0 (sidecar writes `.council/delegations/<id>/result.md`, host
reads it, host decides whether to commit / write state).

## What changed — user visible

### Fallback chain now does what it says

Same config as before, but subprocess failures now advance to the
next model in the fallback list. If you have

```yaml
roles:
  synthesizer:
    - model: gemini-1.5-flash
    - model: claude
      fallback: true
```

and Gemini returns 404 (which is what cnchess saw for deprecated
`gemini-1.5-flash`), 0.1.5 will retry the same request against Claude.
Before 0.1.5, that exact setup would have failed outright with
`error_kind=process_exit` and `fallback_attempted=false`.

### Synthesizer skill protocol is now artifact-first

If you use `project-design`, `project-plan`, or `project-change`, the
updated skill files (in both `D:/project/AutoSkills/skills/` and
`~/.workflow-core/skills/`) now:

1. Pass an explicit negative constraint to the sub-controller when
   delegating: "`不要调用 save_architecture/save_prd/create_tasks/
   add_log 等 MCP 写入工具；host 主控会在拿到 result.md 后负责落盘`".
2. In the host-side persistence step, the skill explicitly reads
   `.council/delegations/<id>/result.md` **before** calling
   `save_architecture` / `save_prd` / `create_tasks` / `add_log`. The
   host is the sole writer to host state.
3. Document the contract as "Synthesizer artifact-first (0.1.5+)" in
   the skill body for future operators.

You don't need to change your project config. You **do** need to
re-sync your local skill copies if you maintain
`~/.workflow-core/skills/` manually (the sync-skills script handles
this; or copy from `D:/project/AutoSkills/skills/`).

## What changed — under the hood

- **`src/councilflow/cli/delegate.py`** (1 char): `"process_error"` →
  `"process_exit"` in `_RETRYABLE_FALLBACK_KINDS`.
- **`tests/test_cli_delegate.py`**: 3 new regression tests for the
  whitelist (positive presence, negative absence, retry-true for
  `process_exit`, retry-false for non-retryable kinds).
- **`tests/test_synthesizer_artifact_contract.py`** (new file): 2 new
  tests that pin the happy path — synthesizer delegation writes
  `result.md` but does not touch `.claude/state/*`, and the MCP
  policy layer reports `decision=allow` for synthesizer (the contract
  is about what the sidecar *does*, not about MCP availability).
- **Skill protocols** (no CouncilFlow code change):
  `project-design/SKILL.md`, `project-plan/SKILL.md`,
  `project-change/SKILL.md` updated in `D:/project/AutoSkills/skills/`
  and `~/.workflow-core/skills/`.
- **`docs/integration.md`**: new "Synthesizer artifact contract
  (0.1.5+)" subsection; "Fallback retry semantics" corrected +
  annotated with the 0.1.5 typo note.

## Backward compatibility

- No new protocol, no new CLI flag, no new config schema.
- All 99 done tasks across 0.1.0 / 0.1.1 / 0.1.2 / 0.1.3 / 0.1.4
  unchanged; zero code rework.
- Existing 0.1.4 `.council/config.yaml` files load identically.
- Adapter behavior unchanged (`--model` override, variant routing,
  fallback list expansion semantics).
- `PROTECTED_WORKFLOW_PATHS` default unchanged, still deny-all.
- `--allow-workflow-state-write` opt-in still works for callers who
  explicitly need sidecar-driven host-state writes.
- Skills that stayed at 0.1.4 still work — they'll just occasionally
  trigger `guardrail_violation` on synthesizer delegation the way
  they did at 0.1.4. 0.1.5 skills are strictly better.

## Test coverage

- **347 pytest cases** (was 342 at 0.1.4): +5 new tests — 3 for the
  fallback typo regression (`test_cli_delegate.py`) and 2 for the
  synthesizer artifact contract
  (`test_synthesizer_artifact_contract.py`).
- `ruff check src/ tests/`: clean.

## Operator guidance

No config migration. Two low-cost operational steps worth considering:

1. **Re-sync workflow skills.** If you maintain
   `~/.workflow-core/skills/` manually, copy
   `project-design/SKILL.md`, `project-plan/SKILL.md`,
   `project-change/SKILL.md` from
   `D:/project/AutoSkills/skills/` — or run
   `sync-skills.ps1`. Skills that stay at 0.1.4 will occasionally
   still hit `guardrail_violation`; 0.1.5 skills avoid it
   structurally.

2. **Audit fallback chains.** If you had written a fallback list and
   thought "it never seems to fire", that was this typo. Test it
   under 0.1.5 with a known-bad primary model (e.g. a deprecated
   Gemini variant that returns 404): the delegation should now
   advance to the next model.

## Known limitations unchanged from 0.1.4

- Real-CLI adapter smoke (live HTTP requests) is manual.
- MCP policy is best-effort on CLIs that ignore worktree-local
  settings; the workspace-import guardrail remains the final
  backstop.
- Skills are not auto-synced on `pipx upgrade` — you still need to
  re-sync manually or via the helper script.

---

See `CHANGELOG.md` `[0.1.5]` for the structured entry,
`docs/integration.md` for the updated reference, and
`docs/synthesizer-artifact-smoke-report-2026-04-20.md` for the
clean-project smoke evidence used to accept this milestone.
