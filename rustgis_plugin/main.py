"""RustGIS process plugin entrypoint for LULCkit."""

from __future__ import annotations

import json
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

# Support both packaged layout (lulckit/ beside main.py) and repo-checkout development.
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))
_REPO_SRC = _PLUGIN_DIR.parent / "src"
if not (_PLUGIN_DIR / "lulckit").is_dir() and _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

import rasterio  # noqa: E402
from rasterio.errors import NotGeoreferencedWarning  # noqa: E402
from rustgis_plugin import PluginError, Request, ToolOutput, geojson, host, serve  # noqa: E402

from lulckit import __version__  # noqa: E402
from lulckit.bands import (  # noqa: E402
    clip_raster_to_geojson,
    export_band_subset,
    export_band_view,
    export_spectral_index,
    export_visual_rgb_cog,
    list_spectral_indices,
    split_bands_to_folder,
    stack_band_folder,
)
from lulckit.cartography import (  # noqa: E402
    export_interactive_html,
    list_composites,
    list_palettes,
    resolve_composite_bands,
)
from lulckit.geo import compute_spectral_indices  # noqa: E402
from lulckit.inspect import TiffProfile, inspect_tiff  # noqa: E402
from lulckit.models.router import list_models, resolve_device, select_model  # noqa: E402
from lulckit.outputs import (  # noqa: E402
    build_report,
    export_vector_geojson,
    render_preview_png,
    write_csv_summary,
    write_json_report,
)
from lulckit.tiling import run_tiled_inference  # noqa: E402

MAX_VECTOR_LAYER_FEATURES = 100_000
LAST_OUTPUT_STATE = Path.home() / ".cache" / "lulckit" / "rustgis_last_output.json"


