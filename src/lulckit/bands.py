"""Band extraction, multiband composites, spectral indices, and GeoJSON raster clipping."""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.mask import mask as rasterio_mask
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from lulckit import __version__
from lulckit.cartography import (
    _load_boundary_geometries,
    _save_figure,
    draw_north_arrow,
    draw_scale_bar,
    resolve_page_figsize,
)
from lulckit.geo import decimated_shape, normalize_rgb_to_uint8

if TYPE_CHECKING:
    from lulckit.inspect import TiffProfile


SPECTRAL_INDICES: dict[str, dict[str, Any]] = {
    "ndvi": {
        "roles": ("nir", "red"),
        "formula": "(NIR - Red) / (NIR + Red)",
        "cmap": "RdYlGn",
        "range": (-1.0, 1.0),
        "description": "Normalized Difference Vegetation Index",
    },
    "ndwi": {
        "roles": ("green", "nir"),
        "formula": "(Green - NIR) / (Green + NIR)",
        "cmap": "RdBu",
        "range": (-1.0, 1.0),
        "description": "Normalized Difference Water Index (McFeeters)",
    },
    "ndbi": {
        "roles": ("swir1", "nir"),
        "formula": "(SWIR1 - NIR) / (SWIR1 + NIR)",
        "cmap": "RdYlBu_r",
        "range": (-1.0, 1.0),
        "description": "Normalized Difference Built-up Index",
    },
    "savi": {
        "roles": ("nir", "red"),
        "formula": "1.5 * (NIR - Red) / (NIR + Red + 0.5)",
        "cmap": "RdYlGn",
        "range": (-1.0, 1.0),
        "description": "Soil-Adjusted Vegetation Index (L=0.5)",
    },
    "evi": {
        "roles": ("nir", "red", "blue"),
        "formula": "2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1.0)",
        "cmap": "RdYlGn",
        "range": (-1.0, 1.0),
        "description": "Enhanced Vegetation Index",
    },
}


def list_spectral_indices() -> list[dict[str, str]]:
    """Return supported spectral indices and formulas for `lulc styles`."""
    return [
        {
            "name": k,
            "bands": ", ".join(v["roles"]),
            "formula": v["formula"],
            "description": v["description"],
        }
        for k, v in SPECTRAL_INDICES.items()
    ]


def _reflectance_divisor(profile: TiffProfile, band_indices: list[int]) -> float:
    """Return scale divisor to bring DN/TOA reflectance into [0..1] for SAVI/EVI."""
    p98_vals = [
        profile.bands[b - 1].p98
        for b in band_indices
        if profile.bands[b - 1].p98 is not None
    ]
    max_p98 = max(p98_vals) if p98_vals else 1.0
    if max_p98 <= 2.0:
        return 1.0
    dtypes = {profile.bands[b - 1].dtype for b in band_indices}
    if dtypes == {"uint8"} or max_p98 <= 255.0:
        return 255.0
    return 10000.0


