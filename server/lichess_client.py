from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import aiohttp
import chess

logger = logging.getLogger(__name__)

LICHESS_BASE = "https://lichess.org"


def board_from_lichess_state(
    moves_uci: str,
    initial_fen: str | None,
) -> chess.Board:
    fen = (initial_fen or "").strip() or chess.STARTING_FEN
    board = chess.Board(fen)
    moves_uci = (moves_uci or "").strip()
    if not moves_uci:
        return board
    for u in moves_uci.split():
        u = u.strip()
        if not u:
            continue
        move = chess.Move.from_uci(u)
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move in Lichess stream: {u!r} (fen={board.fen()})")
        board.push(move)
    return board


async def post_move(
    session: aiohttp.ClientSession,
    token: str,
    game_id: str,
    uci: str,
) -> None:
    url = f"{LICHESS_BASE}/api/board/game/{game_id}/move/{uci}"
    headers = {"Authorization": f"Bearer {token}"}
    async with session.post(url, headers=headers) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise aiohttp.ClientResponseError(
                resp.request_info,
                resp.history,
                status=resp.status,
                message=text[:500],
                headers=resp.headers,
            )


async def consume_board_stream(
    session: aiohttp.ClientSession,
    token: str,
    game_id: str,
    on_event: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """
    Long-lived GET /api/board/game/stream/{gameId} (NDJSON).
    Calls on_event for each decoded JSON object until connection closes.
    """
    url = f"{LICHESS_BASE}/api/board/game/stream/{game_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/x-ndjson",
    }
    async with session.get(url, headers=headers) as resp:
        if resp.status >= 400:
            body = await resp.text()
            raise aiohttp.ClientResponseError(
                resp.request_info,
                resp.history,
                status=resp.status,
                message=body[:500],
                headers=resp.headers,
            )
        while True:
            raw = await resp.content.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping bad NDJSON line: %s", line[:200])
                continue
            await on_event(obj)
