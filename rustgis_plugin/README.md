# LULCkit for RustGIS

**LULCkit** is a process plugin for [RustGIS](https://rustgis.app/) (desktop and `rustgis-cli`) that turns optical or pre-classified GeoTIFFs into GIS-ready Land Use / Land Cover (LULC) maps, spectral indices, clipped rasters, vector polygons, and publication print cartography.

## Ribbon & Tools

Installing the plugin adds a **LULCkit** ribbon tab and four tools under **Tools › Plugins › LULCkit**:

- **LULC Map & Classification** (`lulc-map`): Classify RGB imagery (`rgb-oem`, `rgb-fast`) or 9–13 band Sentinel-2 scenes (`s2-dw`), or style pre-classified integer rasters (`categorical`), exporting a GeoTIFF with GDAL ColorTable, 300 DPI print map, CSV/JSON reports, optional vector GeoJSON layer, and optional MapLibre HTML viewer.
- **Inspect GeoTIFF Metadata** (`inspect-geotiff`): Profile CRS, GSD, band statistics, layout/COG structure, WGS84 footprint layer, and recommended model.
- **Bands & Spectral Indices** (`spectral-index`): Stream-compute `NDVI`, `NDWI`, `NDBI`, `SAVI`, or `EVI`, standard optical composites (`true-color`, `false-color-nir`, `agriculture`, `swir`), custom 3-band RGBs, or single-band maps.
- **Clip GeoTIFF to Polygon** (`clip-raster`): Clip a GeoTIFF to any RustGIS polygon layer while preserving colormaps and tags.

Two ribbon commands are also available: **Models & Styles** (`models-info`) and **About LULCkit** (`about`).

## Permissions & Runtime Notes

- **Not sandboxed (Python process plugin):** Runs locally on desktop and `rustgis-cli` (not in the RustGIS web app) using a managed Python 3.12 environment created by `uv` from `requirements.txt`.
- **`files` permission:** Requested so file parameters (`Input GeoTIFF`) can read local `.tif`/`.tiff` files by path without the 64 MB buffer limit.
- **Offline vs. pretrained weights:** `categorical`, `inspect-geotiff`, `spectral-index`, and `clip-raster` run 100% offline. Optional ML models (`rgb-oem`, `rgb-fast`, `s2-dw`) download pretrained weights from Hugging Face / GitHub on first use and cache them locally.

## Build Package Locally

```bash
python scripts/build_rustgis_plugin.py
```

This writes `out/lulckit-<version>.rgplugin` and `out/lulckit.json`. Install via **Plugins › Plugin Manager › Settings › Install From File…** or:

```bash
rustgis-cli plugins install out/lulckit-0.1.0.rgplugin
```
