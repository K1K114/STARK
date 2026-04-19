from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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


# --- Physical board LED hints (ESP32 polls GET /hardware/move_hint) ---


class MoveHintRequest(BaseModel):
    """Set which square to highlight first (from), then second (to)."""

    uci: str | None = Field(
        default=None,
        description="Full UCI move, e.g. e2e4 (from = e2, to = e4)",
    )
    clear: bool = Field(
        default=False,
        description="If true, clear hint and turn conceptual LEDs off",
    )

    @model_validator(mode="after")
    def validate_uci_or_clear(self) -> MoveHintRequest:
        if self.clear:
            return self
        u = (self.uci or "").strip()
        if len(u) < 4:
            raise ValueError("Provide uci (e.g. e2e4) or set clear=true")
        self.uci = u
        return self


class SquareLedInfo(BaseModel):
    square: str
    base_led: int = Field(..., ge=0, le=7, description="Index on file / base strip (a=0)")
    side_led: int = Field(..., ge=0, le=7, description="Index on rank / side strip (rank 1=0)")
    # Use list[int] (not tuple) so OpenAPI 3.0 gets { type: array, items, minItems, maxItems }
    # instead of JSON-Schema prefixItems, which breaks Swagger / some clients.
    rgb: list[int] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="WS2812 RGB, three integers 0-255",
    )

    @field_validator("rgb")
    @classmethod
    def _rgb_range(cls, v: list[int]) -> list[int]:
        for c in v:
            if c < 0 or c > 255:
                raise ValueError("rgb values must be between 0 and 255")
        return v


class MoveHintResponse(BaseModel):
    """Current hint for firmware + UI. When a hint is set, phase alternates from -> to."""

    phase: Literal["idle", "from", "to"]
    uci: str | None = None
    from_square: SquareLedInfo | None = None
    to_square: SquareLedInfo | None = None
    elapsed_sec: float = 0.0
    cycle_from_sec: float = Field(default=1.2, description="Seconds to show from-square")
    cycle_to_sec: float = Field(default=1.2, description="Seconds to show to-square")
