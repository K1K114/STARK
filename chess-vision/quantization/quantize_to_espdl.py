"""
Quantize an ONNX model to ESP-DL (.espdl) with ESP-PPQ (PTQ).

Usage:
    python quantization/quantize_to_espdl.py \
        --onnx model/chess_yolo_320.onnx \
        --output model/chess_yolo_320_p4_int8.espdl \
        --calib-dir data/calibration_images \
        --imgsz 320 \
        --calib-steps 150
"""

from pathlib import Path
import argparse
import math
import tempfile

import cv2
import onnx
from onnx import shape_inference
import torch
from torch.utils.data import DataLoader, Dataset

from esp_ppq.api import espdl_quantize_onnx


def fix_negative_axes(onnx_path: str) -> str:
    """Replace negative axis attributes with positive equivalents for ESP-PPQ compatibility."""
    model = onnx.load(onnx_path)
    model = shape_inference.infer_shapes(model)

    rank_map = {}
    for vi in list(model.graph.value_info) + list(model.graph.input) + list(model.graph.output):
        if vi.type.HasField("tensor_type") and vi.type.tensor_type.HasField("shape"):
            rank_map[vi.name] = len(vi.type.tensor_type.shape.dim)

    for node in model.graph.node:
        for attr in node.attribute:
            if attr.name == "axis" and attr.i < 0:
                input_name = node.input[0] if node.input else None
                if input_name and input_name in rank_map:
                    attr.i = rank_map[input_name] + attr.i

    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    onnx.save(model, tmp.name)
    return tmp.name


class CalibrationImageDataset(Dataset):
    def __init__(self, image_dir: Path, imgsz: int):
        self.image_dir = image_dir
        self.imgsz = imgsz
        patterns = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
        self.image_paths = []
        for pattern in patterns:
            self.image_paths.extend(sorted(image_dir.glob(pattern)))
        if not self.image_paths:
            raise ValueError(f"No calibration images found in: {image_dir}")

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        path = self.image_paths[idx]
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Failed to read image: {path}")
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = cv2.resize(image, (self.imgsz, self.imgsz), interpolation=cv2.INTER_LINEAR)
        tensor = torch.from_numpy(image).permute(2, 0, 1).contiguous().float() / 255.0
        # Return tensor only. collate_fn will stack tensors to [N, C, H, W].
        return tensor


def collate_fn(batch):
    return [torch.stack(batch, dim=0).to("cpu")]


def parse_args():
    parser = argparse.ArgumentParser(description="Quantize ONNX to ESP-DL .espdl")
    parser.add_argument("--onnx", required=True, help="Input ONNX model path")
    parser.add_argument("--output", required=True, help="Output .espdl model path")
    parser.add_argument(
        "--calib-dir",
        required=True,
        help="Directory with unseen calibration images",
    )
    parser.add_argument("--imgsz", type=int, default=320, help="Input size used for export")
    parser.add_argument(
        "--calib-steps",
        type=int,
        default=150,
        help="Number of calibration steps for PTQ",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Calibration dataloader batch size (keep small for memory)",
    )
    parser.add_argument(
        "--target",
        default="esp32p4",
        choices=["esp32p4", "esp32s3", "c"],
        help="ESP target for quantization rules",
    )
    parser.add_argument(
        "--bits",
        type=int,
        default=8,
        choices=[8, 16],
        help="Quantization bit width",
    )
    parser.add_argument(
        "--skip-error-report",
        action="store_true",
        help="Disable graphwise/layerwise error reporting",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    onnx_path = Path(args.onnx)
    output_path = Path(args.output)
    calib_dir = Path(args.calib_dir)

    if not onnx_path.exists():
        raise FileNotFoundError(f"ONNX model not found: {onnx_path}")
    if not calib_dir.exists():
        raise FileNotFoundError(f"Calibration folder not found: {calib_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = CalibrationImageDataset(calib_dir, args.imgsz)
    dataloader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,  # Important: keep deterministic for calibration
        num_workers=0,
        drop_last=False,
    )

    max_steps = math.ceil(len(dataset) / args.batch_size)
    calib_steps = min(args.calib_steps, max_steps)
    if calib_steps < 1:
        raise ValueError("calib_steps resolved to 0; check calibration dataset")

    print(f"Quantizing {onnx_path} -> {output_path}")
    print(f"Calibration images: {len(dataset)}, batch_size={args.batch_size}, calib_steps={calib_steps}")

    fixed_onnx = fix_negative_axes(str(onnx_path))
    print(f"Preprocessed ONNX (fixed negative axes): {fixed_onnx}")

    # esp-ppq appends .espdl automatically — strip the extension if present
    export_stem = str(output_path.with_suffix("") if output_path.suffix == ".espdl" else output_path)

    espdl_quantize_onnx(
        onnx_import_file=fixed_onnx,
        espdl_export_file=export_stem,
        calib_dataloader=dataloader,
        calib_steps=calib_steps,
        input_shape=[1, 3, args.imgsz, args.imgsz],
        target=args.target,
        num_of_bits=args.bits,
        collate_fn=lambda x: x,
        device="cpu",
        error_report=not args.skip_error_report,
        skip_export=False,
        export_test_values=True,
        verbose=1,
    )

    print(f"Done. ESP-DL model exported to: {output_path}")


if __name__ == "__main__":
    main()
