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

# LULCkit Studio on Hugging Face Spaces

Free server-side web UI for **[LULCkit](https://github.com/madeshchkma/LULCkit)** supporting:
- **Pretrained ML inference** (`rgb-oem` SegFormer-B4, `rgb-fast` SegFormer-B0, `s2-dw` Dynamic World)
- **Pre-classified categorical GeoTIFF styling** (`categorical`) with embedded GDAL ColorTable
- **Spectral indices** (`NDVI`, `NDWI`, `NDBI`, `SAVI`, `EVI`) & multiband optical composites
- **Full-page publication print maps** (A4/A5/A3/Letter/Square, X/Y coordinate grids, compass roses, ArcGIS scale bars) + interactive MapLibre HTML + CSV/JSON reports

## Deploy in 3 Steps (Free CPU Tier)

1. Go to https://huggingface.co/new-space and choose **Gradio** + **CPU basic · 2 vCPU · 16 GB · FREE**.
2. Upload the 3 files from `spaces/` (`README.md`, `requirements.txt`, `app.py`) to the root of your Space repository.
3. Hugging Face automatically installs `lulckit` from `https://github.com/madeshchkma/LULCkit.git` and starts the Space.
