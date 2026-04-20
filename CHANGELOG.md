# Changelog

All notable changes to CouncilFlow are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.5] — 2026-04-20

Patch release closing two structural defects that survived into 0.1.4
and were exposed by the cnchess test project on 2026-04-20:

1. `src/councilflow/cli/delegate.py:149` `_RETRYABLE_FALLBACK_KINDS`
   listed the string `"process_error"`, but every adapter emits
   `"process_exit"`. The typo had been live since 0.1.3, silently
   disabling fallback on any CLI-subprocess failure.
2. `project-design` / `project-plan` / `project-change` skill
   protocols did not warn the delegated sidecar to avoid MCP writes
   into host `.claude/state/*`. A sub-controller that "helpfully"
   saved its output via `save_architecture` / `save_prd` /
   `create_tasks` triggered the protected-paths guardrail and got
   rolled back as `guardrail_violation`.

### Fixed

- **Fallback retry no longer silent-fails on `process_exit`**.
  `_RETRYABLE_FALLBACK_KINDS` now contains the correct
  `"process_exit"` string. Correctly-configured fallback chains
  (`roles.<role>: [ {model: A}, {model: B, fallback: true} ]`) start
  working as PRD §31.2 originally promised. Regression tests
  (`test_fallback_whitelist_contains_process_exit_not_process_error`,
  `test_is_retryable_with_fallback_true_for_process_exit`,
  `test_is_retryable_with_fallback_false_for_guardrail_violation`)
  pin the correct classification.

### Changed

