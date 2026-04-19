"""
Extract calibration images for ESP-PPQ from a recorded video.

Uses the same perspective warp as the live pipeline, then detects stretches of
frames where the warped board barely changes (hand gone, pieces settled).
Saves the **raw** BGR frame as JPEG so it matches what the camera / P4 path sees.

Usage:
    python quantization/extract_calibration_frames.py \\
        --video path/to/game_recording.mp4 \\
        --out-dir data/calibration_images \\
        --calibration calibration/calibration.json
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


def parse_args():
    p = argparse.ArgumentParser(description="Extract stable frames for PTQ calibration")
    p.add_argument("--video", required=True, help="Input video path")
    p.add_argument(
        "--out-dir",
        default="data/calibration_images",
        help="Output directory for JPEGs",
    )
    p.add_argument(
        "--calibration",
        default="calibration/calibration.json",
        help="calibration.json for board warp",
    )
    p.add_argument(
        "--stability-frames",
        type=int,
        default=8,
        help="Consecutive stable frames required before saving",
    )
    p.add_argument(
        "--mae-threshold",
        type=float,
        default=1.5,
        help="Mean abs diff (0-255) on warped grayscale vs previous frame",
    )
    p.add_argument(
        "--min-frames-between-saves",
        type=int,
        default=24,
        help="Minimum frames between two saves (debounce)",
    )
    p.add_argument("--max-saves", type=int, default=200, help="Stop after this many images")
    p.add_argument("--prefix", default="calib", help="Filename prefix")
    p.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="First output index (useful when appending to an existing folder)",
    )
    return p.parse_args()


def warp_gray(frame: np.ndarray, M: np.ndarray, board_size: int) -> np.ndarray:
    warped = cv2.warpPerspective(frame, M, (board_size, board_size))
    return cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)


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

    prev_gray: np.ndarray | None = None
    stable = 0
    saved = 0
    frame_idx = 0
    frames_since_save = args.min_frames_between_saves
    next_index = args.start_index

    while saved < args.max_saves:
        ok, frame = cap.read()
        if not ok:
            break

        gray = warp_gray(frame, M, board_size)

        if prev_gray is None:
            prev_gray = gray
            frame_idx += 1
            frames_since_save += 1
            continue

        mae = float(np.mean(cv2.absdiff(gray, prev_gray)))
        prev_gray = gray

        if mae <= args.mae_threshold:
            stable += 1
        else:
            stable = 0

        frames_since_save += 1

        if stable >= args.stability_frames and frames_since_save >= args.min_frames_between_saves:
            name = f"{args.prefix}_{next_index:05d}.jpg"
            path = out_dir / name
            if cv2.imwrite(str(path), frame):
                print(f"saved {path} (frame {frame_idx}, mae<={args.mae_threshold})")
                saved += 1
                next_index += 1
                stable = 0
                frames_since_save = 0
            else:
                print(f"failed to write {path}")

        frame_idx += 1

    cap.release()
    print(f"Done. Saved {saved} images under {out_dir.resolve()}")


if __name__ == "__main__":
    main()
