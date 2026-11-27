"""Report generation, GeoJSON vectorization, quick-look PNG rendering, and Rich output."""

from __future__ import annotations

import csv
import json
import warnings
from pathlib import Path
from typing import Any

import rasterio
from pyproj import Geod, Transformer
from rasterio.errors import NotGeoreferencedWarning
from rasterio.features import shapes
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

from lulckit import __version__
from lulckit.cartography import render_print_map
from lulckit.inspect import TiffProfile
from lulckit.models.base import NODATA_VALUE, BaseLULCModel, ClassSpec
from lulckit.tiling import InferenceStats


_WGS84_GEOD = Geod(ellps="WGS84")


def _format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    val = float(size)
    for unit in units:
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.2f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{size} B"


def build_report(
    profile: TiffProfile,
    model: BaseLULCModel,
    stats: InferenceStats,
    spectral_indices: dict[str, dict[str, float]],
    warnings_list: list[str],
    output_files: dict[str, Path | None],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build complete JSON-serializable report combining TIFF profile and LULC stats."""
    pdict = profile.to_dict()
    valid_px = stats.valid_pixels
    has_area = bool(stats.class_area_m2) and profile.is_georeferenced

    class_rows: list[dict[str, Any]] = []
    dominant_name: str | None = None
    dominant_px = -1

    has_conf = bool(getattr(model, "has_confidence", True))
    for cls in model.classes:
        px = int(stats.class_pixels.get(cls.id, 0))
        pct = round((px / valid_px) * 100.0, 4) if valid_px > 0 else 0.0
        conf_sum = float(stats.class_conf_sum.get(cls.id, 0.0))
        mean_conf = round(conf_sum / px, 2) if (has_conf and px > 0) else None

        if has_area:
            area_m2 = round(float(stats.class_area_m2.get(cls.id, 0.0)), 2)
            area_ha = round(area_m2 / 10_000.0, 4)
            area_km2 = round(area_m2 / 1_000_000.0, 6)
        else:
            area_m2 = area_ha = area_km2 = None

        if px > dominant_px and px > 0:
            dominant_px = px
            dominant_name = cls.name

        class_rows.append(
            {
                "id": cls.id,
                "name": cls.name,
                "hex": cls.hex,
                "rgb": list(cls.color),
                "pixels": px,
                "percent": pct,
                "area_m2": area_m2,
                "area_ha": area_ha,
                "area_km2": area_km2,
                "mean_confidence": mean_conf,
            }
        )

    total_m2 = pdict["total_area_m2"]
    computed_valid_m2 = round(sum(stats.class_area_m2.values()), 2) if has_area else None

    return {
        "tool": {"name": "lulckit", "version": __version__},
        "file": {
            "path": pdict["path"],
            "file_name": pdict["file_name"],
            "file_size_bytes": pdict["file_size_bytes"],
            "file_size_human": _format_bytes(profile.file_size_bytes),
            "driver": pdict["driver"],
            "width": pdict["width"],
            "height": pdict["height"],
            "band_count": pdict["band_count"],
            "total_pixels": pdict["total_pixels"],
            "dtypes": pdict["dtypes"],
            "nodata": pdict["nodata"],
            "compression": pdict["compression"],
            "is_tiled": pdict["is_tiled"],
            "block_shapes": pdict["block_shapes"],
            "interleave": pdict["interleave"],
            "photometric": pdict["photometric"],
            "overviews": pdict["overviews"],
            "is_cog_like": pdict["is_cog_like"],
            "stats_sampled": pdict["stats_sampled"],
            "valid_pixel_ratio": pdict["valid_pixel_ratio"],
            "detected_profile": pdict["detected_profile"],
        },
        "geospatial": {
            "is_georeferenced": pdict["is_georeferenced"],
            "crs_epsg": pdict["crs_epsg"],
            "crs_name": pdict["crs_name"],
            "crs_units": pdict["crs_units"],
            "crs_is_projected": pdict["crs_is_projected"],
            "crs_is_geographic": pdict["crs_is_geographic"],
            "crs_wkt": pdict["crs_wkt"],
            "crs_proj4": pdict["crs_proj4"],
            "transform": pdict["transform"],
            "gsd_meters": pdict["gsd_meters"],
            "bounds_native": pdict["bounds_native"],
            "bounds_wgs84": pdict["bounds_wgs84"],
            "centroid_wgs84": pdict["centroid_wgs84"],
            "total_area_m2": round(total_m2, 2) if total_m2 is not None else None,
            "total_area_ha": round(total_m2 / 10_000.0, 4) if total_m2 is not None else None,
            "total_area_km2": round(total_m2 / 1_000_000.0, 6) if total_m2 is not None else None,
            "valid_area_m2": computed_valid_m2,
            "valid_area_ha": round(computed_valid_m2 / 10_000.0, 4) if computed_valid_m2 is not None else None,
            "valid_area_km2": round(computed_valid_m2 / 1_000_000.0, 6) if computed_valid_m2 is not None else None,
        },
        "bands": pdict["bands"],
        "tags": pdict["tags"],
        "tag_namespaces": pdict["tag_namespaces"],
        "spectral_indices": spectral_indices,
        "inference": {
            "model": model.name,
            "description": model.description,
            "optimal_gsd_m": model.optimal_gsd_m,
            "repo_id": getattr(model, "repo_id", None),
            "device": params.get("device"),
            "tile_size": params.get("tile_size"),
            "overlap": params.get("overlap"),
            "batch_size": params.get("batch_size"),
            "band_indices": params.get("band_indices"),
            "preprocess_mode": params.get("preprocess_mode"),
            "tiles_processed": stats.tiles_processed,
            "runtime_seconds": stats.runtime_seconds,
            "valid_pixels": stats.valid_pixels,
            "nodata_pixels": stats.nodata_pixels,
        },
        "lulc": {
            "dominant_class": dominant_name,
            "classes": class_rows,
        },
        "warnings": warnings_list,
        "output_files": {k: str(v) for k, v in output_files.items() if v is not None},
    }


def write_json_report(report: dict[str, Any], path: str | Path) -> None:
    """Write structured JSON report to disk."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")


