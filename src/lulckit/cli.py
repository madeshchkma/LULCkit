"""Typer CLI entry point for LULCkit (`inspect`, `bands`, `clip`, `map`, `batch`, `wizard`, `models`, `styles`)."""

from __future__ import annotations

import json
import shlex
import warnings
from pathlib import Path
from typing import Any, Optional

import rasterio
import typer
from rasterio.errors import NotGeoreferencedWarning
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from lulckit import __version__
from lulckit.bands import (
    SPECTRAL_INDICES,
    clip_raster_to_geojson,
    export_band_view,
    export_spectral_index,
    list_spectral_indices,
)
from lulckit.cartography import (
    ARROW_STYLES,
    COMPOSITES,
    PAGE_SIZES,
    SCALEBAR_STYLES,
    export_interactive_html,
    list_arrow_styles,
    list_composites,
    list_page_sizes,
    list_palettes,
    list_scalebar_styles,
    resolve_composite_bands,
)
from lulckit.geo import compute_spectral_indices
from lulckit.inspect import TiffProfile, inspect_tiff
from lulckit.models.router import UnsupportedRasterError, list_models, resolve_device, select_model
from lulckit.outputs import (
    build_report,
    export_vector_geojson,
    render_preview_png,
    render_rich_inspect,
    render_rich_map_summary,
    write_csv_summary,
    write_json_report,
)
from lulckit.tiling import run_tiled_inference


