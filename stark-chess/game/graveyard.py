"""
Graveyard state tracker.

Physical layout (single column, one side of board):

    Slot  │ Side   │ Aligned with
    ──────┼────────┼─────────────
    B1    │ Black  │ rank 8
    B2    │ Black  │ rank 7
    B3    │ Black  │ rank 6
    B4    │ Black  │ rank 5
    W1    │ White  │ rank 4
    W2    │ White  │ rank 3
    W3    │ White  │ rank 2
    W4    │ White  │ rank 1

Top 4 slots hold any captured black pieces; bottom 4 hold any captured white pieces.
Pieces fill the next empty slot in their section; overflow when all 4 are full.

Slot pixel centers come from calibration.json (graveyard_slots key).
When USE_YOLO=True, scan_with_cv() cross-checks software state against camera.
"""

import chess

SLOT_ORDER = ["B1", "B2", "B3", "B4", "W1", "W2", "W3", "W4"]

SLOT_COLOR = {
    "B1": chess.BLACK, "B2": chess.BLACK, "B3": chess.BLACK, "B4": chess.BLACK,
    "W1": chess.WHITE, "W2": chess.WHITE, "W3": chess.WHITE, "W4": chess.WHITE,
}

TRACKED_PIECE_TYPES = {chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN}

SLOT_RADIUS_PX = 40


class Graveyard:
    def __init__(self, calibration=None):
        self.slots = {slot: None for slot in SLOT_ORDER}
        self._centers = {}
        if calibration and "graveyard_slots" in calibration:
            for slot, center in zip(SLOT_ORDER, calibration["graveyard_slots"]):
                self._centers[slot] = center

    @property
    def has_cv_positions(self):
        return len(self._centers) == len(SLOT_ORDER)

    # ------------------------------------------------------------------
    # Slot management
    # ------------------------------------------------------------------

    def get_slot_for(self, color, piece_type):
        """Return the next empty slot for a captured piece, or None.

        Returns None for pawns/kings (not tracked) and when all 4 color slots are full.
        """
        if piece_type not in TRACKED_PIECE_TYPES:
            return None
        for slot in SLOT_ORDER:
            if SLOT_COLOR[slot] == color and self.slots[slot] is None:
                return slot
        return None

    def mark_occupied(self, slot, label):
        self.slots[slot] = label

    def mark_empty(self, slot):
        self.slots[slot] = None

    def get_center(self, slot):
        """Raw camera pixel [cx, cy] for this slot, or None if not calibrated."""
        return self._centers.get(slot)

    def slot_label(self, slot):
        color_str = "Black" if SLOT_COLOR[slot] == chess.BLACK else "White"
        num = slot[1]
        return f"{color_str} slot {num} ({slot})"

    def slot_position_hint(self, slot):
        idx = SLOT_ORDER.index(slot)
        section = "top (Black)" if idx < 4 else "bottom (White)"
        pos = (idx % 4) + 1
        return f"{section} section of graveyard column, position {pos}"

    # ------------------------------------------------------------------
    # Overflow handling
    # ------------------------------------------------------------------

    def find_overflow_square(self, board, capture_sq_name):
        """Find the nearest empty board square to temporarily park an overflow piece."""
        capture_sq = chess.parse_square(capture_sq_name)
        cf = chess.square_file(capture_sq)
        cr = chess.square_rank(capture_sq)

        for dist in range(1, 8):
            for df in range(-dist, dist + 1):
                for dr in range(-dist, dist + 1):
                    if max(abs(df), abs(dr)) != dist:
                        continue
                    f, r = cf + df, cr + dr
                    if 0 <= f <= 7 and 0 <= r <= 7:
                        sq = chess.square(f, r)
                        if board.piece_at(sq) is None:
                            return chess.square_name(sq)
        return None

    # ------------------------------------------------------------------
    # CV verification
    # ------------------------------------------------------------------

    def scan_with_cv(self, frame, piece_detector):
        """Cross-check graveyard state against what the camera sees.

        Runs YOLO on the raw (unwarped) camera frame and maps detections
        to graveyard slots by proximity to calibrated slot centers.
        No-op when graveyard was not calibrated or no detector is loaded.
        """
        if not self.has_cv_positions or piece_detector is None:
            return

        detections = piece_detector.detect_raw(frame)
        new_state = {slot: None for slot in SLOT_ORDER}
        best_conf = {slot: 0.0 for slot in SLOT_ORDER}

        for det in detections:
            cx, cy = det["cx"], det["cy"]
            for slot, (scx, scy) in self._centers.items():
                dist = ((cx - scx) ** 2 + (cy - scy) ** 2) ** 0.5
                if dist <= SLOT_RADIUS_PX and det["confidence"] > best_conf[slot]:
                    new_state[slot] = det["piece"]
                    best_conf[slot] = det["confidence"]

        for slot in SLOT_ORDER:
            self.slots[slot] = new_state[slot]

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def print_state(self):
        print("  Graveyard:")
        for slot in SLOT_ORDER:
            label = self.slots[slot] or "—"
            print(f"    {slot}: {label}")
