"""Publication-grade cartography, color palettes, optical composites, and MapLibre HTML export."""

from __future__ import annotations

import base64
import html
import io
import json
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from lulckit.geo import normalize_rgb_to_uint8
from lulckit.models.base import NODATA_VALUE, BaseLULCModel

if TYPE_CHECKING:
    from lulckit.inspect import TiffProfile


PALETTES: dict[str, tuple[tuple[int, int, int], ...]] = {
    "default": (
        (27, 138, 90),    # Emerald green
        (231, 111, 81),   # Coral terracotta
        (43, 123, 186),   # Cartographic blue
        (233, 196, 106),  # Warm amber
        (142, 94, 162),   # Muted violet
        (214, 40, 40),    # Crimson
        (72, 202, 228),   # Cyan
        (141, 110, 99),   # Earth brown
        (244, 162, 97),   # Ochre
        (38, 70, 83),     # Deep slate teal
    ),
    "arcgis-crop": (
        (56, 168, 0),     # ArcGIS Crop Green (#38A800)
        (230, 0, 0),      # ArcGIS Crimson Red (#E60000)
        (255, 170, 0),    # ArcGIS Amber (#FFAA00)
        (0, 112, 255),    # ArcGIS Water Blue (#0070FF)
        (168, 112, 0),    # Earth Ochre
        (169, 0, 230),    # Violet
        (0, 230, 169),    # Teal
    ),
    "vivid": (
        (0, 158, 115),
        (213, 94, 0),
        (0, 114, 178),
        (240, 228, 66),
        (204, 121, 167),
        (86, 180, 233),
        (230, 159, 0),
        (140, 86, 75),
    ),
    "earth": (
        (45, 106, 79),
        (212, 163, 115),
        (69, 123, 157),
        (149, 213, 178),
        (188, 71, 73),
        (233, 196, 106),
        (108, 117, 125),
    ),
    "pastel": (
        (102, 194, 165),
        (252, 141, 98),
        (141, 160, 203),
        (231, 138, 195),
        (166, 216, 84),
        (255, 217, 47),
        (229, 196, 148),
    ),
    "colorblind": (
        (0, 114, 178),
        (230, 159, 0),
        (0, 158, 115),
        (213, 94, 0),
        (204, 121, 167),
        (86, 180, 233),
        (240, 228, 66),
    ),
}

COMPOSITES: dict[str, tuple[tuple[str, str, str], str]] = {
    "true-color": (("red", "green", "blue"), "Natural RGB (Red, Green, Blue)"),
    "false-color-nir": (("nir", "red", "green"), "Color Infrared Vegetation (NIR, Red, Green)"),
    "agriculture": (("swir1", "nir", "blue"), "Crop Health / Moisture (SWIR1, NIR, Blue)"),
    "swir": (("swir2", "swir1", "red"), "Shortwave IR / Built-up (SWIR2, SWIR1, Red)"),
}
_COMPOSITE_ALIASES = {"cir": "false-color-nir", "urban": "swir"}

ARROW_STYLES: dict[str, str] = {
    "compass": "Classic 8-point ArcGIS compass rose (N/E/S/W)",
    "classic": "ESRI split black/white tall arrowhead (N)",
    "fancy": "4-point faceted star compass (N)",
    "minimal": "Thin crisp shaft + dark triangle + N label",
    "none": "No north arrow",
}

SCALEBAR_STYLES: dict[str, str] = {
    "arcgis": "Divided alternating bar with left sub-divisions (e.g. 10 5 0 10 20 30 40 km)",
    "alternating": "Compact 2-block black/white alternating scale bar",
    "simple": "Clean line with end ticks and centered distance label",
    "none": "No scale bar",
}

PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (8.27, 11.69),       # 210 x 297 mm
    "a5": (5.83, 8.27),        # 148 x 210 mm
    "a3": (11.69, 16.54),      # 297 x 420 mm
    "letter": (8.50, 11.00),   # 216 x 279 mm
    "legal": (8.50, 14.00),    # 216 x 356 mm
    "square": (10.00, 10.00),  # 254 x 254 mm
}


def list_page_sizes() -> list[dict[str, str]]:
    return [
        {"name": "auto", "dimensions": "Auto (defaults to A4, matching raster orientation)"},
        {"name": "a4", "dimensions": "210 × 297 mm (8.27 × 11.69 in)"},
        {"name": "a5", "dimensions": "148 × 210 mm (5.83 × 8.27 in)"},
        {"name": "a3", "dimensions": "297 × 420 mm (11.69 × 16.54 in)"},
        {"name": "letter", "dimensions": "216 × 279 mm (8.50 × 11.00 in)"},
        {"name": "legal", "dimensions": "216 × 356 mm (8.50 × 14.00 in)"},
        {"name": "square", "dimensions": "254 × 254 mm (10.00 × 10.00 in)"},
    ]