def _record_last_output(path: Path, kind: str) -> None:
    try:
        LAST_OUTPUT_STATE.parent.mkdir(parents=True, exist_ok=True)
        LAST_OUTPUT_STATE.write_text(
            json.dumps({"path": str(path.resolve()), "kind": kind}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _read_last_output() -> Path | None:
    try:
        if not LAST_OUTPUT_STATE.is_file():
            return None
        data = json.loads(LAST_OUTPUT_STATE.read_text(encoding="utf-8"))
        raw = str(data.get("path") or "").strip()
        if raw:
            p = Path(raw)
            if p.is_file():
                return p
    except (OSError, ValueError):
        pass
    return None


def _resolve_input_path(req: Request, param: str) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Resolve a `file` parameter (mode='path' on desktop/CLI, with base64 fallback)."""
    raw = str(req.params.get(param) or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate, None

    if param in req.files:
        name, data = req.file(param)
        tmpdir = tempfile.TemporaryDirectory(prefix="lulckit_in_")
        safe_name = Path(name).name or "input.tif"
        tmp_path = Path(tmpdir.name) / safe_name
        tmp_path.write_bytes(data)
        return tmp_path, tmpdir

    raise ValueError(f"Input GeoTIFF not found for '{param}': {raw!r}")


def _write_layer_to_geojson(features: list[dict[str, Any]], dest: Path) -> Path:
    """Write a RustGIS layer FeatureCollection to a GeoJSON file."""
    if not features:
        raise ValueError("Boundary layer contains no features.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(geojson.collection(features)), encoding="utf-8")
    return dest


def _parse_class_labels(raw: str | None) -> dict[int, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    out: dict[int, str] = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"classLabels entries must be id:Label, got {item!r}")
        k_str, v_str = item.split(":", 1)
        out[int(k_str.strip())] = v_str.strip()
    return out or None


def _parse_class_colors(raw: str | None) -> dict[int, tuple[int, int, int]] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    out: dict[int, tuple[int, int, int]] = {}
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"classColors entries must be id:#RRGGBB, got {item!r}")
        k_str, hex_str = item.split(":", 1)
        h = hex_str.strip().lstrip("#")
        if len(h) != 6:
            raise ValueError(f"Hex color must be #RRGGBB, got {hex_str!r}")
        out[int(k_str.strip())] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return out or None


def _parse_band_list(raw: str | None, expected_len: int | None = None) -> list[int]:
    text = str(raw or "").strip()
    if not text:
        if expected_len is not None:
            raise ValueError(f"Expected {expected_len} comma-separated band indices, got empty text.")
        return []
    vals = [int(tok.strip()) for tok in text.split(",") if tok.strip()]
    if expected_len is not None and len(vals) != expected_len:
        raise ValueError(f"Expected {expected_len} band indices, got {len(vals)}: {vals}")
    return vals


def _resolve_band_tokens(raw: str | None, profile: TiffProfile) -> list[int]:
    """Resolve comma-separated 1-based band indices or band names/roles (e.g. '4,3,2' or 'B4,B3,B2')."""
    text = str(raw or "").strip()
    if not text:
        return []

    role_map = {k.lower(): v for k, v in (profile.spectral_band_map or {}).items()}
    desc_map: dict[str, int] = {}
    for b in profile.bands:
        if b.description:
            desc_map[b.description.strip().lower()] = b.index
    for b in profile.bands:
        desc_map.setdefault(f"b{b.index}", b.index)
        desc_map.setdefault(f"band_{b.index}", b.index)

    out: list[int] = []
    for tok in text.split(","):
        t = tok.strip()
        if not t:
            continue
        if t.isdigit():
            idx = int(t)
        else:
            key = t.lower()
            idx = role_map.get(key) or desc_map.get(key) or 0
            if idx == 0 and key.startswith("b0") and len(key) >= 3 and key[2:].isdigit():
                idx = desc_map.get(f"b{int(key[2:])}", 0)
            if idx == 0:
                raise ValueError(f"Unknown band name or index: {t!r}")
        if idx < 1 or idx > profile.band_count:
            raise ValueError(f"Band index {idx} out of range [1..{profile.band_count}]")
        out.append(idx)
    return out


def _resolve_output_dir(raw_dir: str | None, input_path: Path) -> Path:
    text = str(raw_dir or "").strip()
    out_dir = Path(text).expanduser() if text else (input_path.parent / f"{input_path.stem}_lulckit")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _cmd_models_info(_req: Request) -> dict[str, Any]:
    models = list_models()
    palettes = list_palettes()
    indices = list_spectral_indices()
    composites = list_composites()

    model_names = ", ".join(m["name"] for m in models)
    index_names = ", ".join(idx["name"] for idx in indices)
    host.notify(f"LULCkit v{__version__} | Models: {model_names} | Indices: {index_names}")
    return {
        "version": __version__,
        "models": models,
        "palettes": palettes,
        "indices": indices,
        "composites": composites,
    }


def _cmd_about(_req: Request) -> dict[str, str]:
    msg = f"LULCkit v{__version__} (MIT License) — https://github.com/madeshchkma/LULCkit"
    host.notify(msg)
    return {
        "name": "LULCkit",
        "version": __version__,
        "license": "MIT",
        "homepage": "https://github.com/madeshchkma/LULCkit",
        "docs": "https://madeshchkma.github.io/LULCkit/",
    }


def _cmd_load_output_raster(req: Request) -> dict[str, Any]:
    raw_path = str(req.params.get("path") or "").strip()
    layer_name = str(req.params.get("name") or "").strip()

    if raw_path:
        target = Path(raw_path).expanduser()
        if not target.is_file():
            raise ValueError(f"GeoTIFF file not found: {target}")
    else:
        last = _read_last_output()
        if last is None:
            msg = "No previous LULCkit output GeoTIFF found. Run a LULCkit tool or specify a GeoTIFF path."
            host.notify(msg)
            return {"loaded": False, "report": msg}
        target = last

    add_params: dict[str, Any] = {"path": str(target.resolve())}
    if layer_name:
        add_params["name"] = layer_name
    added = host.run("layer.addData", add_params)
    shown_name = layer_name or target.stem
    host.notify(f"Loaded {target.name} into RustGIS")
    return {
        "loaded": True,
        "path": str(target.resolve()),
        "name": shown_name,
        "result": added,
        "report": f"Loaded **{target.name}** (`{target.resolve()}`) into the current map.",
    }


def _cmd_inspect_active_raster(req: Request) -> dict[str, Any]:
    layer = str(req.params.get("layer") or "").strip()
    call_params = {"layer": layer} if layer else {}
    try:
        info = host.run("raster.info", call_params)
    except PluginError as exc:
        msg = f"No active raster layer found in the current map ({exc})."
        host.notify(msg)
        return {"found": False, "report": msg}

    if not isinstance(info, dict):
        msg = "No raster metadata returned by RustGIS."
        host.notify(msg)
        return {"found": False, "report": msg}

    src_raw = str(info.get("source") or info.get("path") or "").strip()
    src_path = Path(src_raw).expanduser() if src_raw else None
    if src_path is not None and src_path.is_file():
        profile = inspect_tiff(src_path)
        crs_label = f"EPSG:{profile.crs_epsg}" if profile.crs_epsg else (profile.crs_name or "Unreferenced")
        gsd_label = (
            f"{profile.gsd_meters[0]:.2f}x{profile.gsd_meters[1]:.2f} m"
            if profile.gsd_meters
            else "N/A"
        )
        summary = (
            f"{profile.file_name}: {profile.width}x{profile.height} px, {profile.band_count} band(s), "
            f"{crs_label}, profile={profile.detected_profile}, model={profile.recommended_model or 'none'}"
        )
        host.notify(summary)
        report = "\n".join(
            [
                f"### {profile.file_name}",
                f"- **Dimensions:** {profile.width} × {profile.height} px ({profile.band_count} bands)",
                f"- **CRS / GSD:** {crs_label} / {gsd_label}",
                f"- **Detected Sensor Profile:** `{profile.detected_profile}`",
                f"- **Recommended Model:** `{profile.recommended_model or 'none'}`",
                f"- **Path:** `{src_path.resolve()}`",
            ]
        )
        return {"found": True, "profile": profile.to_dict(), "report": report}

    name = str(info.get("name") or layer or "Active raster")
    host.notify(f"Raster info for {name} (source file not on local disk)")
    return {"found": True, "raster_info": info, "report": json.dumps(info, indent=2)}


def _tool_inspect_geotiff(req: Request) -> ToolOutput:
    input_path, tmpdir = _resolve_input_path(req, "input")
    try:
        host.progress(f"Inspecting {input_path.name}...")
        profile = inspect_tiff(input_path)
        pdict = profile.to_dict()

        out_json_raw = str(req.params.get("outputJson") or "").strip()
        saved_json: Path | None = None
        if out_json_raw:
            saved_json = Path(out_json_raw).expanduser()
            write_json_report(pdict, saved_json)

        stem = input_path.stem
        crs_label = f"EPSG:{profile.crs_epsg}" if profile.crs_epsg else (profile.crs_name or "Unreferenced")
        gsd_label = (
            f"{profile.gsd_meters[0]:.2f}x{profile.gsd_meters[1]:.2f} m"
            if profile.gsd_meters
            else "N/A"
        )

        profile_row = {
            "file_name": profile.file_name,
            "width": profile.width,
            "height": profile.height,
            "band_count": profile.band_count,
            "crs": crs_label,
            "gsd_m": gsd_label,
            "detected_profile": profile.detected_profile,
            "recommended_model": profile.recommended_model or "none",
            "compression": profile.compression or "none",
            "is_cog_like": profile.is_cog_like,
            "nodata": "" if profile.nodata is None else str(profile.nodata),
            "file_size_bytes": profile.file_size_bytes,
        }
        band_features = [
            geojson.feature(
                None,
                {
                    "index": b.index,
                    "description": b.description or "",
                    "colorinterp": b.colorinterp,
                    "dtype": b.dtype,
                    "min": b.min,
                    "max": b.max,
                    "mean": round(b.mean, 4) if b.mean is not None else None,
                    "std": round(b.std, 4) if b.std is not None else None,
                    "valid_ratio": round(b.valid_ratio, 4),
                },
            )
            for b in profile.bands
        ]

        out = (
            ToolOutput()
            .table(f"{stem} Profile", geojson.collection([geojson.feature(None, profile_row)]))
            .table(f"{stem} Bands", geojson.collection(band_features))
            .message(
                f"{profile.file_name}: {profile.width}x{profile.height} px, {profile.band_count} band(s), "
                f"CRS={crs_label}, GSD={gsd_label}"
            )
            .message(
                f"Detected profile: {profile.detected_profile} "
                f"(recommended model: {profile.recommended_model or 'none'})"
            )
        )

        if profile.bounds_wgs84 and len(profile.bounds_wgs84) == 4:
            w, s, e, n = profile.bounds_wgs84
            footprint = geojson.polygon([[w, s], [e, s], [e, n], [w, n]])
            out.layer(
                f"{stem} Footprint",
                geojson.collection(
                    [geojson.feature(footprint, {"name": stem, "crs": crs_label, "profile": profile.detected_profile})]
                ),
            )

        if saved_json is not None:
            out.message(f"Saved JSON report: {saved_json}")
        return out
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()


def _tool_lulc_map(req: Request) -> ToolOutput:
    input_path, tmpdir = _resolve_input_path(req, "input")
    try:
        host.progress(f"Profiling {input_path.name}...")
        profile = inspect_tiff(input_path)

        model_name = str(req.params.get("model") or "auto")
        palette = str(req.params.get("palette") or "default")
        title_raw = str(req.params.get("title") or "").strip()
        rgb_bands = _parse_band_list(req.params.get("rgbBands"), 3) if str(req.params.get("rgbBands") or "").strip() else None
        s2_bands = _parse_band_list(req.params.get("s2Bands"), 9) if str(req.params.get("s2Bands") or "").strip() else None
        hf_model = str(req.params.get("hfModel") or "").strip() or None
        labels_map = _parse_class_labels(req.params.get("classLabels"))
        colors_map = _parse_class_colors(req.params.get("classColors"))
        page_size = str(req.params.get("pageSize") or "a4")
        orientation = str(req.params.get("orientation") or "auto")
        arrow_style = str(req.params.get("arrowStyle") or "compass")
        scalebar_style = str(req.params.get("scalebarStyle") or "arcgis")
        show_grid = bool(req.params.get("showGrid", True))
        vector_out = bool(req.params.get("vectorOut", True))
        min_area_pixels = max(1, int(req.params.get("minAreaPixels") or 4))
        save_confidence = bool(req.params.get("saveConfidence", False))
        html_out = bool(req.params.get("htmlOut", False))
        device = str(req.params.get("device") or "auto")

        out_dir = _resolve_output_dir(req.params.get("outputDir"), input_path)
        stem = input_path.stem
        map_title = title_raw or stem

        boundary_name = str(req.params.get("boundary") or "").strip()
        boundary_tmp: tempfile.TemporaryDirectory[str] | None = None
        boundary_path: Path | None = None
        if boundary_name:
            boundary_tmp = tempfile.TemporaryDirectory(prefix="lulckit_bnd_")
            boundary_path = _write_layer_to_geojson(
                req.features("boundary"),
                Path(boundary_tmp.name) / "boundary.geojson",
            )

        try:
            lulc_model, band_indices, preprocess_mode, warnings_list = select_model(
                profile=profile,
                model_name=model_name,
                device=device,
                rgb_bands=rgb_bands,
                s2_bands=s2_bands,
                hf_model=hf_model,
                class_labels=labels_map,
                class_colors=colors_map,
                palette=palette,
            )

            lulc_tif_path = out_dir / f"{stem}_lulc.tif"
            conf_tif_path = (out_dir / f"{stem}_confidence.tif") if save_confidence else None
            json_path = out_dir / f"{stem}_report.json"
            csv_path = out_dir / f"{stem}_summary.csv"
            preview_path = out_dir / f"{stem}_preview.png"
            geojson_path = (out_dir / f"{stem}_lulc.geojson") if vector_out else None
            html_path = (out_dir / f"{stem}_map.html") if html_out else None

            def _on_progress(done: int, total: int) -> None:
                host.progress(f"Processing tile {done}/{total}")

            stats = run_tiled_inference(
                input_path=input_path,
                profile=profile,
                model=lulc_model,
                band_indices=band_indices,
                preprocess_mode=preprocess_mode,
                output_lulc_path=lulc_tif_path,
                output_conf_path=conf_tif_path,
                progress_callback=_on_progress,
            )

            spectral_indices: dict[str, Any] = {}
            if profile.spectral_band_map:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", NotGeoreferencedWarning)
                    with rasterio.open(input_path) as src:
                        spectral_indices = compute_spectral_indices(src, profile.spectral_band_map)

            if geojson_path is not None:
                host.progress("Vectorizing LULC classes to GeoJSON...")
                export_vector_geojson(
                    lulc_tif_path=lulc_tif_path,
                    classes=lulc_model.classes,
                    output_path=geojson_path,
                    min_area_pixels=min_area_pixels,
                )

            output_files: dict[str, Path | None] = {
                "lulc_geotiff": lulc_tif_path,
                "confidence_geotiff": conf_tif_path,
                "report_json": json_path,
                "summary_csv": csv_path,
                "vector_geojson": geojson_path,
                "preview_png": preview_path,
            }
            params = {
                "device": "none (categorical)" if preprocess_mode == "categorical" else resolve_device(device),
                "tile_size": 512,
                "overlap": 0 if preprocess_mode == "categorical" else 64,
                "batch_size": 1 if preprocess_mode == "categorical" else 4,
                "band_indices": band_indices,
                "preprocess_mode": preprocess_mode,
                "display_name": stem,
                "title": map_title,
                "palette": palette,
                "page_size": page_size,
                "orientation": orientation,
            }
            report = build_report(
                profile=profile,
                model=lulc_model,
                stats=stats,
                spectral_indices=spectral_indices,
                warnings_list=warnings_list,
                output_files=output_files,
                params=params,
            )

            if html_path is not None:
                written_html = export_interactive_html(
                    lulc_tif_path=lulc_tif_path,
                    profile=profile,
                    model=lulc_model,
                    report=report,
                    output_path=html_path,
                    title=map_title,
                    boundary_path=boundary_path,
                )
                if written_html is not None:
                    report["output_files"]["interactive_html"] = str(written_html)

            write_json_report(report, json_path)
            write_csv_summary(report, csv_path)

            host.progress("Rendering cartographic print map...")
            preview_rgb = rgb_bands or profile.rgb_bands or (band_indices[:3] if len(band_indices) >= 3 else [1, 1, 1])
            render_preview_png(
                input_path=input_path,
                lulc_tif_path=lulc_tif_path,
                profile=profile,
                model=lulc_model,
                report=report,
                rgb_bands=preview_rgb,
                output_path=preview_path,
                preprocess_mode=preprocess_mode,
                display_name=stem,
                title=map_title,
                arrow_style=arrow_style,
                scalebar_style=scalebar_style,
                show_grid=show_grid,
                boundary_path=boundary_path,
                page_size=page_size,
                orientation=orientation,
            )

            _record_last_output(lulc_tif_path, "lulc-map")

            class_features = [
                geojson.feature(
                    None,
                    {
                        "class_id": row["id"],
                        "class_name": row["name"],
                        "hex": row["hex"],
                        "pixels": row["pixels"],
                        "percent": row["percent"],
                        "area_ha": row["area_ha"],
                        "area_km2": row["area_km2"],
                        "mean_confidence": row["mean_confidence"],
                    },
                )
                for row in report["lulc"]["classes"]
            ]

            out = (
                ToolOutput()
                .table(f"{stem} LULC Summary", geojson.collection(class_features))
                .message(f"Model: {lulc_model.name} | Dominant class: {report['lulc']['dominant_class'] or 'N/A'}")
                .message(f"LULC GeoTIFF (COG + .aux.xml): {lulc_tif_path}")
                .message(f"Print map: {preview_path}")
                .message(f"Summary CSV: {csv_path} | Report JSON: {json_path}")
            )
            if conf_tif_path is not None and conf_tif_path.is_file():
                out.message(f"Confidence GeoTIFF: {conf_tif_path}")

            if geojson_path is not None and geojson_path.is_file():
                fc = json.loads(geojson_path.read_text(encoding="utf-8"))
                n_feats = len(fc.get("features") or [])
                if n_feats <= MAX_VECTOR_LAYER_FEATURES:
                    out.layer(f"{stem} LULC", fc)
                else:
                    out.message(
                        f"Vector GeoJSON has {n_feats:,} features (saved to {geojson_path}, skipped in-map layer load)."
                    )
                out.message(f"Vector GeoJSON: {geojson_path}")

            if html_path is not None and html_path.is_file():
                out.message(f"Interactive HTML map: {html_path}")

            return out
        finally:
            if boundary_tmp is not None:
                boundary_tmp.cleanup()
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()


def _tool_export_bands(req: Request) -> ToolOutput:
    input_path, tmpdir = _resolve_input_path(req, "input")
    try:
        host.progress(f"Profiling {input_path.name}...")
        profile = inspect_tiff(input_path)
        mode = str(req.params.get("mode") or "subset-stack").strip().lower()
        bands_raw = str(req.params.get("bands") or "").strip()
        composite = str(req.params.get("composite") or "auto").strip().lower()
        out_raw = str(req.params.get("outputPath") or "").strip()
        stem = input_path.stem

        if bands_raw:
            selected = _resolve_band_tokens(bands_raw, profile)
        elif composite != "auto":
            selected, _ = resolve_composite_bands(profile, composite)
        elif mode == "visual-rgb":
            selected = list(profile.rgb_bands or (profile.non_alpha_bands[:3]))
        else:
            selected = list(profile.non_alpha_bands or range(1, profile.band_count + 1))

        if mode == "subset-stack":
            out_tif = Path(out_raw).expanduser() if out_raw else (input_path.parent / f"{stem}_bands.tif")
            host.progress(f"Exporting {len(selected)} band(s) to COG...")
            info = export_band_subset(input_path, profile, selected, out_tif, cog=True)
            _record_last_output(out_tif, "export-bands")
            row = {
                "mode": mode,
                "band_count": info["band_count"],
                "bands": ",".join(map(str, info["bands"])),
                "band_names": ", ".join(info["band_names"]),
                "dtype": info["dtype"],
                "output_path": info["output_path"],
            }
            return (
                ToolOutput()
                .table(f"{stem} Band Export", geojson.collection([geojson.feature(None, row)]))
                .message(f"Exported {info['band_count']}-band COG ({row['band_names']}): {info['output_path']}")
            )

        if mode == "split-bands":
            out_dir = Path(out_raw).expanduser() if out_raw else (input_path.parent / f"{stem}_bands")
            host.progress(f"Splitting {len(selected)} band(s) into individual COGs...")
            info = split_bands_to_folder(input_path, profile, out_dir, band_indices=selected, cog=True)
            if info["files"]:
                _record_last_output(Path(info["files"][0]), "split-bands")
            rows = [
                geojson.feature(None, {"band": b, "output_path": p})
                for b, p in zip(info["bands"], info["files"])
            ]
            return (
                ToolOutput()
                .table(f"{stem} Split Bands", geojson.collection(rows))
                .message(f"Split {info['count']} single-band COG(s) into {info['output_dir']}")
            )

        if mode == "visual-rgb":
            out_tif = Path(out_raw).expanduser() if out_raw else (input_path.parent / f"{stem}_visual_rgb.tif")
            host.progress(f"Exporting stretched 8-bit visual RGBA COG (bands {selected})...")
            info = export_visual_rgb_cog(input_path, profile, selected, out_tif, cog=True)
            _record_last_output(out_tif, "visual-rgb")
            return (
                ToolOutput()
                .table(
                    f"{stem} Visual RGB",
                    geojson.collection(
                        [geojson.feature(None, {**info, "bands": ",".join(map(str, info["bands"]))})]
                    ),
                )
                .message(f"Exported 8-bit visual RGBA COG (bands {selected}): {info['output_path']}")
            )

        raise ValueError(f"Unsupported export mode: {mode!r}")
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()


def _tool_stack_bands(req: Request) -> ToolOutput:
    raw_folder = str(req.params.get("inputFolder") or "").strip()
    if not raw_folder:
        raise ValueError("'inputFolder' is required")
    folder = Path(raw_folder).expanduser()
    sensor = str(req.params.get("sensor") or "auto").strip().lower()
    cloud_mask = bool(req.params.get("cloudMask", False))
    out_raw = str(req.params.get("outputPath") or "").strip()
    out_tif = Path(out_raw).expanduser() if out_raw else (folder / f"{folder.name}_stack.tif")

    host.progress(f"Aligning & stacking {sensor} bands from {folder.name}...")
    info = stack_band_folder(folder, out_tif, sensor=sensor, apply_cloud_mask=cloud_mask, cog=True)
    _record_last_output(out_tif, "stack-bands")
    row = {
        "sensor": info["sensor"],
        "band_count": info["band_count"],
        "bands": ", ".join(info["bands"]),
        "width": info["width"],
        "height": info["height"],
        "crs_epsg": info["crs_epsg"],
        "cloud_masked": info["cloud_masked"],
        "output_path": info["output_path"],
    }
    return (
        ToolOutput()
        .table(f"{folder.name} Stack", geojson.collection([geojson.feature(None, row)]))
        .message(
            f"Stacked {info['band_count']} {info['sensor']} bands ({row['bands']}) "
            f"[{info['width']}x{info['height']}]: {info['output_path']}"
        )
    )


def _tool_spectral_index(req: Request) -> ToolOutput:
    input_path, tmpdir = _resolve_input_path(req, "input")
    try:
        host.progress(f"Profiling {input_path.name}...")
        profile = inspect_tiff(input_path)
        mode = str(req.params.get("mode") or "index").strip().lower()
        palette = str(req.params.get("palette") or "auto").strip()
        title_raw = str(req.params.get("title") or "").strip()
        out_dir = _resolve_output_dir(req.params.get("outputDir"), input_path)
        stem = input_path.stem

        out = ToolOutput()
        if mode == "index":
            index_name = str(req.params.get("indexName") or "ndvi").strip().lower()
            out_tif = out_dir / f"{stem}_{index_name}.tif"
            out_png = out_dir / f"{stem}_{index_name}_preview.png"
            cmap = None if palette == "auto" else palette
            host.progress(f"Computing {index_name.upper()}...")
            stats = export_spectral_index(
                input_path,
                profile,
                index_name,
                out_tif,
                output_preview=out_png,
                cmap_name=cmap,
                title=title_raw or f"{stem} — {index_name.upper()}",
            )
            _record_last_output(out_tif, f"index-{index_name}")
            out.table(
                f"{stem} {index_name.upper()} Stats",
                geojson.collection([geojson.feature(None, stats)]),
            )
            out.message(f"{index_name.upper()} GeoTIFF: {out_tif}")
            out.message(f"{index_name.upper()} preview PNG: {out_png}")
            return out

        if mode == "composite":
            comp = str(req.params.get("composite") or "true-color").strip().lower()
            band_indices, comp_key = resolve_composite_bands(profile, comp)
            slug = comp_key.replace("-", "_")
            out_tif = out_dir / f"{stem}_{slug}.tif"
            out_png = out_dir / f"{stem}_{slug}_preview.png"
            title = title_raw or f"{stem} — {comp_key}"
        elif mode == "rgb":
            band_indices = _parse_band_list(req.params.get("rgbBands"), 3)
            out_tif = out_dir / f"{stem}_rgb.tif"
            out_png = out_dir / f"{stem}_rgb_preview.png"
            title = title_raw or f"{stem} — RGB ({','.join(map(str, band_indices))})"
        elif mode == "band":
            b_idx = int(req.params.get("singleBand") or 1)
            if b_idx < 1 or b_idx > profile.band_count:
                raise ValueError(f"singleBand must be in [1..{profile.band_count}], got {b_idx}")
            band_indices = [b_idx]
            out_tif = out_dir / f"{stem}_band{b_idx}.tif"
            out_png = out_dir / f"{stem}_band{b_idx}_preview.png"
            title = title_raw or f"{stem} — Band {b_idx}"
        else:
            raise ValueError(f"Unsupported mode: {mode!r}")

        cmap = "viridis" if palette == "auto" else palette
        host.progress(f"Exporting {mode} view...")
        export_band_view(
            input_path,
            profile,
            band_indices,
            output_tif=out_tif,
            output_preview=out_png,
            cmap_name=cmap,
            title=title,
        )
        _record_last_output(out_tif, mode)
        out.message(f"Exported GeoTIFF ({mode}, bands {band_indices}): {out_tif}")
        out.message(f"Preview PNG: {out_png}")
        return out
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()


def _tool_clip_raster(req: Request) -> ToolOutput:
    input_path, tmpdir = _resolve_input_path(req, "input")
    try:
        features = req.features("boundary")
        crop = bool(req.params.get("crop", True))
        out_raw = str(req.params.get("outputPath") or "").strip()
        out_path = (
            Path(out_raw).expanduser()
            if out_raw
            else (input_path.parent / f"{input_path.stem}_clipped.tif")
        )

        with tempfile.TemporaryDirectory(prefix="lulckit_clip_") as bnd_dir:
            bnd_geojson = _write_layer_to_geojson(features, Path(bnd_dir) / "boundary.geojson")
            host.progress(f"Clipping {input_path.name}...")
            summary = clip_raster_to_geojson(
                input_path,
                bnd_geojson,
                out_path,
                crop=crop,
            )

        _record_last_output(Path(summary["output_path"]), "clip-raster")
        row = {
            "input_width": summary["input_shape"][0],
            "input_height": summary["input_shape"][1],
            "clipped_width": summary["clipped_shape"][0],
            "clipped_height": summary["clipped_shape"][1],
            "band_count": summary["band_count"],
            "crs_epsg": summary["crs_epsg"],
            "nodata": "" if summary["nodata"] is None else str(summary["nodata"]),
            "output_path": summary["output_path"],
        }
        return (
            ToolOutput()
            .table(f"{input_path.stem} Clip Summary", geojson.collection([geojson.feature(None, row)]))
            .message(
                f"Clipped {summary['input_shape'][0]}x{summary['input_shape'][1]} -> "
                f"{summary['clipped_shape'][0]}x{summary['clipped_shape'][1]} px"
            )
            .message(f"Output GeoTIFF: {summary['output_path']}")
        )
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()


def handle(req: Request) -> Any:
    """Dispatch RustGIS command or tool requests to LULCkit."""
    if req.kind == "command":
        commands = {
            "load-output-raster": _cmd_load_output_raster,
            "inspect-active-raster": _cmd_inspect_active_raster,
            "models-info": _cmd_models_info,
            "about": _cmd_about,
        }
        if req.id not in commands:
            raise ValueError(f"Unknown LULCkit command '{req.id}'")
        return commands[req.id](req)

    if req.kind == "tool":
        tools = {
            "lulc-map": _tool_lulc_map,
            "export-bands": _tool_export_bands,
            "stack-bands": _tool_stack_bands,
            "inspect-geotiff": _tool_inspect_geotiff,
            "spectral-index": _tool_spectral_index,
            "clip-raster": _tool_clip_raster,
        }
        if req.id not in tools:
            raise ValueError(f"Unknown LULCkit tool '{req.id}'")
        return tools[req.id](req)

    raise ValueError(f"Unsupported request kind '{req.kind}'")


if __name__ == "__main__":
    serve(handle)
