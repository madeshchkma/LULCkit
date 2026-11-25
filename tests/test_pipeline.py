"""Comprehensive unit and integration tests for LULCkit."""

from __future__ import annotations

import csv
import json
import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from PIL import Image
from pyproj import Geod
from rasterio.enums import ColorInterp
from rasterio.errors import NotGeoreferencedWarning
from typer.testing import CliRunner

from lulckit.cli import app
from lulckit.geo import compute_row_pixel_areas_m2, compute_spectral_indices
from lulckit.inspect import inspect_tiff
from lulckit.models.base import NODATA_VALUE, BaseLULCModel, ClassSpec, color_for_label
from lulckit.models.router import UnsupportedRasterError, select_model
from lulckit.outputs import (
    build_report,
    export_vector_geojson,
    render_preview_png,
    write_csv_summary,
    write_json_report,
)
from lulckit.tiling import run_tiled_inference


def _write_geotiff(
    path: Path,
    data: np.ndarray,
    crs: str | None = "EPSG:32632",
    transform: Affine | None = None,
    nodata: float | int | None = None,
    descriptions: tuple[str, ...] | None = None,
    colorinterp: tuple[ColorInterp, ...] | None = None,
    tags: dict[str, str] | None = None,
) -> Path:
    count, height, width = data.shape
    profile: dict = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": str(data.dtype),
    }
    if nodata is not None:
        profile["nodata"] = nodata
    if crs is not None:
        profile["crs"] = crs
        profile["transform"] = transform or (Affine.translation(500000.0, 5000000.0) @ Affine.scale(1.0, -1.0))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(data)
            if descriptions:
                for i, desc in enumerate(descriptions, start=1):
                    dst.set_band_description(i, desc)
            if colorinterp:
                dst.colorinterp = colorinterp
            if tags:
                dst.update_tags(**tags)
    return path


class _SeamAwareMockRGBModel(BaseLULCModel):
    """Deterministic mock RGB model that deliberately corrupts 8px border halos.

    If tiling overlap/halo discard is broken, class 2 will leak into the output.
    """

    name = "mock-rgb"
    description = "Mock RGB model"
    expected_bands = 3
    optimal_gsd_m = "1.0m"
    classes = [
        ClassSpec(0, "bareland", color_for_label("bareland", 0)),
        ClassSpec(1, "tree", color_for_label("tree", 1)),
        ClassSpec(2, "seam_artifact", (255, 0, 255)),
    ]

    def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        b, h, w, _ = tiles.shape
        labels = (tiles[:, :, :, 0] > 127).astype(np.uint8)
        # Deliberately poison outer 8px edge inside the model tile to verify halo discard
        if h > 16 and w > 16:
            labels[:, :8, :] = 2
            labels[:, -8:, :] = 2
            labels[:, :, :8] = 2
            labels[:, :, -8:] = 2
        conf = np.full((b, h, w), 85, dtype=np.uint8)
        return labels, conf


