# CouncilFlow

CouncilFlow is a CLI-first, local-first, controller-aware sidecar for
multi-model collaboration across Codex CLI, Claude Code CLI, and Gemini CLI.

See `docs/integration.md` for the full integration contract, the workflow
failure report protocol, the sidecar isolation contract, and the optional
OpenAI (`gpt`) advisor adapter setup.

## Installation

```bash
pip install councilflow
```

To enable the optional `gpt` advisor path via OpenAI's Chat Completions API:

```bash
pip install 'councilflow[openai]'
export OPENAI_API_KEY=sk-...
# Optional: override the default model
export OPENAI_MODEL=gpt-4o-mini
```

## Quick start

```bash
council version
council status
council discuss "how should we shape this module?" --models claude,gemini
council delegate --role implementer --objective "..." --task-summary "..."
```
