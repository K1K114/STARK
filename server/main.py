# Run: uvicorn server.main:app --reload

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import aiohttp
import chess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import lichess_client
from .led_map import rgb_for_phase, square_to_led_indices, uci_to_from_to
from .models import (
    AnalyzeLastMoveResponse,
    ConnectLichessLegacyRequest,
    ConnectRequest,
    ConnectResponse,
    EngineReply,
    GameMode,
    GameStateResponse,
    MakeMoveRequest,
    MakeMoveResponse,
    MoveHintRequest,
    MoveHintResponse,
    SquareLedInfo,
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


def _engine_play_limit() -> chess.engine.Limit:
    nodes_s = os.environ.get("LC0_PLAY_NODES", "").strip()
    time_s = os.environ.get("LC0_PLAY_TIME", "").strip()
    if nodes_s.isdigit():
        return chess.engine.Limit(nodes=int(nodes_s))
    if time_s:
        try:
            return chess.engine.Limit(time=float(time_s))
        except ValueError:
            pass
    return chess.engine.Limit(nodes=25_000)


def _human_is_white(human_color: str) -> bool:
    return human_color.strip().lower() == "white"


def _is_human_turn(board: chess.Board, human_color: str) -> bool:
    return board.turn == chess.WHITE if _human_is_white(human_color) else board.turn == chess.BLACK


@dataclass
class AppState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    board: chess.Board = field(default_factory=chess.Board)
    session_active: bool = False
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
    mode: GameMode = "training"
    human_color: Literal["white", "black"] = "white"
    # LED move hint (for ESP32 + static UI): from-square then to-square
    hint_uci: str | None = None
    hint_from: str | None = None
    hint_to: str | None = None
    hint_start_monotonic: float | None = None
    hint_cycle_from_sec: float = 1.2
    hint_cycle_to_sec: float = 1.2


state = AppState()


async def _build_analysis_response(
    before: chess.Board, uci: str
) -> AnalyzeLastMoveResponse:
    try:
        played = chess.Move.from_uci(uci)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid UCI") from e
    if played not in before.legal_moves:
        raise HTTPException(
            status_code=409,
            detail="Stored move is not legal on the saved pre-move board",
        )
    try:
        engine = await state.engine_holder.ensure_engine()
    except (FileNotFoundError, chess.engine.EngineError, OSError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"LC0 engine failed to start: {e!s}. Check LC0_PATH / LC0_WEIGHTS.",
        ) from e
    limit = _engine_limit()
    try:
        infos = await engine.analyse(before, limit, multipv=3)
    except (chess.engine.EngineError, asyncio.CancelledError, BrokenPipeError) as e:
        raise HTTPException(status_code=500, detail=f"Engine analysis failed: {e!s}") from e
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


async def _apply_lichess_event(payload: dict[str, Any]) -> None:
    t = payload.get("type")
    async with state.lock:
        if state.mode != "lichess":
            return
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


@app.get("/")
async def root():
    if (_STATIC_DIR / "index.html").is_file():
        return RedirectResponse(url="/static/index.html")
    return {"ok": True, "docs": "/docs", "hint": "GET /hardware/move_hint"}


def _set_move_hint_uci(uci: str) -> None:
    f, t = uci_to_from_to(uci)
    state.hint_uci = uci.strip().lower()
    state.hint_from = f
    state.hint_to = t
    state.hint_start_monotonic = time.monotonic()


def _clear_move_hint() -> None:
    state.hint_uci = None
    state.hint_from = None
    state.hint_to = None
    state.hint_start_monotonic = None


def _build_move_hint_response() -> MoveHintResponse:
    if not state.hint_from or not state.hint_to or state.hint_start_monotonic is None:
        return MoveHintResponse(
            phase="idle",
            uci=None,
            from_square=None,
            to_square=None,
            elapsed_sec=0.0,
            cycle_from_sec=state.hint_cycle_from_sec,
            cycle_to_sec=state.hint_cycle_to_sec,
        )

    elapsed = time.monotonic() - state.hint_start_monotonic
    cycle = state.hint_cycle_from_sec + state.hint_cycle_to_sec
    t = elapsed % cycle if cycle > 0 else 0.0
    if t < state.hint_cycle_from_sec:
        phase: Literal["from", "to"] = "from"
    else:
        phase = "to"

    fi = square_to_led_indices(state.hint_from)
    ti = square_to_led_indices(state.hint_to)
    from_rgb = rgb_for_phase("from")
    to_rgb = rgb_for_phase("to")

    return MoveHintResponse(
        phase=phase,
        uci=state.hint_uci,
        from_square=SquareLedInfo(
            square=fi["square"],
            base_led=fi["base_led"],
            side_led=fi["side_led"],
            rgb=from_rgb,
        ),
        to_square=SquareLedInfo(
            square=ti["square"],
            base_led=ti["base_led"],
            side_led=ti["side_led"],
            rgb=to_rgb,
        ),
        elapsed_sec=round(elapsed, 3),
        cycle_from_sec=state.hint_cycle_from_sec,
        cycle_to_sec=state.hint_cycle_to_sec,
    )


@app.get("/hardware/move_hint", response_model=MoveHintResponse)
async def get_move_hint() -> MoveHintResponse:
    """Poll from ESP32: current phase + base/side LED indices + RGB."""
    async with state.lock:
        return _build_move_hint_response()


@app.post("/hardware/move_hint", response_model=MoveHintResponse)
async def post_move_hint(body: MoveHintRequest) -> MoveHintResponse:
    """Push a move hint (UCI) or clear. Does not require /connect session."""
    async with state.lock:
        if body.clear:
            _clear_move_hint()
            return _build_move_hint_response()
        assert body.uci is not None
        try:
            _set_move_hint_uci(body.uci)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _build_move_hint_response()


async def _start_connect(body: ConnectRequest) -> ConnectResponse:
    if state.aiohttp_session is None:
        raise HTTPException(status_code=503, detail="HTTP client not ready")

    if state.stream_task and not state.stream_task.done():
        state.stream_task.cancel()
        try:
            await state.stream_task
        except asyncio.CancelledError:
            pass
    state.stream_task = None

    token = (body.token or os.environ.get("LICHESS_TOKEN", "")).strip() or None
    if body.mode == "lichess" and not token:
        raise HTTPException(
            status_code=400,
            detail="lichess mode requires token or LICHESS_TOKEN env",
        )

    async with state.lock:
        state.mode = body.mode
        state.human_color = body.human_color
        state.board_before_last = None
        state.last_move_uci = None
        state.session_active = True
        state.game_status = None
        state.lichess_moves = None
        state.initial_fen = None

        if body.mode == "lichess":
            assert body.game_id is not None
            state.game_id = body.game_id
            state.token = token
            state.board = chess.Board()
        else:
            state.game_id = None
            state.token = None
            state.board = chess.Board()

    if body.mode == "lichess":
        state.stream_task = asyncio.create_task(_stream_worker())

    return ConnectResponse(
        mode=body.mode,
        human_color=body.human_color,
        game_id=body.game_id if body.mode == "lichess" else None,
    )


@app.post("/connect", response_model=ConnectResponse)
async def connect(body: ConnectRequest) -> ConnectResponse:
    return await _start_connect(body)


@app.post("/connect_lichess", response_model=ConnectResponse)
async def connect_lichess(body: ConnectLichessLegacyRequest) -> ConnectResponse:
    """Backward-compatible alias: same as POST /connect with mode=lichess."""
    req = ConnectRequest(
        mode="lichess",
        game_id=body.game_id,
        token=body.token,
        human_color=body.human_color,
    )
    return await _start_connect(req)


@app.get("/game_state", response_model=GameStateResponse)
async def game_state() -> GameStateResponse:
    if not state.session_active:
        raise HTTPException(
            status_code=503,
            detail="Not connected: call POST /connect first",
        )
    async with state.lock:
        fen = state.board.fen()
        turn = "white" if state.board.turn else "black"
        return GameStateResponse(
            fen=fen,
            turn=turn,
            mode=state.mode,
            human_color=state.human_color,
            is_human_turn=_is_human_turn(state.board, state.human_color),
            game_status=state.game_status,
            lichess_moves=state.lichess_moves if state.mode == "lichess" else None,
        )


@app.post("/make_move", response_model=MakeMoveResponse)
async def make_move(body: MakeMoveRequest) -> MakeMoveResponse:
    if not state.session_active:
        raise HTTPException(
            status_code=503,
            detail="Not connected: call POST /connect first",
        )
    uci = body.uci.strip()
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UCI")

    async with state.lock:
        mode = state.mode
        human_c = state.human_color

    if mode == "lichess":
        return await _make_move_lichess(move, uci, human_c)
    if mode == "training":
        return await _make_move_training(move, uci, human_c)
    return await _make_move_playing(move, uci, human_c)


async def _make_move_lichess(
    move: chess.Move, uci: str, human_c: Literal["white", "black"]
) -> MakeMoveResponse:
    if not state.game_id or not state.token or state.aiohttp_session is None:
        raise HTTPException(status_code=503, detail="Lichess session not configured")

    async with state.lock:
        if not _is_human_turn(state.board, human_c):
            raise HTTPException(
                status_code=400,
                detail="Not your turn on the board (lichess: only your color)",
            )
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


async def _make_move_training(
    move: chess.Move, uci: str, human_c: Literal["white", "black"]
) -> MakeMoveResponse:
    async with state.lock:
        if move not in state.board.legal_moves:
            raise HTTPException(status_code=400, detail="Illegal move for current position")
        before = state.board.copy(stack=False)
        human_mover = _is_human_turn(before, human_c)
        state.board.push(move)
        fen = state.board.fen()
        if human_mover:
            state.board_before_last = before
            state.last_move_uci = uci
        else:
            state.board_before_last = None
            state.last_move_uci = None

    feedback: AnalyzeLastMoveResponse | None = None
    if human_mover:
        feedback = await _build_analysis_response(before, uci)
    return MakeMoveResponse(fen=fen, training_feedback=feedback, engine_reply=None)


async def _make_move_playing(
    move: chess.Move, uci: str, human_c: Literal["white", "black"]
) -> MakeMoveResponse:
    async with state.lock:
        if not _is_human_turn(state.board, human_c):
            raise HTTPException(
                status_code=400,
                detail="Not your turn — wait for LC0 (or start a new game)",
            )
        if move not in state.board.legal_moves:
            raise HTTPException(status_code=400, detail="Illegal move for current position")
        before = state.board.copy(stack=False)

    async with state.lock:
        state.board_before_last = before
        state.last_move_uci = uci
        state.board.push(move)
        fen_after_human = state.board.fen()
        game_over = state.board.is_game_over()
        engine_should_play = not game_over and not _is_human_turn(
            state.board, human_c
        )

    engine_reply: EngineReply | None = None
    final_fen = fen_after_human

    if engine_should_play:
        async with state.lock:
            board_engine_turn = state.board.copy(stack=False)
        try:
            engine = await state.engine_holder.ensure_engine()
            play_result = await engine.play(board_engine_turn, _engine_play_limit())
        except (FileNotFoundError, chess.engine.EngineError, OSError) as e:
            raise HTTPException(
                status_code=500,
                detail=f"LC0 could not play: {e!s}. Check LC0_PATH / LC0_WEIGHTS.",
            ) from e
        except (asyncio.CancelledError, BrokenPipeError) as e:
            raise HTTPException(status_code=500, detail=f"Engine play failed: {e!s}") from e

        eng_move = play_result.move
        eng_uci = eng_move.uci()
        if eng_move not in board_engine_turn.legal_moves:
            raise HTTPException(
                status_code=500,
                detail="Engine returned an illegal move",
            )

        async with state.lock:
            if eng_move not in state.board.legal_moves:
                raise HTTPException(
                    status_code=409,
                    detail="Local board out of sync before engine move",
                )
            state.board.push(eng_move)
            final_fen = state.board.fen()
            engine_reply = EngineReply(uci=eng_uci, fen=final_fen)
            try:
                _set_move_hint_uci(eng_uci)
            except ValueError:
                logger.warning("Could not set LED hint for engine UCI %s", eng_uci)

    return MakeMoveResponse(
        fen=final_fen,
        training_feedback=None,
        engine_reply=engine_reply,
    )


@app.post("/analyze_last_move", response_model=AnalyzeLastMoveResponse)
async def analyze_last_move() -> AnalyzeLastMoveResponse:
    async with state.lock:
        uci = state.last_move_uci
        before = state.board_before_last
    if not uci or before is None:
        raise HTTPException(
            status_code=409,
            detail="No move to analyze: make a move as your color first",
        )
    return await _build_analysis_response(before, uci)
