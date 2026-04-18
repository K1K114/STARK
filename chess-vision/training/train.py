"""
Train a YOLOv8s model on the chess piece dataset locally downloaded

Prerequisites:
    1. pip install -r requirements.txt

Usage:
    python training/train.py

After training, best.pt is copied to model/best.pt automatically.
"""
import shutil
from pathlib import Path
from ultralytics import YOLO

REPO_ROOT = Path(__file__).parent.parent
DATA_YAML = REPO_ROOT / "data" / "data.yaml"
MODEL_DIR = REPO_ROOT / "model"

EPOCHS = 10
IMG_SIZE = 640
BATCH_SIZE = 16
BASE_MODEL = "yolov8s.pt"   # start with s; easier than m
DEVICE = "cpu"                  # GPU 0

def train():
    print(f"Training on dataset: {DATA_YAML}")
    model = YOLO(BASE_MODEL)

    model.train(
        data=str(DATA_YAML),
        epochs=EPOCHS,
        imgsz=IMG_SIZE,
        batch=BATCH_SIZE,
        device=DEVICE,
        project="runs/detect",
        name="chess_train",
        exist_ok=True,
        fliplr=0.5,
        flipud=0.0,
        degrees=15.0,
        hsv_v=0.4,
    )

    best = Path("runs/detect/chess_train/weights/best.pt")
    if best.exists():
        MODEL_DIR.mkdir(exist_ok=True)
        dest = MODEL_DIR / "best.pt"
        shutil.copy(best, dest)
        print(f"Best model saved to {dest}")
    else:
        print(f"best.pt not found at {best}")

if __name__ == "__main__":
    train()
