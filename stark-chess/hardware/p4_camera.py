"""
ESP32-P4 camera interface over WiFi HTTP.

The P4 holds the camera and handles ALL vision processing (pixel diff + YOLO).
The laptop only does game logic. Four HTTP endpoints:

    POST /set_reference  →  "OK"
    GET  /poll_move      →  "NONE" or "MOVE:e2e4"
    GET  /infer          →  "e1:white_king,e4:white_pawn,..."
    GET  /frame          →  raw JPEG bytes

Usage:
    p4 = P4Camera("192.168.1.42")    # IP printed on P4 serial after boot
    p4.set_reference()               # call once at game start and after each engine move
    move = p4.poll_move()            # returns "e2e4" or None
    p4.close()
"""

import cv2
import numpy as np
import requests


class P4Camera:
    def __init__(self, host: str, timeout: float = 5.0):
        self._base = f"http://{host}"
        self._timeout = timeout

    def get_frame(self) -> np.ndarray:
        """Fetch the latest camera frame from P4. Returns a BGR numpy array."""
        r = requests.get(f"{self._base}/frame", timeout=self._timeout)
        r.raise_for_status()
        arr = np.frombuffer(r.content, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("P4: failed to decode JPEG frame")
        return frame

    def set_reference(self) -> None:
        """Tell P4 to capture the current frame as the move-detection baseline.
        Call this after every engine move (once gantry finishes).
        """
        r = requests.post(f"{self._base}/set_reference", timeout=self._timeout)
        r.raise_for_status()
        if r.text.strip() != "OK":
            raise RuntimeError(f"P4: set_reference unexpected response: {r.text!r}")

    def poll_move(self) -> str | None:
        """Ask P4 if a human move has been detected since the last set_reference.

        Returns a UCI string like 'e2e4' if a move was confirmed, or None if
        the board is still being watched. The P4 handles pixel diff, stability
        check, and YOLO disambiguation internally.
        """
        r = requests.get(f"{self._base}/poll_move", timeout=self._timeout)
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("MOVE:"):
            return text[5:]
        return None

    def infer(self) -> dict:
        """Tell P4 to run a full-board YOLO snapshot.
        Returns {square: piece_name} dict, e.g. {"e1": "white_king"}.
        """
        r = requests.get(f"{self._base}/infer", timeout=self._timeout)
        r.raise_for_status()
        board = {}
        for item in r.text.strip().split(","):
            item = item.strip()
            if ":" not in item:
                continue
            sq, piece = item.split(":", 1)
            board[sq.strip()] = piece.strip()
        return board

    def close(self):
        pass

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