def resolve_page_figsize(
    page_size: str,
    orientation: str,
    raster_aspect: float,
    default_landscape: bool = False,
) -> tuple[float, float]:
    """Resolve ``(width_in, height_in)`` for print or side-by-side layout."""
    ps = page_size.strip().lower()
    if ps == "auto":
        ps = "a4"
    if ps not in PAGE_SIZES:
        raise ValueError(f"Unknown page size {page_size!r}. Available: auto, {', '.join(PAGE_SIZES)}")

    ori = orientation.strip().lower()
    if ori not in ("auto", "portrait", "landscape"):
        raise ValueError(f"Unknown orientation {orientation!r}. Available: auto, portrait, landscape")

    if ps == "square":
        return PAGE_SIZES["square"]

    short_side, long_side = PAGE_SIZES[ps]
    if ori == "auto":
        use_landscape = default_landscape or (raster_aspect > 1.08)
    else:
        use_landscape = ori == "landscape"
    return (long_side, short_side) if use_landscape else (short_side, long_side)


def list_palettes() -> list[dict[str, str]]:
    """Return built-in color palettes plus Matplotlib colormap support note."""
    rows = [
        {"name": name, "colors": " ".join(f"#{r:02X}{g:02X}{b:02X}" for r, g, b in cols[:6])}
        for name, cols in PALETTES.items()
    ]
    rows.append(
        {
            "name": "<matplotlib>",
            "colors": "Any Matplotlib colormap (viridis, terrain, Spectral, RdYlGn, Set1, Dark2, tab10, Paired, ...)",
        }
    )
    return rows


def list_composites() -> list[dict[str, str]]:
    return [
        {"name": name, "bands": ", ".join(bands), "description": desc}
        for name, (bands, desc) in COMPOSITES.items()
    ]


def list_arrow_styles() -> list[dict[str, str]]:
    return [{"name": k, "description": v} for k, v in ARROW_STYLES.items()]


def list_scalebar_styles() -> list[dict[str, str]]:
    return [{"name": k, "description": v} for k, v in SCALEBAR_STYLES.items()]


def resolve_palette_color(palette_name: str, idx: int, total: int = 8) -> tuple[int, int, int]:
    """Resolve an RGB 0..255 tuple from a named built-in palette or Matplotlib colormap."""
    key = palette_name.strip()
    lower = key.lower()
    if lower in PALETTES:
        cols = PALETTES[lower]
        return cols[idx % len(cols)]

    import matplotlib

    try:
        cmap = matplotlib.colormaps[key]
    except KeyError as exc:
        valid = ", ".join(PALETTES)
        raise ValueError(
            f"Unknown palette {palette_name!r}. Built-in palettes: {valid}; or pass any Matplotlib colormap name."
        ) from exc

    if hasattr(cmap, "colors") and len(cmap.colors) <= 20:
        rgba = cmap.colors[idx % len(cmap.colors)]
    else:
        t = idx / float(max(total - 1, 1))
        rgba = cmap(t)
    return (
        int(round(float(rgba[0]) * 255)),
        int(round(float(rgba[1]) * 255)),
        int(round(float(rgba[2]) * 255)),
    )


def resolve_composite_bands(profile: TiffProfile, composite_name: str) -> tuple[list[int], str]:
    """Resolve a multiband composite preset to 1-based band indices for optical display."""
    key = composite_name.strip().lower()
    key = _COMPOSITE_ALIASES.get(key, key)
    if key not in COMPOSITES:
        raise ValueError(
            f"Unknown composite {composite_name!r}. Available presets: {', '.join(COMPOSITES)}"
        )

    roles, _ = COMPOSITES[key]
    sp_map = profile.spectral_band_map or {}
    missing = [r for r in roles if r not in sp_map]
    if missing:
        avail = ", ".join(sorted(sp_map.keys())) or "none"
        raise ValueError(
            f"Composite '{key}' requires spectral band(s) {missing}, which are missing in this TIFF "
            f"(detected roles: {avail}). Use --rgb-bands R,G,B to choose bands manually."
        )
    return [sp_map[r] for r in roles], key


def _load_boundary_geometries(
    boundary_path: str | Path,
    target_crs_wkt: str | None,
) -> list[Any]:
    """Load GeoJSON boundary geometries and reproject into target CRS if georeferenced."""
    bpath = Path(boundary_path)
    if not bpath.is_file():
        raise FileNotFoundError(f"Boundary GeoJSON file not found: {bpath}")

    raw = json.loads(bpath.read_text(encoding="utf-8"))
    raw_geoms: list[Any] = []
    if raw.get("type") == "FeatureCollection":
        for feat in raw.get("features", []):
            if feat.get("geometry"):
                raw_geoms.append(shape(feat["geometry"]))
    elif raw.get("type") == "Feature":
        if raw.get("geometry"):
            raw_geoms.append(shape(raw["geometry"]))
    elif "coordinates" in raw or "geometries" in raw:
        raw_geoms.append(shape(raw))

    if not raw_geoms or not target_crs_wkt:
        return raw_geoms

    src_crs = "EPSG:4326"
    crs_obj = raw.get("crs")
    if isinstance(crs_obj, dict):
        name = crs_obj.get("properties", {}).get("name")
        if name:
            src_crs = str(name)

    transformer = Transformer.from_crs(src_crs, target_crs_wkt, always_xy=True)
    return [shapely_transform(transformer.transform, g) for g in raw_geoms if not g.is_empty]


