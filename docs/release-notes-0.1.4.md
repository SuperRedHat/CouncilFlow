# CouncilFlow 0.1.4 — Claude variant routing

**Release date:** 2026-04-20
**Type:** Patch release (closes 0.1.3 Part A gap)
**Upgrade path:** `pipx upgrade councilflow` — no config or workflow
changes required.

## Why this release exists

0.1.3 shipped **Dynamic Role Routing** (Part A of the workflow
token-efficiency phase). The promise was: route cheap / fast Claude
sub-models to low-stakes roles (tester, reviewer) and reserve the full
Sonnet / Opus tier for implementer. The `default-config.yaml` template
even advertises this in its commented Example 1:

```yaml
roles:
  tester:
    - model: claude-haiku     # cheap, for simple verification
    - model: claude-sonnet
      fallback: true
```

**It didn't actually work.** The config-load-time whitelist
(`resolve_adapter_model`) only knew about `claude` — no variant
suffixes. Any value of the form `claude-<something>` would raise
`ValueError("unknown adapter: claude-haiku")` and fail to load.
Gemini's equivalent path (`gemini-1.5-flash`) *did* work because
Gemini had been treated as a special case since 0.1.0. Claude was
stuck with a single opaque identifier.

0.1.4 is the minimal patch that closes that gap. It also quietly
fixes a latent 0.1.3 bug where even Gemini variants were being
collapsed back to the family name by an over-eager `MODEL_ALIASES`
entry, defeating the point of the `--model` CLI flag.

## What changed — user visible

### 1. Claude variants are now valid config values

| Config value | Accepted? | Adapter | CLI receives |
|--------------|-----------|---------|--------------|
| `claude` | yes (unchanged) | ClaudeCodeCliAdapter | no `--model` flag |
| `claude-haiku` | **new** | ClaudeCodeCliAdapter | `--model haiku` |
| `claude-sonnet` | **new** | ClaudeCodeCliAdapter | `--model sonnet` |
| `claude-opus` | **new** | ClaudeCodeCliAdapter | `--model opus` |
| `claude-3-5-sonnet-20241022` | **new** | ClaudeCodeCliAdapter | `--model claude-3-5-sonnet-20241022` |
| `claude-haiku-4-5` | **new** | ClaudeCodeCliAdapter | `--model claude-haiku-4-5` |
| `haiku` (short alias) | **new** | ClaudeCodeCliAdapter | `--model haiku` |
| `sonnet` (short alias) | **new** | ClaudeCodeCliAdapter | `--model sonnet` |
| `opus` (short alias) | **new** | ClaudeCodeCliAdapter | `--model opus` |
| `claude-` (empty suffix) | **rejected** | — | — |

The split between short aliases (haiku / sonnet / opus) and versioned
names is intentional: Claude Code CLI's `--model` flag accepts both
the short identifiers and the full `claude-3-5-sonnet-20241022` form,
so 0.1.4 translates `claude-haiku` → `haiku` but passes
`claude-3-5-sonnet-20241022` through verbatim. You don't need to know
which form the upstream CLI wants; CouncilFlow sorts that out.

### 2. Gemini variants stop collapsing

0.1.2 / 0.1.3 had this in `MODEL_ALIASES`:

```python
"gemini-1.5-flash": "gemini",
"gemini-1.5-pro": "gemini",
```

Intent: treat these as synonyms of the family. Effect:
`GeminiCliAdapter` lost the variant information before it could
inject `--model gemini-1.5-flash` into the subprocess, silently
downgrading the user's intent to whatever `gemini-cli`'s default
model happens to be.

0.1.4 removes those entries. Variant preservation is now symmetric
across Claude and Gemini.

### 3. Dynamic routing now actually delivers cost savings

Before 0.1.4:

```yaml
# Example 1 from 0.1.3's default-config.yaml
roles:
  tester:
    - model: claude-haiku     # ← config-load error, task blocked
```

After 0.1.4:

```yaml
roles:
  tester: claude-haiku                 # shorthand form
  # or
  reviewer:
    - model: claude-haiku              # dynamic route
      when: artifacts.count < 3
    - model: claude-sonnet
      fallback: true
```

