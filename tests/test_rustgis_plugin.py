"""Tests for the LULCkit RustGIS process plugin protocol, tools, and .rgplugin packager."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "rustgis_plugin"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from lulckit.inspect import inspect_tiff  # noqa: E402


def _call_plugin(
    request: dict[str, Any],
    answers: dict[str, Any] | None = None,
    *,
    expect_error: bool = False,
) -> tuple[Any, list[dict[str, Any]]]:
    """Run ``rustgis_plugin/main.py`` over JSON-lines stdin/stdout like RustGIS does."""
    payload = {"abi": 1, "lang": "en", "params": {}, **request}
    proc = subprocess.Popen(
        [sys.executable, str(PLUGIN_DIR / "main.py")],
        cwd=PLUGIN_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()

    calls: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    defaults: dict[str, Any] = {"host.notify": None, **(answers or {})}

    for line in proc.stdout:
        msg = json.loads(line)
        if "call" in msg:
            call = msg["call"]
            calls.append(call)
            op = call["op"]
            ans = defaults.get(op)
            if isinstance(ans, Exception):
                proc.stdin.write(json.dumps({"error": str(ans)}) + "\n")
            else:
                proc.stdin.write(json.dumps({"ok": ans}) + "\n")
            proc.stdin.flush()
        elif "ok" in msg or "error" in msg:
            result = msg
            break

    proc.stdin.close()
    stderr_text = proc.stderr.read() if proc.stderr else ""
    code = proc.wait(timeout=60)
    assert code == 0, f"Plugin exited with {code}: {stderr_text}"
    assert result is not None, f"Plugin returned no result: {stderr_text}"
    if expect_error:
        assert "error" in result
        return result["error"], calls
    assert "error" not in result, f"Plugin returned error: {result.get('error')}"
    return result["ok"], calls


def _write_test_rasters(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    transform = from_origin(500000.0, 2700000.0, 10.0, 10.0)

    cat_path = tmp_path / "cat.tif"
    cat_arr = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [0, 0, 2, 2],
            [0, 0, 1, 1],
        ],
        dtype=np.uint8,
    )
    with rasterio.open(
        cat_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:32645",
        transform=transform,
    ) as dst:
        dst.write(cat_arr, 1)

    ms_path = tmp_path / "ms.tif"
    ms_arr = np.zeros((4, 4, 4), dtype=np.uint16)
    ms_arr[0] = 500   # Blue
    ms_arr[1] = 800   # Green
    ms_arr[2] = 600   # Red
    ms_arr[3] = 2400  # NIR
    with rasterio.open(
        ms_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=4,
        dtype="uint16",
        crs="EPSG:32645",
        transform=transform,
    ) as dst:
        for i, desc in enumerate(["B2", "B3", "B4", "B8"], start=1):
            dst.write(ms_arr[i - 1], i)
            dst.set_band_description(i, desc)

    ls_path = tmp_path / "LC09_L2SP_sample.tif"
    ls_arr = np.zeros((6, 4, 4), dtype=np.uint16)
    ls_arr[0] = 500   # SR_B2 (Blue)
    ls_arr[1] = 900   # SR_B3 (Green)
    ls_arr[2] = 700   # SR_B4 (Red)
    ls_arr[3] = 2600  # SR_B5 (NIR)
    ls_arr[4] = 1500  # SR_B6 (SWIR1)
    ls_arr[5] = 1100  # SR_B7 (SWIR2)
    with rasterio.open(
        ls_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=6,
        dtype="uint16",
        crs="EPSG:32645",
        transform=from_origin(500000.0, 2700000.0, 30.0, 30.0),
    ) as dst:
        for i, desc in enumerate(["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"], start=1):
            dst.write(ls_arr[i - 1], i)
            dst.set_band_description(i, desc)

    with rasterio.open(cat_path) as src:
        from rasterio.warp import transform_bounds

        w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    boundary_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "aoi"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
                },
            }
        ],
    }
    return cat_path, ms_path, ls_path, boundary_fc


def _write_s2_folder(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    t10 = from_origin(500000.0, 2700000.0, 10.0, 10.0)
    t20 = from_origin(500000.0, 2700000.0, 20.0, 20.0)

    for code, val in (("B02", 500), ("B03", 800), ("B04", 600), ("B08", 2500)):
        with rasterio.open(
            folder / f"T45QYG_{code}_10m.tif",
            "w",
            driver="GTiff",
            height=8,
            width=8,
            count=1,
            dtype="uint16",
            crs="EPSG:32645",
            transform=t10,
        ) as dst:
            dst.write(np.full((8, 8), val, dtype=np.uint16), 1)

    for code, val in (("B05", 1100), ("B06", 1800), ("B07", 2100), ("B11", 1600), ("B12", 1200)):
        with rasterio.open(
            folder / f"T45QYG_{code}_20m.tif",
            "w",
            driver="GTiff",
            height=4,
            width=4,
            count=1,
            dtype="uint16",
            crs="EPSG:32645",
            transform=t20,
        ) as dst:
            dst.write(np.full((4, 4), val, dtype=np.uint16), 1)

    scl = np.full((4, 4), 4, dtype=np.uint8)
    scl[0, 0] = 9  # Cloud high probability in top-left 20m cell (2x2 10m pixels)
    with rasterio.open(
        folder / "T45QYG_SCL_20m.tif",
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:32645",
        transform=t20,
    ) as dst:
        dst.write(scl, 1)

    return folder


def test_commands_models_about_and_map_hooks(tmp_path: Path) -> None:
    res_models, calls_models = _call_plugin({"kind": "command", "id": "models-info"})
    assert any(c["op"] == "host.notify" for c in calls_models)
    assert any(m["name"] == "categorical" for m in res_models["models"])
    assert any(idx["name"] == "nbr" for idx in res_models["indices"])
    assert any(idx["name"] == "mndwi" for idx in res_models["indices"])

    res_about, calls_about = _call_plugin({"kind": "command", "id": "about"})
    assert any(c["op"] == "host.notify" for c in calls_about)
    assert res_about["name"] == "LULCkit"
    assert res_about["version"] == "0.3.0"

    cat_path, _, _, _ = _write_test_rasters(tmp_path)
    res_load, calls_load = _call_plugin(
        {"kind": "command", "id": "load-output-raster", "params": {"path": str(cat_path), "name": "Cat"}},
        answers={"layer.addData": {"layer": "Cat"}},
    )
    assert res_load["loaded"] is True
    assert any(c["op"] == "layer.addData" and c["params"]["name"] == "Cat" for c in calls_load)

    res_inspect_active, _ = _call_plugin(
        {"kind": "command", "id": "inspect-active-raster", "params": {"layer": "Cat"}},
        answers={"raster.info": {"name": "Cat", "source": str(cat_path)}},
    )
    assert res_inspect_active["found"] is True
    assert res_inspect_active["profile"]["recommended_model"] == "categorical"

    res_no_raster, _ = _call_plugin(
        {"kind": "command", "id": "inspect-active-raster"},
        answers={"raster.info": RuntimeError("no raster layer")},
    )
    assert res_no_raster["found"] is False


def test_tools_end_to_end_and_v02_features(tmp_path: Path) -> None:
    cat_path, ms_path, ls_path, boundary_fc = _write_test_rasters(tmp_path)

    # Landsat 6-band fingerprinting
    ls_prof = inspect_tiff(ls_path)
    assert ls_prof.detected_profile == "landsat-multispectral"
    assert set(("blue", "green", "red", "nir", "swir1", "swir2")) <= set(ls_prof.spectral_band_map)

    # 1. inspect-geotiff
    inspect_json = tmp_path / "inspect.json"
    out_inspect, _ = _call_plugin(
        {
            "kind": "tool",
            "id": "inspect-geotiff",
            "params": {"input": str(cat_path), "outputJson": str(inspect_json)},
        }
    )
    assert inspect_json.is_file()
    assert len(out_inspect["tables"]) == 2
    assert len(out_inspect["layers"]) == 1

    # 2. lulc-map (categorical) -> verify .aux.xml <CategoryNames> and optional confidence
    map_out_dir = tmp_path / "map_out"
    out_map, _ = _call_plugin(
        {
            "kind": "tool",
            "id": "lulc-map",
            "params": {
                "input": str(cat_path),
                "model": "categorical",
                "palette": "arcgis-crop",
                "classLabels": "0:Non Boro,1:Early Boro,2:Late Boro",
                "vectorOut": True,
                "saveConfidence": True,
                "minAreaPixels": 1,
                "outputDir": str(map_out_dir),
            },
        }
    )
    lulc_tif = map_out_dir / "cat_lulc.tif"
    aux_xml = Path(f"{lulc_tif}.aux.xml")
    assert lulc_tif.is_file()
    assert aux_xml.is_file()
    root = ET.fromstring(aux_xml.read_text(encoding="utf-8"))
    cats = [el.text for el in root.findall(".//CategoryNames/Category")]
    assert cats == ["Non Boro", "Early Boro", "Late Boro"]
    assert (map_out_dir / "cat_confidence.tif").is_file()
    assert (map_out_dir / "cat_preview.png").is_file()
    assert (map_out_dir / "cat_summary.csv").is_file()
    assert (map_out_dir / "cat_report.json").is_file()
    assert (map_out_dir / "cat_lulc.geojson").is_file()
    assert len(out_map["tables"][0]["geojson"]["features"]) == 3

    # 3. export-bands: subset-stack, split-bands, visual-rgb
    subset_tif = tmp_path / "subset.tif"
    _call_plugin(
        {
            "kind": "tool",
            "id": "export-bands",
            "params": {
                "input": str(ms_path),
                "mode": "subset-stack",
                "bands": "B4,B3,B2,B8",
                "outputPath": str(subset_tif),
            },
        }
    )
    with rasterio.open(subset_tif) as src:
        assert src.count == 4
        assert list(src.descriptions) == ["B4", "B3", "B2", "B8"]
        assert src.tags(1).get("CENTRAL_WAVELENGTH_UM") == "0.665"
        assert src.tags(4).get("CENTRAL_WAVELENGTH_UM") == "0.842"

    split_dir = tmp_path / "split_out"
    out_split, _ = _call_plugin(
        {
            "kind": "tool",
            "id": "export-bands",
            "params": {
                "input": str(ms_path),
                "mode": "split-bands",
                "outputPath": str(split_dir),
            },
        }
    )
    assert len(list(split_dir.glob("*.tif"))) == 4
    assert len(out_split["tables"][0]["geojson"]["features"]) == 4

    vis_tif = tmp_path / "visual_rgb.tif"
    _call_plugin(
        {
            "kind": "tool",
            "id": "export-bands",
            "params": {
                "input": str(ms_path),
                "mode": "visual-rgb",
                "composite": "true-color",
                "outputPath": str(vis_tif),
            },
        }
    )
    with rasterio.open(vis_tif) as src:
        assert src.count == 4
        assert src.dtypes[0] == "uint8"

    # 4. stack-bands: S2 folder with mixed 10m/20m bands + SCL cloud mask
    s2_folder = _write_s2_folder(tmp_path / "s2_scene")
    s2_stack = tmp_path / "s2_stack.tif"
    out_stack, _ = _call_plugin(
        {
            "kind": "tool",
            "id": "stack-bands",
            "params": {
                "inputFolder": str(s2_folder),
                "sensor": "auto",
                "cloudMask": True,
                "outputPath": str(s2_stack),
            },
        }
    )
    assert s2_stack.is_file()
    stack_prof = inspect_tiff(s2_stack)
    assert stack_prof.detected_profile == "sentinel2-multispectral"
    assert stack_prof.recommended_model == "s2-dw"
    assert out_stack["tables"][0]["geojson"]["features"][0]["properties"]["cloud_masked"] is True
    with rasterio.open(s2_stack) as src:
        assert src.count == 9
        assert src.width == 8 and src.height == 8
        b1 = src.read(1)
        assert b1[0, 0] == 0  # Masked by SCL=9

    # 5. spectral-index (ndvi + nbr + mndwi)
    idx_out_dir = tmp_path / "idx_out"
    for idx_name in ("nbr", "mndwi"):
        out_idx, _ = _call_plugin(
            {
                "kind": "tool",
                "id": "spectral-index",
                "params": {
                    "input": str(ls_path),
                    "mode": "index",
                    "indexName": idx_name,
                    "outputDir": str(idx_out_dir),
                },
            }
        )
        assert (idx_out_dir / f"LC09_L2SP_sample_{idx_name}.tif").is_file()
        assert out_idx["tables"][0]["geojson"]["features"][0]["properties"]["index"] == idx_name

    # 6. clip-raster
    clipped_path = tmp_path / "clipped.tif"
    out_clip, _ = _call_plugin(
        {
            "kind": "tool",
            "id": "clip-raster",
            "params": {
                "input": str(cat_path),
                "boundary": "AOI",
                "crop": True,
                "outputPath": str(clipped_path),
            },
            "layers": {"AOI": boundary_fc},
        }
    )
    assert clipped_path.is_file()
    assert len(out_clip["tables"]) == 1


def test_package_builder_deterministic_and_clean(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("build_rustgis_plugin", ROOT / "scripts" / "build_rustgis_plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out1 = tmp_path / "b1"
    out2 = tmp_path / "b2"
    pkg1, json1, sha1 = mod.build_rustgis_package(output_dir=out1, tag="v0.3.0")
    pkg2, _, sha2 = mod.build_rustgis_package(output_dir=out2, tag="v0.3.0")

    assert sha1 == sha2
    assert pkg1.is_file() and pkg2.is_file()

    entry = json.loads(json1.read_text(encoding="utf-8"))
    assert entry["id"] == "lulckit"
    assert entry["source"]["sha256"] == sha1
    assert entry["categories"] == ["Raster", "Imagery", "Analysis", "Cartography"]

    with zipfile.ZipFile(pkg1) as zf:
        names = set(zf.namelist())
        assert {"plugin.json", "main.py", "rustgis_plugin.py", "requirements.txt", "lulckit/__init__.py"} <= names
        assert "lulckit/cli.py" not in names
        assert "lulckit/__main__.py" not in names
        assert not any("__pycache__" in n for n in names)
