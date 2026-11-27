---
title: LULCkit Studio
emoji: 🗺️
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "5.12.0"
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
short_description: Turn any GeoTIFF into LULC maps, indices & area reports
---

# LULCkit Studio on Hugging Face Spaces (v0.3.0)

Free GPU-accelerated (ZeroGPU) web UI for **[LULCkit](https://github.com/madeshchkma/LULCkit)** supporting:
- **Pretrained & custom ML inference** (`rgb-oem` SegFormer-B4, `rgb-fast` SegFormer-B0, `s2-dw` Dynamic World, plus any custom Hugging Face semantic segmentation repo via `AutoModelForSemanticSegmentation` — SegFormer, UPerNet, Mask2Former, DPT)
- **Inference quality controls**: optional 4-way flip Test-Time Augmentation (`TTA`) and `O(1)`-RAM tile-level speckle `sieve` filtering
- **Pre-classified categorical GeoTIFF styling** (`categorical`) with COG output and embedded GDAL ColorTable / `.aux.xml` legends
- **Spectral indices & COG exports**: `NDVI`, `NDWI`, `MNDWI`, `NDBI`, `SAVI`, `EVI`, `NBR`, Multi-Band Subset COG, Visual 8-bit RGB COG, and optical composites
- **Full-page publication print maps** (A4/A5/A3/Letter/Square, X/Y coordinate grids, compass roses, ArcGIS scale bars) + interactive MapLibre HTML + CSV/JSON/GeoJSON reports

## Deploy in 3 Steps (CPU Basic or ZeroGPU)

1. Go to https://huggingface.co/new-space and choose **Gradio** + **CPU basic · 2 vCPU · 16 GB · FREE** (or **ZeroGPU**).
2. Upload the 3 files from `spaces/` (`README.md`, `requirements.txt`, `app.py`) to the root of your Space repository.
3. Hugging Face automatically installs `lulckit` from `https://github.com/madeshchkma/LULCkit.git` and starts the Space.
