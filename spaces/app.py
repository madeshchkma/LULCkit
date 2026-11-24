"""Hugging Face Spaces Gradio app backed directly by lulckit."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import spaces  # Hugging Face ZeroGPU runtime

    _gpu = getattr(spaces, "GPU", None)
except ImportError:
    _gpu = None

if _gpu is None:
    def _gpu(fn: Any) -> Any:
        return fn

# Fallback to local repo src/ when running from a checkout without pip install -e .
_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from lulckit.bands import (  # noqa: E402
    export_band_view,
    export_spectral_index,
)
from lulckit.cartography import resolve_composite_bands  # noqa: E402
from lulckit.cli import (  # noqa: E402
    _execute_map,
    _parse_band_list,
    _parse_class_colors,
    _parse_class_labels,
)
from lulckit.inspect import inspect_tiff  # noqa: E402


def _normalize_file_path(file_input: Any) -> Path:
    if file_input is None:
        raise ValueError("Please upload a .tif or .tiff GeoTIFF file.")
    if isinstance(file_input, (str, Path)):
        p = Path(file_input)
    else:
        p = Path(getattr(file_input, "name", None) or str(file_input))
    if not p.is_file():
        raise FileNotFoundError(f"Uploaded file not found: {p}")
    return p


def run_inspect_space(file_input: Any) -> tuple[str, dict[str, Any]]:
    """Inspect uploaded GeoTIFF and return formatted summary + full JSON profile."""
    tiff_path = _normalize_file_path(file_input)
    profile = inspect_tiff(tiff_path)
    payload = profile.to_dict()
    epsg = f"EPSG:{profile.crs_epsg} ({profile.crs_name})" if profile.crs_epsg else (profile.crs_name or "Unreferenced")
    gsd = f"{profile.gsd_meters[0]:.3f} × {profile.gsd_meters[1]:.3f} m/px" if profile.gsd_meters else "N/A"
    area = (
        f"{profile.valid_area_m2 / 10_000.0:,.2f} ha ({profile.valid_area_m2 / 1_000_000.0:,.4f} km²)"
        if profile.valid_area_m2 is not None
        else "N/A"
    )
    summary = (
        f"### {profile.file_name}\n"
        f"- **Dimensions:** `{profile.width:,} × {profile.height:,} px` (`{profile.band_count}` band(s), `{profile.file_size_bytes / 1_048_576:.2f} MB`)\n"
        f"- **CRS:** `{epsg}`\n"
        f"- **GSD / Valid Area:** `{gsd}` · `{area}`\n"
        f"- **Detected Profile:** `{profile.detected_profile}` -> recommended model: `{profile.recommended_model}`"
    )
    return summary, payload


def run_map_space(
    file_input: Any,
    *,
    model: str = "auto",
    title: str = "",
    palette: str = "arcgis-crop",
    class_labels: str = "",
    class_colors: str = "",
    nodata_value: str = "",
    page_size: str = "a4",
    orientation: str = "auto",
    arrow_style: str = "compass",
    scalebar_style: str = "arcgis",
    show_grid: bool = True,
    export_html: bool = True,
    export_vector: bool = False,
) -> tuple[str | None, str | None, str | None, str | None, str | None, list[list[Any]], dict[str, Any]]:
    """Run LULCkit full map pipeline and return preview, files, table rows, and JSON report."""
    tiff_path = _normalize_file_path(file_input)
    work_dir = Path(tempfile.mkdtemp(prefix="lulckit_space_"))

    nd_val: int | None = int(nodata_value.strip()) if nodata_value and nodata_value.strip() else None
    labels_map = _parse_class_labels(class_labels.strip() or None)
    colors_map = _parse_class_colors(class_colors.strip() or None)

    report = _execute_map(
        tiff_path,
        output_dir=work_dir,
        title=title.strip() or None,
        model=model.strip() or "auto",
        device="auto",
        palette=palette.strip() or "default",
        labels_map=labels_map,
        colors_map=colors_map,
        nodata_value=nd_val,
        arrow_style=arrow_style,
        scalebar_style=scalebar_style,
        grid=bool(show_grid),
        page_size=page_size,
        orientation=orientation,
        map_format="png",
        dpi=200,
        html=bool(export_html),
        vector=bool(export_vector),
        print_summary=False,
    )

    out_files = report.get("output_files", {})
    rows = [
        [
            c["id"],
            c["name"],
            c["hex"],
            c["pixels"],
            c["percent"],
            c["area_ha"],
            c["area_km2"],
        ]
        for c in report.get("lulc", {}).get("classes", [])
    ]
    return (
        out_files.get("preview_png"),
        out_files.get("lulc_geotiff"),
        out_files.get("summary_csv"),
        out_files.get("report_json"),
        out_files.get("interactive_html"),
        rows,
        report,
    )


def run_bands_space(
    file_input: Any,
    *,
    mode: str = "Spectral Index",
    index_name: str = "ndvi",
    composite_name: str = "false-color-nir",
    rgb_bands: str = "1,2,3",
    single_band: int = 1,
    cmap_name: str = "viridis",
    title: str = "",
    page_size: str = "a4",
) -> tuple[str, str, str]:
    """Run LULCkit bands/index export in a temporary folder."""
    tiff_path = _normalize_file_path(file_input)
    profile = inspect_tiff(tiff_path)
    work_dir = Path(tempfile.mkdtemp(prefix="lulckit_bands_"))
    stem = tiff_path.stem
    out_tif = work_dir / f"{stem}_band_out.tif"
    out_png = work_dir / f"{stem}_band_preview.png"

    if mode == "Spectral Index":
        stats = export_spectral_index(
            input_path=tiff_path,
            profile=profile,
            index_name=index_name,
            output_tif=out_tif,
            output_preview=out_png,
            cmap_name=cmap_name if cmap_name != "auto" else None,
            title=title.strip() or None,
            page_size=page_size,
            dpi=200,
        )
        msg = (
            f"Computed **{index_name.upper()}**: `min={stats['min']}`, `max={stats['max']}`, "
            f"`mean={stats['mean']}`, `std={stats['std']}` ({stats['valid_pixels']:,} valid pixels)"
        )
        return str(out_png), str(out_tif), msg

    if mode == "Optical Composite":
        chosen, tag = resolve_composite_bands(profile, composite_name)
    elif mode == "Custom 3-Band RGB":
        chosen = _parse_band_list(rgb_bands, 3, "rgb_bands") or [1, 2, 3]
        tag = f"RGB {chosen}"
    else:
        chosen = [int(single_band)]
        tag = f"Band {single_band}"

    export_band_view(
        input_path=tiff_path,
        profile=profile,
        band_indices=chosen,
        output_tif=out_tif,
        output_preview=out_png,
        cmap_name=cmap_name if cmap_name != "auto" else "viridis",
        title=title.strip() or f"{profile.file_name} — {tag}",
        page_size=page_size,
        dpi=200,
    )
    return str(out_png), str(out_tif), f"Exported **{tag}** (`bands={chosen}`) successfully."


@_gpu
def _gradio_run_map(
    f: Any,
    m: str,
    t: str,
    p: str,
    l: str,
    c: str,
    n: str,
    ps: str,
    o: str,
    a: str,
    s: str,
    g: bool,
    h: bool,
    v: bool,
) -> tuple[str | None, str | None, str | None, str | None, str | None, list[list[Any]], dict[str, Any]]:
    return run_map_space(
        f,
        model=m,
        title=t,
        palette=p,
        class_labels=l,
        class_colors=c,
        nodata_value=n,
        page_size=ps,
        orientation=o,
        arrow_style=a,
        scalebar_style=s,
        show_grid=g,
        export_html=h,
        export_vector=v,
    )


def _gradio_run_bands(
    f: Any,
    md: str,
    idx: str,
    cmp_: str,
    rgb: str,
    sb: float | int | None,
    cm: str,
    t: str,
    ps: str,
) -> tuple[str, str, str]:
    return run_bands_space(
        f,
        mode=md,
        index_name=idx,
        composite_name=cmp_,
        rgb_bands=rgb,
        single_band=int(sb or 1),
        cmap_name=cm,
        title=t,
        page_size=ps,
    )


def build_app() -> Any:
    """Construct the Gradio Blocks UI (imports gradio lazily for headless testing)."""
    import gradio as gr

    with gr.Blocks(title="LULCkit Studio", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# LULCkit Studio\n"
            "Upload any optical (RGB / Sentinel-2) or pre-classified categorical `.tif` / `.tiff` GeoTIFF to generate "
            "publication print maps, GeoTIFF colormaps, spectral indices, and area analytics."
        )

        with gr.Tab("LULC Map Generator"):
            with gr.Row():
                with gr.Column(scale=1):
                    map_file = gr.File(label="Upload TIFF / GeoTIFF", file_types=[".tif", ".tiff"])
                    map_model = gr.Dropdown(["auto", "categorical", "rgb-fast", "rgb-oem", "s2-dw"], value="auto", label="Model")
                    map_title = gr.Textbox(label="Map Title (optional)", placeholder="Boro Area Mapping for Bogura - 2026")
                    map_palette = gr.Dropdown(["arcgis-crop", "default", "vivid", "earth", "pastel", "colorblind"], value="arcgis-crop", label="Palette")
                    map_labels = gr.Textbox(label="Class Labels (id:Name,...)", placeholder="0:Non Boro,1:Early Boro,2:Late Boro")
                    map_colors = gr.Textbox(label="Class Colors (id:#RRGGBB,...)", placeholder="0:#FFFFFF,1:#38A800,2:#E60000")
                    map_nodata = gr.Textbox(label="Extra Nodata Integer (optional)")
                    with gr.Row():
                        map_page = gr.Dropdown(["a4", "a5", "a3", "letter", "legal", "square"], value="a4", label="Page Size")
                        map_ori = gr.Dropdown(["auto", "landscape", "portrait"], value="auto", label="Orientation")
                    with gr.Row():
                        map_arrow = gr.Dropdown(["compass", "classic", "fancy", "minimal", "none"], value="compass", label="North Arrow")
                        map_scale = gr.Dropdown(["arcgis", "alternating", "simple", "none"], value="arcgis", label="Scale Bar")
                    with gr.Row():
                        map_grid = gr.Checkbox(value=True, label="X/Y Coordinate Axes")
                        map_html = gr.Checkbox(value=True, label="Export MapLibre HTML")
                        map_vec = gr.Checkbox(value=False, label="Export Vector GeoJSON")
                    map_btn = gr.Button("Generate LULC Map", variant="primary")

                with gr.Column(scale=2):
                    out_preview = gr.Image(label="Publication Map Preview", type="filepath")
                    with gr.Row():
                        out_tif = gr.File(label="LULC GeoTIFF")
                        out_csv = gr.File(label="Summary CSV")
                        out_json_file = gr.File(label="Report JSON")
                        out_html = gr.File(label="Interactive HTML Map")
                    out_table = gr.Dataframe(
                        headers=["ID", "Class Name", "Hex", "Pixels", "Share (%)", "Area (ha)", "Area (km²)"],
                        label="Class Area Breakdown",
                    )
                    out_report = gr.JSON(label="Metadata & Inference Report")

            map_btn.click(
                fn=_gradio_run_map,
                inputs=[
                    map_file, map_model, map_title, map_palette, map_labels, map_colors, map_nodata,
                    map_page, map_ori, map_arrow, map_scale, map_grid, map_html, map_vec,
                ],
                outputs=[out_preview, out_tif, out_csv, out_json_file, out_html, out_table, out_report],
            )

        with gr.Tab("Bands & Spectral Indices"):
            with gr.Row():
                with gr.Column(scale=1):
                    b_file = gr.File(label="Upload Optical GeoTIFF", file_types=[".tif", ".tiff"])
                    b_mode = gr.Radio(["Spectral Index", "Optical Composite", "Custom 3-Band RGB", "Single Band"], value="Spectral Index", label="Operation")
                    b_index = gr.Dropdown(["ndvi", "ndwi", "ndbi", "savi", "evi"], value="ndvi", label="Spectral Index")
                    b_comp = gr.Dropdown(["true-color", "false-color-nir", "agriculture", "swir"], value="false-color-nir", label="Optical Composite")
                    b_rgb = gr.Textbox(value="1,2,3", label="Custom RGB Bands (1-based)")
                    b_single = gr.Number(value=1, precision=0, label="Single Band Index (1-based)")
                    b_cmap = gr.Dropdown(["auto", "viridis", "RdYlGn", "Blues", "RdBu", "gray"], value="auto", label="Colormap")
                    b_title = gr.Textbox(label="Map Title (optional)")
                    b_page = gr.Dropdown(["a4", "a5", "a3", "letter", "square"], value="a4", label="Page Size")
                    b_btn = gr.Button("Process Bands", variant="primary")
                with gr.Column(scale=2):
                    b_preview = gr.Image(label="Rendered Output", type="filepath")
                    b_tif = gr.File(label="Output GeoTIFF")
                    b_msg = gr.Markdown()

            b_btn.click(
                fn=_gradio_run_bands,
                inputs=[b_file, b_mode, b_index, b_comp, b_rgb, b_single, b_cmap, b_title, b_page],
                outputs=[b_preview, b_tif, b_msg],
            )

        with gr.Tab("TIFF Inspector"):
            ins_file = gr.File(label="Upload TIFF / GeoTIFF", file_types=[".tif", ".tiff"])
            ins_btn = gr.Button("Inspect Metadata & Bands", variant="primary")
            ins_md = gr.Markdown()
            ins_json = gr.JSON(label="Full Geospatial JSON Profile")
            ins_btn.click(fn=run_inspect_space, inputs=[ins_file], outputs=[ins_md, ins_json])

    return demo


if __name__ == "__main__":
    build_app().launch()