def _draw_shapely_outlines(ax: Any, geoms: list[Any], edgecolor: str = "#222222", lw: float = 0.9) -> None:
    from matplotlib.patches import Polygon as MplPolygon

    def _add_poly(poly: Any) -> None:
        coords = np.asarray(poly.exterior.coords)
        ax.add_patch(
            MplPolygon(
                coords,
                closed=True,
                facecolor="none",
                edgecolor=edgecolor,
                linewidth=lw,
                zorder=5,
            )
        )

    for g in geoms:
        gtype = g.geom_type
        if gtype == "Polygon":
            _add_poly(g)
        elif gtype == "MultiPolygon":
            for p in g.geoms:
                _add_poly(p)
        elif gtype in ("LineString", "MultiLineString"):
            lines = [g] if gtype == "LineString" else list(g.geoms)
            for ln in lines:
                pts = np.asarray(ln.coords)
                ax.plot(pts[:, 0], pts[:, 1], color=edgecolor, linewidth=lw, zorder=5)


def draw_north_arrow(
    ax: Any,
    style: str = "compass",
    pos: str = "top-right",
    *,
    box_w_frac: float = 0.15,
    box_h_frac: float = 0.15,
    font_scale: float = 1.0,
) -> None:
    """Draw a vector north arrow inside a 1:1 square inset axes anchored to ``pos``."""
    from matplotlib.patches import Circle, Polygon

    key = style.strip().lower()
    if key == "none":
        return
    if key not in ARROW_STYLES:
        raise ValueError(f"Unknown arrow style {style!r}. Available: {', '.join(ARROW_STYLES)}")

    pos_map = {
        "top-right": ([1.0 - 0.025 - box_w_frac, 1.0 - 0.08 - box_h_frac, box_w_frac, box_h_frac], "NE"),
        "top-left": ([0.025, 1.0 - 0.08 - box_h_frac, box_w_frac, box_h_frac], "NW"),
        "bottom-right": ([1.0 - 0.025 - box_w_frac, 0.11, box_w_frac, box_h_frac], "SE"),
        "bottom-left": ([0.025, 0.11, box_w_frac, box_h_frac], "SW"),
    }
    if pos not in pos_map:
        raise ValueError(f"Unknown arrow position {pos!r}. Available: {', '.join(pos_map)}")

    bounds, anchor = pos_map[pos]
    sub = ax.inset_axes(bounds, transform=ax.transAxes)
    sub.set_aspect("equal", adjustable="box")
    sub.set_anchor(anchor)
    sub.set_xlim(-1.45, 1.45)
    sub.set_ylim(-1.45, 1.45)
    sub.axis("off")
    sub.patch.set_alpha(0.0)

    if key == "compass":
        sub.add_patch(Circle((0, 0), 0.66, fill=False, edgecolor="#111111", linewidth=1.1, zorder=2))
        sub.add_patch(Circle((0, 0), 0.56, fill=False, edgecolor="#111111", linewidth=0.7, zorder=2))

        def _star_points(angles_deg: tuple[int, ...], r_tip: float, r_mid: float, z: int) -> None:
            for deg in angles_deg:
                rad = np.deg2rad(deg)
                rad_l = np.deg2rad(deg + 45)
                rad_r = np.deg2rad(deg - 45)
                tip = (r_tip * np.cos(rad), r_tip * np.sin(rad))
                mid_l = (r_mid * np.cos(rad_l), r_mid * np.sin(rad_l))
                mid_r = (r_mid * np.cos(rad_r), r_mid * np.sin(rad_r))
                sub.add_patch(Polygon([(0, 0), tip, mid_l], closed=True, facecolor="#111111", edgecolor="#111111", linewidth=0.6, zorder=z))
                sub.add_patch(Polygon([(0, 0), tip, mid_r], closed=True, facecolor="#FFFFFF", edgecolor="#111111", linewidth=0.6, zorder=z))

        _star_points((45, 135, 225, 315), r_tip=0.76, r_mid=0.19, z=3)
        _star_points((90, 0, 270, 180), r_tip=1.02, r_mid=0.24, z=4)
        for lbl, (lx, ly) in (("N", (0, 1.25)), ("E", (1.25, 0)), ("S", (0, -1.25)), ("W", (-1.27, 0))):
            sub.text(lx, ly, lbl, ha="center", va="center", fontsize=9.0 * font_scale, fontweight="bold", color="#111111")

    elif key == "classic":
        sub.add_patch(Polygon([(0, 0.92), (-0.38, -0.78), (0, -0.45)], closed=True, facecolor="#111111", edgecolor="#111111", linewidth=0.9))
        sub.add_patch(Polygon([(0, 0.92), (0.38, -0.78), (0, -0.45)], closed=True, facecolor="#FFFFFF", edgecolor="#111111", linewidth=0.9))
        sub.text(0, 1.20, "N", ha="center", va="center", fontsize=10.5 * font_scale, fontweight="bold", color="#111111")

    elif key == "fancy":
        for deg in (90, 0, 270, 180):
            rad = np.deg2rad(deg)
            rad_l = np.deg2rad(deg + 45)
            rad_r = np.deg2rad(deg - 45)
            tip = (0.98 * np.cos(rad), 0.98 * np.sin(rad))
            mid_l = (0.22 * np.cos(rad_l), 0.22 * np.sin(rad_l))
            mid_r = (0.22 * np.cos(rad_r), 0.22 * np.sin(rad_r))
            sub.add_patch(Polygon([(0, 0), tip, mid_l], closed=True, facecolor="#111111", edgecolor="#111111", linewidth=0.7))
            sub.add_patch(Polygon([(0, 0), tip, mid_r], closed=True, facecolor="#FFFFFF", edgecolor="#111111", linewidth=0.7))
        sub.text(0, 1.25, "N", ha="center", va="center", fontsize=10.0 * font_scale, fontweight="bold", color="#111111")

    elif key == "minimal":
        sub.plot([0, 0], [-0.82, 0.55], color="#111111", linewidth=1.8)
        sub.add_patch(Polygon([(0, 0.92), (-0.25, 0.35), (0.25, 0.35)], closed=True, facecolor="#111111", edgecolor="#111111"))
        sub.text(0, 1.22, "N", ha="center", va="center", fontsize=10.0 * font_scale, fontweight="bold", color="#111111")