def test_inspect_all_seven_raster_types(tmp_path: Path) -> None:
    rng = np.random.default_rng(42)

    # (a) Projected UTM 3-band RGB GeoTIFF
    utm_rgb = _write_geotiff(
        tmp_path / "utm_rgb.tif",
        rng.integers(10, 250, size=(3, 64, 80), dtype=np.uint8),
        crs="EPSG:32632",
        transform=Affine.translation(500000.0, 5000000.0) @ Affine.scale(0.5, -0.5),
        tags={"SENSOR": "AerialTest"},
    )
    p_utm = inspect_tiff(utm_rgb)
    assert p_utm.is_georeferenced is True
    assert p_utm.crs_epsg == 32632
    assert p_utm.gsd_meters == pytest.approx([0.5, 0.5], rel=1e-4)
    assert p_utm.total_area_m2 == pytest.approx(64 * 80 * 0.25, rel=1e-6)
    assert p_utm.detected_profile == "rgb-highres"
    assert p_utm.recommended_model == "rgb-oem"
    assert p_utm.tags["SENSOR"] == "AerialTest"

    # (b) Geographic EPSG:4326 3-band RGB GeoTIFF
    geo_rgb = _write_geotiff(
        tmp_path / "geo_4326.tif",
        rng.integers(0, 255, size=(3, 50, 60), dtype=np.uint8),
        crs="EPSG:4326",
        transform=Affine.translation(10.0, 45.0) @ Affine.scale(0.0001, -0.0001),
    )
    p_geo = inspect_tiff(geo_rgb)
    assert p_geo.crs_epsg == 4326
    assert p_geo.crs_is_geographic is True
    assert p_geo.gsd_meters is not None and 5.0 < p_geo.gsd_meters[0] < 15.0

    # (c) 4-band RGBA GeoTIFF
    rgba_arr = rng.integers(20, 240, size=(4, 40, 40), dtype=np.uint8)
    rgba_arr[3, :10, :10] = 0
    rgba_arr[3, 10:, :] = 255
    rgba_arr[3, :, 10:] = 255
    rgba_tif = _write_geotiff(
        tmp_path / "rgba.tif",
        rgba_arr,
        colorinterp=(ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha),
    )
    p_rgba = inspect_tiff(rgba_tif)
    assert p_rgba.alpha_band == 4
    assert p_rgba.non_alpha_bands == [1, 2, 3]
    assert p_rgba.detected_profile == "rgb-highres"
    assert p_rgba.valid_pixel_ratio == pytest.approx((1600 - 100) / 1600, abs=1e-4)

    # (d) 4-band RGBN GeoTIFF + NDVI/NDWI computation
    rgbn_arr = np.full((4, 32, 32), 1000, dtype=np.uint16)
    rgbn_arr[0] = 800   # Red
    rgbn_arr[1] = 900   # Green
    rgbn_arr[2] = 600   # Blue
    rgbn_arr[3] = 2400  # NIR
    rgbn_tif = _write_geotiff(
        tmp_path / "rgbn.tif",
        rgbn_arr,
        descriptions=("Red", "Green", "Blue", "NIR"),
    )
    p_rgbn = inspect_tiff(rgbn_tif)
    assert p_rgbn.alpha_band is None
    assert p_rgbn.detected_profile == "rgbn-aerial"
    assert p_rgbn.spectral_band_map["nir"] == 4
    with rasterio.open(rgbn_tif) as src:
        indices = compute_spectral_indices(src, p_rgbn.spectral_band_map)
    assert indices["ndvi"]["mean"] == pytest.approx((2400 - 800) / (2400 + 800), abs=1e-3)
    assert indices["ndwi"]["mean"] == pytest.approx((900 - 2400) / (900 + 2400), abs=1e-3)

    # (e) 9-band & 13-band Sentinel-2 GeoTIFFs
    s2_9 = _write_geotiff(
        tmp_path / "s2_9band.tif",
        rng.integers(300, 3000, size=(9, 32, 32), dtype=np.uint16),
        transform=Affine.translation(500000.0, 5000000.0) @ Affine.scale(10.0, -10.0),
        descriptions=("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12"),
    )
    p_s2_9 = inspect_tiff(s2_9)
    assert p_s2_9.detected_profile == "sentinel2-multispectral"
    assert p_s2_9.recommended_model == "s2-dw"
    assert p_s2_9.s2_bands == [1, 2, 3, 4, 5, 6, 7, 8, 9]

    s2_13 = _write_geotiff(
        tmp_path / "s2_13band_no_desc.tif",
        rng.integers(300, 3000, size=(13, 32, 32), dtype=np.uint16),
        transform=Affine.translation(500000.0, 5000000.0) @ Affine.scale(10.0, -10.0),
    )
    p_s2_13 = inspect_tiff(s2_13)
    assert p_s2_13.detected_profile == "sentinel2-multispectral"
    assert p_s2_13.recommended_model == "s2-dw"
    assert p_s2_13.s2_bands == [2, 3, 4, 5, 6, 7, 8, 12, 13]

    # (f) Plain non-georeferenced RGB TIFF
    plain_tif = _write_geotiff(
        tmp_path / "plain.tif",
        rng.integers(0, 255, size=(3, 48, 64), dtype=np.uint8),
        crs=None,
    )
    p_plain = inspect_tiff(plain_tif)
    assert p_plain.is_georeferenced is False
    assert p_plain.gsd_meters is None
    assert p_plain.total_area_m2 is None
    assert p_plain.detected_profile == "plain-rgb"
    assert p_plain.recommended_model == "rgb-oem"

    # (g) 1-band DEM GeoTIFF (unsupported)
    dem_tif = _write_geotiff(
        tmp_path / "dem.tif",
        rng.uniform(100.0, 500.0, size=(1, 32, 32)).astype(np.float32),
        nodata=-9999.0,
    )
    p_dem = inspect_tiff(dem_tif)
    assert p_dem.detected_profile == "single-band-unsupported"
    assert p_dem.recommended_model is None
    with pytest.raises(UnsupportedRasterError):
        select_model(p_dem, model_name="auto")