With a Claude Code CLI controller, the tester / reviewer subprocesses
now spawn with `--model haiku` injected before `-p`, which is the
actual cost path users expected from 0.1.3.

## What changed — under the hood

- **`src/councilflow/models/roles.py`**: `resolve_adapter_model`
  gained a `claude-` prefix branch. `MODEL_ALIASES` lost the
  variant-collapsing entries (`gemini-1.5-flash → gemini`, etc.) and
  gained short aliases (`haiku → claude-haiku`, `sonnet →
  claude-sonnet`, `opus → claude-opus`). Empty-suffix guards reject
  both `claude-` and `gemini-`.
- **`src/councilflow/providers/claude_code_cli.py`**: new
  `_variant_to_cli_model_arg()` helper strips the `claude-` prefix
  for short aliases and passes versioned names through.
  `ClaudeCodeCliAdapter.__init__` accepts a new `model: str | None`
  parameter, stores `self.claude_variant`, and injects `--model
  <arg>` into the command ahead of `-p`. `model_name` still returns
  `"claude"` so logging and run-record aggregation are unchanged; the
  original variant surfaces in `ProviderResponse.metadata.claude_variant`.
- **`src/councilflow/cli/delegate.py`**: `get_provider_adapter` now
  has a Claude variant branch that mirrors the existing Gemini
  variant branch — `claude-<variant>` where variant is non-empty
  routes through `ClaudeCodeCliAdapter(model=<variant>)`.
- **`docs/integration.md`**: Dynamic Role Routing section gained a
  **Provider variants (0.1.4+)** subsection with the mapping tables.

## Backward compatibility

- All 93 done tasks across 0.1.0 / 0.1.1 / 0.1.2 / 0.1.3 required
  zero code rework.
- Pre-existing `.council/config.yaml` files with `roles.<role>:
  claude` / `gemini` / `codex` / `gpt` load and behave identically.
- `council delegate` JSON response shape for success paths is
  unchanged.
- `--model` CLI flag override retains highest priority.
- Claude Code CLI invocations *without* a variant still use the
  exact same command as 0.1.3 — no `--model` flag injected.
- Dynamic routing semantics (AST-restricted `when` expressions,
  fallback chaining, `routing_no_match` error kind) are unchanged.

## Test coverage

- **342 pytest cases** (was 318 at 0.1.3).
- New `tests/test_claude_adapter.py` (11 cases): parametrized
  `_variant_to_cli_model_arg` coverage, constructor with/without
  variant, `--model` precedes `-p`, custom command preserves
  variant, metadata surfaces variant.
- `tests/test_alias_normalization.py`: Claude variant acceptance,
  Gemini variant preservation, empty-suffix rejection for both
  `claude-` and `gemini-`.
- `tests/test_cli_delegate.py`: 4 new cases exercising
  `get_provider_adapter` for Claude variants and the end-to-end
  config-load-does-not-reject-claude-haiku path.
- `tests/test_config_loader.py`: updated to assert variant
  preservation on load.
- `ruff check src/ tests/`: clean.

## Operator guidance

No migration actions. If you were working around the 0.1.3 gap by
pinning `tester: claude` everywhere, you can now switch to
`claude-haiku` (short alias, alias table) or your preferred variant.

If you want to test without changing your production config:

```bash
council delegate --role tester --model claude-haiku \
  --objective "smoke test" --task-summary "variant routing check"
```

The delegation record at `.council/delegations/<id>/record.json`
will show `effective_model: claude-haiku` on a successful route.

## Known limitations unchanged from 0.1.3

- Real-CLI adapter smoke (live HTTP requests) is manual.
- MCP policy is best-effort on CLIs that ignore worktree-local
  settings; the workspace-import guardrail remains the final
  backstop.
- Claude Code CLI's own `--model` flag semantics are the upstream
  CLI's responsibility — CouncilFlow transmits the value verbatim
  (for versioned names) or the short form (for aliases).

---

See `CHANGELOG.md` for the structured changelog entry and the full
set of accepted aliases.
