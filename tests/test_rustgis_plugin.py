"""Tests for the LULCkit RustGIS process plugin protocol, tools, and .rgplugin packager."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "rustgis_plugin"


def _call_plugin(request: dict[str, Any], answers: dict[str, Any] | None = None) -> tuple[Any, list[dict[str, Any]]]:
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
            proc.stdin.write(json.dumps({"ok": defaults.get(op)}) + "\n")
            proc.stdin.flush()
        elif "ok" in msg or "error" in msg:
            result = msg
            break

    proc.stdin.close()
    stderr_text = proc.stderr.read() if proc.stderr else ""
    code = proc.wait(timeout=60)
    assert code == 0, f"Plugin exited with {code}: {stderr_text}"
    assert result is not None, f"Plugin returned no result: {stderr_text}"
    assert "error" not in result, f"Plugin returned error: {result.get('error')}"
    return result["ok"], calls


def _write_test_rasters(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
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

    # 10m UTM EPSG:32645 bounds in WGS84 around (87.0 E, 24.4 N)
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
    return cat_path, ms_path, boundary_fc


def test_commands_models_and_about() -> None:
    res_models, calls_models = _call_plugin({"kind": "command", "id": "models-info"})
    assert any(c["op"] == "host.notify" for c in calls_models)
    assert any(m["name"] == "categorical" for m in res_models["models"])

    res_about, calls_about = _call_plugin({"kind": "command", "id": "about"})
    assert any(c["op"] == "host.notify" for c in calls_about)
    assert res_about["name"] == "LULCkit"
    assert res_about["license"] == "MIT"


def test_tools_end_to_end(tmp_path: Path) -> None:
    cat_path, ms_path, boundary_fc = _write_test_rasters(tmp_path)

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
    assert out_inspect["layers"][0]["geojson"]["features"][0]["geometry"]["type"] == "Polygon"

    # 2. lulc-map (categorical)
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
                "outputDir": str(map_out_dir),
            },
        }
    )
    assert (map_out_dir / "cat_lulc.tif").is_file()
    assert (map_out_dir / "cat_preview.png").is_file()
    assert (map_out_dir / "cat_summary.csv").is_file()
    assert (map_out_dir / "cat_report.json").is_file()
    assert (map_out_dir / "cat_lulc.geojson").is_file()
    assert len(out_map["tables"]) == 1
    assert len(out_map["tables"][0]["geojson"]["features"]) == 3
    assert len(out_map["layers"]) == 1

    # 3. spectral-index (ndvi)
    idx_out_dir = tmp_path / "idx_out"
    out_idx, _ = _call_plugin(
        {
            "kind": "tool",
            "id": "spectral-index",
            "params": {
                "input": str(ms_path),
                "mode": "index",
                "indexName": "ndvi",
                "outputDir": str(idx_out_dir),
            },
        }
    )
    assert (idx_out_dir / "ms_ndvi.tif").is_file()
    assert (idx_out_dir / "ms_ndvi_preview.png").is_file()
    assert len(out_idx["tables"]) == 1
    assert out_idx["tables"][0]["geojson"]["features"][0]["properties"]["index"] == "ndvi"

    # 4. clip-raster
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
    pkg1, json1, sha1 = mod.build_rustgis_package(output_dir=out1, tag="v0.1.0")
    pkg2, _, sha2 = mod.build_rustgis_package(output_dir=out2, tag="v0.1.0")

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
