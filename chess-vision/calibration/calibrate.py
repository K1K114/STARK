"""
Board calibration: click 4 corners of the chess board to compute the perspective
transform. Saves corner coordinates and a per-square pixel map to calibration.json.

Usage:
    python calibration/calibrate.py                   # use webcam
    python calibration/calibrate.py --image path.jpg  # use a still image
"""

import cv2
import numpy as np
import json
import os
import argparse

BOARD_SIZE = 480  # pixels in the output bird's-eye-view square
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "calibration.json")

# Board orientation: a-file on the left, rank 8 at the top of the warped image.
# Adjust FILES / RANKS if your camera is mounted differently.
FILES = "abcdefgh"
RANKS = "87654321"  # row 0 = rank 8, row 7 = rank 1

_corners = []  # module-level list written by the mouse callback


def _mouse_callback(event, x, y, flags, display_img):
    """Record up to 4 corner clicks and draw a marker on each."""
    if event == cv2.EVENT_LBUTTONDOWN and len(_corners) < 4:
        _corners.append([x, y])
        print(f"  Corner {len(_corners)}: ({x}, {y})")
        cv2.circle(display_img, (x, y), 8, (0, 255, 0), -1)
        if len(_corners) > 1:
            cv2.line(
                display_img,
                tuple(_corners[-2]),
                tuple(_corners[-1]),
                (0, 255, 0),
                2,
            )
        cv2.imshow("Calibrate — click 4 corners", display_img)


def _compute_square_centers():
    """Return {square_name: [cx, cy]} in warped-image coordinates.

    The perspective transform maps the real board to a BOARD_SIZE x BOARD_SIZE
    image, so each of the 64 squares is exactly (BOARD_SIZE/8) pixels wide.
    """
    cell = BOARD_SIZE / 8
    squares = {}
    for row, rank in enumerate(RANKS):
        for col, file in enumerate(FILES):
            cx = int(col * cell + cell / 2)
            cy = int(row * cell + cell / 2)
            squares[f"{file}{rank}"] = [cx, cy]
    return squares


def calibrate_from_image(image_path=None, camera_index=0):
    """Interactive calibration. Click the 4 board corners in order:
    top-left → top-right → bottom-right → bottom-left.

    Saves calibration.json and returns the calibration dict.
    """
    global _corners
    _corners = []

    if image_path:
        frame = cv2.imread(image_path)
        if frame is None:
            raise FileNotFoundError(f"Could not read image: {image_path}")
    else:
        cap = cv2.VideoCapture(camera_index)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError("Failed to capture frame from webcam")

    display = frame.copy()
    cv2.namedWindow("Calibrate — click 4 corners")
    cv2.setMouseCallback("Calibrate — click 4 corners", _mouse_callback, display)

    print("\nCalibration — click the 4 board corners in this order:")
    print("  1) a8  (top-left,    far-left  — Black's queen-rook corner)")
    print("  2) h8  (top-right,   far-right — Black's king-rook corner)")
    print("  3) h1  (bottom-right, near-right — White's king-rook corner)")
    print("  4) a1  (bottom-left,  near-left  — White's queen-rook corner)")
    print("White must be at the BOTTOM of your camera view for this to work.")
    print("Press Q to quit without saving.\n")

    while True:
        cv2.imshow("Calibrate — click 4 corners", display)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("q"):
            cv2.destroyAllWindows()
            raise RuntimeError("Calibration cancelled by user")
        if len(_corners) == 4:
            print("All 4 corners recorded. Press any key to save…")
            cv2.waitKey(0)
            break

    cv2.destroyAllWindows()

    src = np.float32(_corners)
    dst = np.float32(
        [[0, 0], [BOARD_SIZE, 0], [BOARD_SIZE, BOARD_SIZE], [0, BOARD_SIZE]]
    )
    M = cv2.getPerspectiveTransform(src, dst)

    calibration = {
        "corners": _corners,
        "transform_matrix": M.tolist(),
        "board_size": BOARD_SIZE,
        "squares": _compute_square_centers(),
    }

    # ------------------------------------------------------------------
    # Optional: calibrate graveyard column
    # ------------------------------------------------------------------
    graveyard_slots = _calibrate_graveyard(frame)
    if graveyard_slots:
        calibration["graveyard_slots"] = graveyard_slots
        print("Graveyard calibration saved.")
    else:
        print("Graveyard calibration skipped — graveyard CV will be disabled.")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(calibration, f, indent=2)

    print(f"Calibration saved → {OUTPUT_PATH}")

    # Show the warped result so the user can sanity-check alignment
    warped = cv2.warpPerspective(frame, M, (BOARD_SIZE, BOARD_SIZE))
    cell = BOARD_SIZE // 8
    for i in range(1, 8):
        cv2.line(warped, (i * cell, 0), (i * cell, BOARD_SIZE), (0, 200, 0), 1)
        cv2.line(warped, (0, i * cell), (BOARD_SIZE, i * cell), (0, 200, 0), 1)
    cv2.imshow("Warped result — press any key to close", warped)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return calibration


