# Changelog

All notable changes to `LULCkit` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-11-27

### Added
- 10 new standard GIS & EO palettes across Python core, CLI, Spaces, QGIS, RustGIS, and Browser Studio (16 palettes total: `esa-worldcover`, `esri-lulc`, `dynamic-world`, `nlcd`, `corine`, `qgis-spectral`, `arcgis-topo`, `urban-heat`, `hydrology`, `ag-phenology`, plus the 6 existing presets).
- QGIS `.qml` (`--qml`) and OGC `.sld` (`--sld`) layer style XML exporters (`write_qgis_qml_style`, `write_sld_style`) in `lulc map` and client-side Browser Studio.
- ArcGIS Pro / QGIS parity tools in Browser GeoTIFF Studio (`docs/`): Singleband Pseudocolor stretch mode (`2%–98%`, `Min–Max`, `Mean ± 2σ`, `Custom`), RGB Stretch + Gamma slider, 13 continuous color ramps with Invert Ramp, Class Visibility checkboxes + Invert/Randomize palette, Legal print size, click Identify Pixel on both Print Map & Web Map, geodesic Distance & Area measurement tools, Zoom to Layer, Resampling (`nearest`/`linear`), and Dark Matter / Esri Topo basemaps.

## [0.3.0] - 2026-11-27

### Added
- Broader Hugging Face segmentation support via `AutoModelForSemanticSegmentation` (SegFormer, UPerNet, Mask2Former, DPT) and `post_process_semantic_segmentation` query-head fallback in `HFSegFormerModel`.
- 4-way flip Test-Time Augmentation (`--tta`), CUDA `torch.amp.autocast`, and bounded in-memory model caching for Hugging Face and Dynamic World inference.
- Tile-level `O(1)`-RAM speckle filtering (`--sieve-size`) via `rasterio.features.sieve`.
- Synced Hugging Face Spaces ZeroGPU UI (`spaces/app.py`), RustGIS plugin (`tta`, `sieveSize`, updated `hfModel`), and GitHub Pages Browser Studio (`MNDWI`, `NBR`) with `v0.3.0`.

## [0.2.0] - 2026-11-27

### Added
- Cloud-Optimized GeoTIFF (`COG`) outputs with GDAL `.aux.xml` Raster Attribute Tables / named legends (`write_gdal_category_aux_xml`).
- Additional spectral indices (`MNDWI` and `NBR`), multi-band subset COG export, visual 8-bit RGB COG export, and Sentinel-2 / Landsat folder band stacking (`lulc bands --stack-dir`).
- Official RustGIS plugin (`rustgis_plugin/`) with `LULCkit` ribbon tab, Processing tools, and `.rgplugin` package builder.

## [0.1.0] - 2026-11-24

### Added
- `lulc inspect`: Zero-ML profiler for TIFF/GeoTIFF layout, CRS, GSD, WGS84 bounds/centroid, GDAL/TIFF tags, band stats, and sensor fingerprinting.
- `lulc map`: Memory-safe windowed tiled inference (`O(1)` RAM with overlap halo discard) supporting:
  - `rgb-oem` (`nave1616/SegFormer-landcover-FT`, 9 OpenEarthMap classes)
  - `rgb-fast` (`florian-morel22/segformer-b0-deepglobe-land-cover`, 7 DeepGlobe classes)
  - `s2-dw` (`calebrob6/dynamic_world_pytorch`, 9 Sentinel-2 classes)
  - `categorical` (zero-ML pass-through for pre-classified single-band GeoTIFFs)
- `lulc bands`: Inspect band spectral roles, extract/render single bands or custom 3-band RGB composites, and stream-compute `NDVI`, `NDWI`, `NDBI`, `SAVI`, and `EVI`.
- `lulc clip`: Clip any georeferenced TIFF/GeoTIFF to a GeoJSON polygon boundary while preserving colormaps and metadata.
- `lulc batch`: Process folders of TIFF/GeoTIFF files with summary reporting.
- `lulc wizard`: Interactive guided setup printing reproducible `lulc map` commands.
- `lulc models` & `lulc styles`: Inspect model cache status, color palettes, optical composites, spectral indices, north arrows, scale bars, and print page sizes.
- Full-page print cartography (`a4`, `a5`, `a3`, `letter`, `legal`, `square`) with 5 north arrow styles, ArcGIS-style scale bars, X/Y coordinate grids, GeoJSON boundary overlays, `png`/`pdf`/`svg` export, and GeoLibre-inspired MapLibre GL JS `--html` maps.