def test_geodesic_and_projected_area_accuracy(tmp_path: Path) -> None:
    # EPSG:4326 box area vs compute_row_pixel_areas_m2
    tr = Affine.translation(-74.0, 40.8) @ Affine.scale(0.0005, -0.0005)
    h, w = 100, 120
    tif_4326 = _write_geotiff(
        tmp_path / "geo.tif",
        np.ones((3, h, w), dtype=np.uint8),
        crs="EPSG:4326",
        transform=tr,
    )
    with rasterio.open(tif_4326) as src:
        row_areas = compute_row_pixel_areas_m2(src.crs, src.transform, h, w)
        assert row_areas is not None
        computed_total = float(np.sum(row_areas) * w)
        b = src.bounds
        geod = Geod(ellps="WGS84")
        poly_area, _ = geod.polygon_area_perimeter(
            [b.left, b.right, b.right, b.left],
            [b.top, b.top, b.bottom, b.bottom],
        )
        expected_total = abs(poly_area)
    assert computed_total == pytest.approx(expected_total, rel=1e-3)

    # Projected UTM exact area
    tr_utm = Affine.translation(500000.0, 5000000.0) @ Affine.scale(2.5, -2.5)
    tif_utm = _write_geotiff(
        tmp_path / "utm.tif",
        np.ones((3, h, w), dtype=np.uint8),
        crs="EPSG:32632",
        transform=tr_utm,
    )
    with rasterio.open(tif_utm) as src:
        row_areas_utm = compute_row_pixel_areas_m2(src.crs, src.transform, h, w)
        assert row_areas_utm is not None
        assert float(np.sum(row_areas_utm) * w) == pytest.approx(h * w * 2.5 * 2.5, rel=1e-9)


def test_tiled_inference_seams_tiny_nodata_and_outputs(tmp_path: Path) -> None:
    model = _SeamAwareMockRGBModel()

    # 1. Non-multiple raster (311x257) with nodata corners (nodata=0)
    data = np.full((3, 257, 311), 200, dtype=np.uint8)
    data[:, :, :150] = 50
    data[:, :20, :20] = 0  # nodata corner
    in_tif = _write_geotiff(
        tmp_path / "scene.tif",
        data,
        crs="EPSG:32632",
        transform=Affine.translation(500000.0, 5000000.0) @ Affine.scale(2.0, -2.0),
        nodata=0,
    )
    profile = inspect_tiff(in_tif)
    out_lulc = tmp_path / "out" / "scene_lulc.tif"
    out_conf = tmp_path / "out" / "scene_conf.tif"

    stats = run_tiled_inference(
        input_path=in_tif,
        profile=profile,
        model=model,
        band_indices=[1, 2, 3],
        preprocess_mode="rgb",
        output_lulc_path=out_lulc,
        output_conf_path=out_conf,
        tile_size=128,
        overlap=32,
        batch_size=2,
    )

    assert stats.class_pixels[2] == 0  # No halo seam leakage!
    assert stats.nodata_pixels == 400
    assert stats.valid_pixels == 257 * 311 - 400
    expected_valid_m2 = stats.valid_pixels * 4.0
    assert sum(stats.class_area_m2.values()) == pytest.approx(expected_valid_m2, rel=1e-6)

    with rasterio.open(out_lulc) as dst:
        assert dst.shape == (257, 311)
        assert dst.crs.to_epsg() == 32632
        assert dst.nodata == NODATA_VALUE
        cmap = dst.colormap(1)
        assert cmap[0][:3] == model.classes[0].color
        assert cmap[1][:3] == model.classes[1].color
        arr = dst.read(1)
        assert np.all(arr[:20, :20] == NODATA_VALUE)
        assert np.all(arr[20:, :150] == 0)
        assert np.all(arr[:, 150:] == 1)

    # Outputs: JSON, CSV, GeoJSON, PNG preview
    report = build_report(
        profile=profile,
        model=model,
        stats=stats,
        spectral_indices={},
        warnings_list=[],
        output_files={"lulc_geotiff": out_lulc, "confidence_geotiff": out_conf},
        params={"device": "cpu", "tile_size": 128, "overlap": 32, "batch_size": 2, "band_indices": [1, 2, 3], "preprocess_mode": "rgb"},
    )
    json_path = tmp_path / "out" / "scene_report.json"
    csv_path = tmp_path / "out" / "scene_summary.csv"
    geojson_path = tmp_path / "out" / "scene_lulc.geojson"
    preview_path = tmp_path / "out" / "scene_preview.png"

    write_json_report(report, json_path)
    write_csv_summary(report, csv_path)
    n_feats = export_vector_geojson(out_lulc, model.classes, geojson_path, min_area_pixels=4)
    render_preview_png(in_tif, out_lulc, profile, model, report, [1, 2, 3], preview_path)

    loaded_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded_json["lulc"]["dominant_class"] == "tree"
    assert loaded_json["geospatial"]["valid_area_m2"] == pytest.approx(expected_valid_m2, rel=1e-4)

    with csv_path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(model.classes)

    gj = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert gj["type"] == "FeatureCollection"
    assert n_feats == len(gj["features"]) >= 2
    for feat in gj["features"]:
        assert feat["properties"]["class_id"] != NODATA_VALUE
        assert feat["properties"]["area_m2"] > 0

    with Image.open(preview_path) as im:
        assert im.width > 100 and im.height > 100

    # 2. Tiny raster (40x30 < tile_size=64) with nodata corner
    tiny_data = np.full((3, 30, 40), 200, dtype=np.uint8)
    tiny_data[:, :5, :5] = 0
    tiny_tif = _write_geotiff(tmp_path / "tiny.tif", tiny_data, nodata=0)
    tiny_prof = inspect_tiff(tiny_tif)
    tiny_out = tmp_path / "tiny_lulc.tif"
    tiny_stats = run_tiled_inference(
        input_path=tiny_tif,
        profile=tiny_prof,
        model=model,
        band_indices=[1, 2, 3],
        preprocess_mode="rgb",
        output_lulc_path=tiny_out,
        tile_size=64,
        overlap=8,
        batch_size=1,
    )
    assert tiny_stats.valid_pixels == 30 * 40 - 25
    assert tiny_stats.class_pixels[2] == 0


