"""
Train a YOLOv8s model on the chess piece dataset.

Prerequisites:
    1. pip install -r requirements.txt
    2. Export your Roboflow dataset to data/ as YOLOv8 format
       (data/images/train, data/images/val, data/data.yaml)

Usage:
    python training/train.py

After training, best.pt is copied to model/best.pt and exported to
model/chess_yolo_320.onnx automatically (ready for quantization).
"""
import shutil
from pathlib import Path

from ultralytics import YOLO

REPO_ROOT = Path(__file__).parent.parent
DATA_YAML = REPO_ROOT / "data" / "data.yaml"
MODEL_DIR = REPO_ROOT / "model"

EPOCHS = 100          # fine-tuning from pretrained weights; 100 is a safe minimum
IMG_SIZE = 320        # match deployment size on P4 (quantization exports at 320)
BATCH_SIZE = 16
BASE_MODEL = "yolov8s.pt"
# device omitted — Ultralytics auto-selects MPS / CUDA / CPU


def train():
    if not DATA_YAML.exists():
        raise FileNotFoundError(
            f"data.yaml not found at {DATA_YAML}\n"
            "Export your Roboflow dataset to chess-vision/data/ in YOLOv8 format."
        )

    print(f"Training on: {DATA_YAML}")
    print(f"epochs: {EPOCHS}  |  imgsz: {IMG_SIZE}  |  device: auto")
    model = YOLO(BASE_MODEL)

    results = model.train(
        data=str(DATA_YAML),
        epochs=EPOCHS,
        imgsz=IMG_SIZE,
        batch=BATCH_SIZE,
        project="runs/detect",
        name="chess_train",
        exist_ok=True,
        fliplr=0.5,
        flipud=0.0,
        degrees=15.0,
        hsv_v=0.4,
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    if not best.exists():
        print(f"WARNING: best.pt not found at {best}")
        return

    MODEL_DIR.mkdir(exist_ok=True)
    dest_pt = MODEL_DIR / "best.pt"
    shutil.copy(best, dest_pt)
    print(f"best.pt  → {dest_pt}")

    # Export to ONNX at 320×320 (required for ESP-PPQ quantization pipeline)
    print("Exporting to ONNX…")
    trained = YOLO(str(dest_pt))
    trained.export(format="onnx", imgsz=IMG_SIZE, opset=13, simplify=True, dynamic=False)

    # Ultralytics writes the ONNX next to the .pt file — move it to model/
    onnx_src = dest_pt.with_suffix(".onnx")
    if onnx_src.exists():
        onnx_dest = MODEL_DIR / f"chess_yolo_{IMG_SIZE}.onnx"
        shutil.move(str(onnx_src), onnx_dest)
        print(f"ONNX     → {onnx_dest}")
        print("\nNext step: quantize for P4")
        print(f"  python quantization/quantize_to_espdl.py "
              f"--onnx {onnx_dest} "
              f"--output model/chess_yolo_{IMG_SIZE}_p4_int8.espdl "
              f"--calib-dir data/calibration_images")
    else:
        print("ONNX export not found — run quantization/export_yolo_to_onnx.py manually.")


if __name__ == "__main__":
    train()