def _compute_index_array(
    index_key: str,
    bands_dict: dict[str, np.ndarray],
    valid_mask: np.ndarray,
    refl_div: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute clipped float32 spectral index and boolean valid mask."""
    if index_key == "ndvi":
        a, b = bands_dict["nir"], bands_dict["red"]
        num, den = a - b, a + b
    elif index_key == "ndwi":
        a, b = bands_dict["green"], bands_dict["nir"]
        num, den = a - b, a + b
    elif index_key == "ndbi":
        a, b = bands_dict["swir1"], bands_dict["nir"]
        num, den = a - b, a + b
    elif index_key == "savi":
        nir = bands_dict["nir"] / refl_div
        red = bands_dict["red"] / refl_div
        num, den = 1.5 * (nir - red), nir + red + 0.5
    elif index_key == "evi":
        nir = bands_dict["nir"] / refl_div
        red = bands_dict["red"] / refl_div
        blue = bands_dict["blue"] / refl_div
        num, den = 2.5 * (nir - red), nir + 6.0 * red - 7.5 * blue + 1.0
    else:
        raise ValueError(f"Unsupported spectral index: {index_key}")

    good = valid_mask & np.isfinite(num) & np.isfinite(den) & (np.abs(den) > 1e-6)
    out = np.full(num.shape, -9999.0, dtype=np.float32)
    if np.any(good):
        out[good] = np.clip(num[good] / den[good], -1.0, 1.0).astype(np.float32)
    return out, good


def _render_array_print_map(
    profile: TiffProfile,
    img_data: np.ndarray,
    output_path: Path,
    *,
    title: str,
    cmap_name: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    colorbar_label: str | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
    arrow_style: str = "compass",
    scalebar_style: str = "arcgis",
    show_grid: bool = True,
    dpi: int = 300,
) -> None:
    """Render a full-page cartographic figure for a 3-band RGB or 1-band scalar raster."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if profile.is_georeferenced and profile.bounds_native:
        left, bottom, right, top = profile.bounds_native
    else:
        left, bottom, right, top = 0.0, 0.0, float(profile.width), float(profile.height)

    dx = max(right - left, 1e-9)
    dy = max(top - bottom, 1e-9)
    fig_w, fig_h = resolve_page_figsize(page_size, orientation, dx / dy)
    font_scale = max(0.72, min(1.35, min(fig_w, fig_h) / 8.27))

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor="white")
    has_cbar = cmap_name is not None and img_data.ndim == 2
    if show_grid:
        ax_l = 0.125 if fig_w >= 8.0 else 0.155
        ax_r = 0.13 if has_cbar else 0.03
        ax_b = 0.075 if fig_h >= 8.0 else 0.09
        ax_t = 0.03
    else:
        ax_l = 0.03
        ax_r = 0.13 if has_cbar else 0.03
        ax_b = 0.03
        ax_t = 0.03
    ax_w = 1.0 - ax_l - ax_r
    ax_h = 1.0 - ax_b - ax_t

    ax = fig.add_axes([ax_l, ax_b, ax_w, ax_h], facecolor="white")
    imshow_kw: dict[str, Any] = {
        "extent": [left, right, bottom, top],
        "aspect": "equal",
        "origin": "upper",
        "zorder": 1,
    }
    if has_cbar:
        cmap_obj = matplotlib.colormaps[cmap_name].copy()
        cmap_obj.set_bad(color="#F2F4F7")
        imshow_kw["cmap"] = cmap_obj
        if vmin is not None:
            imshow_kw["vmin"] = vmin
        if vmax is not None:
            imshow_kw["vmax"] = vmax

    im = ax.imshow(img_data, **imshow_kw)

    box_aspect = (ax_w * fig_w) / (ax_h * fig_h)
    min_x_span = dx * 1.08
    min_y_span = dy * 1.28
    if (min_x_span / min_y_span) < box_aspect:
        y_span = min_y_span
        x_span = y_span * box_aspect
    else:
        x_span = min_x_span
        y_span = x_span / box_aspect

    cx = 0.5 * (left + right)
    x_min, x_max = cx - 0.5 * x_span, cx + 0.5 * x_span
    extra_y = y_span - dy
    top_pad = max(0.12 * dy, 0.38 * extra_y)
    bottom_pad = extra_y - top_pad
    y_min, y_max = bottom - bottom_pad, top + top_pad
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("#111111")
        spine.set_linewidth(1.25)

    if show_grid:
        if profile.is_georeferenced:
            if profile.crs_is_projected:
                ax.set_xlabel("Easting (m)", fontsize=9.5 * font_scale, fontweight="bold", labelpad=6)
                ax.set_ylabel("Northing (m)", fontsize=9.5 * font_scale, fontweight="bold", labelpad=6)
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
                ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
            else:
                ax.set_xlabel("Longitude (°)", fontsize=9.5 * font_scale, fontweight="bold", labelpad=6)
                ax.set_ylabel("Latitude (°)", fontsize=9.5 * font_scale, fontweight="bold", labelpad=6)
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.3f}°"))
                ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.3f}°"))
        else:
            ax.set_xlabel("Column (px)", fontsize=9.5 * font_scale, fontweight="bold", labelpad=6)
            ax.set_ylabel("Row (px)", fontsize=9.5 * font_scale, fontweight="bold", labelpad=6)
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.tick_params(
            labelsize=8.5 * font_scale,
            direction="out",
            length=4,
            width=0.9,
            top=True,
            right=True,
            labeltop=False,
            labelright=False,
        )
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.35, color="#777777")
    else:
        ax.set_xticks([])
        ax.set_yticks([])

    ax.text(
        0.50,
        0.955,
        title,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=14.5 * font_scale,
        fontweight="bold",
        color="#111111",
        zorder=8,
    )

    arrow_in = 1.2 * font_scale
    draw_north_arrow(
        ax,
        style=arrow_style,
        pos="top-right",
        box_w_frac=min(0.24, arrow_in / (ax_w * fig_w)),
        box_h_frac=min(0.24, arrow_in / (ax_h * fig_h)),
        font_scale=font_scale,
    )
    draw_scale_bar(
        ax,
        profile,
        (left, bottom, right, top),
        style=scalebar_style,
        y_bar=y_min + 0.036 * y_span,
        center_x=cx,
        bar_height=0.017 * y_span,
        font_scale=font_scale,
    )

    if has_cbar:
        cax = fig.add_axes([ax_l + ax_w + 0.02, ax_b + 0.15 * ax_h, 0.024, 0.70 * ax_h])
        cbar = fig.colorbar(im, cax=cax)
        cbar.ax.tick_params(labelsize=8.5 * font_scale)
        if colorbar_label:
            cbar.set_label(colorbar_label, fontsize=9.5 * font_scale, fontweight="bold")

    _save_figure(fig, output_path, dpi)
    plt.close(fig)


