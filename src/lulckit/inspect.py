"""Full TIFF/GeoTIFF metadata profiling, band statistics, and sensor fingerprinting."""

from __future__ import annotations

import math
import re
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from lulckit.geo import (
    compute_gsd_meters,
    compute_row_pixel_areas_m2,
    decimated_shape,
)


_S2_DW_BANDS = ("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12")
_S2_CANONICAL_MAPS: dict[int, tuple[list[int], list[int], dict[str, int]]] = {
    # (s2_dw_9bands_1based, rgb_bands_1based, spectral_band_map)
    9: ([1, 2, 3, 4, 5, 6, 7, 8, 9], [3, 2, 1], {"blue": 1, "green": 2, "red": 3, "nir": 7, "swir1": 8, "swir2": 9}),
    10: ([1, 2, 3, 4, 5, 6, 7, 9, 10], [3, 2, 1], {"blue": 1, "green": 2, "red": 3, "nir": 7, "swir1": 9, "swir2": 10}),
    12: ([2, 3, 4, 5, 6, 7, 8, 11, 12], [4, 3, 2], {"blue": 2, "green": 3, "red": 4, "nir": 8, "swir1": 11, "swir2": 12}),
    13: ([2, 3, 4, 5, 6, 7, 8, 12, 13], [4, 3, 2], {"blue": 2, "green": 3, "red": 4, "nir": 8, "swir1": 12, "swir2": 13}),
}

_INT_DTYPES = frozenset({"uint8", "int8", "uint16", "int16", "uint32", "int32"})
_TAG_NAMESPACES = ("IMAGE_STRUCTURE", "EXIF", "DERIVED_SUBDATASETS", "RPC", "GEOLOCATION")


