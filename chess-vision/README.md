# Chess Vision

Computer vision pipeline for the StarkHacks 2026 autonomous chess board.

Detects human moves from an overhead webcam feed and outputs them as UCI move strings (e.g. `e2e4`) so the main game loop can feed them to Stockfish and command the gantry.

---

## Stack

| Layer | Tool |
|-------|------|
| Object detection | YOLOv8s (ultralytics) — trained on custom 3D-printed pieces |
| Change detection | OpenCV absolute frame diff + contour analysis |
| Board calibration | OpenCV perspective transform |
| Dataset management | Roboflow |
| Training hardware | AMD cloud GPU (ROCm) |
| Inference hardware | AMD Ryzen AI laptop |
| Serial comms | pyserial (stub — implemented in firmware repo) |

---

## Repo Structure

```
chess-vision/
├── calibration/
│   ├── calibrate.py        # interactive corner-click calibration tool
│   └── calibration.json    # generated output (commit this after calibrating)
├── inference/
│   ├── board_state.py      # contour-diff move detector (layer 1)
│   └── detect.py           # YOLOv8 piece identifier (layer 2)
├── quantization/
│   ├── export_yolo_to_onnx.py       # export best.pt -> ONNX (320x320)
│   ├── extract_calibration_frames.py # video -> stable JPEGs in data/calibration_images
│   ├── quantize_to_espdl.py         # PTQ ONNX -> .espdl with esp-ppq
│   └── validate_quantization.py     # size + smoke checks vs ONNX
├── training/
│   ├── train.py            # download dataset + train YOLOv8
│   ├── chess.yaml          # dataset config
│   └── requirements.txt    # training-only deps
├── model/
│   └── best.pt             # trained model (gitignored — download link below)
├── data/                   # dataset images (gitignored — download via Roboflow)
├── tests/
│   └── test_detection.py   # sanity checks
├── requirements.txt
└── .gitignore
```

---

## Setup

```bash
git clone https://github.com/K1K114/chess-vision.git
cd chess-vision
pip install -r requirements.txt
```

Create a `.env` file for Roboflow credentials (only needed for training):

```
ROBOFLOW_API_KEY=your_key_here
ROBOFLOW_WORKSPACE=your-workspace-slug
ROBOFLOW_PROJECT=chess-pieces
ROBOFLOW_VERSION=1
```

Download `best.pt` from [Google Drive — add link here] and place it at `model/best.pt`.

---

## Pipeline

```
Webcam frame
     │
     ▼
[Layer 1: board_state.py]
OpenCV contour diff vs reference frame
Wait for 8 stable frames with exactly 2 changed squares
     │ "e2e4" (sorted square pair)
     ▼
[Layer 2: detect.py]  ← called by main game loop after layer 1 triggers
YOLOv8 identifies piece type on each square
     │ board state dict
     ▼
[Main game loop — separate repo]
python-chess validates the move legality
Stockfish calculates response
ESP32 serial command → gantry moves piece
```

---

## Step 1 — Calibrate the Camera

Run once before each session (or whenever the camera moves):

```bash
python calibration/calibrate.py              # use webcam
python calibration/calibrate.py --image board.jpg  # use a still photo
```

An OpenCV window will open. **Click the 4 corners of the chess board in order:**

1. Top-left
2. Top-right
3. Bottom-right
4. Bottom-left

The script saves `calibration/calibration.json` with the perspective transform matrix and the pixel coordinates of all 64 squares. Commit this file so teammates don't have to recalibrate.

---

## Step 2 — Train the Model

Only needed if you're starting fresh or adding new piece images.

```bash
python training/train.py
```

This downloads the Roboflow dataset, trains YOLOv8s for 50 epochs, and copies `best.pt` to `model/best.pt`. Training takes ~20–40 minutes on a GPU.

**Upload `model/best.pt` to Google Drive** and add the link to this README — the file is too large for git.

To adjust training:
- Edit `training/chess.yaml` to match your Roboflow class names
- Edit `EPOCHS`, `BATCH_SIZE`, `BASE_MODEL` in `training/train.py`

---

## Step 3 — Run Inference

### Test piece detection on a single image