def test_canonical_color_mapping_matches_verified_id2label() -> None:
    oem_labels = {
        0: "background",
        1: "bareland",
        2: "rangeland",
        3: "developed space",
        4: "road",
        5: "tree",
        6: "water",
        7: "agriculture land",
        8: "buildings",
    }
    dg_labels = {
        0: "urban_land",
        1: "agriculture_land",
        2: "rangeland",
        3: "forest_land",
        4: "water",
        5: "barren_land",
        6: "unknown",
    }
    oem_colors = [color_for_label(name, cid) for cid, name in oem_labels.items()]
    dg_colors = [color_for_label(name, cid) for cid, name in dg_labels.items()]
    assert len(set(oem_colors)) == len(oem_labels)
    assert len(set(dg_colors)) == len(dg_labels)


def test_cli_commands(tmp_path: Path) -> None:
    runner = CliRunner()

    res_models = runner.invoke(app, ["models"])
    assert res_models.exit_code == 0
    assert "rgb-oem" in res_models.stdout
    assert "rgb-fast" in res_models.stdout
    assert "s2-dw" in res_models.stdout
    assert "categorical" in res_models.stdout

    rgb_tif = _write_geotiff(
        tmp_path / "sample.tif",
        np.full((3, 32, 32), 120, dtype=np.uint8),
    )
    res_insp = runner.invoke(app, ["inspect", str(rgb_tif), "--json"])
    assert res_insp.exit_code == 0
    parsed = json.loads(res_insp.stdout)
    assert parsed["file_name"] == "sample.tif"
    assert parsed["recommended_model"] == "rgb-oem"

    dem_tif = _write_geotiff(
        tmp_path / "dem.tif",
        np.full((1, 32, 32), 250.0, dtype=np.float32),
    )
    res_dem = runner.invoke(app, ["map", str(dem_tif), "-o", str(tmp_path / "out")])
    assert res_dem.exit_code == 2