def write_csv_summary(report: dict[str, Any], path: str | Path) -> None:
    """Write per-class LULC summary CSV."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "class_id",
        "class_name",
        "hex_color",
        "pixels",
        "percent",
        "area_m2",
        "area_ha",
        "area_km2",
        "mean_confidence",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in report["lulc"]["classes"]:
            writer.writerow(
                {
                    "class_id": row["id"],
                    "class_name": row["name"],
                    "hex_color": row["hex"],
                    "pixels": row["pixels"],
                    "percent": row["percent"],
                    "area_m2": "" if row["area_m2"] is None else row["area_m2"],
                    "area_ha": "" if row["area_ha"] is None else row["area_ha"],
                    "area_km2": "" if row["area_km2"] is None else row["area_km2"],
                    "mean_confidence": "" if row["mean_confidence"] is None else row["mean_confidence"],
                }
            )


def export_vector_geojson(
    lulc_tif_path: str | Path,
    classes: list[ClassSpec],
    output_path: str | Path,
    min_area_pixels: int = 4,
) -> int:
    """Polygonize classified LULC raster into RFC 7946 GeoJSON and return feature count."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cls_map = {c.id: c for c in classes}

    features: list[dict[str, Any]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(lulc_tif_path) as src:
            band = src.read(1)
            mask = band != NODATA_VALUE
            is_georef = src.crs is not None
            tr = src.transform
            pixel_area_native = abs(float(tr.a * tr.e - tr.b * tr.d)) if is_georef else 1.0
            if pixel_area_native <= 0:
                pixel_area_native = 1.0

            transformer = (
                Transformer.from_crs(src.crs.to_wkt(), "EPSG:4326", always_xy=True)
                if is_georef
                else None
            )

            for geom_dict, val in shapes(band, mask=mask, transform=tr):
                cid = int(val)
                if cid == NODATA_VALUE:
                    continue
                geom = shape(geom_dict)
                if geom.is_empty:
                    continue
                est_pixels = geom.area / pixel_area_native
                if est_pixels < min_area_pixels:
                    continue

                if transformer is not None:
                    out_geom = shapely_transform(transformer.transform, geom)
                    area_m2 = abs(float(_WGS84_GEOD.geometry_area_perimeter(out_geom)[0]))
                    area_ha = round(area_m2 / 10_000.0, 4)
                    area_m2 = round(area_m2, 2)
                else:
                    out_geom = geom
                    area_m2 = None
                    area_ha = None

                cls = cls_map.get(cid)
                props: dict[str, Any] = {
                    "class_id": cid,
                    "class_name": cls.name if cls else f"class_{cid}",
                    "hex_color": cls.hex if cls else "#808080",
                    "approx_pixels": round(est_pixels, 1),
                    "area_m2": area_m2,
                    "area_ha": area_ha,
                }
                features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(out_geom),
                        "properties": props,
                    }
                )

    fc = {"type": "FeatureCollection", "features": features}
    out.write_text(json.dumps(fc), encoding="utf-8")
    return len(features)


