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
    print("  1) Top-left   2) Top-right   3) Bottom-right   4) Bottom-left")
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
