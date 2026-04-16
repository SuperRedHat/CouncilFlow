# Release Checklist

## Automated Verification

- Run `python -m ruff check .`
- Run `python -m pytest`

## Manual Smoke

- Verify `council discuss`, `council delegate`, and `council status` from a Codex-controlled session.
- Verify the same command set from a Claude Code-controlled session.
- Verify same-controller discuss requests show a warning instead of triggering sidecar execution.
- Verify duplicate discuss models are ignored after normalization.
- Verify `.council/` state can be reused after interruption and restart.
- Verify no sidecar activation happens when a role resolves to the current controller.

## Gate Rule

- Do not modify `C:\Users\David Zhai\.workflow-core` shared skills until every automated check passes and every manual smoke item above is accepted.
