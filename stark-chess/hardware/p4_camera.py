"""
ESP32-P4 camera interface over USB serial.

The P4 holds the camera and handles ALL vision processing (pixel diff + YOLO).
The laptop only does game logic. Four commands:

    Laptop → P4:  b"SET_REFERENCE\\n"
    P4 → Laptop:  "OK\\n"
    (P4 captures current frame as move-detection baseline)

    Laptop → P4:  b"POLL_MOVE\\n"
    P4 → Laptop:  "NONE\\n"  or  "MOVE:e2e4\\n"
    (non-blocking; P4 runs pixel diff + YOLO internally)

    Laptop → P4:  b"INFER\\n"
    P4 → Laptop:  "e1:white_king,e4:white_pawn,d8:black_queen\\n"
    (full board YOLO snapshot)

    Laptop → P4:  b"FRAME_REQUEST\\n"
    P4 → Laptop:  [4-byte big-endian size] + [JPEG bytes]
    (debug only — grab a raw frame for inspection)

Usage:
    p4 = P4Camera("/dev/tty.usbmodem1234")
    p4.set_reference()              # call once at game start and after each engine move
    move = p4.poll_move()           # returns "e2e4" or None
    p4.close()
"""

import struct
import cv2
import numpy as np


class P4Camera:
    def __init__(self, port: str, baud: int = 921600, timeout: float = 3.0):
        try:
            import serial
        except ImportError:
            raise ImportError("pyserial not installed. Run: pip install pyserial")
        import serial as _serial
        self._ser = _serial.Serial(port, baud, timeout=timeout)

    def get_frame(self) -> np.ndarray:
        """Ask P4 for the latest camera frame. Returns a BGR numpy array."""
        self._ser.reset_input_buffer()
        self._ser.write(b"FRAME_REQUEST\n")

        size_bytes = self._ser.read(4)
        if len(size_bytes) < 4:
            raise RuntimeError("P4: timeout waiting for frame size header")

        size = struct.unpack(">I", size_bytes)[0]
        jpeg_data = self._ser.read(size)
        if len(jpeg_data) < size:
            raise RuntimeError(f"P4: expected {size} bytes, got {len(jpeg_data)}")

        arr = np.frombuffer(jpeg_data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("P4: failed to decode JPEG frame")
        return frame

    def set_reference(self) -> None:
        """Tell P4 to capture the current frame as the move-detection baseline.
        Call this after every engine move (once gantry finishes).
        """
        self._ser.reset_input_buffer()
        self._ser.write(b"SET_REFERENCE\n")
        resp = self._ser.readline().decode("ascii", errors="replace").strip()
        if resp != "OK":
            raise RuntimeError(f"P4: SET_REFERENCE unexpected response: {resp!r}")

    def poll_move(self) -> str | None:
        """Ask P4 if a human move has been detected since the last SET_REFERENCE.

        Returns a UCI string like 'e2e4' if a move was confirmed, or None if
        the board is still being watched. The P4 handles pixel diff, stability
        check, and YOLO disambiguation internally.
        """
        self._ser.reset_input_buffer()
        self._ser.write(b"POLL_MOVE\n")
        line = self._ser.readline().decode("ascii", errors="replace").strip()
        if not line or line == "NONE":
            return None
        if line.startswith("MOVE:"):
            return line[5:].strip()
        return None

    def infer(self) -> dict:
        """Tell P4 to run inference. Returns {square: piece_name} dict."""
        self._ser.reset_input_buffer()
        self._ser.write(b"INFER\n")

        line = self._ser.readline().decode("ascii", errors="replace").strip()
        if not line:
            return {}

        board = {}
        for item in line.split(","):
            item = item.strip()
            if ":" not in item:
                continue
            sq, piece = item.split(":", 1)
            board[sq.strip()] = piece.strip()
        return board

    def close(self):
        if self._ser.is_open:
            self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class P4CameraStub:
    """Drop-in stub for development without the P4 connected."""

    def get_frame(self) -> np.ndarray:
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def set_reference(self) -> None:
        pass

    def poll_move(self) -> str | None:
        return None

    def infer(self) -> dict:
        return {}

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