def export_spectral_index(
    input_path: str | Path,
    profile: TiffProfile,
    index_name: str,
    output_tif: str | Path,
    *,
    output_preview: str | Path | None = None,
    cmap_name: str | None = None,
    title: str | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
    arrow_style: str = "compass",
    scalebar_style: str = "arcgis",
    show_grid: bool = True,
    dpi: int = 300,
) -> dict[str, Any]:
    """Stream-compute a spectral index GeoTIFF and optionally render a full-page map."""
    key = index_name.strip().lower()
    if key not in SPECTRAL_INDICES:
        raise ValueError(f"Unknown index {index_name!r}. Available: {', '.join(SPECTRAL_INDICES)}")

    spec = SPECTRAL_INDICES[key]
    roles: tuple[str, ...] = spec["roles"]
    sp_map = profile.spectral_band_map or {}
    missing = [r for r in roles if r not in sp_map]
    if missing:
        avail = ", ".join(sorted(sp_map.keys())) or "none"
        raise ValueError(
            f"Spectral index '{key}' requires band role(s) {missing}, not detected in this TIFF "
            f"(available roles: {avail})."
        )

    needed = [(r, sp_map[r]) for r in roles]
    band_indices = [b for _, b in needed]
    refl_div = _reflectance_divisor(profile, band_indices)

    out_tif = Path(output_tif)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    nodata_out = -9999.0

    valid_n = 0
    total_sum = 0.0
    total_sq = 0.0
    g_min = float("inf")
    g_max = float("-inf")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(input_path) as src:
            out_meta: dict[str, Any] = {
                "driver": "GTiff",
                "height": src.height,
                "width": src.width,
                "count": 1,
                "dtype": "float32",
                "nodata": nodata_out,
                "compress": "deflate",
                "tiled": src.width >= 256 and src.height >= 256,
            }
            if out_meta["tiled"]:
                out_meta.update({"blockxsize": 256, "blockysize": 256})
            if src.crs is not None:
                out_meta["crs"] = src.crs
                out_meta["transform"] = src.transform

            with rasterio.open(out_tif, "w", **out_meta) as dst:
                dst.set_band_description(1, key.upper())
                dst.update_tags(
                    spectral_index=key,
                    formula=spec["formula"],
                    created_by=f"lulckit/{__version__}",
                )
                step = 1024
                for row_off in range(0, src.height, step):
                    h = min(step, src.height - row_off)
                    for col_off in range(0, src.width, step):
                        w = min(step, src.width - col_off)
                        win = Window(col_off, row_off, w, h)
                        raw = src.read(band_indices, window=win).astype(np.float32)
                        masks = src.read_masks(band_indices, window=win)
                        valid = np.all(masks > 0, axis=0)
                        if profile.alpha_band is not None:
                            valid &= src.read(profile.alpha_band, window=win) > 0

                        bdict = {role: raw[i] for i, (role, _) in enumerate(needed)}
                        idx_arr, good = _compute_index_array(key, bdict, valid, refl_div)
                        dst.write(idx_arr, 1, window=win)

                        if np.any(good):
                            vals = idx_arr[good].astype(np.float64)
                            valid_n += int(vals.size)
                            total_sum += float(np.sum(vals))
                            total_sq += float(np.sum(vals * vals))
                            g_min = min(g_min, float(np.min(vals)))
                            g_max = max(g_max, float(np.max(vals)))

    if valid_n > 0:
        mean_v = total_sum / valid_n
        var_v = max(0.0, (total_sq / valid_n) - (mean_v * mean_v))
        stats = {
            "index": key,
            "valid_pixels": valid_n,
            "min": round(g_min, 4),
            "max": round(g_max, 4),
            "mean": round(mean_v, 4),
            "std": round(math.sqrt(var_v), 4),
        }
    else:
        stats = {"index": key, "valid_pixels": 0, "min": None, "max": None, "mean": None, "std": None}

    if output_preview is not None:
        out_h, out_w, _ = decimated_shape(profile.height, profile.width, max_pixels=4_000_000)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(out_tif) as src_idx:
                arr = src_idx.read(1, out_shape=(out_h, out_w), resampling=Resampling.nearest)
        masked = np.ma.masked_where(arr == nodata_out, arr)
        vmin, vmax = spec["range"]
        _render_array_print_map(
            profile=profile,
            img_data=masked,
            output_path=Path(output_preview),
            title=title or f"{profile.file_name} — {key.upper()}",
            cmap_name=cmap_name or spec["cmap"],
            vmin=vmin,
            vmax=vmax,
            colorbar_label=key.upper(),
            page_size=page_size,
            orientation=orientation,
            arrow_style=arrow_style,
            scalebar_style=scalebar_style,
            show_grid=show_grid,
            dpi=dpi,
        )

    return stats


