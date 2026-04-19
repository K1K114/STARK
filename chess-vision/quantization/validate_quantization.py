"""
Validate a quantization/export run for chess YOLO models.

This script focuses on practical checks you can run on your laptop:
1) Artifact existence and file size reduction (.pt -> .onnx/.espdl)
2) Inference smoke test on sample images using .pt vs .onnx
3) Optional validation-set metric comparison using Ultralytics `model.val()`

Usage:
    python quantization/validate_quantization.py \
      --pt model/best.pt \
      --onnx model/chess_yolo_320.onnx \
      --espdl model/chess_yolo_320_p4_int8.espdl \
      --sample-dir data/test/images \
      --imgsz 320
"""

from pathlib import Path
import argparse
import statistics

from ultralytics import YOLO


def file_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def pct_reduction(old: float, new: float) -> float:
    if old <= 0:
        return 0.0
    return 100.0 * (old - new) / old


def collect_images(sample_dir: Path, max_images: int):
    patterns = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
    images = []
    for pattern in patterns:
        images.extend(sorted(sample_dir.glob(pattern)))
    return images[:max_images]


def summarize_inference(model, images, conf, imgsz):
    det_counts = []
    confidences = []
    for img in images:
        results = model(str(img), imgsz=imgsz, conf=conf, verbose=False)
        r = results[0]
        count = len(r.boxes) if r.boxes is not None else 0
        det_counts.append(count)
        if r.boxes is not None and len(r.boxes) > 0:
            confidences.extend([float(c) for c in r.boxes.conf.tolist()])
    return {
        "images": len(images),
        "total_detections": sum(det_counts),
        "avg_detections_per_image": statistics.mean(det_counts) if det_counts else 0.0,
        "avg_confidence": statistics.mean(confidences) if confidences else 0.0,
    }


def print_summary(title: str, summary: dict):
    print(f"\n{title}")
    print("-" * len(title))
    print(f"images: {summary['images']}")
    print(f"total detections: {summary['total_detections']}")
    print(f"avg detections/image: {summary['avg_detections_per_image']:.3f}")
    print(f"avg confidence: {summary['avg_confidence']:.3f}")


def parse_args():
    parser = argparse.ArgumentParser(description="Validate quantization/export artifacts")
    parser.add_argument("--pt", required=True, help="Path to FP32 .pt model")
    parser.add_argument("--onnx", required=True, help="Path to exported ONNX model")
    parser.add_argument("--espdl", default=None, help="Path to quantized .espdl model (size check only — can't run on laptop)")
    parser.add_argument("--sample-dir", required=True, help="Image folder for smoke inference checks")
    parser.add_argument("--imgsz", type=int, default=320, help="Inference image size")
    parser.add_argument("--max-images", type=int, default=50, help="Max sample images to evaluate")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold for detection")
    parser.add_argument("--data-yaml", help="Optional dataset yaml for model.val() comparison")
    return parser.parse_args()


def main():
    args = parse_args()
    pt_path = Path(args.pt)
    onnx_path = Path(args.onnx)
    espdl_path = Path(args.espdl) if args.espdl else None
    sample_dir = Path(args.sample_dir)

    for path in [pt_path, onnx_path]:
        if not path.exists():
            raise FileNotFoundError(f"Missing artifact: {path}")
    if not sample_dir.exists():
        raise FileNotFoundError(f"Missing sample image folder: {sample_dir}")

    # 1) Artifact and size checks
    pt_mb = file_mb(pt_path)
    onnx_mb = file_mb(onnx_path)
    print("Artifact Size Check")
    print("-------------------")
    print(f"PT:    {pt_path}  ({pt_mb:.2f} MB)")
    print(f"ONNX:  {onnx_path}  ({onnx_mb:.2f} MB)  reduction vs PT: {pct_reduction(pt_mb, onnx_mb):.2f}%")
    if espdl_path and espdl_path.exists():
        espdl_mb = file_mb(espdl_path)
        print(f"ESPDL: {espdl_path}  ({espdl_mb:.2f} MB)  reduction vs PT: {pct_reduction(pt_mb, espdl_mb):.2f}%")
    else:
        print("ESPDL: not provided (run quantize_to_espdl.py first)")

    # 2) Inference smoke test on sample images (.pt vs .onnx)
    images = collect_images(sample_dir, args.max_images)
    if not images:
        raise ValueError(f"No images found in {sample_dir}")
    print(f"\nRunning smoke inference on {len(images)} images from {sample_dir} ...")

    pt_model = YOLO(str(pt_path))
    onnx_model = YOLO(str(onnx_path))

    pt_summary = summarize_inference(pt_model, images, conf=args.conf, imgsz=args.imgsz)
    onnx_summary = summarize_inference(onnx_model, images, conf=args.conf, imgsz=args.imgsz)
    print_summary("FP32 (.pt) Smoke Summary", pt_summary)
    print_summary("ONNX Smoke Summary", onnx_summary)

    # 3) Optional metric comparison on full validation set
    if args.data_yaml:
        data_yaml = Path(args.data_yaml)
        if not data_yaml.exists():
            raise FileNotFoundError(f"data.yaml not found: {data_yaml}")
        print("\nRunning optional validation metrics (this may take time)...")
        pt_metrics = pt_model.val(data=str(data_yaml), imgsz=args.imgsz, verbose=False)
        onnx_metrics = onnx_model.val(data=str(data_yaml), imgsz=args.imgsz, verbose=False)

        print("\nValidation Metrics")
        print("------------------")
        print(f"PT   mAP50-95: {pt_metrics.box.map:.4f} | mAP50: {pt_metrics.box.map50:.4f}")
        print(f"ONNX mAP50-95: {onnx_metrics.box.map:.4f} | mAP50: {onnx_metrics.box.map50:.4f}")
        print(f"Delta mAP50-95 (ONNX-PT): {onnx_metrics.box.map - pt_metrics.box.map:+.4f}")

    print("\nValidation complete.")
    print("Note: .espdl runtime correctness is finalized on-device using ESP-DL inference checks.")


if __name__ == "__main__":
    main()
