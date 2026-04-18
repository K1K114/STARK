"""
Sanity checks for the chess vision pipeline.

Run from the repo root:
    python tests/test_detection.py

Tests that require calibration.json will skip if the file doesn't exist yet.
Tests that require best.pt will skip if the model hasn't been trained.
"""

import sys
import os
import json
import numpy as np

# Allow imports from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

CALIBRATION_PATH = "calibration/calibration.json"
MODEL_PATH = "model/best.pt"

_passed = 0
_failed = 0
_skipped = 0


def _result(name, passed, msg=""):
    global _passed, _failed
    if passed:
        print(f"  PASS  {name}")
        _passed += 1
    else:
        print(f"  FAIL  {name}" + (f": {msg}" if msg else ""))
        _failed += 1


def _skip(name, reason):
    global _skipped
    print(f"  SKIP  {name} ({reason})")
    _skipped += 1


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_module_imports():
    print("\n[Imports]")
    for module, symbol in [
        ("calibration.calibrate", "load_calibration"),
        ("inference.board_state", "BoardStateDetector"),
        ("inference.detect", "PieceDetector"),
    ]:
        try:
            mod = __import__(module, fromlist=[symbol])
            getattr(mod, symbol)
            _result(f"import {module}.{symbol}", True)
        except Exception as e:
            _result(f"import {module}.{symbol}", False, str(e))


# ------------------------------------------------------------------
# Calibration tests
# ------------------------------------------------------------------

def test_calibration_file_structure():
    print("\n[Calibration]")
    if not os.path.exists(CALIBRATION_PATH):
        _skip("calibration file structure", f"{CALIBRATION_PATH} not found — run calibrate.py first")
        return

    with open(CALIBRATION_PATH) as f:
        cal = json.load(f)

    _result("has 'corners' key", "corners" in cal)
    _result("has 'transform_matrix' key", "transform_matrix" in cal)
    _result("has 'squares' key", "squares" in cal)
    _result("exactly 4 corners", len(cal.get("corners", [])) == 4)
    _result("exactly 64 squares", len(cal.get("squares", {})) == 64)

    # Every square a1–h8 must be present
    expected = {f"{f}{r}" for f in "abcdefgh" for r in "12345678"}
    missing = expected - set(cal.get("squares", {}).keys())
    _result("all 64 square names present", len(missing) == 0, f"missing: {missing}")

    # transform_matrix must be 3×3
    M = cal.get("transform_matrix", [])
    _result("3×3 transform matrix", len(M) == 3 and all(len(row) == 3 for row in M))


def test_board_state_detector():
    print("\n[BoardStateDetector]")
    if not os.path.exists(CALIBRATION_PATH):
        _skip("BoardStateDetector init", f"{CALIBRATION_PATH} not found")
        return

    from inference.board_state import BoardStateDetector
    det = BoardStateDetector(CALIBRATION_PATH)

    _result("reference_frame starts as None", det.reference_frame is None)
    _result("stability_count starts at 0", det.stability_count == 0)

    # Pixel-to-square mapping (uses fixed cell geometry, no real image needed)
    board_size = det.board_size
    cell = board_size / 8

    a1 = det._pixel_to_square(cell * 0.5, cell * 7.5)  # col=0, row=7
    _result("bottom-left cell = a1", a1 == "a1", f"got {a1}")

    h8 = det._pixel_to_square(cell * 7.5, cell * 0.5)  # col=7, row=0
    _result("top-right cell = h8", h8 == "h8", f"got {h8}")

    e4 = det._pixel_to_square(cell * 4.5, cell * 4.5)  # col=4, row=4
    _result("center-ish cell = e4", e4 == "e4", f"got {e4}")

    # update() without a reference should set it and return None
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = det.update(fake_frame)
    _result("first update sets reference, returns None", result is None)
    _result("reference_frame set after first update", det.reference_frame is not None)

    # gantry_moving=True should reset stability counter
    det.stability_count = 5
    det.update(fake_frame, gantry_moving=True)
    _result("gantry_moving resets stability_count", det.stability_count == 0)


# ------------------------------------------------------------------
# PieceDetector tests (model-optional)
# ------------------------------------------------------------------

def test_piece_detector():
    print("\n[PieceDetector]")
    if not os.path.exists(CALIBRATION_PATH):
        _skip("PieceDetector", f"{CALIBRATION_PATH} not found")
        return
    if not os.path.exists(MODEL_PATH):
        _skip("PieceDetector model load", f"{MODEL_PATH} not found — train first")
        return

    from inference.detect import PieceDetector
    try:
        det = PieceDetector(MODEL_PATH, CALIBRATION_PATH)
        _result("PieceDetector loads model", True)

        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        board = det.get_board_state(fake_frame)
        _result("get_board_state returns dict", isinstance(board, dict))
        _result("no detections on blank frame (expected)", len(board) == 0)
    except Exception as e:
        _result("PieceDetector init", False, str(e))


# ------------------------------------------------------------------
# Run all
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("Chess Vision — Test Suite")
    print("=" * 50)

    test_module_imports()
    test_calibration_file_structure()
    test_board_state_detector()
    test_piece_detector()

    print(f"\n{'=' * 50}")
    print(f"Results: {_passed} passed, {_failed} failed, {_skipped} skipped")
    if _failed > 0:
        sys.exit(1)