```bash
python inference/detect.py --image path/to/frame.jpg
```

Prints detected pieces and their squares, then shows the annotated frame.

### Test move detection on the webcam

```bash
python inference/board_state.py  # not yet a standalone script — use tests instead
python tests/test_detection.py
```

---

## Step 4 — Quantize for ESP32-P4

Use this when moving inference from laptop to ESP32-P4.

Collect calibration JPEGs (normal photos — PTQ does not use special “quantized” image files). Easiest path: record a game, then extract stable frames:

```bash
python quantization/extract_calibration_frames.py \
  --video path/to/recording.mp4 \
  --out-dir data/calibration_images \
  --calibration calibration/calibration.json
```

See `data/calibration_images/README.md` for sources and git notes.

Install quantization deps:

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install esp-ppq
```

Export the trained model to ONNX at `320x320`:

```bash
python quantization/export_yolo_to_onnx.py \
  --weights model/best.pt \
  --output model/chess_yolo_320.onnx \
  --imgsz 320
```

Quantize ONNX to ESP-DL (`.espdl`) with calibration images:

```bash
python quantization/quantize_to_espdl.py \
  --onnx model/chess_yolo_320.onnx \
  --output model/chess_yolo_320_p4_int8.espdl \
  --calib-dir data/calibration_images \
  --imgsz 320 \
  --calib-steps 150 \
  --target esp32p4 \
  --bits 8
```

Validate the export/quantization artifacts:

```bash
python quantization/validate_quantization.py \
  --pt model/best.pt \
  --onnx model/chess_yolo_320.onnx \
  --espdl model/chess_yolo_320_p4_int8.espdl \
  --sample-dir data/test/images \
  --imgsz 320 \
  --data-yaml data/data.yaml
```

Notes:
- Use calibration images that were **not** used in training.
- Keep `shuffle=False` in calibration dataloader for stable quantization error analysis.
- `--target esp32p4 --bits 8` maps to ESP-DL INT8 export for P4.
- The generated `.espdl` is flashed with your P4 inference firmware.

---

## Importing into the Main Game Loop

```python
from calibration.calibrate import load_calibration
from inference.board_state import BoardStateDetector
from inference.detect import PieceDetector

# Initialize once
move_detector = BoardStateDetector("calibration/calibration.json")
piece_detector = PieceDetector("model/best.pt", "calibration/calibration.json")

# Set the reference frame at game start
move_detector.set_reference(initial_frame)

# Game loop
while game_running:
    frame = cam.read()

    move_str = move_detector.update(frame, gantry_moving=gantry.is_moving)
    if move_str:
        # move_str is two squares sorted alphabetically, e.g. "e2e4"
        # Try both orderings to find the legal move:
        sq_a, sq_b = move_str[:2], move_str[2:]
        for uci in [move_str, sq_b + sq_a]:
            m = chess.Move.from_uci(uci)
            if board.is_legal(m):
                board.push(m)
                stockfish_response = engine.play(board, chess.engine.Limit(time=1.0))
                gantry.execute(stockfish_response.move)
                break
        else:
            gantry.return_piece_to_origin()  # illegal move

        # Confirm piece positions after gantry finishes
        board_state = piece_detector.get_board_state(frame)
```

---

## Troubleshooting

**Calibration window doesn't open**
Make sure a display is available. On headless servers, use `--image` with a pre-captured photo.

**Contour detection triggers too easily**
Increase `DIFF_THRESHOLD` or `MIN_CONTOUR_AREA` in `inference/board_state.py`.

**Model not detecting pieces reliably**
- Check that `training/chess.yaml` class names match the labels in your Roboflow project exactly
- Add more training images from your specific lighting setup
- Try a larger base model: change `BASE_MODEL = "yolov8m.pt"` in `train.py`

**Move detected while gantry is moving**
Make sure `gantry_moving=True` is passed to `move_detector.update()` throughout the full gantry cycle, including the settle time after the electromagnet releases.

---

## Related Repos

| Repo | Contents |
|------|---------|
| `chess-gantry` | ESP32 firmware, stepper control, serial protocol |
| `stark-chess` | Main Python game loop, Stockfish integration, serial commands |