def _pick_arcgis_major_meters(width_m: float) -> float:
    candidates = (
        5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 200.0, 250.0, 500.0,
        1000.0, 2000.0, 5000.0, 10000.0, 20000.0, 25000.0, 50000.0, 100000.0,
    )
    target_total = width_m * 0.50
    valid = [c for c in candidates if 5.0 * c <= width_m * 0.68]
    pool = valid or [candidates[0]]
    return min(pool, key=lambda c: abs(5.0 * c - target_total))


def _fmt_scale_num(val: float) -> str:
    if abs(val - round(val)) < 1e-6:
        return str(int(round(val)))
    return f"{val:.1f}"


def draw_scale_bar(
    ax: Any,
    profile: TiffProfile,
    bounds: tuple[float, float, float, float],
    style: str = "arcgis",
    y_bar: float | None = None,
    x_left: float | None = None,
    bar_height: float | None = None,
    center_x: float | None = None,
    font_scale: float = 1.0,
) -> None:
    """Draw a geometrically accurate scale bar in data coordinates inside ``ax``."""
    from matplotlib.patches import Rectangle

    key = style.strip().lower()
    if key == "none":
        return
    if key not in SCALEBAR_STYLES:
        raise ValueError(f"Unknown scalebar style {style!r}. Available: {', '.join(SCALEBAR_STYLES)}")
    if not profile.is_georeferenced or not profile.gsd_meters or profile.gsd_meters[0] <= 0:
        return

    left, bottom, right, top = bounds
    dx = right - left
    dy = top - bottom
    width_m = profile.width * profile.gsd_meters[0]
    data_per_m = dx / width_m

    major_m = _pick_arcgis_major_meters(width_m)
    use_km = major_m >= 1000.0 or (5.0 * major_m) >= 2000.0
    div = 1000.0 if use_km else 1.0
    unit_label = "Kilometers" if use_km else "Meters"

    major_d = major_m * data_per_m
    total_d = 5.0 * major_d
    if x_left is not None:
        x0 = x_left
    elif center_x is not None:
        x0 = center_x - 0.5 * total_d - (0.04 * dx if key == "arcgis" else 0.0)
    else:
        x0 = left + 0.14 * dx
    yb = y_bar if y_bar is not None else (bottom - 0.15 * dy)
    bh = bar_height if bar_height is not None else (0.022 * dy)
    label_y = yb + bh * 1.40

    if key == "arcgis":
        segments = [
            (x0, 0.5 * major_d, True),
            (x0 + 0.5 * major_d, 0.5 * major_d, False),
            (x0 + 1.0 * major_d, 1.0 * major_d, True),
            (x0 + 2.0 * major_d, 1.0 * major_d, False),
            (x0 + 3.0 * major_d, 1.0 * major_d, True),
            (x0 + 4.0 * major_d, 1.0 * major_d, False),
        ]
        half_h = bh * 0.5
        for sx, sw, _is_dark in segments:
            ax.add_patch(Rectangle((sx, yb + half_h), sw, half_h, facecolor="#FFFFFF", edgecolor="#111111", linewidth=0.8, zorder=6))
            ax.add_patch(Rectangle((sx, yb), sw, half_h, facecolor="#FFFFFF", edgecolor="#111111", linewidth=0.8, zorder=6))

        tick_specs = [
            (x0, _fmt_scale_num(major_m / div)),
            (x0 + 0.5 * major_d, _fmt_scale_num((0.5 * major_m) / div)),
            (x0 + 1.0 * major_d, "0"),
            (x0 + 2.0 * major_d, _fmt_scale_num(major_m / div)),
            (x0 + 3.0 * major_d, _fmt_scale_num((2.0 * major_m) / div)),
            (x0 + 4.0 * major_d, _fmt_scale_num((3.0 * major_m) / div)),
            (x0 + 5.0 * major_d, _fmt_scale_num((4.0 * major_m) / div)),
        ]
        for tx, tlabel in tick_specs:
            ax.text(tx, label_y, tlabel, ha="center", va="bottom", fontsize=9.5 * font_scale, color="#111111", zorder=7)
        ax.text(x0 + total_d + 0.02 * dx, yb + half_h, unit_label, ha="left", va="center", fontsize=9.5 * font_scale, color="#111111", zorder=7)

    elif key == "alternating":
        half_d = total_d * 0.5
        ax.add_patch(Rectangle((x0, yb), half_d, bh, facecolor="#111111", edgecolor="#111111", linewidth=0.8, zorder=6))
        ax.add_patch(Rectangle((x0 + half_d, yb), half_d, bh, facecolor="#FFFFFF", edgecolor="#111111", linewidth=0.8, zorder=6))
        for tx, lbl in (
            (x0, "0"),
            (x0 + half_d, _fmt_scale_num((2.5 * major_m) / div)),
            (x0 + total_d, f"{_fmt_scale_num((5.0 * major_m) / div)} {unit_label}"),
        ):
            ax.text(tx, label_y, lbl, ha="center", va="bottom", fontsize=9.0 * font_scale, color="#111111", zorder=7)

    elif key == "simple":
        ax.plot([x0, x0 + total_d], [yb + bh * 0.4, yb + bh * 0.4], color="#111111", linewidth=1.5, zorder=6)
        ax.plot([x0, x0], [yb, yb + bh * 0.85], color="#111111", linewidth=1.2, zorder=6)
        ax.plot([x0 + total_d, x0 + total_d], [yb, yb + bh * 0.85], color="#111111", linewidth=1.2, zorder=6)
        ax.text(
            x0 + total_d * 0.5,
            label_y,
            f"{_fmt_scale_num((5.0 * major_m) / div)} {unit_label}",
            ha="center",
            va="bottom",
            fontsize=9.5 * font_scale,
            color="#111111",
            zorder=7,
        )