def render_preview_png(
    input_path: str | Path,
    lulc_tif_path: str | Path,
    profile: TiffProfile,
    model: BaseLULCModel,
    report: dict[str, Any],
    rgb_bands: list[int],
    output_path: str | Path,
    max_size: int = 2200,
    preprocess_mode: str = "rgb",
    display_name: str | None = None,
    *,
    layout: str = "auto",
    title: str | None = None,
    arrow_style: str = "compass",
    arrow_pos: str = "top-right",
    scalebar_style: str = "arcgis",
    legend_pos: str = "bottom-left",
    legend_areas: bool = False,
    show_grid: bool = True,
    boundary_path: str | Path | None = None,
    boundary_label: str | None = None,
    dpi: int = 300,
    composite_label: str | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
) -> None:
    """Delegate map rendering to ``cartography.render_print_map``."""
    resolved_layout = ("print" if preprocess_mode == "categorical" else "side-by-side") if layout == "auto" else layout
    render_print_map(
        input_path=input_path,
        lulc_tif_path=lulc_tif_path,
        profile=profile,
        model=model,
        report=report,
        rgb_bands=rgb_bands,
        output_path=output_path,
        layout=resolved_layout,
        title=title or display_name,
        arrow_style=arrow_style,
        arrow_pos=arrow_pos,
        scalebar_style=scalebar_style,
        legend_pos=legend_pos,
        legend_areas=legend_areas,
        show_grid=show_grid,
        boundary_path=boundary_path,
        boundary_label=boundary_label,
        dpi=dpi,
        max_size=max_size,
        composite_label=composite_label,
        page_size=page_size,
        orientation=orientation,
    )


