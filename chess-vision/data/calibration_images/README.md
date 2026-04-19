# Calibration images (PTQ, not “quantized images”)

Post-training quantization (ESP-PPQ) still feeds **normal 8-bit RGB JPEGs** into the model. The tool measures activations on those images and picks INT8 scales. The images themselves are not stored as INT8 tensors in this folder.

## Where these files come from

1. **Recommended:** Record a game from your mounted camera, then extract stable frames:

   ```bash
   python quantization/extract_calibration_frames.py \
     --video path/to/recording.mp4 \
     --out-dir data/calibration_images \
     --calibration calibration/calibration.json
   ```

2. **Alternative:** Copy a few dozen full-frame photos that were **not** used in YOLO training into this folder (same lighting and camera as deploy).

3. **Not ideal:** Random frames from `train/` — better to hold out separate images so calibration matches “real world” variance without reusing training pixels.

## Git

Generated `*.jpg` files here are ignored by `.gitignore` so large folders are not committed by accident. Keep this README (and `.gitkeep`) in git; regenerate images locally or share via drive.