def _read_colorized_lulc(
    lulc_tif_path: str | Path,
    profile: TiffProfile,
    model: BaseLULCModel,
    max_size: int,
    nodata_rgb: tuple[int, int, int] = (255, 255, 255),
) -> tuple[np.ndarray, np.ndarray]:
    max_dim = max(profile.width, profile.height, 1)
    scale = min(1.0, max_size / float(max_dim))
    out_w = max(1, int(round(profile.width * scale)))
    out_h = max(1, int(round(profile.height * scale)))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(lulc_tif_path) as src_lulc:
            lulc_arr = src_lulc.read(1, out_shape=(out_h, out_w), resampling=Resampling.nearest)

    lut = np.empty((256, 3), dtype=np.uint8)
    lut[:, 0], lut[:, 1], lut[:, 2] = nodata_rgb
    for cls in model.classes:
        if 0 <= cls.id < 255:
            lut[cls.id] = cls.color
    return lulc_arr, lut[lulc_arr]


def _build_legend_handles(
    report: dict[str, Any],
    legend_areas: bool,
    boundary_label: str | None = None,
) -> list[Any]:
    from matplotlib.patches import Patch

    handles: list[Any] = []
    for row in report["lulc"]["classes"]:
        if row["pixels"] <= 0:
            continue
        if legend_areas:
            area_part = f" ({row['area_ha']:,.1f} ha)" if row["area_ha"] is not None else f" ({row['pixels']:,} px)"
            label = f"{row['name']}: {row['percent']:.1f}%{area_part}"
        else:
            label = row["name"]
        handles.append(
            Patch(
                facecolor=row["hex"],
                edgecolor="#444444",
                linewidth=0.6,
                label=label,
            )
        )
    if boundary_label:
        handles.append(
            Patch(
                facecolor="none",
                edgecolor="#222222",
                linewidth=1.0,
                label=boundary_label,
            )
        )
    return handles


def _save_figure(fig: Any, out: Path, dpi: int) -> None:
    """Save figure atomically via memory buffer so Windows overwrites never hit PIL Errno 22."""
    fmt = out.suffix.lstrip(".").lower() or "png"
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi)
    tmp_out = out.with_name(f".{out.stem}.tmp{out.suffix}")
    tmp_out.write_bytes(buf.getvalue())
    os.replace(tmp_out, out)


