"""
Leela Chess Zero (UCI) analysis and move classification.

Centipawn-loss buckets (tunable constants, mover POV at root):
  Brilliant — best engine move plus sacrifice / large second-best gap heuristic
  Great     — 0 < loss <= 2
  Best      — loss == 0 (ties best line)
  Excellent — 2 < loss <= 10
  Good      — 10 < loss <= 25
  Inaccuracy — 25 < loss <= 50
  Mistake   — 50 < loss <= 100
  Blunder   — loss > 100

Mate positions: scores use a large mate_score substitute for comparisons; cp_loss may be null if only mates involved.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine

MATE_CP = 100_000

# Piece values for simple sacrifice detection (centipawns)
_PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def _material_sum(board: chess.Board, color: chess.Color) -> int:
    s = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color:
            s += _PIECE_VALUE.get(p.piece_type, 0)
    return s


def _score_cp_mover(score: chess.engine.PovScore, board: chess.Board) -> int | None:
    """Integer centipawns from side-to-move POV; mate as large substitute."""
    rel = score.relative_to(board.turn)
    if rel.is_mate():
        m = rel.mate()
        if m is None:
            return None
        return MATE_CP if m > 0 else -MATE_CP
    cp = rel.score()
    return int(cp) if cp is not None else None


async def _cp_loss_with_fallback(
    engine: chess.engine.UciProtocol,
    board_before: chess.Board,
    infos: list[dict[str, Any]],
    played: chess.Move,
    limit: chess.engine.Limit,
) -> tuple[float | None, int | None, int | None, str | None]:
    """
    Returns (cp_loss, best_cp, played_cp, best_uci) using root multipv scores;
    if played is outside top multipv, re-analyse with root_moves=[played].
    """
    if not infos:
        return None, None, None, None
    best_info = infos[0]
    pv0 = best_info.get("pv") or []
    best_move = pv0[0] if pv0 else None
    best_uci = best_move.uci() if best_move else None

    best_cp = _score_cp_mover(best_info["score"], board_before)

    played_cp: int | None = None
    for inf in infos:
        pv = inf.get("pv") or []
        if pv and pv[0] == played:
            played_cp = _score_cp_mover(inf["score"], board_before)
            break

    if played_cp is None and played in board_before.legal_moves:
        forced = await engine.analyse(
            board_before, limit, multipv=1, root_moves=[played]
        )
        if forced:
            played_cp = _score_cp_mover(forced[0]["score"], board_before)

    if played_cp is None:
        return None, best_cp, None, best_uci

    if best_cp is None or played_cp is None:
        return None, best_cp, played_cp, best_uci

    loss = float(best_cp - played_cp)
    return loss, best_cp, played_cp, best_uci


def _is_brilliant(
    board_before: chess.Board,
    played: chess.Move,
    best_uci: str | None,
    infos: list[dict[str, Any]],
) -> bool:
    if best_uci is None or played.uci() != best_uci:
        return False
    b = board_before.copy(stack=False)
    our = b.turn
    mat_before = _material_sum(b, our)
    b.push(played)
    mat_after = _material_sum(b, our)
    material_lost = mat_before - mat_after
    if material_lost >= 100 and played.is_capture():
        return True
    if len(infos) >= 2:
        cp0 = _score_cp_mover(infos[0]["score"], board_before)
        cp1 = _score_cp_mover(infos[1]["score"], board_before)
        if cp0 is not None and cp1 is not None and (cp0 - cp1) >= 80:
            return True
    return False


async def classify_move(
    engine: chess.engine.UciProtocol,
    board_before: chess.Board,
    infos: list[dict[str, Any]],
    played: chess.Move,
    limit: chess.engine.Limit,
) -> tuple[str, float | None, str | None, int | None, int | None]:
    loss, best_cp, played_cp, best_uci = await _cp_loss_with_fallback(
        engine, board_before, infos, played, limit
    )
    if loss is None:
        return "Good", None, best_uci, best_cp, played_cp

    if loss <= 0:
        if _is_brilliant(board_before, played, best_uci, infos):
            return "Brilliant", max(0.0, loss), best_uci, best_cp, played_cp
        if loss < 0:
            return "Great", loss, best_uci, best_cp, played_cp
        return "Best", 0.0, best_uci, best_cp, played_cp

    if loss <= 2:
        return "Great", loss, best_uci, best_cp, played_cp
    if loss <= 10:
        return "Excellent", loss, best_uci, best_cp, played_cp
    if loss <= 25:
        return "Good", loss, best_uci, best_cp, played_cp
    if loss <= 50:
        return "Inaccuracy", loss, best_uci, best_cp, played_cp
    if loss <= 100:
        return "Mistake", loss, best_uci, best_cp, played_cp
    return "Blunder", loss, best_uci, best_cp, played_cp


def build_top_lines(
    board_before: chess.Board,
    infos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, inf in enumerate(infos, start=1):
        sc = inf.get("score")
        cp = None
        mate = None
        if isinstance(sc, chess.engine.PovScore):
            rel = sc.relative_to(board_before.turn)
            if rel.is_mate():
                mate = rel.mate()
            else:
                s = rel.score()
                cp = int(s) if s is not None else None
        pv = inf.get("pv") or []
        pv_uci = [m.uci() for m in pv[:12]]
        out.append({"multipv": i, "score_cp": cp, "mate": mate, "pv_uci": pv_uci})
    return out


@dataclass
class EngineHolder:
    transport: chess.engine.BaseTransport | None = None
    engine: chess.engine.UciProtocol | None = None

    async def ensure_engine(self) -> chess.engine.UciProtocol:
        if self.engine is not None:
            return self.engine

        cmd = os.environ.get("LC0_PATH") or shutil.which("lc0") or "lc0"
        extra = os.environ.get("LC0_ARGS", "").strip()
        argv = [cmd] + (extra.split() if extra else [])

        transport, engine = await chess.engine.popen_uci(argv)
        self.transport = transport
        self.engine = engine

        opts: dict[str, str | int] = {}
        weights = os.environ.get("LC0_WEIGHTS", "").strip()
        if weights:
            opts["WeightsFile"] = weights
        threads = os.environ.get("LC0_THREADS", "").strip()
        if threads.isdigit():
            opts["Threads"] = int(threads)
        if opts:
            await engine.configure(opts)

        return engine

    async def close(self) -> None:
        if self.engine is not None:
            try:
                await self.engine.quit()
            except (asyncio.CancelledError, BrokenPipeError, OSError, chess.engine.EngineError):
                pass
            self.engine = None
        self.transport = None
