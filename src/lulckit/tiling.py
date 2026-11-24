"""Memory-safe sliding-window tiled inference with overlap halo discard."""

from __future__ import annotations

import json
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.windows import Window

from lulckit import __version__
from lulckit.geo import compute_row_pixel_areas_m2, normalize_rgb_to_uint8
from lulckit.inspect import TiffProfile
from lulckit.models.base import NODATA_VALUE, BaseLULCModel


@dataclass
class InferenceStats:
    """Streaming classification metrics accumulated during tiled inference."""

    class_pixels: dict[int, int] = field(default_factory=dict)
    class_area_m2: dict[int, float] = field(default_factory=dict)
    class_conf_sum: dict[int, float] = field(default_factory=dict)
    valid_pixels: int = 0
    nodata_pixels: int = 0
    tiles_processed: int = 0
    runtime_seconds: float = 0.0


def _build_tile_grid(width: int, height: int, step: int) -> list[tuple[int, int, int, int]]:
    windows: list[tuple[int, int, int, int]] = []
    for row_off in range(0, height, step):
        core_h = min(step, height - row_off)
        for col_off in range(0, width, step):
            core_w = min(step, width - col_off)
            windows.append((col_off, row_off, core_w, core_h))
    return windows


def run_tiled_inference(
    input_path: str | Path,
    profile: TiffProfile,
    model: BaseLULCModel,
    band_indices: list[int],
    preprocess_mode: str,
    output_lulc_path: str | Path,
    output_conf_path: str | Path | None = None,
    tile_size: int = 512,
    overlap: int = 64,
    batch_size: int = 4,
    progress_callback: Callable[[int, int], None] | None = None,
    extra_nodata_value: int | None = None,
) -> InferenceStats:
    """Run O(1)-RAM sliding-window LULC inference and stream GeoTIFF outputs to disk."""
    if tile_size < 64 or tile_size % 32 != 0:
        raise ValueError(f"tile_size must be >= 64 and divisible by 32, got {tile_size}")
    if overlap < 0 or overlap >= tile_size // 2:
        raise ValueError(f"overlap must satisfy 0 <= overlap < tile_size // 2 ({tile_size // 2}), got {overlap}")
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    is_categorical = preprocess_mode == "categorical"
    has_confidence = bool(getattr(model, "has_confidence", True))
    eff_tile_size = max(tile_size, 1024) if is_categorical else tile_size
    eff_overlap = 0 if is_categorical else overlap
    eff_batch_size = 1 if is_categorical else batch_size

    t_start = time.perf_counter()
    in_path = Path(input_path)
    out_lulc = Path(output_lulc_path)
    out_conf = Path(output_conf_path) if output_conf_path is not None else None
    out_lulc.parent.mkdir(parents=True, exist_ok=True)
    if out_conf is not None:
        out_conf.parent.mkdir(parents=True, exist_ok=True)

    width = profile.width
    height = profile.height
    step = eff_tile_size - 2 * eff_overlap
    grid = _build_tile_grid(width, height, step)
    total_tiles = len(grid)

    p2 = [
        profile.bands[b - 1].p2 if profile.bands[b - 1].p2 is not None else 0.0
        for b in band_indices
    ]
    p98 = [
        profile.bands[b - 1].p98 if profile.bands[b - 1].p98 is not None else 255.0
        for b in band_indices
    ]
    band_dtypes = {profile.bands[b - 1].dtype for b in band_indices}
    src_dtype = next(iter(band_dtypes)) if len(band_dtypes) == 1 else "float32"

    max_class_id = max((c.id for c in model.classes), default=0)
    class_pixels = {c.id: 0 for c in model.classes}
    class_conf_sum = {c.id: 0.0 for c in model.classes}
    class_area_m2: dict[int, float] = {c.id: 0.0 for c in model.classes}

    colormap = {c.id: (c.color[0], c.color[1], c.color[2], 255) for c in model.classes}
    colormap[NODATA_VALUE] = (0, 0, 0, 0)
    classes_meta = [
        {"id": c.id, "name": c.name, "hex": c.hex, "rgb": list(c.color)}
        for c in model.classes
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(in_path) as src:
            row_areas_m2 = (
                compute_row_pixel_areas_m2(src.crs, src.transform, height, width)
                if src.crs is not None
                else None
            )
            is_projected = bool(src.crs is not None and src.crs.is_projected)

            out_meta: dict = {
                "driver": "GTiff",
                "height": height,
                "width": width,
                "count": 1,
                "dtype": "uint8",
                "nodata": NODATA_VALUE,
                "compress": "deflate",
            }
            if src.crs is not None:
                out_meta["crs"] = src.crs
                out_meta["transform"] = src.transform
            if width >= 256 and height >= 256:
                out_meta.update({"tiled": True, "blockxsize": 256, "blockysize": 256})
            else:
                out_meta["tiled"] = False

            conf_meta = {**out_meta, "nodata": 0}
            conf_ctx = rasterio.open(out_conf, "w", **conf_meta) if out_conf is not None else None

            try:
                with rasterio.open(out_lulc, "w", **out_meta) as dst_lulc:
                    dst_lulc.write_colormap(1, colormap)
                    dst_lulc.set_band_description(1, "LULC_Class")
                    dst_lulc.update_tags(
                        lulc_model=model.name,
                        lulc_classes_json=json.dumps(classes_meta),
                        source_file=profile.file_name,
                        created_by=f"lulckit/{__version__}",
                    )
                    if conf_ctx is not None:
                        conf_ctx.set_band_description(1, "Confidence_Percent")
                        conf_ctx.update_tags(
                            lulc_model=model.name,
                            source_file=profile.file_name,
                            created_by=f"lulckit/{__version__}",
                        )

                    valid_total = 0
                    nodata_total = 0

                    for start in range(0, total_tiles, eff_batch_size):
                        batch_specs = grid[start : start + eff_batch_size]
                        batch_inputs: list[np.ndarray] = []
                        batch_core_info: list[tuple[Window, np.ndarray]] = []

                        for col_off, row_off, core_w, core_h in batch_specs:
                            if is_categorical:
                                core_win = Window(col_off, row_off, core_w, core_h)
                                arr = src.read(band_indices, window=core_win)
                                tile_ready = arr[0]
                                rx0, ry0 = col_off, row_off
                            else:
                                x0 = col_off - eff_overlap
                                y0 = row_off - eff_overlap
                                x1 = x0 + eff_tile_size
                                y1 = y0 + eff_tile_size

                                rx0 = max(0, x0)
                                ry0 = max(0, y0)
                                rx1 = min(width, x1)
                                ry1 = min(height, y1)
                                rw = rx1 - rx0
                                rh = ry1 - ry0

                                arr = src.read(band_indices, window=Window(rx0, ry0, rw, rh))
                                pad_left = rx0 - x0
                                pad_top = ry0 - y0
                                pad_right = x1 - rx1
                                pad_bottom = y1 - ry1

                                if pad_left or pad_right or pad_top or pad_bottom:
                                    padded = np.pad(
                                        arr,
                                        ((0, 0), (pad_top, pad_bottom), (pad_left, pad_right)),
                                        mode="edge",
                                    )
                                else:
                                    padded = arr

                                if preprocess_mode == "rgb":
                                    tile_ready = normalize_rgb_to_uint8(padded, p2, p98, src_dtype)
                                elif preprocess_mode == "s2":
                                    tile_ready = padded.astype(np.float32, copy=False)
                                else:
                                    raise ValueError(f"Unsupported preprocess_mode: {preprocess_mode}")

                                core_win = Window(col_off, row_off, core_w, core_h)

                            core_masks = src.read_masks(band_indices, window=core_win)
                            valid = np.all(core_masks > 0, axis=0)
                            if profile.alpha_band is not None:
                                alpha_arr = src.read(profile.alpha_band, window=core_win)
                                valid &= alpha_arr > 0

                            cy0 = row_off - ry0
                            cx0 = col_off - rx0
                            core_raw = arr[:, cy0 : cy0 + core_h, cx0 : cx0 + core_w]
                            if extra_nodata_value is not None and is_categorical:
                                valid &= core_raw[0] != extra_nodata_value
                            if np.issubdtype(core_raw.dtype, np.floating):
                                valid &= np.all(np.isfinite(core_raw), axis=0)

                            batch_inputs.append(tile_ready)
                            batch_core_info.append((core_win, valid))

                        batch_arr = np.stack(batch_inputs, axis=0)
                        pred_batch, conf_batch = model.predict_batch(batch_arr)

                        for idx, (core_win, valid) in enumerate(batch_core_info):
                            core_w = int(core_win.width)
                            core_h = int(core_win.height)
                            row_off = int(core_win.row_off)

                            core_pred = pred_batch[
                                idx, eff_overlap : eff_overlap + core_h, eff_overlap : eff_overlap + core_w
                            ].copy()
                            core_conf = conf_batch[
                                idx, eff_overlap : eff_overlap + core_h, eff_overlap : eff_overlap + core_w
                            ].copy()
                            core_pred[~valid] = NODATA_VALUE
                            core_conf[~valid] = 0

                            dst_lulc.write(core_pred, 1, window=core_win)
                            if conf_ctx is not None:
                                conf_ctx.write(core_conf, 1, window=core_win)

                            v_count = int(np.count_nonzero(valid))
                            valid_total += v_count
                            nodata_total += int(core_pred.size - v_count)

                            if v_count > 0:
                                valid_preds = core_pred[valid]
                                counts = np.bincount(valid_preds, minlength=max_class_id + 1)
                                conf_sums = (
                                    np.bincount(
                                        valid_preds,
                                        weights=core_conf[valid].astype(np.float64),
                                        minlength=max_class_id + 1,
                                    )
                                    if has_confidence
                                    else None
                                )
                                present = np.flatnonzero(counts)
                                for cid in present.tolist():
                                    cnt = int(counts[cid])
                                    class_pixels[cid] = class_pixels.get(cid, 0) + cnt
                                    if conf_sums is not None:
                                        class_conf_sum[cid] = class_conf_sum.get(cid, 0.0) + float(conf_sums[cid])
                                    if row_areas_m2 is not None:
                                        if is_projected:
                                            class_area_m2[cid] = class_area_m2.get(cid, 0.0) + cnt * float(row_areas_m2[0])
                                        else:
                                            row_counts = np.count_nonzero(valid & (core_pred == cid), axis=1)
                                            area_slice = float(
                                                np.dot(row_counts, row_areas_m2[row_off : row_off + core_h])
                                            )
                                            class_area_m2[cid] = class_area_m2.get(cid, 0.0) + area_slice

                        if progress_callback is not None:
                            progress_callback(min(start + len(batch_specs), total_tiles), total_tiles)

                    if max(width, height) > 1024:
                        factors = [2, 4, 8, 16, 32] if max(width, height) > 4096 else [2, 4, 8, 16]
                        dst_lulc.build_overviews(factors, Resampling.nearest)
                        dst_lulc.update_tags(ns="rio_overview", resampling="nearest")
            finally:
                if conf_ctx is not None:
                    conf_ctx.close()

    if row_areas_m2 is None:
        final_area_m2: dict[int, float] = {}
    else:
        final_area_m2 = class_area_m2

    return InferenceStats(
        class_pixels=class_pixels,
        class_area_m2=final_area_m2,
        class_conf_sum=class_conf_sum,
        valid_pixels=valid_total,
        nodata_pixels=nodata_total,
        tiles_processed=total_tiles,
        runtime_seconds=round(time.perf_counter() - t_start, 3),
    )
