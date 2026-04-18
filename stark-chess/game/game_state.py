"""
Game state tracker.

Wraps python-chess Board to provide a clean interface for the main game loop.
Tracks move history and whose turn it is.

Usage:
    state = GameState()
    state.apply_move(chess.Move.from_uci("e2e4"))
    print(state.turn)       # "black"
    print(state.is_over())  # False
"""

import chess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MoveRecord:
    move: chess.Move
    uci: str
    san: str          # Standard algebraic notation e.g. "Nf3"
    by: str           # "human" or "engine"


class GameState:
    def __init__(self, fen=chess.STARTING_FEN):
        self.board = chess.Board(fen)
        self.history: list[MoveRecord] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def turn(self):
        """Returns "white" or "black"."""
        return "white" if self.board.turn == chess.WHITE else "black"

    @property
    def move_number(self):
        return self.board.fullmove_number

    @property
    def fen(self):
        return self.board.fen()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def apply_move(self, move: chess.Move, by="human"):
        """Push a legal move onto the board.

        Args:
            move: chess.Move (must be legal).
            by: "human" or "engine" — for logging.

        Raises:
            ValueError if the move is illegal.
        """
        if not self.board.is_legal(move):
            raise ValueError(f"Illegal move: {move.uci()} in position {self.fen}")
        san = self.board.san(move)
        self.board.push(move)
        self.history.append(MoveRecord(move=move, uci=move.uci(), san=san, by=by))

    def undo_last_move(self):
        """Pop the last move. Used when the gantry needs to return a piece."""
        if self.history:
            self.board.pop()
            return self.history.pop()
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_over(self):
        return self.board.is_game_over()

    def result(self):
        """Returns "1-0", "0-1", "1/2-1/2", or "*" (not over)."""
        return self.board.result()

    def outcome_message(self):
        """Human-readable game-over message."""
        outcome = self.board.outcome()
        if outcome is None:
            return "Game still in progress"
        termination = outcome.termination.name.replace("_", " ").title()
        winner = outcome.result()
        return f"{termination} — Result: {winner}"

    def last_move(self) -> Optional[MoveRecord]:
        return self.history[-1] if self.history else None

    def print_board(self):
        print(f"\n  Move {self.move_number} — {self.turn.capitalize()} to move")
        print(self.board)
        print()
