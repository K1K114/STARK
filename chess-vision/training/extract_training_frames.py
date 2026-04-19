"""
Extract training images from a game video for YOLO piece detection.

Improvements over extract_calibration_frames.py:
- State machine: only saves after motion (piece placement) followed by extended
  stability, so the hand must be fully clear before a frame is saved.
- Perceptual hash deduplication: rejects board states too similar to already-saved
  ones, even if many frames apart.
- Optional live preview window showing current state and save count.

State machine:
    WAITING  → motion detected          → MOVING
    MOVING   → motion stops             → SETTLING
    SETTLING → stable for settle_frames → SAVE (if hash is unique) → WAITING
    SETTLING → motion resumes           → MOVING  (hand came back)

Usage:
    python training/extract_training_frames.py \\
        --video path/to/recording.mp4 \\
        --out-dir data/training_images \\
        --calibration calibration/calibration.json \\
        --max-saves 500 \\
        --preview
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from calibration.calibrate import load_calibration


# ---------------------------------------------------------------------------
# Perceptual hash helpers
# ---------------------------------------------------------------------------

def _ahash(gray: np.ndarray, size: int = 8) -> np.ndarray:
    """Average hash of a grayscale image — returns a flat bool array of size*size."""
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    return (small > small.mean()).flatten()


def _hamming(h1: np.ndarray, h2: np.ndarray) -> int:
    return int(np.count_nonzero(h1 != h2))


def _is_duplicate(new_hash: np.ndarray, saved_hashes: list, min_distance: int) -> bool:
    """Return True if new_hash is too similar to any already-saved hash."""
    return any(_hamming(new_hash, h) < min_distance for h in saved_hashes)


# ---------------------------------------------------------------------------
# Warp helper
# ---------------------------------------------------------------------------

def _warp_gray(frame: np.ndarray, M: np.ndarray, board_size: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (warped_bgr, warped_gray)."""
    warped = cv2.warpPerspective(frame, M, (board_size, board_size))
    return warped, cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)


# ---------------------------------------------------------------------------
# Arg parse
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Extract training frames from video")
    p.add_argument("--video", required=True, help="Input video path")
    p.add_argument("--out-dir", default="data/training_images", help="Output JPEG directory")
    p.add_argument("--calibration", default="calibration/calibration.json")
    p.add_argument(
        "--motion-threshold", type=float, default=3.0,
        help="MAE above this = motion detected (hand moving)"
    )
    p.add_argument(
        "--settle-frames", type=int, default=60,
        help="Consecutive stable frames required after motion stops before saving. "
             "At 30fps, 45 = 1.5 seconds — enough for hand to fully clear the board."
    )
    p.add_argument(
        "--hash-distance", type=int, default=12,
        help="Minimum perceptual hash Hamming distance (0-64) between saved frames. "
             "Higher = more unique frames required. 12/64 ≈ 80%% similarity threshold."
    )
    p.add_argument("--max-saves", type=int, default=500, help="Stop after this many images")
    p.add_argument("--prefix", default="train", help="Output filename prefix")
    p.add_argument("--start-index", type=int, default=0, help="Starting file index")
    p.add_argument("--preview", action="store_true", help="Show live preview window")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    video_path = Path(args.video)
    out_dir = Path(args.out_dir)

    if not video_path.exists():
        raise FileNotFoundError(video_path)

    cal = load_calibration(args.calibration)
    M = np.asarray(cal["transform_matrix"], dtype=np.float32)
    board_size = int(cal["board_size"])

    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video: {video_path.name}  |  {total_frames} frames @ {fps:.1f} fps")
    print(f"Settle window: {args.settle_frames} frames ({args.settle_frames/fps:.1f}s)")
    print(f"Hash distance threshold: {args.hash_distance}/64")
    print(f"Output: {out_dir.resolve()}\n")

    # State machine
    STATE_WAITING  = "WAITING"
    STATE_MOVING   = "MOVING"
    STATE_SETTLING = "SETTLING"
    state = STATE_WAITING

    prev_gray: np.ndarray | None = None
    stable_count = 0
    saved = 0
    saved_hashes: list[np.ndarray] = []
    next_index = args.start_index
    frame_idx = 0

    while saved < args.max_saves:
        ok, frame = cap.read()
        if not ok:
            break

        _, warped_gray = _warp_gray(frame, M, board_size)

        if prev_gray is None:
            prev_gray = warped_gray
            frame_idx += 1
            continue

        mae = float(np.mean(cv2.absdiff(warped_gray, prev_gray)))
        moving = mae > args.motion_threshold
        prev_gray = warped_gray

        # --- State transitions ---
        if state == STATE_WAITING:
            if moving:
                state = STATE_MOVING
                stable_count = 0

        elif state == STATE_MOVING:
            if not moving:
                state = STATE_SETTLING
                stable_count = 1
            # else: still moving, stay in MOVING

        elif state == STATE_SETTLING:
            if moving:
                # Hand came back — reset
                state = STATE_MOVING
                stable_count = 0
            else:
                stable_count += 1
                if stable_count >= args.settle_frames:
                    # Ready to save — check for duplicates
                    new_hash = _ahash(warped_gray)
                    if not _is_duplicate(new_hash, saved_hashes, args.hash_distance):
                        name = f"{args.prefix}_{next_index:05d}.jpg"
                        path = out_dir / name
                        if cv2.imwrite(str(path), frame):
                            saved_hashes.append(new_hash)
                            saved += 1
                            next_index += 1
                            pct = 100 * frame_idx / total_frames if total_frames else 0
                            print(f"[{pct:5.1f}%] saved {name}  (mae={mae:.2f}, {saved}/{args.max_saves})")
                        else:
                            print(f"  WARNING: failed to write {path}")
                    else:
                        print(f"[{100*frame_idx/total_frames:5.1f}%] skipped — duplicate (mae={mae:.2f})")
                    state = STATE_WAITING
                    stable_count = 0

        # --- Optional preview ---
        if args.preview:
            warped_bgr = cv2.warpPerspective(frame, M, (board_size, board_size))
            display = warped_bgr.copy()
            colors = {STATE_WAITING: (180, 180, 0), STATE_MOVING: (0, 0, 255), STATE_SETTLING: (0, 200, 255)}
            color = colors[state]
            label = f"{state}  stable={stable_count}/{args.settle_frames}  saved={saved}"
            cv2.putText(display, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
            cv2.imshow("Training frame extractor — q to quit", display)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("Quit.")
                break

        frame_idx += 1

    cap.release()
    cv2.destroyAllWindows()
    print(f"\nDone. Saved {saved} images to {out_dir.resolve()}")


if __name__ == "__main__":
    main()
