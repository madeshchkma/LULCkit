# LULCkit QGIS Plugin (`lulckit_qgis`)

Native **QGIS 3.22+ / QGIS 4 (Qt5 & Qt6)** Processing Provider and menu integration for **LULCkit** — run automated LULC classification, spectral indices (`NDVI`, `NDWI`, `NDBI`, `SAVI`, `EVI`), sensor inspection, publication print cartography, MapLibre HTML export, and polygon clipping directly from your QGIS Layers Panel and Graphical Modeler.

---

## Processing Tools Included

Found under **Processing Toolbox → LULCkit** (or **Plugins → LULCkit**):

1. **`LULC Classification & Cartographic Map` (`lulckit:map`)**
   - Supports `auto`, `categorical`, `rgb-oem`, `rgb-fast`, and `s2-dw` (Sentinel-2 Dynamic World) models.
   - Outputs styled GeoTIFF (`*_lulc.tif` auto-loaded onto canvas), 300 DPI print map (`*_preview.png`), `*_summary.csv`, `*_report.json`, optional vector polygons (`*_lulc.geojson`), and optional MapLibre interactive map (`*_map.html`).
2. **`Spectral Indices & Band Composites` (`lulckit:bands`)**
   - Computes float32 `NDVI`, `NDWI`, `NDBI`, `SAVI`, `EVI` rasters or renders 3-band RGB composites (`true-color`, `false-color-nir`, `agriculture`, `swir`, or custom band triplets) and loads the output directly into QGIS.
3. **`Inspect GeoTIFF Metadata & Sensor Profile` (`lulckit:inspect`)**
   - Prints CRS, metric GSD, WGS84 extent, COG overview info, band percentiles, and auto-detected sensor type cleanly in the Processing log (plus optional JSON export).
4. **`Clip GeoTIFF to Polygon Layer` (`lulckit:clip`)**
   - Clips any GeoTIFF to any QGIS polygon vector layer (Shapefile, GeoPackage, memory layer, or selected features) preserving embedded GDAL colormaps.

---

## Installation in QGIS

### Option A — Install from ZIP (`Install from ZIP`)

1. Build the ZIP archive (or download it from GitHub Releases):
   ```powershell
   python scripts/build_qgis_plugin.py
   ```
   This generates `out/lulckit_qgis_v0.1.0.zip`.
2. In QGIS, open **Plugins → Manage and Install Plugins… → Install from ZIP**.
3. Select `out/lulckit_qgis_v0.1.0.zip` and click **Install Plugin**.
4. Enable **LULCkit** in the Installed Plugins list.

### Option B — Direct Local Profile Install (for Contributors)

```powershell
python scripts/build_qgis_plugin.py --install
```

Restart QGIS, then enable **LULCkit** under **Plugins → Manage and Install Plugins**.

---

## Connecting the LULCkit Python Backend

Because QGIS uses its own bundled Python environment (which usually does not ship `torch` or `transformers`), the plugin invokes LULCkit cleanly in an external Python/CLI process so heavy ML dependencies never destabilize QGIS:

1. If `lulc` / `lulckit` is already on your system `PATH` or installed in `~/.lulckit-qgis-venv`, QGIS detects it automatically.
2. Otherwise open **Plugins → LULCkit → Settings & Environment…**:
   - Either **Browse…** to your existing virtual environment's `python.exe` (for example `...\LULCkit\.venv\Scripts\python.exe`), **or**
   - Click **Install LULCkit into User Venv (`~/.lulckit-qgis-venv`)** to set up an isolated environment automatically without admin rights.
