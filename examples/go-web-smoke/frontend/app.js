const boardElement = document.getElementById("board");
const playerElement = document.getElementById("current-player");
const moveCountElement = document.getElementById("move-count");
const messageElement = document.getElementById("message");
const resetButton = document.getElementById("reset-button");

let gameState = null;
let busy = false;

function playerLabel(player) {
  return player === 1 ? "黑" : "白";
}

function setMessage(message, isError = false) {
  messageElement.textContent = message;
  messageElement.style.color = isError ? "#b91c1c" : "#166534";
}

function renderBoard() {
  if (!gameState) {
    return;
  }

  boardElement.innerHTML = "";
  playerElement.textContent = `当前执子：${playerLabel(gameState.next_player)}`;
  moveCountElement.textContent = `手数：${gameState.move_count}`;

  gameState.board.forEach((row, rowIndex) => {
    row.forEach((cell, colIndex) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cell";
      button.setAttribute("aria-label", `第 ${rowIndex + 1} 行，第 ${colIndex + 1} 列`);
      button.addEventListener("click", () => placeStone(rowIndex, colIndex));

      if (cell !== 0) {
        const stone = document.createElement("div");
        stone.className = `stone ${cell === 1 ? "black" : "white"}`;
        button.appendChild(stone);
      }

      boardElement.appendChild(button);
    });
  });
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败。");
  }
  return payload;
}

async function refreshState() {
  gameState = await requestJson("/api/state");
  renderBoard();
}

async function placeStone(row, col) {
  if (busy) {
    return;
  }
  busy = true;
  try {
    gameState = await requestJson("/api/move", {
      method: "POST",
      body: JSON.stringify({ row, col }),
    });
    setMessage(`已落子：${row + 1} 行 ${col + 1} 列。`);
    renderBoard();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    busy = false;
  }
}

resetButton.addEventListener("click", async () => {
  if (busy) {
    return;
  }
  busy = true;
  try {
    gameState = await requestJson("/api/reset", { method: "POST", body: "{}" });
    setMessage("棋盘已重置。");
    renderBoard();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    busy = false;
  }
});

refreshState()
  .then(() => setMessage("点击棋盘开始这轮烟测。"))
  .catch((error) => setMessage(error.message, true));