def _calibrate_graveyard(frame):
    """Ask the user to click the top and bottom of the graveyard column.

    Computes 8 equally-spaced slot centers between those two points in raw
    camera pixel space (no perspective warp — the graveyard is outside the
    board area). Returns a list of 8 [cx, cy] pairs ordered top→bottom:
        [BQ, BR, BB, BN, WN, WB, WR, WQ]
    Returns None if the user skips (presses Q).
    """
    SLOT_NAMES = ["BQ (Black Queen)", "BR (Black Rook)", "BB (Black Bishop)",
                  "BN (Black Knight)", "WN (White Knight)", "WB (White Bishop)",
                  "WR (White Rook)", "WQ (White Queen)"]

    clicks = []
    display = frame.copy()

    def _gy_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 2:
            clicks.append([x, y])
            label = "TOP slot center (Black Queen)" if len(clicks) == 1 else "BOTTOM slot center (White Queen)"
            print(f"  Graveyard {label}: ({x}, {y})")
            cv2.circle(display, (x, y), 6, (0, 165, 255), -1)
            cv2.putText(display, f"GY {len(clicks)}", (x + 8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            cv2.imshow("Graveyard calibration", display)

    cv2.namedWindow("Graveyard calibration")
    cv2.setMouseCallback("Graveyard calibration", _gy_mouse)

    print("\nGraveyard calibration (optional)")
    print("  Click the CENTER of the TOP graveyard slot    (Black Queen position, aligned with rank 8)")
    print("  Click the CENTER of the BOTTOM graveyard slot (White Queen position, aligned with rank 1)")
    print("  Press Q to skip graveyard calibration.\n")

    while True:
        cv2.imshow("Graveyard calibration", display)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("q"):
            cv2.destroyAllWindows()
            return None
        if len(clicks) == 2:
            print("Both graveyard points recorded. Press any key to save…")
            cv2.waitKey(0)
            break

    cv2.destroyAllWindows()

    # Interpolate 8 equally-spaced centers between top and bottom clicks
    x0, y0 = clicks[0]
    x1, y1 = clicks[1]
    centers = []
    for i in range(8):
        t = i / 7  # 0.0 → 1.0
        cx = int(x0 + t * (x1 - x0))
        cy = int(y0 + t * (y1 - y0))
        centers.append([cx, cy])
        print(f"  Slot {SLOT_NAMES[i]:30s} → pixel ({cx}, {cy})")

    return centers


def load_calibration(calibration_path=None):
    """Load calibration.json. Returns dict with transform_matrix as np.float32."""
    if calibration_path is None:
        calibration_path = OUTPUT_PATH
    with open(calibration_path) as f:
        data = json.load(f)
    data["transform_matrix"] = np.float32(data["transform_matrix"])
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate chess board camera")
    parser.add_argument("--image", help="Path to a still image instead of webcam")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index (default 0)")
    args = parser.parse_args()
    calibrate_from_image(image_path=args.image, camera_index=args.camera)
