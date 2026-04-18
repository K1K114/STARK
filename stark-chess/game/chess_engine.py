"""
Stockfish integration via python-chess.

Wraps engine lifecycle, move validation, and best-move calculation.

Usage:
    engine = ChessEngine(stockfish_path="/usr/local/bin/stockfish")
    best_move = engine.get_best_move(board, time_limit=1.0)
    engine.close()

Or use as a context manager:
    with ChessEngine() as engine:
        move = engine.get_best_move(board)
"""

import chess
import chess.engine
import os


# Default Stockfish path — override with STOCKFISH_PATH env var or pass explicitly
DEFAULT_STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "stockfish")


class ChessEngine:
    def __init__(self, stockfish_path=DEFAULT_STOCKFISH_PATH, skill_level=10):
        """
        Args:
            stockfish_path: Path to the Stockfish binary.
            skill_level: Stockfish skill level 0–20. Lower = easier opponent.
        """
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Stockfish not found at '{stockfish_path}'.\n"
                "Install it: brew install stockfish  (Mac)\n"
                "            sudo apt install stockfish  (Linux)\n"
                "Or set STOCKFISH_PATH in your .env file."
            )
        self._engine.configure({"Skill Level": skill_level})

    # ------------------------------------------------------------------
    # Move validation
    # ------------------------------------------------------------------

    @staticmethod
    def parse_move(board, move_str):
        """Try to parse a UCI move string, trying both square orderings.

        board_state.py returns two changed squares sorted alphabetically
        (e.g. "e2e4"). This function tries both orderings and returns the
        legal one.

        Args:
            board: chess.Board at the current position.
            move_str: 4-character string like "e2e4" or "e4e2".

        Returns:
            chess.Move if one ordering is legal, else None.
        """
        if len(move_str) != 4:
            return None
        sq_a, sq_b = move_str[:2], move_str[2:]
        for uci in [move_str, sq_b + sq_a]:
            try:
                move = chess.Move.from_uci(uci)
                if board.is_legal(move):
                    return move
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Engine queries
    # ------------------------------------------------------------------

    def get_best_move(self, board, time_limit=1.0):
        """Ask Stockfish for the best response move.

        Args:
            board: chess.Board (should have the human's move already pushed).
            time_limit: Seconds to think.

        Returns:
            chess.Move or None if the game is already over.
        """
        if board.is_game_over():
            return None
        result = self._engine.play(board, chess.engine.Limit(time=time_limit))
        return result.move

    def evaluate(self, board, time_limit=0.1):
        """Return centipawn score from White's perspective (positive = White winning)."""
        info = self._engine.analyse(board, chess.engine.Limit(time=time_limit))
        score = info["score"].white()
        if score.is_mate():
            return float("inf") if score.mate() > 0 else float("-inf")
        return score.score()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        self._engine.quit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