def test_categorical_classified_geotiff_pipeline(tmp_path: Path) -> None:
    arr = np.zeros((1, 80, 100), dtype=np.uint8)
    arr[0, 10:40, 20:60] = 1
    arr[0, 40:70, 20:80] = 2
    cat_tif = _write_geotiff(
        tmp_path / "boro_cat.tif",
        arr,
        crs="EPSG:32645",
        transform=Affine.translation(698500.0, 2780590.0) @ Affine.scale(10.0, -10.0),
        descriptions=("Boro_Class",),
    )

    prof = inspect_tiff(cat_tif)
    assert prof.detected_profile == "categorical-classified"
    assert prof.recommended_model == "categorical"
    assert prof.unique_values == [0, 1, 2]
    assert prof.zero_is_background is True

    runner = CliRunner()
    out_dir = tmp_path / "cat_out"
    res = runner.invoke(
        app,
        [
            "map",
            str(cat_tif),
            "-o",
            str(out_dir),
            "--name",
            "Custom_Boro",
            "--class-labels",
            "1:Water,2:Boro Rice",
            "--nodata-value",
            "0",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "Associated TIFF Details" in res.output
    assert "WGS84 Bounds" in res.output
    assert "EPSG:32645" in res.output

    lulc_p = out_dir / "Custom_Boro_lulc.tif"
    report_p = out_dir / "Custom_Boro_report.json"
    csv_p = out_dir / "Custom_Boro_summary.csv"
    png_p = out_dir / "Custom_Boro_preview.png"
    assert lulc_p.is_file() and report_p.is_file() and csv_p.is_file() and png_p.is_file()

    rep = json.loads(report_p.read_text(encoding="utf-8"))
    assert rep["inference"]["model"] == "categorical"
    assert rep["inference"]["device"] == "none (categorical)"
    assert rep["inference"]["nodata_pixels"] == 80 * 100 - (30 * 40 + 30 * 60)
    assert rep["inference"]["valid_pixels"] == 30 * 40 + 30 * 60
    by_id = {c["id"]: c for c in rep["lulc"]["classes"]}
    assert 0 not in by_id
    assert by_id[1]["name"] == "Water" and by_id[1]["pixels"] == 1200
    assert by_id[2]["name"] == "Boro Rice" and by_id[2]["pixels"] == 1800
    assert by_id[1]["mean_confidence"] is None

    with rasterio.open(lulc_p) as src:
        assert src.nodata == NODATA_VALUE
        assert src.colormap(1)[1][:3] != (0, 0, 0)

    with Image.open(png_p) as im:
        assert im.width > 500 and im.height > 300


def test_cartography_styles_composites_boundary_and_html(tmp_path: Path) -> None:
    from lulckit.cartography import (
        ARROW_STYLES,
        SCALEBAR_STYLES,
        resolve_composite_bands,
        resolve_palette_color,
    )

    runner = CliRunner()
    res_styles = runner.invoke(app, ["styles"])
    assert res_styles.exit_code == 0
    for token in ("compass", "classic", "arcgis-crop", "false-color-nir", "arcgis", "a4", "a5"):
        assert token in res_styles.stdout

    # Palettes including Matplotlib colormaps
    assert resolve_palette_color("arcgis-crop", 0) == (56, 168, 0)
    assert resolve_palette_color("arcgis-crop", 1) == (230, 0, 0)
    assert len(resolve_palette_color("viridis", 2, total=5)) == 3
    assert len(resolve_palette_color("colorblind", 1, total=5)) == 3

    # Composites on 9-band Sentinel-2 vs 3-band RGB error
    rng = np.random.default_rng(11)
    s2_9 = _write_geotiff(
        tmp_path / "s2.tif",
        rng.integers(200, 3000, size=(9, 32, 32), dtype=np.uint16),
        transform=Affine.translation(500000.0, 5000000.0) @ Affine.scale(10.0, -10.0),
        descriptions=("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12"),
    )
    p_s2 = inspect_tiff(s2_9)
    bands_cir, key_cir = resolve_composite_bands(p_s2, "false-color-nir")
    assert key_cir == "false-color-nir" and bands_cir == [7, 3, 2]
    bands_ag, key_ag = resolve_composite_bands(p_s2, "agriculture")
    assert key_ag == "agriculture" and bands_ag == [8, 7, 1]

    rgb_only = _write_geotiff(tmp_path / "rgb.tif", rng.integers(0, 255, size=(3, 32, 32), dtype=np.uint8))
    p_rgb = inspect_tiff(rgb_only)
    with pytest.raises(ValueError):
        resolve_composite_bands(p_rgb, "false-color-nir")

    # Categorical raster with boundary GeoJSON, PDF/SVG export, all arrow & scalebar styles, and HTML export
    arr = np.zeros((1, 60, 80), dtype=np.uint8)
    arr[0, 10:40, 15:45] = 1
    arr[0, 20:50, 35:65] = 2
    cat_tif = _write_geotiff(
        tmp_path / "cat.tif",
        arr,
        crs="EPSG:32645",
        transform=Affine.translation(698500.0, 2780590.0) @ Affine.scale(10.0, -10.0),
    )
    prof = inspect_tiff(cat_tif)
    w, s, e, n = prof.bounds_wgs84  # type: ignore[misc]
    boundary_gj = tmp_path / "aoi.geojson"
    boundary_gj.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "AOI"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    for a_style in ARROW_STYLES:
        out_dir = tmp_path / f"out_{a_style}"
        r = runner.invoke(
            app,
            [
                "map",
                str(cat_tif),
                "-o",
                str(out_dir),
                "--palette",
                "arcgis-crop",
                "--arrow-style",
                a_style,
                "--scalebar-style",
                "arcgis" if a_style == "compass" else "alternating",
                "--dpi",
                "100",
                "--boundary",
                str(boundary_gj),
                "--boundary-label",
                "District Boundary",
            ],
        )
        assert r.exit_code == 0, r.output
        assert (out_dir / "cat_preview.png").is_file()

    for sb_style in SCALEBAR_STYLES:
        out_dir = tmp_path / f"sb_{sb_style}"
        r = runner.invoke(
            app,
            ["map", str(cat_tif), "-o", str(out_dir), "--scalebar-style", sb_style, "--dpi", "100"],
        )
        assert r.exit_code == 0, r.output

    for fmt in ("pdf", "svg"):
        out_dir = tmp_path / f"fmt_{fmt}"
        r = runner.invoke(
            app,
            [
                "map",
                str(cat_tif),
                "-o",
                str(out_dir),
                "--map-format",
                fmt,
                "--html",
                "--boundary",
                str(boundary_gj),
                "--class-labels",
                "0:Non Boro,1:Early Boro,2:Late Boro",
            ],
        )
        assert r.exit_code == 0, r.output
        assert (out_dir / f"cat_preview.{fmt}").is_file()
        html_p = out_dir / "cat_map.html"
        assert html_p.is_file()
        html_txt = html_p.read_text(encoding="utf-8")
        assert "maplibregl" in html_txt
        assert "data:image/png;base64," in html_txt
        assert "Early Boro" in html_txt
        assert "Late Boro" in html_txt

    # Page size & orientation pixel dimensions check at 100 DPI
    for ps, ori, exp_w, exp_h in (
        ("a4", "portrait", 827, 1169),
        ("a5", "landscape", 827, 583),
        ("a3", "auto", 1654, 1169),
    ):
        out_dir = tmp_path / f"ps_{ps}_{ori}"
        r = runner.invoke(
            app,
            ["map", str(cat_tif), "-o", str(out_dir), "--page-size", ps, "--orientation", ori, "--dpi", "100"],
        )
        assert r.exit_code == 0, r.output
        with Image.open(out_dir / "cat_preview.png") as im:
            assert abs(im.width - exp_w) <= 3
            assert abs(im.height - exp_h) <= 3


def test_cli_help_panels() -> None:
    runner = CliRunner()
    res_root = runner.invoke(app, ["--help"])
    assert res_root.exit_code == 0
    for cmd in ("inspect", "bands", "clip", "map", "batch", "wizard", "models", "styles"):
        assert cmd in res_root.stdout

    res_map = runner.invoke(app, ["map", "--help"])
    assert res_map.exit_code == 0
    for panel in ("Model & Inference", "Bands & Styling", "Cartography & Page Layout", "Outputs & Export"):
        assert panel in res_map.stdout


def test_bands_clip_batch_and_wizard(tmp_path: Path) -> None:
    runner = CliRunner()
    rng = np.random.default_rng(19)

    # 1. `lulc bands` on a 9-band Sentinel-2 GeoTIFF
    s2_data = rng.integers(300, 2800, size=(9, 48, 64), dtype=np.uint16)
    s2_data[2] = 600   # B4 Red
    s2_data[6] = 3000  # B8 NIR
    s2_tif = _write_geotiff(
        tmp_path / "s2.tif",
        s2_data,
        crs="EPSG:32645",
        transform=Affine.translation(698500.0, 2780590.0) @ Affine.scale(10.0, -10.0),
        descriptions=("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12"),
    )

    r_info = runner.invoke(app, ["bands", str(s2_tif)])
    assert r_info.exit_code == 0, r_info.output
    assert "false-color-nir" in r_info.output
    assert "ndvi" in r_info.output

    r_json = runner.invoke(app, ["bands", str(s2_tif), "--json"])
    assert r_json.exit_code == 0
    b_json = json.loads(r_json.stdout)
    assert b_json["band_count"] == 9
    assert b_json["spectral_band_map"]["nir"] == 7

    # Composites & custom RGB & single-band exports
    cir_png = tmp_path / "b_out" / "cir.png"
    cir_tif = tmp_path / "b_out" / "cir.tif"
    assert runner.invoke(app, ["bands", str(s2_tif), "--composite", "false-color-nir", "--dpi", "100", "-o", str(cir_png)]).exit_code == 0
    assert cir_png.is_file()
    assert runner.invoke(app, ["bands", str(s2_tif), "--composite", "false-color-nir", "-o", str(cir_tif)]).exit_code == 0
    with rasterio.open(cir_tif) as src:
        assert src.count == 3 and src.dtypes[0] == "uint8"

    custom_png = tmp_path / "b_out" / "rgb321.png"
    assert runner.invoke(app, ["bands", str(s2_tif), "--rgb-bands", "3,2,1", "--dpi", "100", "-o", str(custom_png)]).exit_code == 0
    assert custom_png.is_file()

    b7_tif = tmp_path / "b_out" / "b7.tif"
    b7_png = tmp_path / "b_out" / "b7.png"
    assert runner.invoke(app, ["bands", str(s2_tif), "--band", "7", "--palette", "viridis", "--dpi", "100", "-o", str(b7_tif), "--preview-out", str(b7_png)]).exit_code == 0
    assert b7_tif.is_file() and b7_png.is_file()

    # All 5 spectral indices (NDVI + preview, NDWI, NDBI, SAVI, EVI)
    ndvi_tif = tmp_path / "b_out" / "ndvi.tif"
    ndvi_png = tmp_path / "b_out" / "ndvi.png"
    r_ndvi = runner.invoke(app, ["bands", str(s2_tif), "--index", "ndvi", "--dpi", "100", "-o", str(ndvi_tif), "--preview-out", str(ndvi_png)])
    assert r_ndvi.exit_code == 0, r_ndvi.output
    assert ndvi_tif.is_file() and ndvi_png.is_file()
    with rasterio.open(ndvi_tif) as src:
        assert src.dtypes[0] == "float32"
        vals = src.read(1)
        assert float(vals.mean()) == pytest.approx((3000 - 600) / (3000 + 600), abs=1e-3)

    for idx_name in ("ndwi", "ndbi", "savi", "evi"):
        idx_tif = tmp_path / "b_out" / f"{idx_name}.tif"
        assert runner.invoke(app, ["bands", str(s2_tif), "--index", idx_name, "-o", str(idx_tif)]).exit_code == 0
        assert idx_tif.is_file()

    # Unavailable index cleanly fails with exit code 2
    rgb_tif = _write_geotiff(tmp_path / "rgb_only.tif", rng.integers(0, 255, size=(3, 24, 24), dtype=np.uint8))
    assert runner.invoke(app, ["bands", str(rgb_tif), "--index", "ndvi"]).exit_code == 2

    # 2. `lulc clip` on categorical GeoTIFF with embedded colormap
    cat_arr = np.zeros((1, 80, 100), dtype=np.uint8)
    cat_arr[0, 10:70, 15:85] = 1
    cat_arr[0, 30:60, 40:70] = 2
    cat_tif = _write_geotiff(
        tmp_path / "cat_src.tif",
        cat_arr,
        crs="EPSG:32645",
        transform=Affine.translation(698500.0, 2780590.0) @ Affine.scale(10.0, -10.0),
    )
    with rasterio.open(cat_tif, "r+") as dst:
        dst.write_colormap(1, {0: (255, 255, 255, 255), 1: (56, 168, 0, 255), 2: (230, 0, 0, 255)})

    prof_cat = inspect_tiff(cat_tif)
    w, s, e, n = prof_cat.bounds_wgs84  # type: ignore[misc]
    dw, dh = (e - w) * 0.25, (n - s) * 0.25
    sub_gj = tmp_path / "sub_aoi.geojson"
    sub_gj.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[w + dw, s + dh], [e - dw, s + dh], [e - dw, n - dh], [w + dw, n - dh], [w + dw, s + dh]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    clipped_tif = tmp_path / "clipped.tif"
    r_clip = runner.invoke(app, ["clip", str(cat_tif), str(sub_gj), "-o", str(clipped_tif)])
    assert r_clip.exit_code == 0, r_clip.output
    with rasterio.open(clipped_tif) as src_c:
        assert src_c.crs.to_epsg() == 32645
        assert src_c.width < 100 and src_c.height < 80
        assert src_c.colormap(1)[1][:3] == (56, 168, 0)

    # 3. `lulc batch` with 2 valid categorical TIFFs + 1 unsupported DEM
    batch_in = tmp_path / "batch_in"
    batch_in.mkdir()
    _write_geotiff(batch_in / "a.tif", cat_arr, crs="EPSG:32645")
    _write_geotiff(batch_in / "b.tif", cat_arr, crs="EPSG:32645")
    _write_geotiff(batch_in / "dem.tif", np.full((1, 20, 20), 100.0, dtype=np.float32), crs="EPSG:32645")

    batch_out = tmp_path / "batch_out"
    r_batch = runner.invoke(app, ["batch", str(batch_in), "-o", str(batch_out), "--continue-on-error"])
    assert r_batch.exit_code == 0, r_batch.output
    assert (batch_out / "a" / "a_lulc.tif").is_file()
    assert (batch_out / "b" / "b_lulc.tif").is_file()
    assert not (batch_out / "dem" / "dem_lulc.tif").exists()

    # 4. `lulc wizard` interactive prompt flow
    wiz_out = tmp_path / "wiz_out"
    wiz_inputs = "\n".join(
        [
            "categorical",
            "arcgis-crop",
            "Wizard Test Map",
            "a5",
            "landscape",
            "classic",
            "alternating",
            "n",
            str(wiz_out),
        ]
    ) + "\n"
    r_wiz = runner.invoke(app, ["wizard", str(cat_tif)], input=wiz_inputs)
    assert r_wiz.exit_code == 0, r_wiz.output
    assert "Equivalent command:" in r_wiz.output
    assert "lulc map" in r_wiz.output
    assert (wiz_out / "cat_src_lulc.tif").is_file()
    assert (wiz_out / "cat_src_preview.png").is_file()


def test_spaces_handlers_and_pages_assets(tmp_path: Path) -> None:
    """Verify GitHub Pages assets exist and Spaces handlers run end-to-end offline."""
    import importlib.util
    import shutil
    import xml.etree.ElementTree as ET

    root = Path(__file__).resolve().parent.parent
    required = [
        root / "docs" / ".nojekyll",
        root / "docs" / "index.html",
        root / "docs" / "app.js",
        root / "docs" / "auth.js",
        root / "docs" / "styles.css",
        root / "firestore.rules",
        root / "docs" / "assets" / "logo.svg",
        root / "docs" / "assets" / "favicon.svg",
        root / "docs" / "assets" / "og-card.png",
        root / "docs" / "assets" / "lulckit-promo.mp4",
        root / "docs" / "assets" / "promo-poster.jpg",
        root / "docs" / "assets" / "lulckit-promo.vtt",
        root / "docs" / "robots.txt",
        root / "docs" / "sitemap.xml",
        root / "docs" / "site.webmanifest",
        root / "docs" / "llms.txt",
        root / ".github" / "workflows" / "pages.yml",
        root / "spaces" / "app.py",
        root / "spaces" / "requirements.txt",
        root / "spaces" / "README.md",
    ]
    for path in required:
        assert path.is_file(), f"Missing web/deploy file: {path}"
    for xml_path in (
        root / "docs" / "assets" / "logo.svg",
        root / "docs" / "assets" / "favicon.svg",
        root / "docs" / "sitemap.xml",
    ):
        ET.fromstring(xml_path.read_text(encoding="utf-8"))
    json.loads((root / "docs" / "site.webmanifest").read_text(encoding="utf-8"))

    spec = importlib.util.spec_from_file_location("lulckit_spaces_app", root / "spaces" / "app.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    arr = np.zeros((1, 48, 48), dtype=np.uint8)
    arr[0, 10:25, 10:25] = 1
    arr[0, 25:42, 20:40] = 2
    tif_path = _write_geotiff(tmp_path / "space_cat.tif", arr, crs="EPSG:32645")

    summary, profile_dict = mod.run_inspect_space(tif_path)
    assert "EPSG:32645" in summary
    assert profile_dict["detected_profile"] == "categorical-classified"

    prev_png, out_tif, out_csv, out_json, out_html, rows, report = mod.run_map_space(
        tif_path,
        model="categorical",
        title="Spaces Smoke Test",
        export_html=True,
    )
    try:
        assert prev_png and Path(prev_png).is_file()
        assert out_tif and Path(out_tif).is_file()
        assert out_csv and Path(out_csv).is_file()
        assert out_json and Path(out_json).is_file()
        assert out_html and Path(out_html).is_file()
        assert len(rows) == 3
        assert len(report["lulc"]["classes"]) == 3
    finally:
        if prev_png:
            shutil.rmtree(Path(prev_png).parent, ignore_errors=True)
