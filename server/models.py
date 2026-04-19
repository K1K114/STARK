from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConnectLichessRequest(BaseModel):
    game_id: str = Field(..., min_length=1, description="Lichess game ID")
    token: str | None = Field(
        default=None,
        description="Bearer token; defaults to LICHESS_TOKEN env if omitted",
    )


class ConnectLichessResponse(BaseModel):
    ok: bool = True
    game_id: str


class GameStateResponse(BaseModel):
    fen: str
    turn: Literal["white", "black"]
    game_status: str | None = None
    lichess_moves: str | None = Field(
        default=None,
        description="Space-separated UCI moves from Lichess stream, if known",
    )


class MakeMoveRequest(BaseModel):
    uci: str = Field(..., min_length=4, max_length=5, description="UCI move, e.g. e2e4")


class MakeMoveResponse(BaseModel):
    ok: bool = True
    fen: str


class TopLineInfo(BaseModel):
    multipv: int
    score_cp: int | None = None
    mate: int | None = None
    pv_uci: list[str] = Field(default_factory=list)


class AnalyzeLastMoveResponse(BaseModel):
    classification: str
    uci_played: str
    centipawn_loss: float | None = Field(
        default=None,
        description="Approximate centipawn loss from mover POV; null if mate-only",
    )
    best_uci: str | None = None
    best_score_cp: int | None = None
    played_score_cp: int | None = None
    top_lines: list[TopLineInfo] = Field(default_factory=list)
