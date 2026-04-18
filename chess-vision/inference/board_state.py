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

    def update(self, frame, gantry_moving=False):
        """Process a new camera frame.

        Args:
            frame: BGR frame from the webcam.
            gantry_moving: Set True while the electromagnet/gantry is active.
                           The detector resets its stability counter so it
                           doesn't misinterpret the gantry's movement as a
                           human move.

        Returns:
            A UCI move string like "e2e4" when a stable human move is
            detected, or None while still waiting.

        Note:
            The returned string is the two changed squares sorted
            alphabetically. If the order matters (it does for python-chess),
            try both orderings and pick the legal one:

                sq_a, sq_b = move[:2], move[2:]
                for uci in [move, sq_b + sq_a]:
                    m = chess.Move.from_uci(uci)
                    if board.is_legal(m): ...
        """
        if gantry_moving:
            # Gantry is moving pieces — ignore all visual changes
            self.stability_count = 0
            self.last_changed = frozenset()
            return None

        if self.reference_frame is None:
            self.set_reference(frame)
            return None

        warped = self._warp(frame)
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)

        # Compute per-pixel absolute difference vs the reference
        diff = cv2.absdiff(gray, self.reference_frame)
        _, thresh = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        # Dilate to merge nearby noise into solid blobs
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

        changed_frozen = frozenset(changed_squares)

        # Require exactly 2 changed squares (from-square + to-square).
        # Captures also produce exactly 2 changes. En passant produces 3 —
        # handled below by using the two most-changed squares.
        if len(changed_squares) == 2:
            if changed_frozen == self.last_changed:
                self.stability_count += 1
            else:
                self.stability_count = 1
                self.last_changed = changed_frozen

            if self.stability_count >= STABILITY_FRAMES:
                squares_sorted = sorted(changed_squares)
                move_str = squares_sorted[0] + squares_sorted[1]
                self.set_reference(frame)  # update baseline to new board state
                return move_str
        else:
            # Not exactly 2 squares — reset stability
            self.stability_count = 0
            self.last_changed = changed_frozen

        return None
