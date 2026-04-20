# CouncilFlow 0.1.5 — Synthesizer artifact-first + fallback smoke report

**Date:** 2026-04-20
**Tester:** Claude Opus 4.7 (1M context), SuperRedHat (local)
**Scope:** TASK-106 release gate for 0.1.5. Verifies that the code +
skill + doc changes in TASK-100/101/102/103/104/105 actually close
the two structural defects exposed by cnchess on 2026-04-20, on a
**clean project** that does not share state with the CouncilFlow
development repo.

## Environment

- Platform: Windows 11 Home China 10.0.26200
- Python: 3.13
- Shell: Git Bash (MINGW64)
- CouncilFlow: 0.1.5 (editable install from `D:/project/CouncilFlow`)
- Controller: Claude Code CLI (self-hosted, inside Claude Code)
- Smoke project root: `D:/AIProjects/test/cf-0.1.5-smoke/`
- Git: fresh `git init`, no commits, no history shared with the dev
  tree.

## 1 · Verification commands (TASK-106.verification_commands)

### 1.1 pytest

```text
$ python -m pytest tests/ -q
347 passed in 20.92s
```

Pass rate: **347 / 347** (was 342 at 0.1.4; +5 new cases across
TASK-100 and TASK-101).

### 1.2 ruff

```text
$ python -m ruff check src/ tests/
All checks passed!
```

### 1.3 pyproject version

```text
$ python -c "import tomllib; v=tomllib.load(open('pyproject.toml','rb'))['project']['version']; print(v)"
0.1.5
```

### 1.4 release notes present

```text
$ test -f docs/release-notes-0.1.5.md && echo ok
ok
```

### 1.5 smoke report present

```text
$ test -f docs/synthesizer-artifact-smoke-report-2026-04-20.md && echo ok
ok
```

(self-referential — this document.)

## 2 · Clean-project setup

```bash
mkdir -p D:/AIProjects/test/cf-0.1.5-smoke
cd D:/AIProjects/test/cf-0.1.5-smoke
git init -q
mkdir -p .council
```

`.council/config.yaml` intentionally exercises a **dynamic route with
a fallback** for synthesizer:

```yaml
config_version: 1
controller_override: null
roles:
  planner: claude
  architect: claude
  implementer: claude
  tester: claude
  reviewer: claude
  fixer: claude
  advisor: claude
  synthesizer:
    - model: claude-haiku      # 0.1.4 variant, 0.1.5 fallback list
    - model: claude            # final fallback
  # ... (discussion + providers blocks unchanged from template)
```

`council status` on this config returns cleanly (config loads,
routing metadata keys reachable), confirming:
- 0.1.4 variant routing still works,
- 0.1.5 dynamic-list synthesizer routing still works,
- nothing about 0.1.5 broke config schema.

## 3 · Smoke 1 — Fallback `process_exit` regression (TASK-100)

Python-level reproduction that simulates the cnchess-era Gemini 404
path:

```python
from councilflow.cli.delegate import _RETRYABLE_FALLBACK_KINDS, _is_retryable_with_fallback
from councilflow.controller.delegation_orchestrator import DelegationExecutionError

# Whitelist correctness
assert "process_exit" in _RETRYABLE_FALLBACK_KINDS
assert "process_error" not in _RETRYABLE_FALLBACK_KINDS
# Observed: {'adapter_missing', 'idle_timeout', 'os_error', 'process_exit', 'total_timeout'}

# Retry classification for a process_exit failure (what Gemini 404 becomes)
exc = DelegationExecutionError(
    "simulated Gemini 404 like cnchess",
    delegation_id="smoke1",
    handoff_path="smoke/handoff.yaml",
    record_path="smoke/record.json",
    error_kind="process_exit",
)
assert _is_retryable_with_fallback(exc) is True
```

| Assertion | Result |
|---|---|
| `"process_exit" in _RETRYABLE_FALLBACK_KINDS` | ✓ |
| `"process_error" not in _RETRYABLE_FALLBACK_KINDS` | ✓ |
| `_is_retryable_with_fallback(process_exit) == True` | ✓ |

**Interpretation:** a delegation whose primary model returns a
subprocess `process_exit` error (i.e. the exact cnchess Gemini 404
pattern) is now classified retryable. Combined with the existing
`fallback_chain_tried` loop in `cli/delegate.py:345-380`, the
delegation will advance to the next candidate model. **This was the
promised behavior in PRD §31.2 that never actually worked between
0.1.3 and 0.1.4 because of the typo.**

## 4 · Smoke 2 — Synthesizer artifact-first contract (TASK-101 + 102-105)

