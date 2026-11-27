# LULCkit for RustGIS

**LULCkit** is a process plugin for [RustGIS](https://rustgis.app/) (desktop and `rustgis-cli`) that turns optical or pre-classified GeoTIFFs, VRTs, or JP2 archives into Cloud-Optimized Land Use / Land Cover (LULC) maps, multi-band COGs, spectral indices, clipped rasters, vector polygons, and publication print cartography.

## Ribbon & Tools

Installing the plugin adds a **LULCkit** ribbon tab and six tools under **Tools › Plugins › LULCkit**:

- **LULC Map & Classification** (`lulc-map`): Classify RGB imagery (`rgb-oem`, `rgb-fast`, or custom `--hf-model`) or 9–13 band Sentinel-2 scenes (`s2-dw`), or style pre-classified integer rasters (`categorical`), exporting a COG with GDAL ColorTable + `.aux.xml` `<CategoryNames>`, optional confidence GeoTIFF, 300 DPI print map, CSV/JSON reports, optional vector GeoJSON layer, and optional MapLibre HTML viewer.
- **Export & Split Raster Bands** (`export-bands`): Export any arbitrary subset of bands into a multi-band COG (`subset-stack`), split bands into per-band COGs (`split-bands`), or export a stretched 8-bit visual RGBA COG (`visual-rgb`) — preserving band descriptions and `CENTRAL_WAVELENGTH_UM` metadata for RustGIS's Spectral Profile.
- **Stack Band Folder (S2 / Landsat)** (`stack-bands`): Recursively stack per-band Sentinel-2 (`.jp2`/`.tif`) or Landsat Collection 2 (`SR_B*.tif`) files from a folder into one aligned multi-band COG, with optional `SCL` / `QA_PIXEL` cloud masking.
- **Bands & Spectral Indices** (`spectral-index`): Stream-compute `NDVI`, `NDWI`, `MNDWI`, `NDBI`, `SAVI`, `EVI`, or `NBR`, standard optical composites (`true-color`, `false-color-nir`, `agriculture`, `swir`), custom 3-band RGBs, or single-band maps.
- **Inspect GeoTIFF Metadata** (`inspect-geotiff`): Profile CRS, GSD, band statistics, layout/COG structure, WGS84 footprint layer, and recommended model (`.tif`, `.tiff`, `.vrt`, `.jp2`).
- **Clip GeoTIFF to Polygon** (`clip-raster`): Clip a GeoTIFF to any RustGIS polygon layer while preserving colormaps and tags.

Four ribbon commands are also available under **LULCkit › Map & Info**:

- **Load Last Output** (`load-output-raster`): Loads the latest LULCkit output GeoTIFF (or a specified path) directly onto the active RustGIS map via `layer.addData`.
- **Inspect Layer** (`inspect-active-raster`): Queries an open RustGIS raster layer (`raster.info`) and runs LULCkit sensor fingerprinting + model recommendation.
- **Models & Styles** (`models-info`) & **About LULCkit** (`about`).

## Permissions & Runtime Notes

- **Not sandboxed (Python process plugin):** Runs locally on desktop and `rustgis-cli` (not in the RustGIS web app) using a managed Python 3.12 environment created by `uv` from `requirements.txt`.
- **`files` permission:** Requested so file parameters (`Input GeoTIFF`) can read local `.tif`/`.tiff`/`.vrt`/`.jp2` files by path without the 64 MB buffer limit.
- **`edit` permission:** Requested so **Load Last Output** (`load-output-raster`) can add generated GeoTIFF/COG layers directly onto the map with `layer.addData`.
- **Offline vs. pretrained weights:** `categorical`, `export-bands`, `stack-bands`, `inspect-geotiff`, `spectral-index`, and `clip-raster` run 100% offline. Optional ML models (`rgb-oem`, `rgb-fast`, `s2-dw`) download pretrained weights from Hugging Face / GitHub on first use and cache them locally.

## Build Package Locally

```bash
python scripts/build_rustgis_plugin.py
```

This writes `out/lulckit-0.2.0.rgplugin` and `out/lulckit.json`. Install via **Plugins › Plugin Manager › Settings › Install From File…** or:

```bash
rustgis-cli plugins install out/lulckit-0.2.0.rgplugin
```
