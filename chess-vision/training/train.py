"""
Train a YOLOv8s model on the chess piece dataset from Roboflow.

Prerequisites:
    1. pip install -r requirements.txt
    2. Create a .env file in the repo root with:
          ROBOFLOW_API_KEY=your_key_here
          ROBOFLOW_WORKSPACE=your-workspace-slug
          ROBOFLOW_PROJECT=your-project-slug
          ROBOFLOW_VERSION=1

Usage:
    python training/train.py

After training, best.pt is copied to model/best.pt automatically.
"""

import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from ultralytics import YOLO

load_dotenv()

# --- Config (override via .env or environment variables) ---
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
ROBOFLOW_WORKSPACE = os.getenv("ROBOFLOW_WORKSPACE", "your-workspace")
ROBOFLOW_PROJECT = os.getenv("ROBOFLOW_PROJECT", "chess-pieces")
ROBOFLOW_VERSION = int(os.getenv("ROBOFLOW_VERSION", "1"))

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
MODEL_DIR = REPO_ROOT / "model"
YAML_PATH = Path(__file__).parent / "chess.yaml"

EPOCHS = 50
IMG_SIZE = 640
BATCH_SIZE = 16
BASE_MODEL = "yolov8m.pt"   # swap for yolov8n.pt to train faster, yolov8m.pt for more accuracy
DEVICE = 0                   # 0 = first GPU; "cpu" if no GPU available


def download_dataset():
    """Pull the dataset from Roboflow in YOLOv8 format."""
    if not ROBOFLOW_API_KEY:
        raise EnvironmentError(
            "ROBOFLOW_API_KEY not set.\n"
            "Add it to a .env file in the repo root:\n"
            "  ROBOFLOW_API_KEY=your_key_here"
        )
    try:
        from roboflow import Roboflow
    except ImportError:
        raise ImportError("Run: pip install roboflow")

    print(f"Downloading dataset from Roboflow ({ROBOFLOW_WORKSPACE}/{ROBOFLOW_PROJECT} v{ROBOFLOW_VERSION})…")
    rf = Roboflow(api_key=ROBOFLOW_API_KEY)
    project = rf.workspace(ROBOFLOW_WORKSPACE).project(ROBOFLOW_PROJECT)
    dataset = project.version(ROBOFLOW_VERSION).download("yolov8", location=str(DATA_DIR))
    print(f"Dataset saved to {DATA_DIR}")
    return dataset


def train():
    download_dataset()

    print(f"\nStarting YOLOv8 training — {EPOCHS} epochs, img {IMG_SIZE}px, batch {BATCH_SIZE}")
    model = YOLO(BASE_MODEL)
    model.train(
        data=str(YAML_PATH),
        epochs=EPOCHS,
        imgsz=IMG_SIZE,
        batch=BATCH_SIZE,
        device=DEVICE,
        project="runs/detect",
        name="chess_train",
        exist_ok=True,
        # Augmentation tweaks for overhead chess photography:
        # pieces don't flip upside-down, but they do rotate and vary in brightness
        fliplr=0.5,
        flipud=0.0,
        degrees=15.0,
        hsv_v=0.4,   # brightness variation for different lighting conditions
    )

    # Copy the best checkpoint to a stable location
    best = Path("runs/detect/chess_train/weights/best.pt")
    if best.exists():
        MODEL_DIR.mkdir(exist_ok=True)
        dest = MODEL_DIR / "best.pt"
        shutil.copy(best, dest)
        print(f"\nBest model saved → {dest}")
        print("Upload this file to Google Drive and add the link to README.md")
    else:
        print(f"\nWarning: best.pt not found at {best}")
        print("Check the runs/detect/chess_train/ directory manually.")


if __name__ == "__main__":
    train()