def render_rich_inspect(profile: TiffProfile, console: Any) -> None:
    """Print detailed TIFF/GeoTIFF metadata tables to a Rich console."""
    from rich.table import Table

    meta_table = Table(title=f"TIFF Profile: {profile.file_name}", show_header=False)
    meta_table.add_column("Property", style="bold cyan", no_wrap=True)
    meta_table.add_column("Value")

    gsd_str = (
        f"{profile.gsd_meters[0]:.3f} × {profile.gsd_meters[1]:.3f} m/px"
        if profile.gsd_meters
        else "N/A (non-georeferenced)"
    )
    crs_str = (
        f"EPSG:{profile.crs_epsg} ({profile.crs_name})"
        if profile.crs_epsg
        else (profile.crs_name or "None")
    )
    area_str = (
        f"{profile.valid_area_m2 / 10_000:.4f} ha ({profile.valid_area_m2 / 1_000_000:.6f} km²)"
        if profile.valid_area_m2 is not None
        else "N/A"
    )

    rows = [
        ("Path", profile.path),
        ("Size", f"{_format_bytes(profile.file_size_bytes)} ({profile.driver})"),
        ("Dimensions", f"{profile.width} × {profile.height} px ({profile.total_pixels:,} px), {profile.band_count} band(s)"),
        ("Dtypes / Nodata", f"{', '.join(sorted(set(profile.dtypes)))} | nodata={profile.nodata} | valid={profile.valid_pixel_ratio * 100:.2f}%"),
        ("Layout", f"compression={profile.compression}, tiled={profile.is_tiled}, blocks={profile.block_shapes[:1]}, overviews={profile.overviews}, cog_like={profile.is_cog_like}"),
        ("Georeferenced", str(profile.is_georeferenced)),
        ("CRS", crs_str),
        ("GSD", gsd_str),
        ("Valid Area", area_str),
        ("WGS84 Bounds", str(profile.bounds_wgs84) if profile.bounds_wgs84 else "N/A"),
        ("Centroid (lon,lat)", str(profile.centroid_wgs84) if profile.centroid_wgs84 else "N/A"),
        ("Detected Profile", f"{profile.detected_profile} -> recommended model: {profile.recommended_model or 'none'}"),
    ]
    for k, v in rows:
        meta_table.add_row(k, v)
    console.print(meta_table)

    band_table = Table(title="Bands & Statistics" + (" (sampled)" if profile.stats_sampled else ""))
    for col in ("#", "Dtype", "Interp", "Description", "Min", "Max", "Mean", "p2..p98", "Valid%"):
        band_table.add_column(col, justify="right" if col in ("#", "Min", "Max", "Mean", "Valid%") else "left")

    def _fmt(v: Any) -> str:
        return f"{v:.3f}" if isinstance(v, float) else (str(v) if v is not None else "-")

    for b in profile.bands:
        p_range = f"{_fmt(b.p2)} .. {_fmt(b.p98)}" if b.p2 is not None and b.p98 is not None else "-"
        band_table.add_row(
            str(b.index),
            b.dtype,
            b.colorinterp,
            b.description or "-",
            _fmt(b.min),
            _fmt(b.max),
            _fmt(b.mean),
            p_range,
            f"{b.valid_ratio * 100:.1f}%",
        )
    console.print(band_table)

    if profile.tags:
        tag_table = Table(title="TIFF / GDAL Tags")
        tag_table.add_column("Tag", style="cyan")
        tag_table.add_column("Value")
        for k, v in sorted(profile.tags.items()):
            tag_table.add_row(k, v)
        console.print(tag_table)

    for w in profile.warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")


