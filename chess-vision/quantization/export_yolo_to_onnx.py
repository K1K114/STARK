"""
Export a trained Ultralytics YOLO model (.pt) to ONNX for ESP-PPQ.

Usage:
    python quantization/export_yolo_to_onnx.py \
        --weights model/best.pt \
        --output model/chess_yolo_320.onnx \
        --imgsz 320
"""

from pathlib import Path
import argparse

from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="Export YOLO .pt to ONNX")
    parser.add_argument("--weights", default="model/best.pt", help="Path to trained .pt model")
    parser.add_argument(
        "--output",
        default="model/chess_yolo_320.onnx",
        help="Output ONNX path",
    )
    parser.add_argument("--imgsz", type=int, default=320, help="Square inference size")
    parser.add_argument(
        "--opset",
        type=int,
        default=13,
        help="ONNX opset version (11 or 13 recommended for esp-ppq)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    weights_path = Path(args.weights)
    output_path = Path(args.output)

    if not weights_path.exists():
        raise FileNotFoundError(f"Model not found: {weights_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(weights_path))
    # Ultralytics writes into the chosen directory/name and returns exported path.
    exported_path = model.export(
        format="onnx",
        imgsz=args.imgsz,
        opset=args.opset,
        simplify=True,
        dynamic=False,
        half=False,
        int8=False,
        nms=False,
    )

    exported_path = Path(str(exported_path))
    if exported_path.resolve() != output_path.resolve():
        output_path.write_bytes(exported_path.read_bytes())
        print(f"Copied ONNX export -> {output_path}")
    else:
        print(f"ONNX export ready at {output_path}")


if __name__ == "__main__":
    main()
