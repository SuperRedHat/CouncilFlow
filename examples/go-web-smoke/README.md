# Go Web Smoke Example

This example is a deliberately small 9x9 Go-like web game used to verify that `CouncilFlow` can support a real development loop under a Codex-led session.

## Scope

- Minimal Python backend using the standard library
- Static frontend with plain HTML, CSS, and JavaScript
- Board rendering, turn switching, reset, and occupied-point validation
- No capture, ko, suicide, territory, or scoring rules

## Run

```powershell
python examples/go-web-smoke/backend/server.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API

- `GET /api/state`
- `POST /api/move` with `{ "row": 4, "col": 4 }`
- `POST /api/reset`
