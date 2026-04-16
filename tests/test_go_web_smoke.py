from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

SERVER_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "go-web-smoke"
    / "backend"
    / "server.py"
)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(method: str, url: str, payload: dict[str, object] | None = None) -> tuple[int, str]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


@pytest.fixture()
def go_web_server() -> Iterator[str]:
    port = _pick_free_port()
    env = os.environ.copy()
    env["GO_WEB_SMOKE_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            status, _ = _request("GET", f"{base_url}/api/state")
        except OSError:
            time.sleep(0.2)
            continue
        if status == 200:
            break
    else:
        stdout, stderr = process.communicate(timeout=2)
        raise AssertionError(
            "Go web smoke server failed to start.\n"
            f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
        )

    try:
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_go_web_smoke_serves_frontend(go_web_server: str) -> None:
    status, body = _request("GET", f"{go_web_server}/")

    assert status == 200
    assert "围棋网页小游戏" in body
    assert "app.js" in body


def test_go_web_smoke_move_and_reset_flow(go_web_server: str) -> None:
    status, body = _request("GET", f"{go_web_server}/api/state")
    payload = json.loads(body)

    assert status == 200
    assert payload["size"] == 9
    assert payload["board"][4][4] == 0
    assert payload["next_player"] == 1

    move_status, move_body = _request(
        "POST",
        f"{go_web_server}/api/move",
        {"row": 4, "col": 4},
    )
    move_payload = json.loads(move_body)

    assert move_status == 200
    assert move_payload["board"][4][4] == 1
    assert move_payload["next_player"] == 2
    assert move_payload["move_count"] == 1

    invalid_status, invalid_body = _request(
        "POST",
        f"{go_web_server}/api/move",
        {"row": 4, "col": 4},
    )
    invalid_payload = json.loads(invalid_body)

    assert invalid_status == 400
    assert "occupied" in invalid_payload["error"].lower()

    reset_status, reset_body = _request("POST", f"{go_web_server}/api/reset", {})
    reset_payload = json.loads(reset_body)

    assert reset_status == 200
    assert reset_payload["board"][4][4] == 0
    assert reset_payload["next_player"] == 1
    assert reset_payload["move_count"] == 0
