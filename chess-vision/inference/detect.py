"""
YOLOv8 piece detector.

Loads a trained best.pt model and maps each detected piece to a chess square
using the perspective transform from calibration.json.

Typical usage from the main game loop:

    detector = PieceDetector("model/best.pt", "calibration/calibration.json")

    # After board_state.py signals a move:
    board_dict = detector.get_board_state(frame)
    # {"e1": "white_king", "e4": "white_pawn", ...}

Standalone test:
    python inference/detect.py --image path/to/image.jpg
"""

import sys
import os
import cv2
import numpy as np
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from calibration.calibrate import load_calibration

try:
    from ultralytics import YOLO
except ImportError:
    raise ImportError("ultralytics not installed. Run: pip install ultralytics")


class PieceDetector:
    def __init__(
        self,
        model_path="model/best.pt",
        calibration_path="calibration/calibration.json",
        rotate=0,
    ):
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Model not found: {model_path}\n"
                "Train a model first with: python training/train.py\n"
                "Or download best.pt from the shared Google Drive link in README."
            )
        self.model = YOLO(model_path)

        cal = load_calibration(calibration_path)
        self.M = cal["transform_matrix"]
        self.board_size = cal["board_size"]
        self._build_grid_map(rotate=rotate)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _build_grid_map(self, rotate=0):
        """Build (col, row) → square name mapping.

        rotate: degrees CW the board appears rotated in the warped image.
        Use 90/180/270 if calibration corners were clicked in a non-standard order.
        Standard order: click a8 (top-left) → h8 → h1 → a1 (bottom-left).
        """
        files = "abcdefgh"
        ranks = "87654321"
        self.grid_map = {}
        for row in range(8):
            for col in range(8):
                if rotate == 90:
                    sq = files[row] + ranks[7 - col]
                elif rotate == 180:
                    sq = files[7 - col] + ranks[7 - row]
                elif rotate == 270:
                    sq = files[7 - row] + ranks[col]
                else:
                    sq = files[col] + ranks[row]
                self.grid_map[(col, row)] = sq

    def _warp(self, frame):
        return cv2.warpPerspective(frame, self.M, (self.board_size, self.board_size))

    def _raw_center_to_square(self, cx, cy):
        """Map a raw-frame pixel center through the perspective transform to a square name."""
        pt = np.array([[[cx, cy]]], dtype=np.float32)
        warped_pt = cv2.perspectiveTransform(pt, self.M)
        wx, wy = warped_pt[0][0]
        return self._pixel_to_square(wx, wy)

    def _pixel_to_square(self, x, y):
        cell = self.board_size / 8
        col = max(0, min(7, int(x // cell)))
        row = max(0, min(7, int(y // cell)))
        return self.grid_map.get((col, row))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, frame):
        """Run YOLOv8 inference on the raw camera frame, mapping detections to squares.

        Runs YOLO on the undistorted raw frame so pieces aren't warped/cut off,
        then maps each detected center through the perspective transform to assign
        a board square.

        Returns:
            List of dicts: [{"square": "e4", "piece": "white_pawn", "confidence": 0.92}, ...]
        """
        results = self.model(frame, verbose=False)

        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                square = self._raw_center_to_square(cx, cy)
                piece = self.model.names[int(box.cls[0])]
                conf = round(float(box.conf[0]), 3)
                if square:
                    detections.append(
                        {"square": square, "piece": piece, "confidence": conf}
                    )
        return detections

    def get_board_state(self, frame):
        """Return a full board snapshot as a dict.

        Returns:
            {"e1": "white_king", "e8": "black_king", ...}
            Only occupied squares are included. If two detections map to the
            same square, the higher-confidence one wins.
        """
        detections = sorted(self.detect(frame), key=lambda d: d["confidence"])
        board = {}
        for d in detections:
            board[d["square"]] = d["piece"]  # higher confidence overwrites lower
        return board

    def detect_raw(self, frame):
        """Run YOLOv8 on the raw (unwarped) camera frame.

        Unlike detect(), this does NOT apply the perspective transform, so
        detections cover the full camera view including the graveyard area.
        Returns pixel-space centers rather than board square names.

        Returns:
            List of dicts: [{"cx": 412, "cy": 87, "piece": "black_queen", "confidence": 0.91}, ...]
        """
        results = self.model(frame, verbose=False)
        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append({
                    "cx": (x1 + x2) / 2,
                    "cy": (y1 + y2) / 2,
                    "piece": self.model.names[int(box.cls[0])],
                    "confidence": round(float(box.conf[0]), 3),
                })
        return detections

    def annotate(self, frame):
        """Return a copy of the raw frame with bounding boxes drawn.
        Useful for debugging model performance.
        """
        results = self.model(frame, verbose=False)
        return results[0].plot()

    def debug_board_view(self, frame, detections=None):
        """Return a warped bird's-eye view with grid lines and square labels.

        Draws the 8x8 grid, file labels (a-h) along the top, rank labels (1-8)
        along the left, and any detected piece names inside their assigned squares.
        Use this to visually verify the perspective transform is accurate.

        Args:
            frame: Raw BGR camera frame.
            detections: Output of detect(frame). If None, runs detect() internally.

        Returns:
            BGR image of the warped board with overlay.
        """
        if detections is None:
            detections = self.detect(frame)

        warped = self._warp(frame)
        out = warped.copy()
        cell = self.board_size / 8
        files = "abcdefgh"
        ranks = "87654321"

        # Draw grid lines
        for i in range(9):
            pos = int(i * cell)
            cv2.line(out, (pos, 0), (pos, self.board_size), (0, 255, 0), 1)
            cv2.line(out, (0, pos), (self.board_size, pos), (0, 255, 0), 1)

        # File labels along top (a-h)
        for col, f in enumerate(files):
            x = int(col * cell + cell / 2)
            cv2.putText(out, f, (x - 5, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)

        # Rank labels along left (8 at top → 1 at bottom)
        for row, r in enumerate(ranks):
            y = int(row * cell + cell / 2)
            cv2.putText(out, r, (3, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)

        # Piece labels inside their squares
        for d in detections:
            sq = d["square"]
            col = files.index(sq[0])
            row = ranks.index(sq[1])
            cx = int(col * cell + cell / 2)
            cy = int(row * cell + cell / 2)
            label = d["piece"].replace("_", " ")
            conf = d["confidence"]
            cv2.putText(out, label, (cx - int(cell * 0.45), cy - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 0), 1, cv2.LINE_AA)
            cv2.putText(out, f"{conf:.2f}", (cx - int(cell * 0.45), cy + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.25, (200, 200, 0), 1, cv2.LINE_AA)

        return out


# ------------------------------------------------------------------
# Roboflow hosted detector (drop-in replacement for PieceDetector)
# ------------------------------------------------------------------

class RoboflowDetector:
    """Same interface as PieceDetector, but runs inference via Roboflow's hosted API.

    Uses model stark-47vov/3 (STARK 3 — YOLO, trained on orange + white pieces).
    "orange_*" classes are normalized to "black_*" for the chess engine.

    Usage:
        detector = RoboflowDetector(api_key="...", calibration_path="calibration/calibration.json")
        board = detector.get_board_state(frame)  # {"e1": "white_king", ...}
    """

    MODEL_ID = "stark-47vov/3"

    def __init__(self, api_key: str, calibration_path="calibration/calibration.json"):
        try:
            from inference_sdk import InferenceHTTPClient
        except ImportError:
            raise ImportError("inference-sdk not installed. Run: pip install inference-sdk")

        self._client = InferenceHTTPClient(
            api_url="https://detect.roboflow.com",
            api_key=api_key,
        )

        cal = load_calibration(calibration_path)
        self.M = np.array(cal["transform_matrix"], dtype=np.float32)
        self.board_size = cal["board_size"]
        self._build_grid_map()

    def _build_grid_map(self):
        files = "abcdefgh"
        ranks = "87654321"
        self.grid_map = {}
        for row, rank in enumerate(ranks):
            for col, file in enumerate(files):
                self.grid_map[(col, row)] = f"{file}{rank}"

    def _pixel_to_square(self, x, y):
        cell = self.board_size / 8
        col = max(0, min(7, int(x // cell)))
        row = max(0, min(7, int(y // cell)))
        return self.grid_map.get((col, row))

    def _raw_center_to_square(self, cx, cy):
        pt = np.array([[[cx, cy]]], dtype=np.float32)
        warped = cv2.perspectiveTransform(pt, self.M)
        wx, wy = warped[0][0]
        return self._pixel_to_square(wx, wy)

    @staticmethod
    def _normalize_class(label: str) -> str:
        """Map orange_* → black_* so the chess engine sees standard color names."""
        return label.replace("orange_", "black_")

    def detect(self, frame: np.ndarray) -> list:
        """Run Roboflow inference, return list of {square, piece, confidence} dicts."""
        result = self._client.infer(frame, model_id=self.MODEL_ID)
        raw_preds = result.get("predictions", [])
        detections = []
        for p in raw_preds:
            cx = p.get("x", 0)
            cy = p.get("y", 0)
            label = self._normalize_class(p.get("class", ""))
            conf = round(float(p.get("confidence", 0.0)), 3)
            if not label:
                continue
            sq = self._raw_center_to_square(cx, cy)
            if sq:
                detections.append({"square": sq, "piece": label, "confidence": conf})
        return detections

    def get_board_state(self, frame: np.ndarray) -> dict:
        """Return {square: piece_name} dict. Higher-confidence detection wins per square."""
        detections = sorted(self.detect(frame), key=lambda d: d["confidence"])
        board = {}
        for d in detections:
            board[d["square"]] = d["piece"]
        return board

    def detect_raw(self, frame: np.ndarray) -> list:
        """Return raw pixel-space detections (for graveyard scanning)."""
        result = self._client.infer(frame, model_id=self.MODEL_ID)
        return [
            {
                "cx": p.get("x", 0),
                "cy": p.get("y", 0),
                "piece": self._normalize_class(p.get("class", "")),
                "confidence": round(float(p.get("confidence", 0.0)), 3),
            }
            for p in result.get("predictions", [])
            if p.get("class")
        ]

    def debug_board_view(self, frame: np.ndarray, detections: list = None) -> np.ndarray:
        """Warped bird's-eye board view with grid and piece labels.
        Pass detections from a previous detect() call to avoid a second API hit.
        """
        warped = cv2.warpPerspective(frame, self.M, (self.board_size, self.board_size))
        out = warped.copy()
        cell = self.board_size / 8
        files = "abcdefgh"
        ranks = "87654321"

        for i in range(9):
            pos = int(i * cell)
            cv2.line(out, (pos, 0), (pos, self.board_size), (0, 255, 0), 1)
            cv2.line(out, (0, pos), (self.board_size, pos), (0, 255, 0), 1)
        for col, f in enumerate(files):
            cv2.putText(out, f, (int(col * cell + cell / 2) - 5, 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)
        for row, r in enumerate(ranks):
            cv2.putText(out, r, (3, int(row * cell + cell / 2) + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)

        for d in (detections or []):
            sq = d["square"]
            col, row = files.index(sq[0]), ranks.index(sq[1])
            cx, cy = int(col * cell + cell / 2), int(row * cell + cell / 2)
            cv2.putText(out, d["piece"].replace("_", " "),
                        (cx - int(cell * 0.45), cy - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 0), 1, cv2.LINE_AA)
            cv2.putText(out, f"{d['confidence']:.2f}",
                        (cx - int(cell * 0.45), cy + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.25, (200, 200, 0), 1, cv2.LINE_AA)
        return out


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run piece detection on an image or webcam")
    parser.add_argument("--image", help="Path to a test image")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index")
    parser.add_argument("--model", default="model/best.pt")
    parser.add_argument("--calibration", default="calibration/calibration.json")
    parser.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                        help="Rotate grid CW by this many degrees to match your calibration orientation")
    args = parser.parse_args()

    detector = PieceDetector(model_path=args.model, calibration_path=args.calibration, rotate=args.rotate)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Error: could not read {args.image}")
            sys.exit(1)
    else:
        cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            print("Error: could not open webcam")
            sys.exit(1)

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: could not capture from webcam")
                break

            detections = detector.detect(frame)
            board = detector.get_board_state(frame)
            annotated = detector.annotate(frame)
            grid_view = detector.debug_board_view(frame, detections)

            print("\033[2J\033[H", end="")  # clear terminal
            print(f"Detected {len(detections)} pieces:")
            for d in sorted(detections, key=lambda x: x["square"]):
                print(f"  {d['square']:>3}  {d['piece']:<20}  conf={d['confidence']}")

            print(f"\nBoard state ({len(board)} pieces):")
            for rank in "87654321":
                row = "  "
                for file in "abcdefgh":
                    sq = f"{file}{rank}"
                    piece = board.get(sq, ".")
                    row += f"{piece[:2] if piece != '.' else '..'} "
                print(f"  {rank} {row}")

            cv2.imshow("Raw Detection (YOLO boxes) — press q to quit", annotated)
            cv2.imshow("Board Grid View (verify square mapping)", grid_view)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()
        sys.exit(0)