def render_print_map(
    input_path: str | Path,
    lulc_tif_path: str | Path,
    profile: TiffProfile,
    model: BaseLULCModel,
    report: dict[str, Any],
    rgb_bands: list[int],
    output_path: str | Path,
    *,
    layout: str = "print",
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
    max_size: int = 2200,
    composite_label: str | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
) -> None:
    """Render clean ArcGIS/QGIS-style print map or side-by-side optical + LULC figure."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    map_title = title or report.get("inference", {}).get("display_name") or profile.file_name

    _, lulc_rgb = _read_colorized_lulc(
        lulc_tif_path=lulc_tif_path,
        profile=profile,
        model=model,
        max_size=max_size,
        nodata_rgb=(255, 255, 255),
    )

    boundary_geoms: list[Any] = []
    resolved_boundary_label: str | None = None
    if boundary_path is not None:
        boundary_geoms = _load_boundary_geometries(
            boundary_path,
            profile.crs_wkt if profile.is_georeferenced else None,
        )
        resolved_boundary_label = boundary_label or Path(boundary_path).stem

    if profile.is_georeferenced and profile.bounds_native:
        left, bottom, right, top = profile.bounds_native
    else:
        left, bottom, right, top = 0.0, 0.0, float(profile.width), float(profile.height)

    dx = max(right - left, 1e-9)
    dy = max(top - bottom, 1e-9)
    fig_w, fig_h = resolve_page_figsize(
        page_size=page_size,
        orientation=orientation,
        raster_aspect=dx / dy,
        default_landscape=(layout == "side-by-side"),
    )
    font_scale = max(0.72, min(1.35, min(fig_w, fig_h) / 8.27))

    if layout == "side-by-side":
        p2 = [
            profile.bands[b - 1].p2 if profile.bands[b - 1].p2 is not None else 0.0
            for b in rgb_bands
        ]
        p98 = [
            profile.bands[b - 1].p98 if profile.bands[b - 1].p98 is not None else 255.0
            for b in rgb_bands
        ]
        band_dtypes = {profile.bands[b - 1].dtype for b in rgb_bands}
        src_dtype = next(iter(band_dtypes)) if len(band_dtypes) == 1 else "float32"

        out_h, out_w = lulc_rgb.shape[:2]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(input_path) as src_in:
                rgb_raw = src_in.read(
                    rgb_bands,
                    out_shape=(3, out_h, out_w),
                    resampling=Resampling.bilinear,
                )
                rgb_img = normalize_rgb_to_uint8(rgb_raw, p2, p98, src_dtype)

        fig, axes = plt.subplots(1, 2, figsize=(fig_w, fig_h), dpi=dpi, facecolor="white")
        comp_title = f"Optical Composite ({composite_label}: bands {rgb_bands})" if composite_label else f"Input Imagery (bands {rgb_bands})"
        axes[0].imshow(rgb_img)
        axes[0].set_title(comp_title, fontsize=11 * font_scale, fontweight="bold")
        axes[0].axis("off")

        if profile.is_georeferenced and profile.bounds_native:
            axes[1].imshow(lulc_rgb, extent=[left, right, bottom, top], aspect="equal", origin="upper")
            if boundary_geoms:
                _draw_shapely_outlines(axes[1], boundary_geoms)
            axes[1].set_xlim(left - 0.02 * dx, right + 0.02 * dx)
            axes[1].set_ylim(bottom - 0.16 * dy, top + 0.05 * dy)
            draw_scale_bar(
                axes[1],
                profile,
                (left, bottom, right, top),
                style=scalebar_style,
                y_bar=bottom - 0.10 * dy,
                x_left=left + 0.08 * dx,
                bar_height=0.020 * dy,
                font_scale=font_scale,
            )
        else:
            axes[1].imshow(lulc_rgb)
        draw_north_arrow(axes[1], style=arrow_style, pos=arrow_pos, font_scale=font_scale)
        axes[1].set_title(f"LULC Map ({model.name})", fontsize=11 * font_scale, fontweight="bold")
        axes[1].axis("off")

        fig.suptitle(map_title, fontsize=13 * font_scale, fontweight="bold", y=0.97)
        handles = _build_legend_handles(report, legend_areas=True, boundary_label=resolved_boundary_label)
        if handles:
            fig.legend(
                handles=handles,
                loc="lower center",
                ncol=min(4, max(1, len(handles))),
                frameon=True,
                fontsize=8.5 * font_scale,
                bbox_to_anchor=(0.5, 0.02),
            )
        plt.tight_layout(rect=(0.01, 0.10 if handles else 0.02, 0.99, 0.93))
        _save_figure(fig, out, dpi)
        plt.close(fig)
        return

    # Full-page publication print layout (ArcGIS / QGIS style)
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor="white")
    if show_grid:
        ax_l = 0.125 if fig_w >= 8.0 else 0.155
        ax_r = 0.03
        ax_b = 0.075 if fig_h >= 8.0 else 0.09
        ax_t = 0.03
        ax_w = 1.0 - ax_l - ax_r
        ax_h = 1.0 - ax_b - ax_t
    else:
        ax_l, ax_b, ax_w, ax_h = 0.03, 0.03, 0.94, 0.94

    ax = fig.add_axes([ax_l, ax_b, ax_w, ax_h], facecolor="white")
    ax.imshow(lulc_rgb, extent=[left, right, bottom, top], aspect="equal", origin="upper", zorder=1)
    if boundary_geoms:
        _draw_shapely_outlines(ax, boundary_geoms)

    # Match data limits exactly to the physical neatline box aspect so aspect='equal' fills the entire page
    box_aspect = (ax_w * fig_w) / (ax_h * fig_h)
    min_x_span = dx * 1.08
    min_y_span = dy * 1.32
    if (min_x_span / min_y_span) < box_aspect:
        y_span = min_y_span
        x_span = y_span * box_aspect
    else:
        x_span = min_x_span
        y_span = x_span / box_aspect

    cx = 0.5 * (left + right)
    x_min = cx - 0.5 * x_span
    x_max = cx + 0.5 * x_span
    extra_y = y_span - dy
    top_pad = max(0.12 * dy, 0.36 * extra_y)
    bottom_pad = extra_y - top_pad
    y_min = bottom - bottom_pad
    y_max = top + top_pad

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    # Crisp black neatline border
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

    # Centered title inside neatline
    ax.text(
        0.50,
        0.955,
        map_title,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=15.0 * font_scale,
        fontweight="bold",
        color="#111111",
        zorder=8,
    )

    # Vector North Arrow sized in physical inches
    arrow_in = 1.25 * font_scale
    draw_north_arrow(
        ax,
        style=arrow_style,
        pos=arrow_pos,
        box_w_frac=min(0.24, arrow_in / (ax_w * fig_w)),
        box_h_frac=min(0.24, arrow_in / (ax_h * fig_h)),
        font_scale=font_scale,
    )

    # ArcGIS / QGIS Scale Bar centered cleanly along the bottom inside neatline
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

    # Clean Legend
    handles = _build_legend_handles(report, legend_areas=legend_areas, boundary_label=resolved_boundary_label)
    if handles:
        leg_anchors = {
            "bottom-left": ("lower left", (0.025, 0.105)),
            "bottom-right": ("lower right", (0.975, 0.105)),
            "top-left": ("upper left", (0.025, 0.905)),
            "top-right": ("upper right", (0.975, 0.75 if arrow_pos == "top-right" else 0.905)),
            "outside": ("lower left", (1.02, 0.0)),
        }
        if legend_pos not in leg_anchors:
            raise ValueError(f"Unknown legend_pos {legend_pos!r}. Available: {', '.join(leg_anchors)}")
        loc_str, anchor_xy = leg_anchors[legend_pos]
        leg = ax.legend(
            handles=handles,
            title="Legend",
            loc=loc_str,
            bbox_to_anchor=anchor_xy,
            frameon=True,
            facecolor="white",
            edgecolor="none",
            framealpha=0.92,
            fontsize=9.2 * font_scale,
            title_fontsize=10.5 * font_scale,
            handlelength=2.2,
            handleheight=1.1,
            labelspacing=0.55,
            borderpad=0.35,
        )
        leg.get_title().set_fontweight("bold")
        leg._legend_box.align = "left"

    _save_figure(fig, out, dpi)
    plt.close(fig)


def export_interactive_html(
    lulc_tif_path: str | Path,
    profile: TiffProfile,
    model: BaseLULCModel,
    report: dict[str, Any],
    output_path: str | Path,
    *,
    title: str | None = None,
    boundary_path: str | Path | None = None,
    max_size: int = 1600,
) -> Path | None:
    """Export a self-contained GeoLibre-inspired MapLibre GL JS interactive HTML map."""
    if not profile.is_georeferenced or not profile.bounds_wgs84:
        return None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    map_title = title or report.get("inference", {}).get("display_name") or profile.file_name

    lulc_arr, lulc_rgb = _read_colorized_lulc(
        lulc_tif_path=lulc_tif_path,
        profile=profile,
        model=model,
        max_size=max_size,
        nodata_rgb=(0, 0, 0),
    )

    alpha = np.where(lulc_arr == NODATA_VALUE, 0, 255).astype(np.uint8)
    if profile.zero_is_background:
        alpha[lulc_arr == 0] = 0

    rgba = np.dstack([lulc_rgb, alpha])
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, format="PNG", optimize=True)
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    west, south, east, north = profile.bounds_wgs84
    coords = [[west, north], [east, north], [east, south], [west, south]]

    boundary_json_str = "null"
    if boundary_path is not None:
        bpath = Path(boundary_path)
        if bpath.is_file():
            boundary_json_str = bpath.read_text(encoding="utf-8")

    legend_items_html = []
    for row in report["lulc"]["classes"]:
        if row["pixels"] <= 0:
            continue
        area_txt = f"{row['area_ha']:,.1f} ha ({row['percent']:.1f}%)" if row["area_ha"] is not None else f"{row['percent']:.1f}%"
        legend_items_html.append(
            f'<div class="leg-row"><span class="swatch" style="background:{html.escape(row["hex"])}"></span>'
            f'<span class="leg-name">{html.escape(str(row["name"]))}</span>'
            f'<span class="leg-val">{html.escape(area_txt)}</span></div>'
        )

    geo = report["geospatial"]
    meta_sub = f"EPSG:{geo['crs_epsg']} · {geo['gsd_meters'][0]:.1f}m GSD" if geo["crs_epsg"] and geo["gsd_meters"] else "WGS84 Overlay"

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(map_title)} — Interactive LULC Map</title>
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
  <style>
    html, body, #map {{ margin: 0; padding: 0; width: 100%; height: 100%; font-family: system-ui, -apple-system, sans-serif; }}
    .panel {{
      position: absolute; top: 12px; left: 12px; z-index: 10; width: 300px; max-height: calc(100vh - 48px);
      overflow-y: auto; background: rgba(255,255,255,0.94); backdrop-filter: blur(8px);
      border-radius: 10px; box-shadow: 0 4px 18px rgba(0,0,0,0.16); padding: 14px 16px; color: #1a1f24;
    }}
    .panel h1 {{ font-size: 15px; margin: 0 0 4px; }}
    .sub {{ font-size: 12px; color: #57606a; margin-bottom: 12px; }}
    .ctrl {{ margin-bottom: 10px; font-size: 12.5px; }}
    .ctrl label {{ display: block; font-weight: 600; margin-bottom: 4px; }}
    select, input[type=range], button {{ width: 100%; box-sizing: border-box; }}
    .btn {{ margin-top: 6px; padding: 6px 10px; border: 1px solid #d0d7de; border-radius: 6px; background: #f6f8fa; cursor: pointer; font-weight: 600; }}
    .btn:hover {{ background: #eaeef2; }}
    .leg-title {{ font-size: 12.5px; font-weight: 700; margin: 10px 0 6px; border-top: 1px solid #eaeef2; padding-top: 8px; }}
    .leg-row {{ display: flex; align-items: center; gap: 8px; font-size: 12px; margin-bottom: 5px; }}
    .swatch {{ width: 14px; height: 14px; border-radius: 3px; border: 1px solid #555; flex-shrink: 0; }}
    .leg-name {{ flex: 1; }}
    .leg-val {{ color: #57606a; font-variant-numeric: tabular-nums; }}
    .coords {{
      position: absolute; bottom: 12px; left: 12px; z-index: 10; background: rgba(255,255,255,0.9);
      padding: 4px 10px; border-radius: 6px; font-size: 11.5px; font-family: monospace; box-shadow: 0 2px 8px rgba(0,0,0,0.12);
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <h1>{html.escape(map_title)}</h1>
    <div class="sub">{html.escape(meta_sub)}</div>
    <div class="ctrl">
      <label for="basemap">Basemap</label>
      <select id="basemap">
        <option value="positron" selected>Carto Positron Light</option>
        <option value="osm">OpenStreetMap</option>
        <option value="esri">Esri World Imagery (Satellite)</option>
        <option value="white">Clean White Canvas</option>
      </select>
    </div>
    <div class="ctrl">
      <label for="opacity">Layer Opacity: <span id="op-val">90%</span></label>
      <input id="opacity" type="range" min="0" max="100" value="90" />
    </div>
    <div class="ctrl">
      <label><input id="vis" type="checkbox" checked /> Show LULC Layer</label>
      <button id="fit" class="btn">Zoom to Extent</button>
    </div>
    <div class="leg-title">Legend</div>
    {''.join(legend_items_html)}
  </div>
  <div id="coords" class="coords">Lon: —, Lat: —</div>
  <script>
    const BOUNDS = [[{west}, {south}], [{east}, {north}]];
    const IMG_COORDS = {json.dumps(coords)};
    const DATA_URI = {json.dumps(data_uri)};
    const BOUNDARY_DATA = {boundary_json_str};

    const BASEMAP_SOURCES = {{
      positron: ['https://basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png'],
      osm: ['https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'],
      esri: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{x}}/{{y}}'],
      white: []
    }};

    const map = new maplibregl.Map({{
      container: 'map',
      style: {{
        version: 8,
        sources: {{
          positron: {{ type: 'raster', tiles: BASEMAP_SOURCES.positron, tileSize: 256, attribution: '© Carto © OSM' }},
          osm: {{ type: 'raster', tiles: BASEMAP_SOURCES.osm, tileSize: 256, attribution: '© OpenStreetMap' }},
          esri: {{ type: 'raster', tiles: BASEMAP_SOURCES.esri, tileSize: 256, attribution: '© Esri' }},
          lulc: {{ type: 'image', url: DATA_URI, coordinates: IMG_COORDS }}
        }},
        layers: [
          {{ id: 'bg', type: 'background', paint: {{ 'background-color': '#ffffff' }} }},
          {{ id: 'bm-positron', type: 'raster', source: 'positron', layout: {{ visibility: 'visible' }} }},
          {{ id: 'bm-osm', type: 'raster', source: 'osm', layout: {{ visibility: 'none' }} }},
          {{ id: 'bm-esri', type: 'raster', source: 'esri', layout: {{ visibility: 'none' }} }},
          {{ id: 'lulc-layer', type: 'raster', source: 'lulc', paint: {{ 'raster-opacity': 0.9, 'raster-resampling': 'nearest' }} }}
        ]
      }},
      bounds: BOUNDS,
      fitBoundsOptions: {{ padding: 40 }}
    }});

    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl({{ unit: 'metric' }}), 'bottom-right');

    map.on('load', () => {{
      if (BOUNDARY_DATA) {{
        map.addSource('boundary', {{ type: 'geojson', data: BOUNDARY_DATA }});
        map.addLayer({{
          id: 'boundary-line',
          type: 'line',
          source: 'boundary',
          paint: {{ 'line-color': '#111111', 'line-width': 1.5 }}
        }});
      }}
    }});

    document.getElementById('basemap').addEventListener('change', (e) => {{
      const val = e.target.value;
      ['positron', 'osm', 'esri'].forEach((k) => {{
        map.setLayoutProperty('bm-' + k, 'visibility', k === val ? 'visible' : 'none');
      }});
    }});

    document.getElementById('opacity').addEventListener('input', (e) => {{
      const p = Number(e.target.value);
      document.getElementById('op-val').textContent = p + '%';
      map.setPaintProperty('lulc-layer', 'raster-opacity', p / 100);
    }});

    document.getElementById('vis').addEventListener('change', (e) => {{
      map.setLayoutProperty('lulc-layer', 'visibility', e.target.checked ? 'visible' : 'none');
    }});

    document.getElementById('fit').addEventListener('click', () => {{
      map.fitBounds(BOUNDS, {{ padding: 40 }});
    }});

    map.on('mousemove', (e) => {{
      document.getElementById('coords').textContent =
        'Lon: ' + e.lngLat.lng.toFixed(5) + ', Lat: ' + e.lngLat.lat.toFixed(5);
    }});
  </script>
</body>
</html>
"""
    out.write_text(html_doc, encoding="utf-8")
    return out
