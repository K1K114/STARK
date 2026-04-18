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
        self._build_grid_map()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _build_grid_map(self):
        cell = self.board_size / 8
        files = "abcdefgh"
        ranks = "87654321"
        self.grid_map = {}
        for row, rank in enumerate(ranks):
            for col, file in enumerate(files):
                self.grid_map[(col, row)] = f"{file}{rank}"

    def _warp(self, frame):
        import numpy as np
        return cv2.warpPerspective(frame, self.M, (self.board_size, self.board_size))

    def _pixel_to_square(self, x, y):
        cell = self.board_size / 8
        col = max(0, min(7, int(x // cell)))
        row = max(0, min(7, int(y // cell)))
        return self.grid_map.get((col, row))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, frame):
        """Run YOLOv8 inference on a single frame.

        Returns:
            List of dicts: [{"square": "e4", "piece": "white_pawn", "confidence": 0.92}, ...]
        """
        warped = self._warp(frame)
        results = self.model(warped, verbose=False)

        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                square = self._pixel_to_square(cx, cy)
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

    def annotate(self, frame):
        """Return a copy of the warped frame with bounding boxes drawn.
        Useful for debugging model performance.
        """
        warped = self._warp(frame)
        results = self.model(warped, verbose=False)
        return results[0].plot()


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run piece detection on an image or webcam")
    parser.add_argument("--image", help="Path to a test image")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index")
    parser.add_argument("--model", default="model/best.pt")
    parser.add_argument("--calibration", default="calibration/calibration.json")
    args = parser.parse_args()

    detector = PieceDetector(model_path=args.model, calibration_path=args.calibration)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Error: could not read {args.image}")
            sys.exit(1)
    else:
        cap = cv2.VideoCapture(args.camera)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print("Error: could not capture from webcam")
            sys.exit(1)

    detections = detector.detect(frame)
    board = detector.get_board_state(frame)

    print(f"\nDetected {len(detections)} pieces:")
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

    annotated = detector.annotate(frame)
    cv2.imshow("Detection result — press any key", annotated)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
