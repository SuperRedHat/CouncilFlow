# Release Checklist

## Automated Verification

- Run `python -m ruff check .`
- Run `python -m pytest`
- Verify workflow integration tests cover the staged
  `implementer -> tester -> reviewer -> [fixer -> tester -> reviewer]*` route loop and stop on
  route/artifact failures.

## Manual Smoke

- Verify `council discuss`, `council delegate`, and `council status` from a Codex-controlled session.
- Verify the same command set from a Claude Code-controlled session.
- Verify the same command set from a Gemini CLI-controlled session.
- Verify a real `council discuss` run now follows `initial_position -> external critique -> controller response`, instead of stopping after the first external agreement.
- Verify a project with `discussion.min_rounds` configured does not converge before that minimum number of rounds is reached.
- Verify omitting `--models` still uses project-local `discussion.default_models`.
- Verify same-controller discuss requests show a warning instead of triggering sidecar execution.
- Verify same-controller delegate requests return local execution instead of triggering sidecar execution.
- Verify duplicate discuss models are ignored after normalization.
- Verify `.council/` state can be reused after interruption and restart.
- Verify no sidecar activation happens when a role resolves to the current controller.
- Verify the upgraded `.council/discuss/<discussion_id>/summary.md` artifact still exposes fields that downstream `project-*` workflows can read explicitly.
- Verify `project-next` now follows
  `implementer -> tester -> reviewer -> [fixer -> tester -> reviewer]*`, instead of letting the
  controller silently run tests, skip review, or patch locally.
- Verify `project-feedback` closes or reopens gates only, and creates follow-up repair work instead
  of directly acting as `tester` or `fixer`.
- Verify route/discuss failures stop the workflow instead of silently switching to local execution.
- Verify temporarily hiding or breaking the `council` command produces an explicit local fallback,
  and that this downgrade is clearly distinguished from normal route failures.

## Gate Rule

- `Codex-first` hardening can ship ahead of the final tri-controller gate, but it does not replace the full release gate.
- Do not modify `C:\Users\David Zhai\.workflow-core` shared skills as the final source of truth until every automated check passes and every tri-controller smoke item above is accepted.
- Do not mark the workflow-hardening gate complete until the staged role loop above is validated in
  a real controller session and no role-driven skill can silently skip routing.