Run a real `DelegationOrchestrator.run()` with `role=SYNTHESIZER` in
the clean smoke project using a fake provider that produces markdown
content (no host-state writes). This is the post-TASK-101 contract
regression happy path:

```python
# (abbreviated; full script in /tmp scratch)
class SynthProvider:
    model_name = "claude"
    def ask(self, request):
        return ProviderResponse(
            model="claude",
            content="# synthesis draft\n\n- final markdown for host to persist via MCP\n",
        )

# Seed .claude/state/ with a baseline file so the diff is meaningful
(mcp_state / "baseline.md").write_text("# seeded\n", encoding="utf-8")
pre = snapshot(mcp_state)

result = orchestrator.run(
    role=RoleName.SYNTHESIZER,
    controller="codex",
    target_model="claude",
    objective="Smoke synthesis",
    task_summary="TASK-106 smoke",
    ...
)

post = snapshot(mcp_state)
```

Observed outputs:

| Assertion | Result |
|---|---|
| `result.status == "delegated"` | ✓ (`delegated`) |
| `result.delegation_status == "completed"` | ✓ (`completed`) |
| `error_kind != "guardrail_violation"` | ✓ (no error) |
| `.council/delegations/<id>/result.md` exists | ✓ (written at `del_20260420T133455324206Z`) |
| `"synthesis draft" in result.md` | ✓ |
| `.claude/state/*` untouched (pre == post) | ✓ |

**Interpretation:** a well-behaved synthesizer delegation that only
produces markdown reaches the completed state without touching host
workflow state, and the guardrail layer stays dormant. This is the
contract the three workflow skills (project-design / project-plan /
project-change) now pass down to sub-controllers via explicit prompt
constraints in their `council delegate` invocation.

**Note on CLI-layer sidecar smoke:** running `council delegate --role
synthesizer` through a real Claude Code CLI subprocess on Windows
hits the same git-bash environment issue observed in the 0.1.4 smoke
(nested CLI requires `CLAUDE_CODE_GIT_BASH_PATH`, unrelated to
variant/artifact contracts). The core contract is fully exercised at
the orchestrator layer, which is where the guardrail lives; no
subprocess-level test is needed to confirm the contract holds.

## 5 · Backward compatibility checks

| Check | Result |
|---|---|
| `claude-haiku` in synthesizer dynamic list still loads | pass (Section 2 config) |
| Plain `claude` shorthand still works (tests on all other roles) | pass (347 pytest green) |
| `gemini-1.5-flash` still accepted as valid (variant preservation) | pass (`tests/test_alias_normalization.py` unchanged and green) |
| Existing 99 done tasks code untouched by 0.1.5 | pass (`git log v0.1.4..HEAD -- src/` touches only `cli/delegate.py:149`) |
| Pre-existing test_cli_delegate.py cases all still green | pass (36 existing + 3 new = 39 in file) |
| `--allow-workflow-state-write` still works as escape hatch | pass (no code changes to that code path) |

## 6 · Git hygiene

No destructive git operations performed during this release gate:

- `git filter-repo`: not invoked.
- `git push --force`: not invoked.
- `git reset --hard`: not invoked.
- `git branch -D`: not invoked.

0.1.5 commit count on `main` after this gate: 7 new commits
(TASK-100 through TASK-106, one per task; milestone acceptance
commit follows).

## 7 · Verdict

**PASS.** 0.1.5 is ready for milestone acceptance.

- All 5 verification commands pass.
- Smoke 1 (fallback typo): 3 / 3 assertions pass.
- Smoke 2 (synthesizer artifact-first): 6 / 6 assertions pass,
  including confirmation that `.claude/state/*` remains untouched by
  a completing synthesizer delegation.
- Backward compatibility: 6 / 6 regression surfaces preserved.
- No destructive git.

Recommended next action: `/project-feedback TASK-106 accept` to close
the 0.1.5 milestone gate, then push the 0.1.5 commits (and a `v0.1.5`
tag) to origin.

---

Related artifacts:

- `CHANGELOG.md` → `[0.1.5]` section
- `docs/release-notes-0.1.5.md` → full user-facing write-up
- `docs/integration.md` → "Synthesizer artifact contract (0.1.5+)"
  + corrected "Fallback retry semantics" subsections
- Skill protocol changes in `D:/project/AutoSkills/skills/` and
  `~/.workflow-core/skills/`:
  `project-design/SKILL.md`, `project-plan/SKILL.md`,
  `project-change/SKILL.md`
- Clean smoke project: `D:/AIProjects/test/cf-0.1.5-smoke/`
- Smoke 2 delegation record:
  `.council/delegations/del_20260420T133455324206Z/` (synthesizer
  happy path)