def _percentile_bounds(
    src: Any,
    band_indices: list[int],
    stretch: tuple[float, float],
    alpha_band: int | None,
) -> tuple[list[float], list[float]]:
    lo_q, hi_q = stretch
    out_h, out_w, _ = decimated_shape(src.height, src.width, max_pixels=1_000_000)
    raw = src.read(band_indices, out_shape=(len(band_indices), out_h, out_w), resampling=Resampling.nearest)
    masks = src.read_masks(band_indices, out_shape=(len(band_indices), out_h, out_w), resampling=Resampling.nearest)
    alpha_ok = (
        src.read(alpha_band, out_shape=(out_h, out_w), resampling=Resampling.nearest) > 0
        if alpha_band is not None
        else np.ones((out_h, out_w), dtype=bool)
    )
    los: list[float] = []
    his: list[float] = []
    for i in range(len(band_indices)):
        valid = (masks[i] > 0) & alpha_ok & np.isfinite(raw[i])
        vals = raw[i][valid]
        if vals.size > 0:
            p_lo, p_hi = np.percentile(vals, [lo_q, hi_q])
            los.append(float(p_lo))
            his.append(float(p_hi))
        else:
            los.append(0.0)
            his.append(255.0)
    return los, his


def export_band_view(
    input_path: str | Path,
    profile: TiffProfile,
    band_indices: list[int],
    *,
    output_tif: str | Path | None = None,
    output_preview: str | Path | None = None,
    stretch: tuple[float, float] = (2.0, 98.0),
    cmap_name: str = "viridis",
    title: str | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
    arrow_style: str = "compass",
    scalebar_style: str = "arcgis",
    show_grid: bool = True,
    dpi: int = 300,
) -> None:
    """Extract/stretch 1 or 3 bands to GeoTIFF and/or render a full-page map graphic."""
    if len(band_indices) not in (1, 3):
        raise ValueError(f"export_band_view supports 1 or 3 bands, got {len(band_indices)}: {band_indices}")
    bad = [b for b in band_indices if b < 1 or b > profile.band_count]
    if bad:
        raise ValueError(f"Band index out of range [1..{profile.band_count}]: {bad}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(input_path) as src:
            los, his = _percentile_bounds(src, band_indices, stretch, profile.alpha_band)
            is_rgb = len(band_indices) == 3

            if output_tif is not None:
                out_tif = Path(output_tif)
                out_tif.parent.mkdir(parents=True, exist_ok=True)
                out_dtype = "uint8" if is_rgb else str(src.dtypes[band_indices[0] - 1])
                out_meta: dict[str, Any] = {
                    "driver": "GTiff",
                    "height": src.height,
                    "width": src.width,
                    "count": len(band_indices),
                    "dtype": out_dtype,
                    "compress": "deflate",
                    "tiled": src.width >= 256 and src.height >= 256,
                }
                if out_meta["tiled"]:
                    out_meta.update({"blockxsize": 256, "blockysize": 256})
                if not is_rgb and src.nodatavals[band_indices[0] - 1] is not None:
                    out_meta["nodata"] = src.nodatavals[band_indices[0] - 1]
                if src.crs is not None:
                    out_meta["crs"] = src.crs
                    out_meta["transform"] = src.transform

                with rasterio.open(out_tif, "w", **out_meta) as dst:
                    for out_idx, in_idx in enumerate(band_indices, start=1):
                        desc = profile.bands[in_idx - 1].description or f"Band_{in_idx}"
                        dst.set_band_description(out_idx, desc)
                    step = 1024
                    for row_off in range(0, src.height, step):
                        h = min(step, src.height - row_off)
                        for col_off in range(0, src.width, step):
                            w = min(step, src.width - col_off)
                            win = Window(col_off, row_off, w, h)
                            chunk = src.read(band_indices, window=win)
                            if is_rgb:
                                rgb_hwc = normalize_rgb_to_uint8(chunk, los, his, "float32")
                                dst.write(np.transpose(rgb_hwc, (2, 0, 1)), window=win)
                            else:
                                dst.write(chunk, window=win)

            if output_preview is not None:
                out_h, out_w, _ = decimated_shape(src.height, src.width, max_pixels=4_000_000)
                raw = src.read(
                    band_indices,
                    out_shape=(len(band_indices), out_h, out_w),
                    resampling=Resampling.bilinear,
                )
                if is_rgb:
                    img_data = normalize_rgb_to_uint8(raw, los, his, "float32")
                    default_title = f"{profile.file_name} — Bands {band_indices}"
                    _render_array_print_map(
                        profile=profile,
                        img_data=img_data,
                        output_path=Path(output_preview),
                        title=title or default_title,
                        page_size=page_size,
                        orientation=orientation,
                        arrow_style=arrow_style,
                        scalebar_style=scalebar_style,
                        show_grid=show_grid,
                        dpi=dpi,
                    )
                else:
                    masks = src.read_masks(
                        band_indices[0],
                        out_shape=(out_h, out_w),
                        resampling=Resampling.nearest,
                    )
                    band_arr = raw[0].astype(np.float32)
                    bad_mask = (masks == 0) | (~np.isfinite(band_arr))
                    masked = np.ma.masked_where(bad_mask, band_arr)
                    b_info = profile.bands[band_indices[0] - 1]
                    b_lbl = b_info.description or f"Band {b_info.index}"
                    _render_array_print_map(
                        profile=profile,
                        img_data=masked,
                        output_path=Path(output_preview),
                        title=title or f"{profile.file_name} — {b_lbl}",
                        cmap_name=cmap_name,
                        vmin=los[0],
                        vmax=his[0] if his[0] > los[0] else los[0] + 1.0,
                        colorbar_label=b_lbl,
                        page_size=page_size,
                        orientation=orientation,
                        arrow_style=arrow_style,
                        scalebar_style=scalebar_style,
                        show_grid=show_grid,
                        dpi=dpi,
                    )


def clip_raster_to_geojson(
    input_path: str | Path,
    boundary_path: str | Path,
    output_path: str | Path,
    *,
    crop: bool = True,
    nodata: float | int | None = None,
) -> dict[str, Any]:
    """Clip a georeferenced TIFF/GeoTIFF to a GeoJSON polygon/multipolygon boundary."""
    in_path = Path(input_path).resolve()
    out_path = Path(output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(in_path) as src:
            if src.crs is None:
                raise ValueError(f"Cannot clip non-georeferenced TIFF (no CRS): {in_path.name}")

            geoms = _load_boundary_geometries(boundary_path, src.crs.to_wkt())
            if not geoms:
                raise ValueError(f"No valid geometries found in boundary file: {boundary_path}")

            eff_nodata = nodata if nodata is not None else src.nodata
            if eff_nodata is None and src.dtypes[0] == "uint8":
                eff_nodata = 255

            out_img, out_transform = rasterio_mask(
                src,
                geoms,
                crop=crop,
                nodata=eff_nodata,
                filled=eff_nodata is not None,
            )

            out_meta = src.meta.copy()
            out_meta.update(
                {
                    "driver": "GTiff",
                    "height": int(out_img.shape[1]),
                    "width": int(out_img.shape[2]),
                    "transform": out_transform,
                    "compress": "deflate",
                }
            )
            if eff_nodata is not None:
                out_meta["nodata"] = eff_nodata
            if out_img.shape[2] >= 256 and out_img.shape[1] >= 256:
                out_meta.update({"tiled": True, "blockxsize": 256, "blockysize": 256})
            else:
                out_meta["tiled"] = False

            cmap = None
            if src.count == 1:
                try:
                    cmap = src.colormap(1)
                except ValueError:
                    cmap = None

            tags = src.tags()
            descriptions = src.descriptions

            with rasterio.open(out_path, "w", **out_meta) as dst:
                dst.write(out_img)
                for idx in range(1, src.count + 1):
                    if idx - 1 < len(descriptions) and descriptions[idx - 1]:
                        dst.set_band_description(idx, descriptions[idx - 1])
                if cmap and out_meta.get("dtype") == "uint8":
                    dst.write_colormap(1, cmap)
                if tags:
                    dst.update_tags(**tags)
                dst.update_tags(clipped_by=f"lulckit/{__version__}")

            with rasterio.open(out_path) as chk:
                bounds_wgs = [round(float(v), 7) for v in transform_bounds(chk.crs, "EPSG:4326", *chk.bounds)]
                epsg = chk.crs.to_epsg()

            return {
                "input_shape": [src.width, src.height],
                "clipped_shape": [int(out_img.shape[2]), int(out_img.shape[1])],
                "band_count": int(out_img.shape[0]),
                "nodata": eff_nodata,
                "crs_epsg": epsg,
                "bounds_wgs84": bounds_wgs,
                "output_path": str(out_path),
            }
