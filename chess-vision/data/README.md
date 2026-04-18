# Dataset

Chess piece images are managed through Roboflow and are **not** stored in this repo.

## Download

Run the training script — it downloads the dataset automatically:

```bash
python training/train.py
```

Or download manually from Roboflow and extract here so the folder looks like:

```
data/
├── images/
│   ├── train/
│   ├── val/
│   └── test/
└── labels/
    ├── train/
    ├── val/
    └── test/
```

## Dataset Info

- Source: Roboflow project (add link here)
- Classes: 12 (6 white + 6 black piece types)
- Augmentations: rotation ±15°, brightness variation, horizontal flip

## Adding New Images

1. Photograph pieces on the board from the overhead camera angle
2. Upload to the Roboflow project
3. Label using Roboflow's annotation tool
4. Increment the version and re-download
