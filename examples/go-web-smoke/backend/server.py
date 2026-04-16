"""Minimal HTTP backend for the Go web smoke example."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = APP_ROOT / "frontend"


def _fresh_board(size: int) -> list[list[int]]:
    return [[0 for _ in range(size)] for _ in range(size)]


@dataclass
class GoSmokeState:
    """Simple 9x9 state store for the smoke-test game."""

    size: int = 9
    board: list[list[int]] = field(default_factory=lambda: _fresh_board(9))
    next_player: int = 1
    move_count: int = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "size": self.size,
            "board": self.board,
            "next_player": self.next_player,
            "move_count": self.move_count,
            "rules_note": (
                "Smoke-test rules only: place stones, alternate turns, reset board. "
                "Captures, ko, suicide, and scoring are intentionally omitted."
            ),
        }

    def reset(self) -> dict[str, object]:
        self.board = _fresh_board(self.size)
        self.next_player = 1
        self.move_count = 0
        return self.snapshot()

    def place_stone(self, row: int, col: int) -> dict[str, object]:
        if not (0 <= row < self.size and 0 <= col < self.size):
            raise ValueError("Move is outside the board.")
        if self.board[row][col] != 0:
            raise ValueError("The selected point is already occupied.")

        player = self.next_player
        self.board[row][col] = player
        self.move_count += 1
        self.next_player = 2 if player == 1 else 1

        payload = self.snapshot()
        payload["placed"] = {"row": row, "col": col, "player": player}
        return payload


GAME_STATE = GoSmokeState()


class GoSmokeHandler(BaseHTTPRequestHandler):
    """Serve the static frontend plus a tiny JSON API."""

    server_version = "GoSmokeHTTP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route in {"/", "/index.html"}:
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if route == "/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
            return
        if route == "/style.css":
            self._serve_static("style.css", "text/css; charset=utf-8")
            return
        if route == "/api/state":
            self._write_json(HTTPStatus.OK, GAME_STATE.snapshot())
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/move":
            payload = self._read_json_body()
            try:
                row = int(payload["row"])
                col = int(payload["col"])
                state = GAME_STATE.place_stone(row, col)
            except (KeyError, TypeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._write_json(HTTPStatus.OK, state)
            return

        if route == "/api/reset":
            self._write_json(HTTPStatus.OK, GAME_STATE.reset())
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        """Keep test output quiet."""

    def _serve_static(self, name: str, content_type: str) -> None:
        target = FRONTEND_ROOT / name
        if not target.exists():
            self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Missing asset: {name}"})
            return

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        decoded = raw.decode("utf-8") if raw else "{}"
        payload = json.loads(decoded or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return payload


def main() -> None:
    host = os.environ.get("GO_WEB_SMOKE_HOST", "127.0.0.1")
    port = int(os.environ.get("GO_WEB_SMOKE_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), GoSmokeHandler)
    print(f"Go web smoke server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
