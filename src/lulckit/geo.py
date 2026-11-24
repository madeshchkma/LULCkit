"""Geospatial math, pixel-area calculation, RGB normalization, and spectral indices."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pyproj import CRS as PyprojCRS
from pyproj import Geod
from rasterio.enums import Resampling


_WGS84_GEOD = Geod(ellps="WGS84")


def projected_unit_to_meters(crs: Any) -> float:
    """Return linear unit-to-meter conversion factor for a projected CRS."""
    if crs is None:
        return 1.0
    try:
        _, factor = crs.linear_units_factor
        if factor and math.isfinite(factor) and factor > 0:
            return float(factor)
    except Exception:
        pass
    try:
        pcrs = PyprojCRS.from_user_input(crs.to_wkt())
        if pcrs.axis_info:
            factor = pcrs.axis_info[0].unit_conversion_factor
            if factor and math.isfinite(factor) and factor > 0:
                return float(factor)
    except Exception:
        pass
    return 1.0


def compute_row_pixel_areas_m2(
    crs: Any,
    transform: Any,
    height: int,
    width: int,
) -> np.ndarray | None:
    """Compute per-row single-pixel ground area in square meters.

    Returns ``None`` for non-georeferenced TIFFs. For projected CRSs every pixel
    has identical area; for geographic CRSs (e.g. EPSG:4326) each row's pixel
    area varies with latitude and is computed on the WGS84 ellipsoid.
    """
    if crs is None or transform is None or height <= 0 or width <= 0:
        return None

    if crs.is_projected:
        unit_m = projected_unit_to_meters(crs)
        area_crs = abs(transform.a * transform.e - transform.b * transform.d)
        area_m2 = float(area_crs * (unit_m ** 2))
        return np.full(height, area_m2, dtype=np.float64)

    if crs.is_geographic:
        # ponytail: assumes row-uniform pixel area on geographic grids (exact for north-up grids).
        areas = np.empty(height, dtype=np.float64)
        a, b, c, d, e, f = (
            float(transform.a),
            float(transform.b),
            float(transform.c),
            float(transform.d),
            float(transform.e),
            float(transform.f),
        )
        for row in range(height):
            r0 = float(row)
            r1 = float(row + 1)
            lons = [
                c + b * r0,
                a + b * r0 + c,
                a + b * r1 + c,
                b * r1 + c,
            ]
            lats = [
                f + e * r0,
                d + e * r0 + f,
                d + e * r1 + f,
                e * r1 + f,
            ]
            poly_area, _ = _WGS84_GEOD.polygon_area_perimeter(lons, lats)
            areas[row] = abs(poly_area)
        return areas

    return None


def compute_gsd_meters(
    crs: Any,
    transform: Any,
    height: int,
    width: int,
) -> tuple[float, float] | None:
    """Return nominal ``(gsd_x_m, gsd_y_m)`` in meters at raster center."""
    if crs is None or transform is None or height <= 0 or width <= 0:
        return None

    if crs.is_projected:
        unit_m = projected_unit_to_meters(crs)
        gsd_x = math.hypot(transform.a, transform.d) * unit_m
        gsd_y = math.hypot(transform.b, transform.e) * unit_m
        return (float(gsd_x), float(gsd_y))

    if crs.is_geographic:
        cx = width / 2.0
        cy = height / 2.0
        lon_c, lat_c = transform @ (cx, cy)
        lon_x, lat_x = transform @ (cx + 1.0, cy)
        lon_y, lat_y = transform @ (cx, cy + 1.0)
        _, _, gsd_x = _WGS84_GEOD.inv(lon_c, lat_c, lon_x, lat_x)
        _, _, gsd_y = _WGS84_GEOD.inv(lon_c, lat_c, lon_y, lat_y)
        return (float(abs(gsd_x)), float(abs(gsd_y)))

    return None


def normalize_rgb_to_uint8(
    tile_chw: np.ndarray,
    p2: list[float],
    p98: list[float],
    src_dtype: str,
) -> np.ndarray:
    """Convert a ``(3, H, W)`` tile to ``(H, W, 3)`` ``uint8`` for RGB models."""
    if tile_chw.shape[0] != 3:
        raise ValueError(f"Expected 3 bands (CHW), got shape {tile_chw.shape}")

    if str(src_dtype) == "uint8":
        arr = np.transpose(tile_chw, (1, 2, 0))
        if arr.dtype == np.uint8:
            return arr
        return np.clip(arr, 0, 255).astype(np.uint8)

    out = np.empty((tile_chw.shape[1], tile_chw.shape[2], 3), dtype=np.uint8)
    for idx in range(3):
        ch = tile_chw[idx].astype(np.float32, copy=False)
        lo = p2[idx] if idx < len(p2) else float("nan")
        hi = p98[idx] if idx < len(p98) else float("nan")
        if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
            finite = ch[np.isfinite(ch)]
            if finite.size == 0:
                out[:, :, idx] = 0
                continue
            lo = float(np.min(finite))
            hi = float(np.max(finite))
            if hi <= lo:
                out[:, :, idx] = 0
                continue
        scaled = (ch - lo) / (hi - lo)
        scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
        out[:, :, idx] = np.clip(scaled * 255.0, 0.0, 255.0).astype(np.uint8)
    return out


def decimated_shape(height: int, width: int, max_pixels: int = 2_000_000) -> tuple[int, int, bool]:
    """Compute a downsampled ``(out_h, out_w, was_sampled)`` preserving aspect ratio."""
    total = height * width
    if total <= max_pixels or total == 0:
        return height, width, False
    scale = math.sqrt(max_pixels / float(total))
    out_h = max(1, int(round(height * scale)))
    out_w = max(1, int(round(width * scale)))
    return out_h, out_w, True


def _index_stats(values: np.ndarray) -> dict[str, float] | None:
    if values.size == 0:
        return None
    return {
        "mean": round(float(np.mean(values)), 4),
        "median": round(float(np.median(values)), 4),
        "std": round(float(np.std(values)), 4),
        "p10": round(float(np.percentile(values, 10)), 4),
        "p90": round(float(np.percentile(values, 90)), 4),
    }


def compute_spectral_indices(
    src: Any,
    band_map: dict[str, int],
    max_pixels: int = 2_000_000,
) -> dict[str, dict[str, float]]:
    """Compute summary stats for NDVI, NDWI, and NDBI when bands are available."""
    recipes: list[tuple[str, str, str]] = [
        ("ndvi", "nir", "red"),
        ("ndwi", "green", "nir"),
        ("ndbi", "swir1", "nir"),
    ]
    active = [r for r in recipes if r[1] in band_map and r[2] in band_map]
    if not active:
        return {}

    out_h, out_w, _ = decimated_shape(src.height, src.width, max_pixels=max_pixels)
    needed_indices = sorted({band_map[b] for _, a, b in active for b in (a, b)})

    raw = src.read(
        needed_indices,
        out_shape=(len(needed_indices), out_h, out_w),
        resampling=Resampling.bilinear,
    ).astype(np.float32)

    masks = src.read_masks(
        needed_indices,
        out_shape=(len(needed_indices), out_h, out_w),
        resampling=Resampling.nearest,
    )
    valid_mask = np.all(masks > 0, axis=0)
    band_arrays = {b_idx: raw[pos] for pos, b_idx in enumerate(needed_indices)}

    results: dict[str, dict[str, float]] = {}
    for name, pos_key, neg_key in active:
        a = band_arrays[band_map[pos_key]]
        b = band_arrays[band_map[neg_key]]
        denom = a + b
        mask = valid_mask & np.isfinite(a) & np.isfinite(b) & (np.abs(denom) > 1e-6)
        if not np.any(mask):
            continue
        idx_vals = np.clip((a[mask] - b[mask]) / denom[mask], -1.0, 1.0)
        stats = _index_stats(idx_vals)
        if stats is not None:
            results[name] = stats
    return results