- **Synthesizer skill protocol is now artifact-first**. The three
  workflow skills pass an explicit negative constraint in their
  `council delegate --role synthesizer` invocation
  ("不要调用 save_architecture / save_prd / create_tasks / add_log
  等 MCP 写入工具"), and the host-side persistence step explicitly
  reads `.council/delegations/<id>/result.md` before driving the
  appropriate MCP writes itself. This aligns synthesizer with the
  `implementer` contract already in place since 0.1.0. Applies to
  `project-design`, `project-plan`, `project-change` across both
  repositories (`D:/project/AutoSkills/skills/` and
  `~/.workflow-core/skills/`).
- `docs/integration.md` gained a "Synthesizer artifact contract
  (0.1.5+)" subsection and the "Fallback retry semantics" section
  was corrected + annotated with the 0.1.5 typo note.

### Backward compatibility guarantees

- No new protocol, no new CLI flag, no new config schema.
- Existing 0.1.4 `.council/config.yaml` files load and behave
  identically.
- All 99 previously-done tasks (0.1.0 through 0.1.4) required zero
  code rework.
- `--allow-workflow-state-write` remains an opt-in escape hatch for
  callers who genuinely need sidecar-driven host-state writes.
- Guardrail default behavior unchanged (`PROTECTED_WORKFLOW_PATHS`
  still deny-all).

### Tests

- **347 pytest cases** (was 342 at 0.1.4, +5 new): 3 in
  `tests/test_cli_delegate.py` for the fallback typo regression + 2
  in the new `tests/test_synthesizer_artifact_contract.py` file.
- `ruff check src/ tests/`: clean.

### Operator note

No upgrade actions required. `pipx upgrade councilflow` picks up
0.1.5. If you maintain a local copy of the workflow skills under
`~/.workflow-core/skills/`, re-sync from AutoSkills (or run
`sync-skills.ps1`) so `project-design` / `project-plan` /
`project-change` pick up the 0.1.5 artifact-first protocol.

See `docs/release-notes-0.1.5.md` for the full write-up.

## [0.1.4] — 2026-04-20

Patch release closing the Claude variant gap left by 0.1.3's Part A
(Dynamic Role Routing). Before 0.1.4, dynamic routes like
`tester: claude-haiku` were rejected at config load because the
`resolve_adapter_model` whitelist only accepted `claude` / `codex` /
`gemini` / `gemini-<variant>` / `gpt-<variant>` / `o1-<variant>`. This
made the primary cost-saving path promised by 0.1.3 (per-role cheap
Claude sub-models) unusable with Claude Code CLI as the controller.
0.1.4 mirrors the Gemini variant pattern to Claude and fixes a latent
0.1.3 bug where Gemini variants were being collapsed back to the
family name.

### Added

- **Claude variant routing**: `resolve_adapter_model` now accepts
  `claude-<variant>` (e.g. `claude-haiku`, `claude-sonnet`,
  `claude-opus`, `claude-3-5-sonnet-20241022`, `claude-haiku-4-5`) the
  same way `gemini-<variant>` already works. Short aliases `haiku` /
  `sonnet` / `opus` normalize to `claude-haiku` / `claude-sonnet` /
  `claude-opus`. Empty suffix `claude-` is rejected.
- **`ClaudeCodeCliAdapter` variant support**: new `model: str | None`
  constructor parameter mirroring `GeminiCliAdapter`. When set,
  injects `--model <cli_arg>` before the `-p` flag. Short aliases
  (`claude-haiku` → `haiku`) are translated to the Claude Code CLI's
  expected short form; versioned names (`claude-3-5-sonnet-20241022`)
  are passed through verbatim. `model_name` stays canonical `"claude"`
  for logging and run-record aggregation; the original variant is
  surfaced in `ProviderResponse.metadata.claude_variant`.
- **`cli/delegate.py` Claude variant route**: `get_provider_adapter`
  now routes `claude-<variant>` (where variant != empty) through
  `ClaudeCodeCliAdapter(model=...)` before falling back to
  `resolve_adapter`, matching the existing Gemini variant branch.
- **Docs**: `docs/integration.md` Dynamic Role Routing section gained a
  **Provider variants (0.1.4+)** subsection documenting the Claude and
  Gemini config-value → normalized → CLI-received mapping tables.

### Fixed

- **0.1.3 default-config Example 1's `claude-haiku` now actually
  works.** The 0.1.3 `src/councilflow/templates/default-config.yaml`
  commented example showed `tester: claude-haiku` but that value would
  have been rejected at config load. 0.1.4 makes the example functional
  without changing the template.
- **Gemini variant collapse bug closed.** In 0.1.2 / 0.1.3,
  `MODEL_ALIASES` had entries like `gemini-1.5-flash → gemini` that
  normalized variants back to the family name, defeating the purpose
  of `GeminiCliAdapter`'s `--model` flag. The aliases map is now
  cleaned up so variants are preserved end-to-end from config load to
  the CLI subprocess. Backward compatibility preserved: the short
  alias `gemini-cli → gemini` (controller identifier) stays mapped as
  before.

### Backward compatibility guarantees

- Shorthand `roles.<role>: claude` / `: gemini` / `: codex` / `: gpt`
  behavior is unchanged from 0.1.3.
- Existing `.council/config.yaml` files load without any change.
- All 93 previously-done tasks (78 at 0.1.2 + 15 at 0.1.3) required
  zero code rework.
- `council delegate` JSON response shape for success paths is
  identical.
- `--model` CLI flag override still takes highest priority.
- Claude Code CLI without a variant still runs exactly the same
  command (`claude -p --verbose --output-format stream-json`), no
  `--model` flag injected.

### Tests

- 342 pytest cases (was 318 at 0.1.3): +24 new tests, including a
  new `tests/test_claude_adapter.py` (11 cases covering
  `_variant_to_cli_model_arg`, constructor behavior, command
  ordering, and metadata), plus variant-preservation updates across
  `tests/test_alias_normalization.py`, `tests/test_config_loader.py`,
  and 4 new Claude-variant routing cases in `tests/test_cli_delegate.py`.
- `ruff check src/ tests/`: clean.

### Operator note

No upgrade actions required. `pipx upgrade councilflow` picks up 0.1.4.
To route a role to a cheap Claude variant, edit your project's
`.council/config.yaml`:

```yaml
roles:
  tester: claude-haiku   # or: claude-sonnet, claude-opus, etc.
```

or use a dynamic route:

```yaml
roles:
  implementer:
    - model: claude-haiku
      when: context.token_count < 4000
    - model: claude-sonnet
      fallback: true
```

See `docs/release-notes-0.1.4.md` for the full write-up.

## [0.1.3] — 2026-04-20

Minor release landing the "workflow token efficiency" optimization phase
(15 tasks, TASK-071 through TASK-085). Introduces **Dynamic Role Routing**
and **Semantic Convergence** as opt-in capabilities on top of the existing
`.council/config.yaml` schema. Fully backward compatible: existing
shorthand configs load unchanged, discussion defaults keep pre-0.1.3
behavior.

### Added

- **Dynamic Role Routing** (Part A): `RoleRoute` Pydantic model with
  `model` / `when` (restricted-AST expression) / `fallback` fields.
  `RoleMapping.<role>` accepts either the shorthand string or a list
  of routes. `councilflow.controller.role_router.resolve()` picks the
  first-matching route; `councilflow.config.when_eval` evaluates `when`
  in a sandboxed AST walker. Routing decisions logged to
  `.council/runs/<run_id>/routing.json`. `cli/delegate.py` consumes the
  router and auto-retries on retryable `error_kind` via the fallback
  chain. New structured error: `error.kind="routing_no_match"`.
- **Semantic Convergence** (Part B): `DiscussionSettings.convergence_policy`
  (`strict_count` / `semantic` / `hybrid`, default `strict_count`) +
  `min_rounds_by_topic`. `convergence_evaluator.evaluate()` is the
  single decision function; never calls an LLM.
  `DiscussionOrchestrator` now routes convergence through the
  evaluator. `DiscussionSummary.convergence_trace` captures per-round
  decisions.
- **Observability**: `council status --recent N` gains
  `routing_distribution` and `convergence_distribution` segments.
  `scripts/measure_ceremony_tokens.py` standalone baseline tool.
- **Docs**: `docs/rfc-workflow-token-optimization.md`,
  `docs/workflow-optimizations-backlog.md`,
  `docs/integration.md` new sections, `docs/release-notes-0.1.3.md`,
  `docs/ceremony-baseline-2026-04-20.md`. Template
  `default-config.yaml` comment block shows 3 routing examples.
  AutoSkills repo: 7 role_driven skills note the routing semantics.

### Deferred (explicitly not in 0.1.3)

- **Link folding** (same-model chain token deduplication) — codex
  review on 2026-04-20 found unresolved generation-consistency issues
  and the baseline measurement showed ceremony tokens are only 5.0%
  of total in the sampled project. Design kept in RFC; implementation
  deferred pending more data.
- Sidecar tiered isolation, artifact schema unification, provider
  session reuse, discussion turn merging — all in
  `docs/workflow-optimizations-backlog.md`.

### Changed

- `convergence_evaluator._evaluate_strict_count` semantics align
  byte-for-byte with the legacy `_round_has_converged` — verified by
  full regression.

### Backward compatibility guarantees

- Shorthand `roles.<role>: <model>` works identically to 0.1.2.
- `discussion.convergence_policy` defaults to `strict_count`.
- `council delegate` JSON shape for success paths unchanged.
- `--model` CLI flag retains highest-priority override behavior.
- Pre-existing 78 done tasks required zero code rework.

### Tests

- 318+ pytest (was 189 at 0.1.2): +129 new tests across
  `test_config_schema.py`, `test_when_eval.py`, `test_role_router.py`,
  `test_convergence_evaluator.py`, routing integration in
  `test_cli_delegate.py`, routing / convergence distribution in
  `test_cli_status.py`, etc.
- `ruff check src/ tests/`: clean.

### Operator note

No upgrade actions required. `pipx upgrade councilflow` picks up 0.1.3.
To opt into dynamic routing, see
`src/councilflow/templates/default-config.yaml` examples or
`docs/integration.md → Dynamic Role Routing`. To opt into semantic
convergence, add `convergence_policy: semantic` (or `hybrid`) to your
project's `discussion` config block.

See `docs/release-notes-0.1.3.md` for the full write-up.

## [0.1.2] — 2026-04-19

Patch release that fixes the second half of the TASK-007A incident. With
0.1.1 the tester preflight stopped blocking on Claude permissions, which
exposed a deeper problem: the sidecar worktree created by ``git worktree
add --detach HEAD`` never included the host's uncommitted changes, so the
tester stage was verifying an empty module instead of the implementer's
just-imported code.

### Fixed

- `materialize_workspace` (git_worktree strategy) now **overlays host
  uncommitted state** onto the freshly-added worktree:
  - Untracked (non-ignored) files are copied in.
  - Modified tracked files are overlaid so the worktree sees working-tree
    content, not HEAD content.
  - Files deleted in the working tree are removed from the worktree so
    tests don't see stale HEAD versions.
  - `IsolatedWorkspace.exclude_patterns` still applies on top of
    `.gitignore`, keeping guarded paths (`.claude/**`, `.council/**`, …)
    out regardless of the host's gitignore configuration.
- This closes the symmetric gap to the TASK-058 baseline-driven diff fix:
  TASK-058 made sure the sidecar's writes correctly import back to the
  host; 0.1.2 makes sure the host's uncommitted state correctly materializes
  into the sidecar. Every delegation phase now sees the same source the
  controller does.

### Tests

- 201 pytest (was 191): +10 new overlay unit tests in
  `tests/test_workspace_overlay.py` covering untracked new files, modified
  tracked files, locally deleted files, gitignored files, isolation
  exclude_patterns, nested directories, CRLF preservation, clean-tree
  no-op, and a parametric multi-path case.
- 29 smoke scenarios (was 27): new S28 (untracked + modified overlay
  visible in sidecar) and S29 (gitignore + exclude_patterns still
  enforced).
- `ruff check .`: clean.

### Operator note

No upgrade steps. If you were pre-committing "intermediate" state in your
workflow as a workaround for the old behavior, you can stop doing that.

## [0.1.1] — 2026-04-19

Patch release that changes the per-CLI permission posture for delegated
stages. Follow-up to a real-project incident where the Claude Code tester
preflight returned `permission_blocked` because the chess repo's
`.claude/settings.json::permissions.allow` didn't yet list the
`verification_commands` that planning had just added.

### Changed

- **Claude Code adapter now runs delegated subprocesses with
  `--dangerously-skip-permissions`**, matching the Gemini adapter's long-
  standing `--approval-mode yolo` posture. Delegation safety is enforced by
  the worktree + writable-glob + protected-paths + MCP-policy guardrail
  stack; the upstream CLI permission gate would only add friction on top of
  those four layers without contributing additional safety for an already-
  contained stage. The flag name surfaces the risk intentionally.
- **Tester preflight dropped the Claude-only allow-list comparison.** The
  preflight now only checks that every verification command resolves to an
  executable on PATH. If any are missing, `error_kind=environment_not_ready`
  still fires exactly as before. The `permission_blocked` discriminator is
  gone from the preflight path.
- `docs/integration.md` gained a **Permission and approval model per CLI**
  section that lays out each CLI's gate and what CouncilFlow does with it.

### Fixed

- Planning pipelines no longer need to pre-seed
  `.claude/settings.json::permissions.allow` for a task's
  `verification_commands` before `council delegate --role tester` can run.
  The old behavior surfaced late (at delegation time) and required either
  reading orchestrator source or guessing the exact `Bash(<subject>:*)`
  subject pattern.

### Notes for operators

- If you use Codex CLI as a delegation target, verify that your local
  `~/.codex/config.toml::approval_policy` does not require interactive
  approval for `codex exec`. CouncilFlow's adapter does not force a Codex
  approval flag (Codex configs are user-specific); an overly restrictive
  policy will hang a delegated `tester` stage.
- No upgrade steps are required beyond bumping to 0.1.1. Existing
  `.claude/settings.json` files keep working; their allow-lists are simply
  no longer consulted by CouncilFlow's preflight.

### Tests

- 190 pytest cases (net +1: the former Claude allow-list regression is
  replaced by two positive tests — preflight-passes-without-allowlist and
  environment_not_ready-still-fires — plus an adapter test that pins
  `--dangerously-skip-permissions` in `CLAUDE_STREAM_FLAGS`).
- `ruff check .`: clean.

## [0.1.0] — 2026-04-19

Initial public release. CouncilFlow is a CLI-first sidecar that lets a single
controller (Codex CLI, Claude Code CLI, or Gemini CLI) delegate staged work to
other models and run a structured discuss / delegate / synthesize loop without
giving up local-first guardrails.

### Added

- **CLI surface** (`council`)
  - `council version`, `council status`
  - `council discuss` — multi-model discussion with explicit
    `--controller-position`, project-level `discussion.default_models`,
    `min_rounds` / `max_rounds` enforcement, and same-controller short-circuit
    warning.
  - `council delegate` — role-scoped sidecar delegation with
    `--writable-glob`, `--readonly-artifact`, `--allow-commit`,
    `--allow-workflow-state-write`, repeatable `--verification-command`, and
    `--required-artifact` wiring.
  - `council synthesize` — combine artifacts into a controller-language
    synthesis.
  - `council delegation wait <id> --timeout 7200 --poll-interval 30` — poll
    `.council/delegations/<id>/record.json` from a controller whose shell
    timeout is shorter than the real stage duration (default 2 h).
- **Controllers** — auto-detection for Codex / Claude Code / Gemini CLI via
  env markers, plus explicit `controller_override` in `.council/config.yaml`.
  Gemini detection takes priority over Codex/Claude when multiple signals are
  present in the same shell.
- **Role system** — `planner`, `architect`, `implementer`, `tester`,
  `reviewer`, `fixer`, `advisor`, `synthesizer`, each with configurable
  `roles.<role>` target model in `.council/config.yaml`.
- **Routing** — route-first hard contract: every delegation returns
  `local_execution` / `delegated` / `error`; host controllers must not execute
  before routing returns.
- **Sidecar isolation contract**
  - Isolation strategies: `git_worktree` (default), `copy`, `none`.
  - Baseline-driven workspace diff: only the sidecar's own edits are
    reported as changes.
  - `DEFAULT_PROTECTED_PATHS` covers `.claude/state`, `.council/state.json`,
    `.workflow-core`, and the three per-controller `skills/` directories.
  - `DEFAULT_DEPENDENCY_SYMLINKS` exposes `node_modules`, `.venv`, `venv`,
    `vendor`, `.gradle`, `.cargo`, `target` via `mklink /J` on Windows so
    `tester` stages can run `pnpm exec` / `pytest` inside the worktree.
  - `ImportManifest.writable_globs` is deny-by-default (empty list rejects
    every write).
- **Env sandbox** — `build_sandboxed_env` strips `CONTROLLER_ENV_KEYS`
  (`CODEX_SHELL`, `CLAUDECODE`, `GEMINI_CLI`, …) and injects
  `COUNCILFLOW_DELEGATED_STAGE=1` + `COUNCILFLOW_DELEGATION_ID` so sidecar
  subprocesses cannot re-enter `council delegate` / `discuss` / `synthesize`.
- **MCP access policy for delegated roles** — `architect`, `planner`,
  `synthesizer` keep MCP; `implementer`, `tester`, `reviewer`, `fixer`,
  `advisor` run with a worktree-local empty MCP config plus env hints so the
  host's `project-manager` cannot silently write `.claude/state/logs.json` from
  a delegated stage. The workspace-import guardrail remains a backstop when a
  CLI ignores the override.
- **Tester preflight** — probes the host environment for verification
  commands availability and Claude Code permission allowlist entries before
  the stage runs, failing fast with `environment_not_ready` /
  `permission_blocked` kinds.
- **Provider adapters** — Claude Code (`claude -p --verbose --output-format
  stream-json`), Codex (`codex exec [--json]`), Gemini (`--approval-mode yolo
  --output-format text|stream-json`), and an opt-in OpenAI Chat Completions
  adapter for the `gpt` family (`pip install councilflow[openai]`).
- **Model naming** — `resolve_adapter_model` handles direct names (`claude`,
  `codex`, `gemini`, `gpt`), MODEL_ALIASES (`gemini-1.5-flash → gemini`,
  `google → gemini`, `claude-code → claude`, …), prefix passthrough for
  variants (`gemini-2.5-pro`, `gpt-4o-mini`, `o1-preview`), and rejects
  unknown adapters at config-load time.
- **Structured failure kinds** — `adapter_missing`,
  `recursive_workflow_violation`, `guardrail_violation`,
  `environment_not_ready`, `permission_blocked`, `wait_timeout`,
  `delegation_not_found`, `total_timeout`, `idle_timeout`, `process_exit`,
  `os_error`.
- **Structured logging** — `configure_logging()` + `COUNCILFLOW_DEBUG=1` env
  flag. Every delegation stage logs `delegation.start / .completed /
  .guardrail_violation / .mcp_policy` with delegation id and timings.
- **MCP manifest single-source** — `~/.workflow-core/mcp-manifest.json` is
  the canonical registration; `install-global-workflow.ps1` and
  `sync-skills.ps1` both read from this manifest.
- **Workflow skills** — the three per-controller `project-*` skills
  (`project-init`, `project-plan`, `project-change`, `project-discuss`,
  `project-design`, `project-next`, `project-review`, `project-feedback`,
  `project-status`, `project-ask`, `project-resume`) are synchronised from
  `~/.workflow-core/skills/` into `.claude/`, `.codex/`, `.gemini/`.
- **project-next polling contract** — skill docs now require a 2-hour
  `council delegation wait` poll after any shell timeout before emitting
  `workflow_failure`.
- **Provider total timeout** — default raised to 7200 s so realistic stage
  work (Canvas UI, multi-file refactor) is not killed by the provider layer.
- **Run records** — every discussion / delegation appends a structured
  record; delegation records now include the effective MCP policy.

### Changed

- `DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS` raised from 900 s to 7200 s.
- `_ALLOWED_RECURSIVE_SUBCOMMANDS` now permits the read-only
  `delegation wait` subcommand inside delegated sidecars.
- Windows argv glob expansion disabled at the Typer/Click entry point so
  patterns like `--writable-glob 'src/features/**'` stay literal.
- `detect_workspace_changes` rewritten around a workspace baseline snapshot
  (compares sidecar-before to sidecar-after, never against the source tree).
- Gemini host detection now runs before Codex / Claude CLI signals so
  Gemini's process-unique env markers stay authoritative.

### Fixed

- Data-loss incident in a real chess project (untracked source files were
  imported back as deletions): the baseline-driven diff plus deny-by-default
  `writable_globs` prevent both halves of the bug.
- Tester stages could not resolve `pnpm exec` / `pytest` in a fresh worktree
  because `node_modules` / `.venv` were excluded from the copy — dependency
  symlinks now expose them without duplicating the directory.
- Click on Windows pre-expanded `--writable-glob` into already-existing
  filesystem entries, dropping future file patterns; fixed by passing
  `windows_expand_args=False` at `main()`.
- `classify_import_changes` used to accept every change when
  `writable_globs=[]`; empty list now means reject-all, matching intent.
- Controllers prematurely declared `workflow_failure` when their shell
  timeout fired mid-delegation; the new `council delegation wait` command
  plus the updated skill doc make 2 h the authoritative budget.

### Security / safety

- Delegated subprocesses cannot re-enter workflow-entry commands
  (`delegate` / `discuss` / `synthesize`) — recursion is explicitly rejected
  with `error_kind=recursive_workflow_violation` and exit code 2.
- Protected workflow directories (`.claude/state`, `.council/state.json`,
  `.workflow-core`, the three controllers' `skills/` folders) are snapshotted
  before a stage runs and restored on violation with
  `error_kind=guardrail_violation`.

### Tests

- 189 pytest cases (includes 12 new cases for `delegation wait` and the MCP
  role policy).
- 27-scenario live smoke harness at `.smoke/full_live_smoke.py` covering the
  CLI, router, guardrails, env sandbox, MCP policy, provider registry, and
  the `delegation wait` polling paths.
- Full smoke report: `docs/full-smoke-report-2026-04-19.md`.

### Known limitations

- Real-CLI adapter smoke (Codex / Claude / Gemini making live HTTP requests)
  is exercised manually; the packaged harness uses fake adapters to stay
  offline. Run a manual smoke with valid credentials before shipping.
- MCP policy is best-effort on CLIs that do not honour worktree-local
  settings — the workspace-import guardrail remains the final backstop.
- Windows-first: dependency symlinks use `mklink /J`; the logic is also
  defined for POSIX symlinks but Linux / macOS coverage is exercised through
  unit tests only, not a packaged smoke run.

[0.1.5]: https://github.com/SuperRedHat/CouncilFlow/releases/tag/v0.1.5
[0.1.4]: https://github.com/SuperRedHat/CouncilFlow/releases/tag/v0.1.4
[0.1.3]: https://github.com/SuperRedHat/CouncilFlow/releases/tag/v0.1.3
[0.1.2]: https://github.com/SuperRedHat/CouncilFlow/releases/tag/v0.1.2
[0.1.1]: https://github.com/SuperRedHat/CouncilFlow/releases/tag/v0.1.1
[0.1.0]: https://github.com/SuperRedHat/CouncilFlow/releases/tag/v0.1.0