app = typer.Typer(
    name="lulc",
    help="Turn any optical or classified TIFF/GeoTIFF into GIS-ready LULC maps, band composites, spectral indices, and metadata reports.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

_GRAPHIC_EXTS = {".png", ".pdf", ".svg"}


def _parse_band_list(raw: str | None, expected_len: int, flag_name: str) -> list[int] | None:
    if raw is None:
        return None
    try:
        vals = [int(tok.strip()) for tok in raw.split(",") if tok.strip()]
    except ValueError as exc:
        raise typer.BadParameter(f"{flag_name} must be comma-separated integers, got {raw!r}") from exc
    if len(vals) != expected_len:
        raise typer.BadParameter(f"{flag_name} requires {expected_len} band indices, got {len(vals)}")
    return vals


def _parse_class_labels(raw: str | None) -> dict[int, str] | None:
    if raw is None:
        return None
    out: dict[int, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise typer.BadParameter(f"--class-labels entries must be id:Label, got {item!r}")
        k_str, v_str = item.split(":", 1)
        try:
            cid = int(k_str.strip())
        except ValueError as exc:
            raise typer.BadParameter(f"Class ID must be an integer in --class-labels, got {k_str!r}") from exc
        out[cid] = v_str.strip()
    return out


def _parse_class_colors(raw: str | None) -> dict[int, tuple[int, int, int]] | None:
    if raw is None:
        return None
    out: dict[int, tuple[int, int, int]] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise typer.BadParameter(f"--class-colors entries must be id:#RRGGBB, got {item!r}")
        k_str, hex_str = item.split(":", 1)
        try:
            cid = int(k_str.strip())
        except ValueError as exc:
            raise typer.BadParameter(f"Class ID must be an integer in --class-colors, got {k_str!r}") from exc
        h = hex_str.strip().lstrip("#")
        if len(h) != 6:
            raise typer.BadParameter(f"Hex color must be #RRGGBB in --class-colors, got {hex_str!r}")
        try:
            rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError as exc:
            raise typer.BadParameter(f"Invalid hex color {hex_str!r} in --class-colors") from exc
        out[cid] = rgb
    return out


def _validate_map_options(
    map_format: str,
    layout: str,
    page_size: str,
    orientation: str,
    arrow_style: str,
    scalebar_style: str,
) -> tuple[str, str, str, str]:
    fmt = map_format.strip().lower()
    if fmt not in ("png", "pdf", "svg"):
        raise typer.BadParameter(f"--map-format must be png, pdf, or svg; got {map_format!r}")
    lay = layout.strip().lower()
    if lay not in ("auto", "print", "side-by-side"):
        raise typer.BadParameter(f"--layout must be auto, print, or side-by-side; got {layout!r}")
    ps = page_size.strip().lower()
    if ps != "auto" and ps not in PAGE_SIZES:
        raise typer.BadParameter(f"--page-size must be auto, {', '.join(PAGE_SIZES)}; got {page_size!r}")
    ori = orientation.strip().lower()
    if ori not in ("auto", "portrait", "landscape"):
        raise typer.BadParameter(f"--orientation must be auto, portrait, or landscape; got {orientation!r}")
    if arrow_style.strip().lower() not in ARROW_STYLES:
        raise typer.BadParameter(f"--arrow-style must be one of {', '.join(ARROW_STYLES)}; got {arrow_style!r}")
    if scalebar_style.strip().lower() not in SCALEBAR_STYLES:
        raise typer.BadParameter(f"--scalebar-style must be one of {', '.join(SCALEBAR_STYLES)}; got {scalebar_style!r}")
    return fmt, lay, ps, ori


def _execute_map(
    tiff_path: Path,
    *,
    output_dir: Path,
    name: str | None = None,
    title: str | None = None,
    model: str = "auto",
    hf_model: str | None = None,
    device: str = "auto",
    tile_size: int = 512,
    overlap: int = 64,
    batch_size: int = 4,
    rgb_list: list[int] | None = None,
    s2_list: list[int] | None = None,
    composite: str | None = None,
    palette: str = "default",
    labels_map: dict[int, str] | None = None,
    colors_map: dict[int, tuple[int, int, int]] | None = None,
    nodata_value: int | None = None,
    arrow_style: str = "compass",
    arrow_pos: str = "top-right",
    scalebar_style: str = "arcgis",
    legend_pos: str = "bottom-left",
    legend_areas: bool = False,
    grid: bool = True,
    layout: str = "auto",
    page_size: str = "a4",
    orientation: str = "auto",
    map_format: str = "png",
    dpi: int = 300,
    boundary: Path | None = None,
    boundary_label: str | None = None,
    html: bool = False,
    save_confidence: bool = False,
    vector: bool = False,
    min_area_pixels: int = 4,
    preview: bool = True,
    print_summary: bool = True,
) -> dict[str, Any]:
    """Run the full inspect -> select -> tile -> vector/html/preview/report pipeline."""
    profile: TiffProfile = inspect_tiff(tiff_path)

    composite_rgb: list[int] | None = None
    composite_key: str | None = None
    if composite is not None:
        composite_rgb, composite_key = resolve_composite_bands(profile, composite)

    lulc_model, band_indices, preprocess_mode, warnings_list = select_model(
        profile=profile,
        model_name=model,
        device=device,
        rgb_bands=rgb_list,
        s2_bands=s2_list,
        hf_model=hf_model,
        class_labels=labels_map,
        class_colors=colors_map,
        nodata_value=nodata_value,
        palette=palette,
    )

    stem = name.strip() if name and name.strip() else tiff_path.stem
    map_title = title.strip() if title and title.strip() else stem
    output_dir.mkdir(parents=True, exist_ok=True)
    lulc_tif_path = output_dir / f"{stem}_lulc.tif"
    conf_tif_path = (output_dir / f"{stem}_confidence.tif") if save_confidence else None
    json_path = output_dir / f"{stem}_report.json"
    csv_path = output_dir / f"{stem}_summary.csv"
    geojson_path = (output_dir / f"{stem}_lulc.geojson") if vector else None
    preview_path = (output_dir / f"{stem}_preview.{map_format}") if preview else None
    html_path = (output_dir / f"{stem}_map.html") if html else None

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(f"Running {lulc_model.name} ({tiff_path.name})", total=None)

        def _on_progress(done: int, total: int) -> None:
            progress.update(task_id, completed=done, total=total)

        stats = run_tiled_inference(
            input_path=tiff_path,
            profile=profile,
            model=lulc_model,
            band_indices=band_indices,
            preprocess_mode=preprocess_mode,
            output_lulc_path=lulc_tif_path,
            output_conf_path=conf_tif_path,
            tile_size=tile_size,
            overlap=overlap,
            batch_size=batch_size,
            progress_callback=_on_progress,
            extra_nodata_value=nodata_value,
        )

    spectral_indices: dict = {}
    if profile.spectral_band_map:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(tiff_path) as src:
                spectral_indices = compute_spectral_indices(src, profile.spectral_band_map)

    if geojson_path is not None:
        if profile.total_pixels > 16_000_000:
            console.print(
                f"[yellow]Warning:[/yellow] Vectorizing large {profile.width}×{profile.height} raster "
                f"({profile.total_pixels:,} px); this may take significant time and memory."
            )
        export_vector_geojson(
            lulc_tif_path=lulc_tif_path,
            classes=lulc_model.classes,
            output_path=geojson_path,
            min_area_pixels=min_area_pixels,
        )

    preview_key = "preview_png" if map_format == "png" else f"preview_{map_format}"
    output_files: dict[str, Path | None] = {
        "lulc_geotiff": lulc_tif_path,
        "confidence_geotiff": conf_tif_path,
        "report_json": json_path,
        "summary_csv": csv_path,
        "vector_geojson": geojson_path,
        preview_key: preview_path,
    }
    params = {
        "device": "none (categorical)" if preprocess_mode == "categorical" else resolve_device(device),
        "tile_size": tile_size,
        "overlap": 0 if preprocess_mode == "categorical" else overlap,
        "batch_size": 1 if preprocess_mode == "categorical" else batch_size,
        "band_indices": band_indices,
        "preprocess_mode": preprocess_mode,
        "display_name": stem,
        "title": map_title,
        "palette": palette,
        "composite": composite_key,
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
            boundary_path=boundary,
        )
        if written_html is not None:
            report["output_files"]["interactive_html"] = str(written_html)
        else:
            report["warnings"].append(
                "Interactive HTML export skipped: raster is not georeferenced (no WGS84 bounds)."
            )

    write_json_report(report, json_path)
    write_csv_summary(report, csv_path)

    if preview_path is not None:
        preview_rgb = (
            composite_rgb
            or rgb_list
            or profile.rgb_bands
            or (band_indices[:3] if len(band_indices) >= 3 else [1, 1, 1])
        )
        render_preview_png(
            input_path=tiff_path,
            lulc_tif_path=lulc_tif_path,
            profile=profile,
            model=lulc_model,
            report=report,
            rgb_bands=preview_rgb,
            output_path=preview_path,
            preprocess_mode=preprocess_mode,
            display_name=stem,
            layout=layout,
            title=map_title,
            arrow_style=arrow_style,
            arrow_pos=arrow_pos,
            scalebar_style=scalebar_style,
            legend_pos=legend_pos,
            legend_areas=legend_areas,
            show_grid=grid,
            boundary_path=boundary,
            boundary_label=boundary_label,
            dpi=dpi,
            composite_label=composite_key,
            page_size=page_size,
            orientation=orientation,
        )

    if print_summary:
        render_rich_map_summary(report, console)

    return report


@app.callback(invoke_without_command=True)
def main_callback(
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit.", is_eager=True),
) -> None:
    if version:
        console.print(f"lulckit {__version__}")
        raise typer.Exit()


@app.command("inspect")
def inspect_cmd(
    tiff_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Input TIFF or GeoTIFF."),
    json_out: bool = typer.Option(False, "--json", help="Print full profile as JSON."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Optional path to save JSON report."),
) -> None:
    """Inspect all metadata, geospatial details, band stats, and sensor profile of a TIFF."""
    profile = inspect_tiff(tiff_path)
    payload = profile.to_dict()

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if json_out:
        typer.echo(json.dumps(payload, indent=2))
    else:
        render_rich_inspect(profile, console)
        if output is not None:
            console.print(f"\nSaved inspection JSON to: [cyan]{output}[/cyan]")


@app.command("bands")
def bands_cmd(
    tiff_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Input TIFF or GeoTIFF."),
    composite: Optional[str] = typer.Option(None, "--composite", help="Export/preview preset composite (true-color, false-color-nir, agriculture, swir)."),
    rgb_bands: Optional[str] = typer.Option(None, "--rgb-bands", help="Export/preview custom 3-band RGB combination (e.g. 4,3,2)."),
    band: Optional[int] = typer.Option(None, "--band", help="Extract or visualize a single 1-based band."),
    index: Optional[str] = typer.Option(None, "--index", help="Compute spectral index (ndvi, ndwi, ndbi, savi, evi)."),
    palette: Optional[str] = typer.Option(None, "--palette", help="Matplotlib colormap for --band or --index (e.g. viridis, RdYlGn, gray)."),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output path (.tif for raster, .png/.pdf/.svg for print map)."),
    preview_out: Optional[Path] = typer.Option(None, "--preview-out", help="Optional print map output when -o is a .tif."),
    title: Optional[str] = typer.Option(None, "--title", help="Map title for rendered graphic."),
    page_size: str = typer.Option("a4", "--page-size", help="Print page size: auto, a4, a5, a3, letter, legal, or square."),
    orientation: str = typer.Option("auto", "--orientation", help="Page orientation: auto, portrait, or landscape."),
    arrow_style: str = typer.Option("compass", "--arrow-style", help="North arrow style: compass, classic, fancy, minimal, or none."),
    scalebar_style: str = typer.Option("arcgis", "--scalebar-style", help="Scale bar style: arcgis, alternating, simple, or none."),
    grid: bool = typer.Option(True, "--grid/--no-grid", help="Show X/Y numerical coordinate axes and gridlines."),
    dpi: int = typer.Option(300, "--dpi", help="Export resolution DPI for map graphic."),
    json_out: bool = typer.Option(False, "--json", help="Print band & index summary as JSON (inspection mode)."),
) -> None:
    """Inspect bands, render custom band composites, or compute NDVI/NDWI/NDBI/SAVI/EVI."""
    modes_chosen = sum(x is not None for x in (composite, rgb_bands, band, index))
    if modes_chosen > 1:
        raise typer.BadParameter("Choose at most one of --composite, --rgb-bands, --band, or --index.")

    rgb_list = _parse_band_list(rgb_bands, 3, "--rgb-bands")
    profile = inspect_tiff(tiff_path)

    if modes_chosen == 0:
        spectral_stats: dict = {}
        if profile.spectral_band_map:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NotGeoreferencedWarning)
                with rasterio.open(tiff_path) as src:
                    spectral_stats = compute_spectral_indices(src, profile.spectral_band_map)

        role_by_band = {idx: role for role, idx in profile.spectral_band_map.items()}
        avail_composites = [
            {"name": k, "bands": ", ".join(roles), "ready": all(r in profile.spectral_band_map for r in roles)}
            for k, (roles, _) in COMPOSITES.items()
        ]
        avail_indices = [
            {"name": k, "roles": ", ".join(spec["roles"]), "ready": all(r in profile.spectral_band_map for r in spec["roles"])}
            for k, spec in SPECTRAL_INDICES.items()
        ]

        if json_out:
            typer.echo(
                json.dumps(
                    {
                        "file": profile.file_name,
                        "band_count": profile.band_count,
                        "bands": profile.to_dict()["bands"],
                        "spectral_band_map": profile.spectral_band_map,
                        "composites": avail_composites,
                        "indices": avail_indices,
                        "spectral_stats": spectral_stats,
                    },
                    indent=2,
                )
            )
            return

        b_table = Table(title=f"Bands in {profile.file_name} ({profile.band_count} total)")
        for col in ("#", "Dtype", "Interp", "Role", "Description", "Min", "Max", "p2..p98", "Valid%"):
            b_table.add_column(col, justify="right" if col in ("#", "Min", "Max", "Valid%") else "left")
        def _fmt(v: Any) -> str:
            return f"{v:.3f}" if isinstance(v, float) else (str(v) if v is not None else "-")

        for b in profile.bands:
            p_rng = f"{_fmt(b.p2)} .. {_fmt(b.p98)}" if b.p2 is not None and b.p98 is not None else "-"
            b_table.add_row(
                str(b.index),
                b.dtype,
                b.colorinterp,
                role_by_band.get(b.index, "-"),
                b.description or "-",
                _fmt(b.min),
                _fmt(b.max),
                p_rng,
                f"{b.valid_ratio * 100:.1f}%",
            )
        console.print(b_table)

        c_table = Table(title="Available Composites & Spectral Indices")
        c_table.add_column("Kind", style="bold cyan")
        c_table.add_column("Name")
        c_table.add_column("Required Bands")
        c_table.add_column("Status")
        for c in avail_composites:
            c_table.add_row("composite", c["name"], c["bands"], "[green]ready[/green]" if c["ready"] else "[dim]missing bands[/dim]")
        for s in avail_indices:
            c_table.add_row("index", s["name"], s["roles"], "[green]ready[/green]" if s["ready"] else "[dim]missing bands[/dim]")
        console.print(c_table)

        if spectral_stats:
            st_table = Table(title="Quick Spectral Index Summary")
            st_table.add_column("Index")
            st_table.add_column("Mean", justify="right")
            st_table.add_column("Median", justify="right")
            st_table.add_column("p10 .. p90", justify="right")
            for k, st in spectral_stats.items():
                st_table.add_row(k.upper(), f"{st['mean']:.4f}", f"{st['median']:.4f}", f"{st['p10']:.4f} .. {st['p90']:.4f}")
            console.print(st_table)
        return

    # Export / visualization modes
    if index is not None:
        tag = index.strip().lower()
        target = output or Path(f"./lulc_out/{tiff_path.stem}_{tag}.tif")
        if target.suffix.lower() in _GRAPHIC_EXTS:
            tif_target = target.with_suffix(".tif")
            map_target = preview_out or target
        else:
            tif_target = target
            map_target = preview_out

        try:
            stats = export_spectral_index(
                input_path=tiff_path,
                profile=profile,
                index_name=tag,
                output_tif=tif_target,
                output_preview=map_target,
                cmap_name=palette,
                title=title,
                page_size=page_size,
                orientation=orientation,
                arrow_style=arrow_style,
                scalebar_style=scalebar_style,
                show_grid=grid,
                dpi=dpi,
            )
        except ValueError as exc:
            err_console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=2) from exc

        console.print(f"[bold green]Computed {tag.upper()}[/bold green] -> [cyan]{tif_target}[/cyan]")
        console.print(
            f"Valid pixels: {stats['valid_pixels']:,} | min={stats['min']} | max={stats['max']} | "
            f"mean={stats['mean']} | std={stats['std']}"
        )
        if map_target is not None:
            console.print(f"Rendered map -> [cyan]{map_target}[/cyan]")
        return

    try:
        if composite is not None:
            chosen_bands, tag = resolve_composite_bands(profile, composite)
        elif rgb_list is not None:
            chosen_bands = rgb_list
            tag = f"bands_{'_'.join(str(b) for b in chosen_bands)}"
        else:
            assert band is not None
            chosen_bands = [band]
            tag = f"band_{band}"

        target = output or Path(f"./lulc_out/{tiff_path.stem}_{tag}.png")
        if target.suffix.lower() in _GRAPHIC_EXTS:
            tif_target = None
            map_target = preview_out or target
        else:
            tif_target = target
            map_target = preview_out

        export_band_view(
            input_path=tiff_path,
            profile=profile,
            band_indices=chosen_bands,
            output_tif=tif_target,
            output_preview=map_target,
            cmap_name=palette or "viridis",
            title=title,
            page_size=page_size,
            orientation=orientation,
            arrow_style=arrow_style,
            scalebar_style=scalebar_style,
            show_grid=grid,
            dpi=dpi,
        )
    except ValueError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc

    if tif_target is not None:
        console.print(f"[bold green]Exported bands {chosen_bands}[/bold green] -> [cyan]{tif_target}[/cyan]")
    if map_target is not None:
        console.print(f"[bold green]Rendered band view {chosen_bands}[/bold green] -> [cyan]{map_target}[/cyan]")


@app.command("clip")
def clip_cmd(
    tiff_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Input GeoTIFF."),
    boundary: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Boundary GeoJSON polygon(s)."),
    output: Path = typer.Option(..., "-o", "--output", help="Output clipped GeoTIFF path."),
    crop: bool = typer.Option(True, "--crop/--no-crop", help="Crop raster extent to boundary bounding box."),
    nodata: Optional[float] = typer.Option(None, "--nodata", help="Override nodata value outside boundary."),
) -> None:
    """Clip any georeferenced TIFF/GeoTIFF to a GeoJSON polygon boundary."""
    try:
        res = clip_raster_to_geojson(
            input_path=tiff_path,
            boundary_path=boundary,
            output_path=output,
            crop=crop,
            nodata=nodata,
        )
    except ValueError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title="Clipped GeoTIFF Summary", show_header=False)
    table.add_column("Property", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Input Size", f"{res['input_shape'][0]:,} × {res['input_shape'][1]:,} px")
    table.add_row("Clipped Size", f"{res['clipped_shape'][0]:,} × {res['clipped_shape'][1]:,} px ({res['band_count']} band(s))")
    table.add_row("CRS", f"EPSG:{res['crs_epsg']}" if res["crs_epsg"] else "Custom CRS")
    table.add_row("WGS84 Bounds", str(res["bounds_wgs84"]))
    table.add_row("Output Path", res["output_path"])
    console.print(table)


@app.command("models")
def models_cmd(
    json_out: bool = typer.Option(False, "--json", help="Print model catalog as JSON."),
) -> None:
    """List available pretrained LULC models and their local cache status."""
    rows = list_models()
    if json_out:
        typer.echo(json.dumps(rows, indent=2))
        return

    table = Table(title="Available Pretrained LULC Models")
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Architecture")
    table.add_column("Bands", justify="right")
    table.add_column("Optimal GSD")
    table.add_column("Classes")
    table.add_column("Cached")
    table.add_column("Source Repo")

    for r in rows:
        cached_badge = "[green]yes[/green]" if r["cached"] else "[dim]no (downloads on 1st use)[/dim]"
        table.add_row(
            r["name"],
            r["architecture"],
            str(r["expected_bands"]),
            r["optimal_gsd_m"],
            r["classes"],
            cached_badge,
            r["repo_id"],
        )
    console.print(table)


@app.command("styles")
def styles_cmd(
    json_out: bool = typer.Option(False, "--json", help="Print all cartographic styles as JSON."),
) -> None:
    """List built-in color palettes, composites, indices, north arrows, scale bars, and page sizes."""
    payload = {
        "palettes": list_palettes(),
        "composites": list_composites(),
        "spectral_indices": list_spectral_indices(),
        "arrow_styles": list_arrow_styles(),
        "scalebar_styles": list_scalebar_styles(),
        "page_sizes": list_page_sizes(),
    }
    if json_out:
        typer.echo(json.dumps(payload, indent=2))
        return

    for heading, rows, cols in (
        ("Color Palettes (--palette)", payload["palettes"], ("name", "colors")),
        ("Multiband Optical Composites (--composite)", payload["composites"], ("name", "bands", "description")),
        ("Spectral Indices (lulc bands --index)", payload["spectral_indices"], ("name", "bands", "formula")),
        ("North Arrow Styles (--arrow-style)", payload["arrow_styles"], ("name", "description")),
        ("Scale Bar Styles (--scalebar-style)", payload["scalebar_styles"], ("name", "description")),
        ("Print Page Sizes (--page-size)", payload["page_sizes"], ("name", "dimensions")),
    ):
        t = Table(title=heading)
        for col in cols:
            t.add_column(col.replace("_", " ").title(), style="bold cyan" if col == "name" else None, no_wrap=(col == "name"))
        for r in rows:
            t.add_row(*(str(r[col]) for col in cols))
        console.print(t)


@app.command("map")
def map_cmd(
    tiff_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Input TIFF or GeoTIFF."),
    output_dir: Path = typer.Option(Path("./lulc_out"), "-o", "--output-dir", help="Directory for output files.", rich_help_panel="Outputs & Export"),
    name: Optional[str] = typer.Option(None, "--name", help="Output filename prefix (defaults to input stem).", rich_help_panel="Outputs & Export"),
    map_format: str = typer.Option("png", "--map-format", help="Graphic export format: png, pdf, or svg.", rich_help_panel="Outputs & Export"),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Render LULC map graphic.", rich_help_panel="Outputs & Export"),
    html: bool = typer.Option(False, "--html", help="Export GeoLibre-inspired interactive MapLibre GL JS HTML map.", rich_help_panel="Outputs & Export"),
    vector: bool = typer.Option(False, "--vector", help="Export polygonized LULC GeoJSON.", rich_help_panel="Outputs & Export"),
    min_area_pixels: int = typer.Option(4, "--min-area-pixels", help="Minimum polygon size in pixels for --vector.", rich_help_panel="Outputs & Export"),
    save_confidence: bool = typer.Option(False, "--save-confidence", help="Write uint8 0-100% confidence GeoTIFF.", rich_help_panel="Outputs & Export"),
    model: str = typer.Option("auto", "--model", "-m", help="Model: auto, rgb-oem, rgb-fast, s2-dw, or categorical.", rich_help_panel="Model & Inference"),
    hf_model: Optional[str] = typer.Option(None, "--hf-model", help="Custom Hugging Face SegFormer repo ID.", rich_help_panel="Model & Inference"),
    device: str = typer.Option("auto", "--device", help="Device: auto, cpu, cuda, or mps.", rich_help_panel="Model & Inference"),
    tile_size: int = typer.Option(512, "--tile-size", help="Inference tile size (multiple of 32, >= 64).", rich_help_panel="Model & Inference"),
    overlap: int = typer.Option(64, "--overlap", help="Halo overlap pixels discarded around each tile core.", rich_help_panel="Model & Inference"),
    batch_size: int = typer.Option(4, "--batch-size", help="Number of tiles per inference batch.", rich_help_panel="Model & Inference"),
    rgb_bands: Optional[str] = typer.Option(None, "--rgb-bands", help="1-based R,G,B bands (e.g. 1,2,3 or 4,3,2).", rich_help_panel="Bands & Styling"),
    s2_bands: Optional[str] = typer.Option(None, "--s2-bands", help="1-based 9 Sentinel-2 bands (B2,B3,B4,B5,B6,B7,B8,B11,B12).", rich_help_panel="Bands & Styling"),
    composite: Optional[str] = typer.Option(None, "--composite", help="Multiband display preset: true-color, false-color-nir, agriculture, or swir.", rich_help_panel="Bands & Styling"),
    palette: str = typer.Option("default", "--palette", help="Color palette (default, arcgis-crop, vivid, earth, pastel, colorblind, or Matplotlib colormap).", rich_help_panel="Bands & Styling"),
    class_labels: Optional[str] = typer.Option(None, "--class-labels", help="Class labels as id:Label (e.g. '0:Non Boro,1:Early,2:Late').", rich_help_panel="Bands & Styling"),
    class_colors: Optional[str] = typer.Option(None, "--class-colors", help="Class colors as id:#RRGGBB (e.g. '0:#FFFFFF,1:#38A800').", rich_help_panel="Bands & Styling"),
    nodata_value: Optional[int] = typer.Option(None, "--nodata-value", help="Integer value in categorical input to mask as nodata.", rich_help_panel="Bands & Styling"),
    title: Optional[str] = typer.Option(None, "--title", help="Map title rendered inside print layout.", rich_help_panel="Cartography & Page Layout"),
    layout: str = typer.Option("auto", "--layout", help="Map layout: auto, print, or side-by-side.", rich_help_panel="Cartography & Page Layout"),
    page_size: str = typer.Option("a4", "--page-size", help="Print page size: auto, a4, a5, a3, letter, legal, or square.", rich_help_panel="Cartography & Page Layout"),
    orientation: str = typer.Option("auto", "--orientation", help="Page orientation: auto, portrait, or landscape.", rich_help_panel="Cartography & Page Layout"),
    arrow_style: str = typer.Option("compass", "--arrow-style", help="North arrow style: compass, classic, fancy, minimal, or none.", rich_help_panel="Cartography & Page Layout"),
    arrow_pos: str = typer.Option("top-right", "--arrow-pos", help="North arrow position: top-right, top-left, bottom-right, bottom-left.", rich_help_panel="Cartography & Page Layout"),
    scalebar_style: str = typer.Option("arcgis", "--scalebar-style", help="Scale bar style: arcgis, alternating, simple, or none.", rich_help_panel="Cartography & Page Layout"),
    legend_pos: str = typer.Option("bottom-left", "--legend-pos", help="Legend position: bottom-left, bottom-right, top-left, top-right, outside.", rich_help_panel="Cartography & Page Layout"),
    legend_areas: bool = typer.Option(False, "--legend-areas", help="Show % and ha values inside the map legend.", rich_help_panel="Cartography & Page Layout"),
    grid: bool = typer.Option(True, "--grid/--no-grid", help="Show X/Y numerical coordinate axes and gridlines on print map.", rich_help_panel="Cartography & Page Layout"),
    boundary: Optional[Path] = typer.Option(None, "--boundary", exists=True, dir_okay=False, readable=True, help="Optional GeoJSON boundary overlay.", rich_help_panel="Cartography & Page Layout"),
    boundary_label: Optional[str] = typer.Option(None, "--boundary-label", help="Legend label for --boundary.", rich_help_panel="Cartography & Page Layout"),
    dpi: int = typer.Option(300, "--dpi", help="Export resolution DPI for map graphic.", rich_help_panel="Cartography & Page Layout"),
) -> None:
    """Classify or style any TIFF/GeoTIFF into a GIS-ready LULC map and metadata bundle."""
    fmt, lay, ps, ori = _validate_map_options(map_format, layout, page_size, orientation, arrow_style, scalebar_style)
    rgb_list = _parse_band_list(rgb_bands, 3, "--rgb-bands")
    s2_list = _parse_band_list(s2_bands, 9, "--s2-bands")
    labels_map = _parse_class_labels(class_labels)
    colors_map = _parse_class_colors(class_colors)

    try:
        _execute_map(
            tiff_path,
            output_dir=output_dir,
            name=name,
            title=title,
            model=model,
            hf_model=hf_model,
            device=device,
            tile_size=tile_size,
            overlap=overlap,
            batch_size=batch_size,
            rgb_list=rgb_list,
            s2_list=s2_list,
            composite=composite,
            palette=palette,
            labels_map=labels_map,
            colors_map=colors_map,
            nodata_value=nodata_value,
            arrow_style=arrow_style,
            arrow_pos=arrow_pos,
            scalebar_style=scalebar_style,
            legend_pos=legend_pos,
            legend_areas=legend_areas,
            grid=grid,
            layout=lay,
            page_size=ps,
            orientation=ori,
            map_format=fmt,
            dpi=dpi,
            boundary=boundary,
            boundary_label=boundary_label,
            html=html,
            save_confidence=save_confidence,
            vector=vector,
            min_area_pixels=min_area_pixels,
            preview=preview,
            print_summary=True,
        )
    except (UnsupportedRasterError, ValueError) as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc


@app.command("batch")
def batch_cmd(
    input_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True, help="Directory of TIFF/GeoTIFF files."),
    output_dir: Path = typer.Option(Path("./lulc_batch_out"), "-o", "--output-dir", help="Parent output directory."),
    pattern: Optional[str] = typer.Option(None, "--pattern", help="Filename glob pattern (defaults to *.tif and *.tiff)."),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Search subdirectories recursively."),
    model: str = typer.Option("auto", "--model", "-m", help="Model: auto, rgb-oem, rgb-fast, s2-dw, or categorical."),
    palette: str = typer.Option("default", "--palette", help="Color palette or Matplotlib colormap."),
    page_size: str = typer.Option("a4", "--page-size", help="Print page size: auto, a4, a5, a3, letter, legal, or square."),
    orientation: str = typer.Option("auto", "--orientation", help="Page orientation: auto, portrait, or landscape."),
    arrow_style: str = typer.Option("compass", "--arrow-style", help="North arrow style: compass, classic, fancy, minimal, or none."),
    scalebar_style: str = typer.Option("arcgis", "--scalebar-style", help="Scale bar style: arcgis, alternating, simple, or none."),
    map_format: str = typer.Option("png", "--map-format", help="Graphic export format: png, pdf, or svg."),
    html: bool = typer.Option(False, "--html", help="Export interactive MapLibre HTML map per raster."),
    vector: bool = typer.Option(False, "--vector", help="Export polygonized GeoJSON per raster."),
    continue_on_error: bool = typer.Option(True, "--continue-on-error/--fail-fast", help="Continue processing remaining files on error."),
) -> None:
    """Process a folder of TIFF/GeoTIFF files in one batch and print a summary table."""
    fmt, lay, ps, ori = _validate_map_options(map_format, "auto", page_size, orientation, arrow_style, scalebar_style)

    globs = [pattern] if pattern else ["*.tif", "*.tiff"]
    seen: dict[Path, None] = {}
    for g in globs:
        matches = input_dir.rglob(g) if recursive else input_dir.glob(g)
        for p in sorted(matches):
            if p.is_file():
                seen[p.resolve()] = None
    files = list(seen.keys())

    if not files:
        err_console.print(f"[yellow]No TIFF files matched in {input_dir}[/yellow]")
        raise typer.Exit(code=1)

    results: list[dict[str, str]] = []
    failures = 0

    for tif in files:
        sub_out = output_dir / tif.stem
        try:
            rep = _execute_map(
                tif,
                output_dir=sub_out,
                model=model,
                palette=palette,
                arrow_style=arrow_style,
                scalebar_style=scalebar_style,
                layout=lay,
                page_size=ps,
                orientation=ori,
                map_format=fmt,
                html=html,
                vector=vector,
                print_summary=False,
            )
            area_ha = rep["geospatial"]["valid_area_ha"]
            results.append(
                {
                    "file": tif.name,
                    "status": "[green]ok[/green]",
                    "model": str(rep["inference"]["model"]),
                    "dominant": str(rep["lulc"]["dominant_class"] or "-"),
                    "area": f"{area_ha:,.2f} ha" if area_ha is not None else "-",
                    "time": f"{rep['inference']['runtime_seconds']:.2f}s",
                    "out": str(sub_out),
                }
            )
        except Exception as exc:
            failures += 1
            results.append(
                {
                    "file": tif.name,
                    "status": "[red]error[/red]",
                    "model": "-",
                    "dominant": str(exc)[:40],
                    "area": "-",
                    "time": "-",
                    "out": "-",
                }
            )
            if not continue_on_error:
                break

    b_table = Table(title=f"Batch Summary ({len(results)}/{len(files)} processed)")
    for col in ("File", "Status", "Model", "Dominant", "Valid Area", "Time", "Output Dir"):
        b_table.add_column(col)
    for r in results:
        b_table.add_row(r["file"], r["status"], r["model"], r["dominant"], r["area"], r["time"], r["out"])
    console.print(b_table)

    if failures == len(files) or (failures > 0 and not continue_on_error):
        raise typer.Exit(code=2)


