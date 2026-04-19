"""
Contour-based board state detector.

Compares each incoming frame against a reference "known state" frame using
absolute pixel difference. When the same two squares appear changed across
STABILITY_FRAMES consecutive frames (and gantry_moving is False), the move
is returned as a UCI-style string like "e2e4".

The caller must call set_reference() once at game start (or after each
confirmed move) to update the baseline.

Typical usage from the main game loop:

    detector = BoardStateDetector("calibration/calibration.json")
    detector.set_reference(first_frame)

    while True:
        frame = cam.read()
        move = detector.update(frame, gantry_moving=gantry.is_moving)
        if move:
            # e.g. "e2e4" — validate with python-chess
            handle_move(move)
"""

import sys
import os
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from calibration.calibrate import load_calibration

# How many consecutive frames must show the same changed squares before we trigger
STABILITY_FRAMES = 8

# Pixel brightness delta to count as "changed"
DIFF_THRESHOLD = 30

# Ignore contours smaller than this area (filters sensor noise and reflections)
MIN_CONTOUR_AREA = 400

# Castling always involves exactly these 4 squares — hardcoded for reliability
CASTLING_SQUARE_SETS = {
    frozenset(["e1", "g1", "h1", "f1"]): "e1g1",  # white kingside
    frozenset(["e1", "c1", "a1", "d1"]): "e1c1",  # white queenside
    frozenset(["e8", "g8", "h8", "f8"]): "e8g8",  # black kingside
    frozenset(["e8", "c8", "a8", "d8"]): "e8c8",  # black queenside
}


class BoardStateDetector:
    def __init__(self, calibration_path="calibration/calibration.json"):
        cal = load_calibration(calibration_path)
        self.M = cal["transform_matrix"]
        self.board_size = cal["board_size"]
        self._build_grid_map()

        self.reference_frame = None  # grayscale warped reference
        self.stability_count = 0
        self.last_changed = frozenset()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _build_grid_map(self):
        """Map (col, row) grid indices → chess square name."""
        cell = self.board_size / 8
        files = "abcdefgh"
        ranks = "87654321"  # row 0 = rank 8
        self.grid_map = {}
        for row, rank in enumerate(ranks):
            for col, file in enumerate(files):
                self.grid_map[(col, row)] = f"{file}{rank}"

    def _warp(self, frame):
        return cv2.warpPerspective(frame, self.M, (self.board_size, self.board_size))

    def _pixel_to_square(self, x, y):
        """Convert a pixel coordinate in the warped image to a square name."""
        cell = self.board_size / 8
        col = max(0, min(7, int(x // cell)))
        row = max(0, min(7, int(y // cell)))
        return self.grid_map.get((col, row))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_reference(self, frame):
        """Store the current board state as the new baseline.

        Call this:
          - once at game start on the initial board position
          - after every confirmed move (the detector calls this automatically
            when it triggers, but you can also call it manually)
        """
        warped = self._warp(frame)
        self.reference_frame = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        self.stability_count = 0
        self.last_changed = frozenset()

    def update(self, frame, gantry_moving=False, board=None):
        """Process a new camera frame.

        Args:
            frame: BGR frame from the webcam.
            gantry_moving: Set True while the electromagnet/gantry is active.
            board: Optional chess.Board at the current position. Used to
                   disambiguate en passant (3 changed squares).

        Returns:
            A UCI move string when a stable move is detected, or None.
            Special moves:
              - Normal / capture: "e2e4" (two squares, sorted alphabetically —
                parse_move tries both orderings)
              - Castling: "e1g1" / "e1c1" / "e8g8" / "e8c8" (king's movement)
              - En passant: "e5d6" style (from-sq + ep target, sorted)
        """
        if gantry_moving:
            self.stability_count = 0
            self.last_changed = frozenset()
            return None

        if self.reference_frame is None:
            self.set_reference(frame)
            return None

        warped = self._warp(frame)
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)

        diff = cv2.absdiff(gray, self.reference_frame)
        _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        thresh = cv2.dilate(thresh, kernel, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        changed_squares = set()
        for cnt in contours:
            if cv2.contourArea(cnt) < MIN_CONTOUR_AREA:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            sq = self._pixel_to_square(x + w // 2, y + h // 2)
            if sq:
                changed_squares.add(sq)

        move_str = self._interpret_changed_squares(changed_squares, board)
        changed_frozen = frozenset(changed_squares)

        if move_str is not None:
            if changed_frozen == self.last_changed:
                self.stability_count += 1
            else:
                self.stability_count = 1
                self.last_changed = changed_frozen

            if self.stability_count >= STABILITY_FRAMES:
                self.set_reference(frame)
                return move_str
        else:
            self.stability_count = 0
            self.last_changed = changed_frozen

        return None

    def _interpret_changed_squares(self, changed_squares, board=None):
        """Map a set of changed squares to a UCI move string, or None.

        Handles normal moves (2 squares), en passant (3 squares),
        and castling (4 squares).
        """
        n = len(changed_squares)

        if n == 2:
            sq_a, sq_b = sorted(changed_squares)
            return sq_a + sq_b

        if n == 4:
            # Castling: king + rook both move, producing exactly 4 changes
            cast = CASTLING_SQUARE_SETS.get(frozenset(changed_squares))
            if cast:
                return cast

        if n == 3 and board is not None and board.ep_square is not None:
            import chess as _chess
            ep_sq_name = _chess.square_name(board.ep_square)
            if ep_sq_name in changed_squares:
                # ep_square is the to-square; exclude the captured pawn's square
                # (same file as ep_square, same rank as the moving pawn)
                ep_file = ep_sq_name[0]
                remaining = [sq for sq in changed_squares if sq != ep_sq_name]
                # from-square is the one on a different file than the ep target
                from_sq = next((sq for sq in remaining if sq[0] != ep_file), remaining[0])
                sq_a, sq_b = sorted([from_sq, ep_sq_name])
                return sq_a + sq_b

        return None
