"""
Serial interface to the ESP32 gantry controller.

The ESP32 firmware expects newline-terminated commands:
    MOVE <from> <to>\n      — slide electromagnet from square to square
    CAPTURE <square>\n      — remove a captured piece to the side pocket
    HOME\n                  — return gantry to home position

The ESP32 replies:
    MOVING\n                — acknowledged, gantry started
    DONE\n                  — move complete, electromagnet released

Usage:
    gantry = Gantry(port="/dev/cu.usbserial-0001")
    gantry.connect()
    gantry.execute(chess.Move.from_uci("e2e4"))
    gantry.close()

Or as a context manager:
    with Gantry(port="COM3") as gantry:
        gantry.execute(move)
"""

import serial
import time
import threading
import os
import chess


DEFAULT_PORT = os.getenv("GANTRY_PORT", "/dev/cu.usbserial-0001")
DEFAULT_BAUD = int(os.getenv("GANTRY_BAUD", "115200"))
MOVE_TIMEOUT = 30  # seconds — max time to wait for DONE before giving up


class GantryError(Exception):
    pass


class Gantry:
    def __init__(self, port=DEFAULT_PORT, baud=DEFAULT_BAUD):
        self.port = port
        self.baud = baud
        self._serial: serial.Serial | None = None
        self._moving = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        """Open the serial connection to the ESP32."""
        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=1)
            time.sleep(2)  # wait for ESP32 to boot after serial open
            print(f"Gantry connected on {self.port} @ {self.baud} baud")
        except serial.SerialException as e:
            raise GantryError(
                f"Could not open serial port {self.port}.\n"
                "Check: is the ESP32 plugged in? Correct port?\n"
                f"Detail: {e}"
            )

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.close()

    @property
    def is_moving(self):
        """True while the gantry is executing a move. Checked by board_state.py."""
        return self._moving

    # ------------------------------------------------------------------
    # Move execution
    # ------------------------------------------------------------------

    def execute(self, move: chess.Move, board: chess.Board | None = None):
        """Send a move to the gantry and block until it completes.

        Args:
            move: chess.Move to execute physically.
            board: Optional chess.Board — used to detect captures so the
                   captured piece can be removed before moving.

        Raises:
            GantryError on serial failure or timeout.
        """
        if self._serial is None or not self._serial.is_open:
            raise GantryError("Gantry not connected. Call connect() first.")

        with self._lock:
            self._moving = True
            try:
                # If it's a capture, clear the destination square first
                if board is not None and board.is_capture(move):
                    capture_sq = chess.square_name(move.to_square)
                    self._send_command(f"CAPTURE {capture_sq}")
                    self._wait_for_done()

                from_sq = chess.square_name(move.from_square)
                to_sq = chess.square_name(move.to_square)
                self._send_command(f"MOVE {from_sq} {to_sq}")
                self._wait_for_done()

                # Handle castling — move the rook too
                if board is not None and board.is_castling(move):
                    rook_from, rook_to = _castling_rook_squares(move)
                    self._send_command(f"MOVE {rook_from} {rook_to}")
                    self._wait_for_done()

            finally:
                self._moving = False

    def return_to_origin(self, square: str):
        """Send a piece back to its origin square (called on illegal move)."""
        with self._lock:
            self._moving = True
            try:
                self._send_command(f"RETURN {square}")
                self._wait_for_done()
            finally:
                self._moving = False

    def home(self):
        """Return the gantry to its home/rest position."""
        with self._lock:
            self._moving = True
            try:
                self._send_command("HOME")
                self._wait_for_done()
            finally:
                self._moving = False

    # ------------------------------------------------------------------
    # Low-level serial helpers
    # ------------------------------------------------------------------

    def _send_command(self, cmd: str):
        line = (cmd.strip() + "\n").encode()
        self._serial.write(line)
        self._serial.flush()

    def _wait_for_done(self, timeout=MOVE_TIMEOUT):
        """Block until the ESP32 sends DONE, or raise on timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._serial.readline()
            if not raw:
                continue
            response = raw.decode(errors="ignore").strip()
            if response == "DONE":
                return
            # MOVING is an acknowledgement — keep waiting
        raise GantryError(f"Gantry timed out after {timeout}s waiting for DONE")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


def _castling_rook_squares(move: chess.Move):
    """Return (rook_from, rook_to) square names for a castling move."""
    # King moves two squares — rook jumps to the other side
    if move.to_square == chess.G1:  # white kingside
        return "h1", "f1"
    if move.to_square == chess.C1:  # white queenside
        return "a1", "d1"
    if move.to_square == chess.G8:  # black kingside
        return "h8", "f8"
    if move.to_square == chess.C8:  # black queenside
        return "a8", "d8"
    return None, None


# ------------------------------------------------------------------
# Dry-run stub (used when no ESP32 is connected)
# ------------------------------------------------------------------

class GantryStub:
    """Drop-in replacement for Gantry that just prints commands.
    Useful for developing the game loop without hardware.
    """

    def __init__(self, *args, **kwargs):
        self._moving = False

    def connect(self):
        print("[GantryStub] Connected (no-op)")

    def close(self):
        pass

    @property
    def is_moving(self):
        return self._moving

    def execute(self, move: chess.Move, board=None):
        from_sq = chess.square_name(move.from_square)
        to_sq = chess.square_name(move.to_square)
        print(f"[GantryStub] MOVE {from_sq} → {to_sq}")
        self._moving = True
        time.sleep(0.5)  # simulate gantry travel time
        self._moving = False

    def return_to_origin(self, square):
        print(f"[GantryStub] RETURN {square}")

    def home(self):
        print("[GantryStub] HOME")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()
