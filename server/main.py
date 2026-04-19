# Run: uvicorn server.main:app --reload

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import chess
from fastapi import FastAPI, HTTPException

from . import lichess_client
from .models import (
    AnalyzeLastMoveResponse,
    ConnectLichessRequest,
    ConnectLichessResponse,
    GameStateResponse,
    MakeMoveRequest,
    MakeMoveResponse,
    TopLineInfo,
)
from .teaching import EngineHolder, build_top_lines, classify_move

logger = logging.getLogger(__name__)


def _engine_limit() -> chess.engine.Limit:
    nodes_s = os.environ.get("LC0_NODES", "").strip()
    time_s = os.environ.get("LC0_TIME", "").strip()
    if nodes_s.isdigit():
        return chess.engine.Limit(nodes=int(nodes_s))
    if time_s:
        try:
            return chess.engine.Limit(time=float(time_s))
        except ValueError:
            pass
    return chess.engine.Limit(nodes=80_000)


@dataclass
class AppState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    board: chess.Board = field(default_factory=chess.Board)
    game_id: str | None = None
    token: str | None = None
    initial_fen: str | None = None
    lichess_moves: str | None = None
    game_status: str | None = None
    stream_task: asyncio.Task[None] | None = None
    aiohttp_session: aiohttp.ClientSession | None = None
    engine_holder: EngineHolder = field(default_factory=EngineHolder)
    board_before_last: chess.Board | None = None
    last_move_uci: str | None = None


state = AppState()


async def _apply_lichess_event(payload: dict[str, Any]) -> None:
    t = payload.get("type")
    async with state.lock:
        if t == "gameFull":
            gd = payload.get("state") or {}
            moves = gd.get("moves") or ""
            init = (payload.get("initialFen") or "").strip() or None
            state.initial_fen = init
            state.lichess_moves = moves
            state.game_status = gd.get("status")
            try:
                state.board = lichess_client.board_from_lichess_state(moves, init)
            except ValueError as e:
                logger.error("Board sync error: %s", e)
            return
        if t == "gameState":
            moves = payload.get("moves") or ""
            state.lichess_moves = moves
            state.game_status = payload.get("status")
            try:
                state.board = lichess_client.board_from_lichess_state(
                    moves, state.initial_fen
                )
            except ValueError as e:
                logger.error("Board sync error: %s", e)
            return
        if t == "gameFinish":
            state.game_status = "finished"
            return


async def _stream_worker() -> None:
    assert state.aiohttp_session is not None
    assert state.game_id and state.token
    try:
        await lichess_client.consume_board_stream(
            state.aiohttp_session,
            state.token,
            state.game_id,
            _apply_lichess_event,
        )
    except asyncio.CancelledError:
        raise
    except aiohttp.ClientError as e:
        logger.error("Lichess stream error: %s", e)
    except Exception:
        logger.exception("Lichess stream failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
    state.aiohttp_session = aiohttp.ClientSession(timeout=timeout)
    yield
    if state.stream_task and not state.stream_task.done():
        state.stream_task.cancel()
        try:
            await state.stream_task
        except asyncio.CancelledError:
            pass
    state.stream_task = None
    if state.aiohttp_session:
        await state.aiohttp_session.close()
        state.aiohttp_session = None
    await state.engine_holder.close()


app = FastAPI(title="STARK Gantry Lichess + LC0", lifespan=lifespan)


@app.post("/connect_lichess", response_model=ConnectLichessResponse)
async def connect_lichess(body: ConnectLichessRequest) -> ConnectLichessResponse:
    token = (body.token or os.environ.get("LICHESS_TOKEN", "")).strip()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Missing token: set LICHESS_TOKEN or pass token in body",
        )
    if state.aiohttp_session is None:
        raise HTTPException(status_code=503, detail="HTTP client not ready")

    if state.stream_task and not state.stream_task.done():
        state.stream_task.cancel()
        try:
            await state.stream_task
        except asyncio.CancelledError:
            pass

    async with state.lock:
        state.game_id = body.game_id.strip()
        state.token = token
        state.initial_fen = None
        state.lichess_moves = None
        state.game_status = None
        state.board = chess.Board()
        state.board_before_last = None
        state.last_move_uci = None

    state.stream_task = asyncio.create_task(_stream_worker())
    return ConnectLichessResponse(game_id=body.game_id.strip())


@app.get("/game_state", response_model=GameStateResponse)
async def game_state() -> GameStateResponse:
    if not state.game_id:
        raise HTTPException(
            status_code=503,
            detail="Not connected: call POST /connect_lichess first",
        )
    async with state.lock:
        fen = state.board.fen()
        turn = "white" if state.board.turn else "black"
        return GameStateResponse(
            fen=fen,
            turn=turn,
            game_status=state.game_status,
            lichess_moves=state.lichess_moves,
        )


@app.post("/make_move", response_model=MakeMoveResponse)
async def make_move(body: MakeMoveRequest) -> MakeMoveResponse:
    if not state.game_id or not state.token or state.aiohttp_session is None:
        raise HTTPException(
            status_code=503,
            detail="Not connected: call POST /connect_lichess first",
        )
    uci = body.uci.strip()
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UCI")

    async with state.lock:
        if move not in state.board.legal_moves:
            raise HTTPException(status_code=400, detail="Illegal move for current position")
        before = state.board.copy(stack=False)

    try:
        await lichess_client.post_move(
            state.aiohttp_session, state.token, state.game_id, uci
        )
    except aiohttp.ClientResponseError as e:
        raise HTTPException(status_code=502, detail=f"Lichess rejected move: {e.message}")
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Lichess HTTP error: {e!s}")

    async with state.lock:
        state.board_before_last = before
        state.last_move_uci = uci
        state.board.push(move)
        return MakeMoveResponse(fen=state.board.fen())


@app.post("/analyze_last_move", response_model=AnalyzeLastMoveResponse)
async def analyze_last_move() -> AnalyzeLastMoveResponse:
    async with state.lock:
        uci = state.last_move_uci
        before = state.board_before_last
    if not uci or before is None:
        raise HTTPException(
            status_code=409,
            detail="No move to analyze: call POST /make_move first",
        )
    try:
        played = chess.Move.from_uci(uci)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stored UCI")

    if played not in before.legal_moves:
        raise HTTPException(
            status_code=409,
            detail="Stored last move is not legal on the saved pre-move board",
        )

    try:
        engine = await state.engine_holder.ensure_engine()
    except (FileNotFoundError, chess.engine.EngineError, OSError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"LC0 engine failed to start: {e!s}. Check LC0_PATH / LC0_WEIGHTS.",
        )

    limit = _engine_limit()
    try:
        infos = await engine.analyse(before, limit, multipv=3)
    except (chess.engine.EngineError, asyncio.CancelledError, BrokenPipeError) as e:
        raise HTTPException(status_code=500, detail=f"Engine analysis failed: {e!s}")

    label, loss, best_uci, best_cp, played_cp = await classify_move(
        engine, before, infos, played, limit
    )
    tops = [TopLineInfo(**x) for x in build_top_lines(before, infos)]
    return AnalyzeLastMoveResponse(
        classification=label,
        uci_played=uci,
        centipawn_loss=loss,
        best_uci=best_uci,
        best_score_cp=best_cp,
        played_score_cp=played_cp,
        top_lines=tops,
    )