def render_rich_map_summary(report: dict[str, Any], console: Any) -> None:
    """Print Associated TIFF Details, LULC breakdown, spectral indices, and output paths."""
    from rich.table import Table

    inf = report["inference"]
    geo = report["geospatial"]
    fmeta = report["file"]
    bands = report.get("bands", [])

    console.print(
        f"\n[bold green]LULC Mapping Complete[/bold green] — Model: [bold]{inf['model']}[/bold] | "
        f"Tiles: {inf['tiles_processed']} | Time: {inf['runtime_seconds']:.2f}s | "
        f"Dominant: [bold]{report['lulc']['dominant_class'] or 'N/A'}[/bold]"
    )

    layout_str = "COG" if fmeta["is_cog_like"] else ("Tiled" if fmeta["is_tiled"] else "Striped")
    crs_str = f"EPSG:{geo['crs_epsg']} ({geo['crs_name']})" if geo["crs_epsg"] else (geo["crs_name"] or "None")
    gsd_str = f"{geo['gsd_meters'][0]:.3f} × {geo['gsd_meters'][1]:.3f} m/px" if geo["gsd_meters"] else "N/A (non-georeferenced)"
    area_str = (
        f"{geo['valid_area_ha']:,.4f} ha ({geo['valid_area_km2']:,.6f} km²)"
        if geo["valid_area_ha"] is not None
        else "N/A"
    )
    band_desc = ", ".join(
        f"B{b['index']}:{b['description'] or b['colorinterp']}"
        for b in bands[:6]
    ) + (f" (+{len(bands) - 6} more)" if len(bands) > 6 else "")

    tiff_table = Table(title="Associated TIFF Details", show_header=False)
    tiff_table.add_column("Property", style="bold cyan", no_wrap=True)
    tiff_table.add_column("Value")
    for k, v in (
        ("Source", f"{fmeta['file_name']} ({fmeta['file_size_human']}, {fmeta['driver']})"),
        ("Layout & Compression", f"{layout_str} | compression={fmeta['compression'] or 'None'} | blocks={fmeta['block_shapes'][:1]} | overviews={fmeta['overviews']}"),
        ("Dimensions & Bands", f"{fmeta['width']:,} × {fmeta['height']:,} px ({fmeta['total_pixels']:,} px) | {fmeta['band_count']} band(s): {band_desc}"),
        ("Dtypes & Nodata", f"{', '.join(sorted(set(fmeta['dtypes'])))} | nodata={fmeta['nodata']} | valid={fmeta['valid_pixel_ratio'] * 100:.2f}%"),
        ("CRS", crs_str),
        ("GSD", gsd_str),
        ("WGS84 Bounds", str(geo["bounds_wgs84"]) if geo["bounds_wgs84"] else "N/A"),
        ("Centroid (lon, lat)", str(geo["centroid_wgs84"]) if geo["centroid_wgs84"] else "N/A"),
        ("Valid Area", area_str),
    ):
        tiff_table.add_row(k, v)
    console.print(tiff_table)

    table = Table(title="Land Cover Breakdown")
    table.add_column("ID", justify="right")
    table.add_column("Color", justify="center")
    table.add_column("Class")
    table.add_column("Pixels", justify="right")
    table.add_column("Area %", justify="right")
    table.add_column("Area (ha)", justify="right")
    table.add_column("Area (km²)", justify="right")
    table.add_column("Mean Conf", justify="right")

    for r in report["lulc"]["classes"]:
        swatch = f"[{r['hex']}]██[/]"
        table.add_row(
            str(r["id"]),
            swatch,
            r["name"],
            f"{r['pixels']:,}",
            f"{r['percent']:.2f}%",
            f"{r['area_ha']:.4f}" if r["area_ha"] is not None else "-",
            f"{r['area_km2']:.6f}" if r["area_km2"] is not None else "-",
            f"{r['mean_confidence']:.1f}%" if r["mean_confidence"] is not None else "-",
        )
    console.print(table)

    if report["spectral_indices"]:
        idx_table = Table(title="Spectral Indices (Valid Pixels)")
        idx_table.add_column("Index")
        idx_table.add_column("Mean", justify="right")
        idx_table.add_column("Median", justify="right")
        idx_table.add_column("Std", justify="right")
        idx_table.add_column("p10 .. p90", justify="right")
        for name, st in report["spectral_indices"].items():
            idx_table.add_row(
                name.upper(),
                f"{st['mean']:.4f}",
                f"{st['median']:.4f}",
                f"{st['std']:.4f}",
                f"{st['p10']:.4f} .. {st['p90']:.4f}",
            )
        console.print(idx_table)

    for w in report.get("warnings", []):
        console.print(f"[yellow]Warning:[/yellow] {w}")

    out_table = Table(title="Generated Outputs", show_header=False)
    out_table.add_column("Artifact", style="bold cyan")
    out_table.add_column("Path")
    for k, v in report["output_files"].items():
        out_table.add_row(k, v)
    console.print(out_table)
