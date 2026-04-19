"""
Read JPEG frames from serial and run chess-piece object detection.

Protocol expected (matches webcamtoserial.py):
    [4-byte little-endian payload length] + [JPEG bytes]

Notes:
    - ESP-DL .espdl artifacts run on-device (ESP32-P4), not on laptop Python.
    - For laptop testing, pass --model model/chess_yolo_320.onnx (or best.pt).
    - If you pass an .espdl path and a sibling .onnx exists, this script will
      automatically use that .onnx for host inference.
"""

from __future__ import annotations

import argparse
import os
import struct
import time

import cv2
import numpy as np

try:
    import serial
except ImportError as exc:
    raise ImportError("pyserial not installed. Run: pip install pyserial") from exc

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise ImportError("ultralytics not installed. Run: pip install ultralytics") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run chess object detection on JPEG frames received from serial"
    )
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port (example: /dev/tty.usbmodem5B140758861)",
    )
    parser.add_argument("--baud", type=int, default=921600, help="Serial baud rate")
    parser.add_argument(
        "--model",
        default="model/chess_yolo_320_p4_int8.espdl",
        help="Model path (.pt/.onnx for host inference, or .espdl to auto-map to sibling .onnx)",
    )
    parser.add_argument("--conf", type=float, default=0.25, help="Detection confidence")
    parser.add_argument("--imgsz", type=int, default=320, help="Inference image size")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=250000,
        help="Reject incoming frame payloads larger than this",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Disable OpenCV preview window",
    )
    parser.add_argument(
        "--print-every",
        type=int,
        default=10,
        help="Print detections once every N frames",
    )
    return parser.parse_args()


def resolve_host_model(model_path: str) -> str:
    """Resolve a model path usable by Ultralytics on host.

    If .espdl is provided, use a sibling .onnx if present.
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")

    if model_path.lower().endswith(".espdl"):
        onnx_path = os.path.splitext(model_path)[0] + ".onnx"
        if os.path.exists(onnx_path):
            print(
                "[INFO] .espdl selected. Using sibling ONNX for host inference:\n"
                f"       {onnx_path}"
            )
            return onnx_path
        model_dir = os.path.dirname(model_path) or "."
        onnx_candidates = sorted(
            [
                os.path.join(model_dir, name)
                for name in os.listdir(model_dir)
                if name.lower().endswith(".onnx")
            ]
        )
        if onnx_candidates:
            print(
                "[INFO] .espdl selected. No same-stem ONNX found; using ONNX in model directory:\n"
                f"       {onnx_candidates[0]}"
            )
            return onnx_candidates[0]
        raise RuntimeError(
            "Cannot run .espdl directly in Python. Add an ONNX/PT model for host testing, "
            f"or run ESP-DL inference on-device. Missing sibling ONNX: {onnx_path}"
        )

    return model_path


def read_exact(ser: serial.Serial, size: int) -> bytes:
    """Read exactly size bytes or raise on timeout/disconnect."""
    buf = bytearray()
    while len(buf) < size:
        chunk = ser.read(size - len(buf))
        if not chunk:
            raise TimeoutError(f"Serial timeout: needed {size} bytes, got {len(buf)}")
        buf.extend(chunk)
    return bytes(buf)


def decode_frame(payload: bytes) -> np.ndarray:
    arr = np.frombuffer(payload, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Failed to decode JPEG payload")
    return frame


def format_detections(result) -> list[tuple[str, float, tuple[int, int, int, int]]]:
    rows = []
    names = result.names
    boxes = result.boxes
    if boxes is None:
        return rows

    for box in boxes:
        cls_idx = int(box.cls[0])
        label = names.get(cls_idx, str(cls_idx)) if isinstance(names, dict) else str(cls_idx)
        conf = float(box.conf[0])
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        rows.append((label, conf, (x1, y1, x2, y2)))
    return rows


def main() -> None:
    args = parse_args()
    model_path = resolve_host_model(args.model)

    print("=" * 64)
    print("Serial Chess Detector")
    print("=" * 64)
    print(f"Port:   {args.port}")
    print(f"Baud:   {args.baud}")
    print(f"Model:  {model_path}")
    print(f"Conf:   {args.conf}")
    print(f"ImgSz:  {args.imgsz}")
    print("Waiting for frames... (Ctrl+C to stop)")

    model = YOLO(model_path)
    ser = serial.Serial(args.port, args.baud, timeout=2, write_timeout=2)

    frame_count = 0
    last_t = time.time()
    fps = 0.0

    try:
        while True:
            header = read_exact(ser, 4)
            payload_len = struct.unpack("<I", header)[0]

            if payload_len == 0 or payload_len > args.max_bytes:
                print(f"[WARN] Dropping invalid payload size: {payload_len}")
                continue

            payload = read_exact(ser, payload_len)
            frame = decode_frame(payload)

            results = model(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)
            result = results[0]
            detections = format_detections(result)
            frame_count += 1

            now = time.time()
            dt = now - last_t
            if dt > 0:
                fps = 1.0 / dt
            last_t = now

            if args.print_every > 0 and frame_count % args.print_every == 0:
                print(f"\n[Frame {frame_count}] detections={len(detections)} fps={fps:.1f}")
                for label, conf, (x1, y1, x2, y2) in detections:
                    print(
                        f"  - {label:<18} conf={conf:.3f} "
                        f"box=({x1:>3},{y1:>3})-({x2:>3},{y2:>3})"
                    )

            if not args.no_display:
                annotated = result.plot()
                cv2.putText(
                    annotated,
                    f"FPS: {fps:.1f}  frame: {frame_count}",
                    (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow("Serial Chess Detection", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break

    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        cv2.destroyAllWindows()
        print("\nStopped.")


if __name__ == "__main__":
    main()
