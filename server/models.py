from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

GameMode = Literal["lichess", "training", "playing"]


class ConnectRequest(BaseModel):
    """Start a session: Lichess online, or local training / vs-AI."""

    mode: GameMode = Field(
        ...,
        description=(
            "lichess = Board API stream + moves on lichess.org; "
            "training = local board, LC0 feedback after your moves; "
            "playing = local board, you vs LC0 (no Lichess)"
        ),
    )
    game_id: str | None = Field(
        default=None,
        description="Required when mode=lichess",
    )
    token: str | None = Field(
        default=None,
        description="Bearer token; required for lichess (else LICHESS_TOKEN env)",
    )
    human_color: Literal["white", "black"] = Field(
        default="white",
        description="Your color: lichess = only you may POST moves on that turn; "
        "training = feedback only when you move; playing = you vs LC0 on this color",
    )

    @model_validator(mode="after")
    def validate_mode_fields(self) -> ConnectRequest:
        if self.mode == "lichess":
            gid = (self.game_id or "").strip()
            if not gid:
                raise ValueError("lichess mode requires game_id")
            self.game_id = gid
        else:
            self.game_id = None
        return self


class ConnectResponse(BaseModel):
    ok: bool = True
    mode: GameMode
    human_color: Literal["white", "black"]
    game_id: str | None = Field(
        default=None,
        description="Set for lichess; null for local training/playing",
    )


class GameStateResponse(BaseModel):
    fen: str
    turn: Literal["white", "black"]
    mode: GameMode | None = None
    human_color: Literal["white", "black"] | None = None
    is_human_turn: bool | None = Field(
        default=None,
        description="For playing/lichess: your turn to move; for training local, same when it's your color",
    )
    game_status: str | None = None
    lichess_moves: str | None = Field(
        default=None,
        description="Lichess stream move list (lichess mode only)",
    )


class MakeMoveRequest(BaseModel):
    uci: str = Field(..., min_length=4, max_length=5, description="UCI move, e.g. e2e4")


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


class EngineReply(BaseModel):
    """LC0 reply in playing mode (local board only)."""

    uci: str
    fen: str


class MakeMoveResponse(BaseModel):
    ok: bool = True
    fen: str
    training_feedback: AnalyzeLastMoveResponse | None = Field(
        default=None,
        description="training mode: LC0 classification when you (human_color) just moved",
    )
    engine_reply: EngineReply | None = Field(
        default=None,
        description="playing mode: LC0 move after yours",
    )


# --- Legacy body for POST /connect_lichess (maps to mode=lichess) ---


class ConnectLichessLegacyRequest(BaseModel):
    game_id: str = Field(..., min_length=1)
    token: str | None = None
    human_color: Literal["white", "black"] = "white"