@dataclass
class BandInfo:
    index: int
    dtype: str
    nodata: float | int | None
    description: str | None
    colorinterp: str
    min: float | None
    max: float | None
    mean: float | None
    std: float | None
    p2: float | None
    p98: float | None
    valid_ratio: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class TiffProfile:
    path: str
    file_name: str
    file_size_bytes: int
    driver: str
    width: int
    height: int
    band_count: int
    total_pixels: int
    dtypes: list[str]
    nodata: float | int | None
    compression: str | None
    is_tiled: bool
    block_shapes: list[list[int]]
    interleave: str | None
    photometric: str | None
    overviews: list[int]
    is_cog_like: bool
    stats_sampled: bool
    valid_pixel_ratio: float
    is_georeferenced: bool
    crs_epsg: int | None
    crs_name: str | None
    crs_units: str | None
    crs_is_projected: bool | None
    crs_is_geographic: bool | None
    crs_wkt: str | None
    crs_proj4: str | None
    transform: list[float] | None
    gsd_meters: list[float] | None
    bounds_native: list[float] | None
    bounds_wgs84: list[float] | None
    centroid_wgs84: list[float] | None
    total_area_m2: float | None
    valid_area_m2: float | None
    bands: list[BandInfo]
    tags: dict[str, str]
    tag_namespaces: dict[str, dict[str, str]]
    alpha_band: int | None
    non_alpha_bands: list[int]
    detected_profile: str
    recommended_model: str | None
    rgb_bands: list[int] | None
    s2_bands: list[int] | None
    spectral_band_map: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    unique_values: list[int] | None = None
    embedded_colormap: bool = False
    zero_is_background: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize profile to a JSON-safe dictionary."""
        return _json_sanitize(asdict(self))


def _json_sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, np.generic):
        return _json_sanitize(obj.item())
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def _clean_scalar(val: Any) -> float | int | None:
    if val is None:
        return None
    if isinstance(val, np.generic):
        val = val.item()
    if isinstance(val, float) and not math.isfinite(val):
        return None
    return val


def _match_s2_token(text: str) -> str | None:
    """Extract canonical Sentinel-2 band code (e.g. 'B2', 'B8A', 'B11') if present."""
    if not text:
        return None
    upper = text.upper()
    m = re.search(r"(?<![A-Z0-9])B0?(1[0-2]|[1-9])(A)?(?![A-Z0-9])", upper)
    if not m:
        return None
    num = int(m.group(1))
    suffix = m.group(2) or ""
    if suffix and num != 8:
        return None
    return f"B{num}{suffix}"


def _band_text(band: BandInfo) -> str:
    parts = [band.description or ""]
    for key in ("BANDNAME", "NAME", "DESCRIPTION", "WAVELENGTH"):
        if key in band.tags:
            parts.append(band.tags[key])
    return " ".join(parts).strip()


def _detect_spectral_roles(non_alpha: list[BandInfo]) -> dict[str, int]:
    """Identify red/green/blue/nir/swir1/swir2 from descriptions, tags, or ColorInterp."""
    roles: dict[str, int] = {}
    for band in non_alpha:
        ci = band.colorinterp.lower()
        txt = _band_text(band).lower()
        if "red" not in roles and (ci == "red" or re.search(r"\b(red|b0?4|sr_b4)\b", txt)):
            roles["red"] = band.index
        elif "green" not in roles and (ci == "green" or re.search(r"\b(green|b0?3|sr_b3)\b", txt)):
            roles["green"] = band.index
        elif "blue" not in roles and (ci == "blue" or re.search(r"\b(blue|b0?2|sr_b2)\b", txt)):
            roles["blue"] = band.index
        elif "nir" not in roles and re.search(r"\b(nir|near[-_ ]?infrared|b0?8a?|sr_b5)\b", txt):
            roles["nir"] = band.index
        elif "swir1" not in roles and re.search(r"\b(swir[-_ ]?1|b11|sr_b6)\b", txt):
            roles["swir1"] = band.index
        elif "swir2" not in roles and re.search(r"\b(swir[-_ ]?2|b12|sr_b7)\b", txt):
            roles["swir2"] = band.index
    return roles


def _fingerprint_raster(
    path: Path,
    bands: list[BandInfo],
    is_georeferenced: bool,
    gsd_meters: list[float] | None,
    tags: dict[str, str],
    unique_values: list[int] | None = None,
) -> tuple[int | None, list[int], str, str | None, list[int] | None, list[int] | None, dict[str, int], list[str]]:
    notes: list[str] = []
    alpha_indices = [
        b.index
        for b in bands
        if b.colorinterp == "alpha" or (b.description and "alpha" in b.description.lower())
    ]
    alpha_band = alpha_indices[-1] if alpha_indices else None
    non_alpha = [b for b in bands if b.index not in alpha_indices]
    non_alpha_idx = [b.index for b in non_alpha]

    if not non_alpha:
        notes.append("Raster contains only alpha channel(s) and no optical spectral bands.")
        return alpha_band, [], "single-band-unsupported", None, None, None, {}, notes

    gsd_mean = float(sum(gsd_meters) / 2.0) if gsd_meters else None

    # 1. Check explicit Sentinel-2 band descriptions / tags
    s2_found: dict[str, int] = {}
    for band in non_alpha:
        tok = _match_s2_token(_band_text(band))
        if tok and tok not in s2_found:
            s2_found[tok] = band.index

    if all(b in s2_found for b in _S2_DW_BANDS):
        s2_bands = [s2_found[b] for b in _S2_DW_BANDS]
        rgb_bands = [s2_found["B4"], s2_found["B3"], s2_found["B2"]]
        spectral = {
            "blue": s2_found["B2"],
            "green": s2_found["B3"],
            "red": s2_found["B4"],
            "nir": s2_found["B8"],
            "swir1": s2_found["B11"],
            "swir2": s2_found["B12"],
        }
        return alpha_band, non_alpha_idx, "sentinel2-multispectral", "s2-dw", rgb_bands, s2_bands, spectral, notes

    # 2. Canonical Sentinel-2 stack heuristic when band descriptions are absent
    name_hint = any(k in path.stem.upper() for k in ("S2", "SENTINEL", "DYNAMICWORLD", "DW"))
    tag_hint = any("SENTINEL" in str(v).upper() for v in tags.values())
    gsd_s2_like = gsd_mean is not None and 5.0 <= gsd_mean <= 25.0
    if len(non_alpha) in _S2_CANONICAL_MAPS and (gsd_s2_like or name_hint or tag_hint):
        dw_pos, rgb_pos, sp_pos = _S2_CANONICAL_MAPS[len(non_alpha)]
        s2_bands = [non_alpha_idx[i - 1] for i in dw_pos]
        rgb_bands = [non_alpha_idx[i - 1] for i in rgb_pos]
        spectral = {k: non_alpha_idx[v - 1] for k, v in sp_pos.items()}
        notes.append(
            f"Inferred canonical {len(non_alpha)}-band Sentinel-2 band order without explicit band descriptions; "
            "pass --s2-bands if your band order differs."
        )
        return alpha_band, non_alpha_idx, "sentinel2-multispectral", "s2-dw", rgb_bands, s2_bands, spectral, notes

    # 2b. Canonical 6-band Landsat C2 or Sentinel-2 stack (B2,B3,B4,NIR,SWIR1,SWIR2)
    if len(non_alpha) == 6:
        upper_stem = path.stem.upper()
        upper_texts = " ".join(_band_text(b).upper() for b in non_alpha)
        landsat_hint = any(k in upper_stem for k in ("LANDSAT", "LC08", "LC09", "LE07", "LT05")) or "SR_B" in upper_texts
        gsd_landsat_like = gsd_mean is not None and 25.0 <= gsd_mean <= 35.0
        if landsat_hint or gsd_landsat_like or "SR_B5" in upper_texts:
            spectral = {
                "blue": non_alpha_idx[0],
                "green": non_alpha_idx[1],
                "red": non_alpha_idx[2],
                "nir": non_alpha_idx[3],
                "swir1": non_alpha_idx[4],
                "swir2": non_alpha_idx[5],
            }
            rgb_bands = [non_alpha_idx[2], non_alpha_idx[1], non_alpha_idx[0]]
            notes.append(
                "Detected 6-band Landsat multispectral stack (coarse 30m GSD for RGB model; results may be generalized)."
            )
            return alpha_band, non_alpha_idx, "landsat-multispectral", "rgb-oem", rgb_bands, None, spectral, notes

        if name_hint or tag_hint or gsd_s2_like:
            spectral = {
                "blue": non_alpha_idx[0],
                "green": non_alpha_idx[1],
                "red": non_alpha_idx[2],
                "nir": non_alpha_idx[3],
                "swir1": non_alpha_idx[4],
                "swir2": non_alpha_idx[5],
            }
            rgb_bands = [non_alpha_idx[2], non_alpha_idx[1], non_alpha_idx[0]]
            notes.append(
                "Detected 6-band Sentinel-2 stack (B2,B3,B4,B8,B11,B12); using RGB bands for classification "
                "(pass 9-band Sentinel-2 stack for s2-dw)."
            )
            return alpha_band, non_alpha_idx, "sentinel2-6band", "rgb-oem", rgb_bands, None, spectral, notes

    # 3. Single-band categorical vs unsupported 1-band or 2-band rasters
    if len(non_alpha) == 1:
        if unique_values is not None and 1 <= len(unique_values) <= 32:
            vals_str = ", ".join(str(v) for v in unique_values)
            notes.append(
                f"Detected pre-classified discrete categorical raster (values: [{vals_str}]). "
                "Pass --class-labels, --class-colors, or --nodata-value to customize styling and masking."
            )
            return alpha_band, non_alpha_idx, "categorical-classified", "categorical", None, None, {}, notes

        notes.append(
            "Single-band raster detected (e.g., DEM, SAR, thermal, or continuous raster). "
            "Pretrained optical LULC models require 3+ RGB or Sentinel-2 multispectral bands."
        )
        return alpha_band, non_alpha_idx, "single-band-unsupported", None, None, None, {}, notes

    if len(non_alpha) == 2:
        notes.append(
            "Two-band raster detected; optical LULC models require at least 3 RGB bands or 9 Sentinel-2 bands."
        )
        return alpha_band, non_alpha_idx, "two-band-unsupported", None, None, None, {}, notes

    # 4. Optical 3-band / 4-band / other multispectral
    roles = _detect_spectral_roles(non_alpha)
    if all(k in roles for k in ("red", "green", "blue")):
        rgb_bands = [roles["red"], roles["green"], roles["blue"]]
    else:
        rgb_bands = non_alpha_idx[:3]
        roles.setdefault("red", rgb_bands[0])
        roles.setdefault("green", rgb_bands[1])
        roles.setdefault("blue", rgb_bands[2])

    if len(non_alpha) == 4:
        remaining = [idx for idx in non_alpha_idx if idx not in rgb_bands]
        if "nir" not in roles and remaining:
            roles["nir"] = remaining[0]
        if gsd_mean is not None and gsd_mean > 5.0:
            notes.append(
                f"Coarse GSD ({gsd_mean:.1f} m/px) for high-resolution RGB model; fine-scale objects may be missed."
            )
            return alpha_band, non_alpha_idx, "rgbn-multispectral", "rgb-oem", rgb_bands, None, roles, notes
        return alpha_band, non_alpha_idx, "rgbn-aerial", "rgb-oem", rgb_bands, None, roles, notes

    if len(non_alpha) == 3:
        if not is_georeferenced:
            notes.append(
                "Plain non-georeferenced TIFF (no CRS/transform); pixel counts and % coverage will be computed, "
                "while geographic bounds and m²/ha/km² areas will be null."
            )
            return alpha_band, non_alpha_idx, "plain-rgb", "rgb-oem", rgb_bands, None, roles, notes
        if gsd_mean is not None and gsd_mean > 5.0:
            notes.append(
                f"Coarse RGB GSD ({gsd_mean:.1f} m/px) for high-resolution OpenEarthMap model; results may be generalized."
            )
            return alpha_band, non_alpha_idx, "rgb-coarse", "rgb-oem", rgb_bands, None, roles, notes
        return alpha_band, non_alpha_idx, "rgb-highres", "rgb-oem", rgb_bands, None, roles, notes

    # 5+ non-alpha bands not matched as Sentinel-2
    notes.append(
        f"{len(non_alpha)}-band multispectral raster not recognized as Sentinel-2; defaulting to RGB model using bands "
        f"{rgb_bands}. Override with --rgb-bands or --model s2-dw --s2-bands ..."
    )
    return alpha_band, non_alpha_idx, "multispectral-other", "rgb-oem", rgb_bands, None, roles, notes


def inspect_tiff(path: str | Path) -> TiffProfile:
    """Inspect a TIFF/GeoTIFF and return full metadata, stats, and sensor profile."""
    tiff_path = Path(path).resolve()
    if not tiff_path.is_file():
        raise FileNotFoundError(f"TIFF file not found: {tiff_path}")

    file_size = tiff_path.stat().st_size

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        with rasterio.open(tiff_path) as src:
            width = int(src.width)
            height = int(src.height)
            band_count = int(src.count)
            total_pixels = width * height
            driver = str(src.driver)
            dtypes = [str(d) for d in src.dtypes]
            nodata = _clean_scalar(src.nodata)
            compression = src.compression.value if hasattr(src.compression, "value") else (str(src.compression) if src.compression else None)
            is_tiled = bool(src.is_tiled)
            block_shapes = [[int(h), int(w)] for h, w in src.block_shapes]
            interleave = src.interleaving.value if hasattr(src.interleaving, "value") else (str(src.interleaving) if src.interleaving else None)

            root_tags = {str(k): str(v) for k, v in src.tags().items()}
            tag_namespaces: dict[str, dict[str, str]] = {}
            for ns in _TAG_NAMESPACES:
                ns_tags = src.tags(ns=ns)
                if ns_tags:
                    tag_namespaces[ns] = {str(k): str(v) for k, v in ns_tags.items()}
            photometric = tag_namespaces.get("IMAGE_STRUCTURE", {}).get("PHOTOMETRIC") or root_tags.get("PHOTOMETRIC")

            overviews = [int(o) for o in src.overviews(1)] if band_count > 0 else []
            is_cog_like = bool(is_tiled and (bool(overviews) or max(width, height) <= 512))
            embedded_colormap = False
            if band_count > 0:
                try:
                    embedded_colormap = bool(src.colormap(1))
                except ValueError:
                    embedded_colormap = False

            # Geospatial details
            crs = src.crs
            is_georef = crs is not None
            transform_list = [float(v) for v in src.transform[:6]] if is_georef else None

            crs_epsg = crs.to_epsg() if is_georef else None
            crs_name = None
            crs_units = None
            crs_is_proj = None
            crs_is_geo = None
            crs_wkt = None
            crs_proj4 = None
            if is_georef:
                crs_is_proj = bool(crs.is_projected)
                crs_is_geo = bool(crs.is_geographic)
                crs_wkt = crs.to_wkt()
                try:
                    crs_proj4 = crs.to_proj4()
                except Exception:
                    crs_proj4 = None
                try:
                    from pyproj import CRS as PyprojCRS

                    pcrs = PyprojCRS.from_user_input(crs_wkt)
                    crs_name = pcrs.name
                    if pcrs.axis_info:
                        crs_units = pcrs.axis_info[0].unit_name
                except Exception:
                    crs_name = str(crs)

            gsd_tuple = compute_gsd_meters(crs, src.transform, height, width) if is_georef else None
            gsd_meters = [round(gsd_tuple[0], 6), round(gsd_tuple[1], 6)] if gsd_tuple else None

            bounds_native = [float(v) for v in src.bounds] if is_georef else None
            bounds_wgs84 = None
            centroid_wgs84 = None
            if is_georef:
                try:
                    wgs_b = transform_bounds(crs, "EPSG:4326", *src.bounds, densify_pts=21)
                    bounds_wgs84 = [round(float(v), 7) for v in wgs_b]
                    centroid_wgs84 = [
                        round((bounds_wgs84[0] + bounds_wgs84[2]) / 2.0, 7),
                        round((bounds_wgs84[1] + bounds_wgs84[3]) / 2.0, 7),
                    ]
                except Exception:
                    pass

            # Sampled/full band stats
            out_h, out_w, stats_sampled = decimated_shape(height, width, max_pixels=2_000_000)
            arr = src.read(out_shape=(band_count, out_h, out_w), resampling=Resampling.nearest)
            mask_arr = src.read_masks(out_shape=(band_count, out_h, out_w), resampling=Resampling.nearest)
            overall_valid_mask = np.all(mask_arr > 0, axis=0) if band_count > 0 else np.ones((out_h, out_w), dtype=bool)
            valid_pixel_ratio = round(float(np.mean(overall_valid_mask)), 6) if overall_valid_mask.size else 0.0

            row_areas = compute_row_pixel_areas_m2(crs, src.transform, height, width) if is_georef else None
            total_area_m2 = float(np.sum(row_areas) * width) if row_areas is not None else None
            valid_area_m2 = (
                float(total_area_m2 * valid_pixel_ratio)
                if total_area_m2 is not None
                else None
            )

            bands: list[BandInfo] = []
            descriptions = src.descriptions
            colorinterp = src.colorinterp
            nodatavals = src.nodatavals

            for b_idx in range(1, band_count + 1):
                b_data = arr[b_idx - 1].astype(np.float64, copy=False)
                b_mask = (mask_arr[b_idx - 1] > 0) & np.isfinite(b_data)
                b_valid_ratio = round(float(np.mean(b_mask)), 6) if b_mask.size else 0.0
                valid_vals = b_data[b_mask]

                if valid_vals.size > 0:
                    b_min = float(np.min(valid_vals))
                    b_max = float(np.max(valid_vals))
                    b_mean = float(np.mean(valid_vals))
                    b_std = float(np.std(valid_vals))
                    b_p2, b_p98 = (float(x) for x in np.percentile(valid_vals, [2, 98]))
                else:
                    b_min = b_max = b_mean = b_std = b_p2 = b_p98 = None

                ci_obj = colorinterp[b_idx - 1] if b_idx - 1 < len(colorinterp) else ColorInterp.undefined
                ci_name = ci_obj.name if hasattr(ci_obj, "name") else str(ci_obj)
                desc = descriptions[b_idx - 1] if b_idx - 1 < len(descriptions) else None
                desc = desc.strip() if isinstance(desc, str) and desc.strip() else None
                b_nodata = _clean_scalar(nodatavals[b_idx - 1] if b_idx - 1 < len(nodatavals) else nodata)
                b_tags = {str(k): str(v) for k, v in src.tags(b_idx).items()}

                bands.append(
                    BandInfo(
                        index=b_idx,
                        dtype=dtypes[b_idx - 1],
                        nodata=b_nodata,
                        description=desc,
                        colorinterp=ci_name,
                        min=_clean_scalar(b_min),
                        max=_clean_scalar(b_max),
                        mean=_clean_scalar(b_mean),
                        std=_clean_scalar(b_std),
                        p2=_clean_scalar(b_p2),
                        p98=_clean_scalar(b_p98),
                        valid_ratio=b_valid_ratio,
                        tags=b_tags,
                    )
                )

            unique_values: list[int] | None = None
            zero_is_background = False
            non_alpha_candidates = [
                b for b in bands
                if b.colorinterp != "alpha" and not (b.description and "alpha" in b.description.lower())
            ]
            if len(non_alpha_candidates) == 1 and non_alpha_candidates[0].dtype in _INT_DTYPES:
                sb_idx = non_alpha_candidates[0].index
                sample_valid = arr[sb_idx - 1][mask_arr[sb_idx - 1] > 0]
                if sample_valid.size > 0:
                    uniq = np.unique(sample_valid)
                    if 1 <= len(uniq) <= 32:
                        unique_values = [int(v) for v in uniq]
                        if 0 in unique_values and width > 0 and height > 0:
                            corner_coords = (
                                (0, 0),
                                (width - 1, 0),
                                (0, height - 1),
                                (width - 1, height - 1),
                            )
                            corners = [
                                int(src.read(sb_idx, window=Window(cx, cy, 1, 1))[0, 0])
                                for cx, cy in corner_coords
                            ]
                            zero_is_background = all(c == 0 for c in corners)

    (
        alpha_band,
        non_alpha_bands,
        detected_profile,
        recommended_model,
        rgb_bands,
        s2_bands,
        spectral_band_map,
        fp_warnings,
    ) = _fingerprint_raster(
        tiff_path, bands, is_georef, gsd_meters, root_tags, unique_values=unique_values
    )

    return TiffProfile(
        path=str(tiff_path),
        file_name=tiff_path.name,
        file_size_bytes=file_size,
        driver=driver,
        width=width,
        height=height,
        band_count=band_count,
        total_pixels=total_pixels,
        dtypes=dtypes,
        nodata=nodata,
        compression=compression,
        is_tiled=is_tiled,
        block_shapes=block_shapes,
        interleave=interleave,
        photometric=photometric,
        overviews=overviews,
        is_cog_like=is_cog_like,
        stats_sampled=stats_sampled,
        valid_pixel_ratio=valid_pixel_ratio,
        is_georeferenced=is_georef,
        crs_epsg=crs_epsg,
        crs_name=crs_name,
        crs_units=crs_units,
        crs_is_projected=crs_is_proj,
        crs_is_geographic=crs_is_geo,
        crs_wkt=crs_wkt,
        crs_proj4=crs_proj4,
        transform=transform_list,
        gsd_meters=gsd_meters,
        bounds_native=bounds_native,
        bounds_wgs84=bounds_wgs84,
        centroid_wgs84=centroid_wgs84,
        total_area_m2=total_area_m2,
        valid_area_m2=valid_area_m2,
        bands=bands,
        tags=root_tags,
        tag_namespaces=tag_namespaces,
        alpha_band=alpha_band,
        non_alpha_bands=non_alpha_bands,
        detected_profile=detected_profile,
        recommended_model=recommended_model,
        rgb_bands=rgb_bands,
        s2_bands=s2_bands,
        spectral_band_map=spectral_band_map,
        warnings=fp_warnings,
        unique_values=unique_values,
        embedded_colormap=embedded_colormap,
        zero_is_background=zero_is_background,
    )