@app.command("wizard")
def wizard_cmd(
    tiff_path: Optional[Path] = typer.Argument(None, help="Optional input TIFF/GeoTIFF path."),
) -> None:
    """Interactive guided workflow to configure bands, palette, layout, and run `lulc map`."""
    wiz_console = Console()

    if tiff_path is None:
        raw_path = Prompt.ask("Path to TIFF/GeoTIFF", console=wiz_console).strip().strip('"')
        tiff_path = Path(raw_path)
    if not tiff_path.is_file():
        err_console.print(f"[bold red]Error:[/bold red] File not found: {tiff_path}")
        raise typer.Exit(code=2)

    profile = inspect_tiff(tiff_path)
    crs_str = f"EPSG:{profile.crs_epsg}" if profile.crs_epsg else (profile.crs_name or "None")
    gsd_str = f"{profile.gsd_meters[0]:.2f}×{profile.gsd_meters[1]:.2f} m" if profile.gsd_meters else "N/A"
    wiz_console.print(
        f"\n[bold cyan]{profile.file_name}[/bold cyan] — {profile.width:,}×{profile.height:,} px, "
        f"{profile.band_count} band(s), CRS: {crs_str}, GSD: {gsd_str}, profile: [bold]{profile.detected_profile}[/bold]\n"
    )

    default_model = profile.recommended_model or "auto"
    chosen_model = Prompt.ask(
        "Model (auto, rgb-oem, rgb-fast, s2-dw, categorical)",
        default=default_model,
        console=wiz_console,
    ).strip()

    rgb_raw: str | None = None
    s2_raw: str | None = None
    if chosen_model in ("rgb-oem", "rgb-fast") or (chosen_model == "auto" and profile.recommended_model in ("rgb-oem", "rgb-fast")):
        if profile.band_count > 3 and profile.rgb_bands:
            default_rgb = ",".join(str(b) for b in profile.rgb_bands)
            ans_rgb = Prompt.ask("RGB band indices (R,G,B)", default=default_rgb, console=wiz_console).strip()
            if ans_rgb != default_rgb:
                rgb_raw = ans_rgb
    elif chosen_model == "s2-dw" and profile.s2_bands:
        default_s2 = ",".join(str(b) for b in profile.s2_bands)
        ans_s2 = Prompt.ask("Sentinel-2 9 band indices (B2..B8,B11,B12)", default=default_s2, console=wiz_console).strip()
        if ans_s2 != default_s2:
            s2_raw = ans_s2

    chosen_palette = Prompt.ask(
        "Color palette (default, arcgis-crop, vivid, earth, pastel, colorblind, or Matplotlib cmap)",
        default="default",
        console=wiz_console,
    ).strip()
    chosen_title = Prompt.ask("Map title", default=tiff_path.stem, console=wiz_console).strip()
    chosen_page = Prompt.ask("Page size (a4, a5, a3, letter, legal, square)", default="a4", console=wiz_console).strip()
    chosen_ori = Prompt.ask("Orientation (auto, portrait, landscape)", default="auto", console=wiz_console).strip()
    chosen_arrow = Prompt.ask("North arrow (compass, classic, fancy, minimal, none)", default="compass", console=wiz_console).strip()
    chosen_sb = Prompt.ask("Scale bar (arcgis, alternating, simple, none)", default="arcgis", console=wiz_console).strip()
    chosen_html = Confirm.ask("Export interactive MapLibre HTML map?", default=bool(profile.is_georeferenced), console=wiz_console)
    chosen_out = Prompt.ask("Output directory", default=f"./lulc_out/{tiff_path.stem}", console=wiz_console).strip()

    fmt, lay, ps, ori = _validate_map_options("png", "auto", chosen_page, chosen_ori, chosen_arrow, chosen_sb)
    rgb_list = _parse_band_list(rgb_raw, 3, "--rgb-bands")
    s2_list = _parse_band_list(s2_raw, 9, "--s2-bands")

    cmd_parts = [
        "lulc", "map", str(tiff_path),
        "-o", chosen_out,
        "--model", chosen_model,
        "--palette", chosen_palette,
        "--title", chosen_title,
        "--page-size", ps,
        "--orientation", ori,
        "--arrow-style", chosen_arrow,
        "--scalebar-style", chosen_sb,
    ]
    if rgb_raw:
        cmd_parts.extend(["--rgb-bands", rgb_raw])
    if s2_raw:
        cmd_parts.extend(["--s2-bands", s2_raw])
    if chosen_html:
        cmd_parts.append("--html")
    wiz_console.print(f"\n[bold]Equivalent command:[/bold] [dim]{shlex.join(cmd_parts)}[/dim]\n")

    try:
        _execute_map(
            tiff_path,
            output_dir=Path(chosen_out),
            title=chosen_title,
            model=chosen_model,
            rgb_list=rgb_list,
            s2_list=s2_list,
            palette=chosen_palette,
            arrow_style=chosen_arrow,
            scalebar_style=chosen_sb,
            layout=lay,
            page_size=ps,
            orientation=ori,
            map_format=fmt,
            html=chosen_html,
            print_summary=True,
        )
    except (UnsupportedRasterError, ValueError) as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc
