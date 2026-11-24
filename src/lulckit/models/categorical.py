"""Direct pass-through adapter for pre-classified single-band categorical GeoTIFFs."""

from __future__ import annotations

import numpy as np

from lulckit.cartography import resolve_palette_color
from lulckit.models.base import (
    CANONICAL_CLASS_COLORS,
    NODATA_VALUE,
    BaseLULCModel,
    ClassSpec,
)


ESA_WORLDCOVER_CLASSES: dict[int, tuple[str, tuple[int, int, int]]] = {
    10: ("Tree cover", (0, 100, 0)),
    20: ("Shrubland", (255, 187, 34)),
    30: ("Grassland", (255, 255, 76)),
    40: ("Cropland", (240, 150, 255)),
    50: ("Built-up", (250, 0, 0)),
    60: ("Bare / sparse vegetation", (180, 180, 180)),
    70: ("Snow and ice", (240, 240, 240)),
    80: ("Permanent water bodies", (0, 100, 200)),
    90: ("Herbaceous wetland", (0, 150, 160)),
    95: ("Mangroves", (0, 207, 117)),
    100: ("Moss and lichen", (250, 230, 160)),
}

_BACKGROUND_COLOR: tuple[int, int, int] = (255, 255, 255)


def _match_canonical_color(label: str) -> tuple[int, int, int] | None:
    norm = label.strip().lower().replace("-", " ")
    if norm in CANONICAL_CLASS_COLORS:
        return CANONICAL_CLASS_COLORS[norm]
    norm_under = norm.replace(" ", "_")
    return CANONICAL_CLASS_COLORS.get(norm_under)


class CategoricalPassThroughModel(BaseLULCModel):
    """Zero-ML pass-through model for pre-classified integer LULC/crop GeoTIFFs."""

    has_confidence: bool = False

    def __init__(
        self,
        unique_values: list[int],
        band_description: str | None = None,
        embedded_colormap_dict: dict[int, tuple[int, int, int, int]] | None = None,
        class_labels: dict[int, str] | None = None,
        class_colors: dict[int, tuple[int, int, int]] | None = None,
        nodata_value: int | None = None,
        zero_is_background: bool = False,
        palette: str = "default",
    ) -> None:
        self.name = "categorical"
        self.description = "Direct pass-through for pre-classified discrete integer GeoTIFFs (no ML inference)"
        self.expected_bands = 1
        self.optimal_gsd_m = "any"
        self.nodata_value = nodata_value

        labels_override = class_labels or {}
        colors_override = class_colors or {}
        cmap = embedded_colormap_dict or {}
        explicit_palette = palette.strip().lower() != "default"

        active_vals = sorted(v for v in unique_values if nodata_value is None or v != nodata_value)
        if not active_vals:
            raise ValueError("No non-nodata classes remain after excluding nodata_value.")

        self._identity = all(0 <= v < NODATA_VALUE for v in active_vals)
        if self._identity:
            self.raw_to_out = {v: v for v in active_vals}
        else:
            if len(active_vals) > NODATA_VALUE:
                raise ValueError(f"Too many discrete classes ({len(active_vals)}) to fit into uint8 [0..254].")
            self.raw_to_out = {v: idx for idx, v in enumerate(active_vals)}

        is_esa = len(active_vals) >= 2 and all(v in ESA_WORLDCOVER_CLASSES for v in active_vals)
        clean_desc = band_description.strip() if band_description else ""
        fg_total = max(1, sum(1 for v in active_vals if not (v == 0 and zero_is_background)))

        self.classes = []
        fg_idx = 0
        for raw_val in active_vals:
            out_id = self.raw_to_out[raw_val]
            is_bg = raw_val == 0 and zero_is_background

            # 1. Name priority: explicit > ESA WorldCover > band description / background
            if raw_val in labels_override:
                label = labels_override[raw_val]
            elif is_esa:
                label = ESA_WORLDCOVER_CLASSES[raw_val][0]
            elif is_bg:
                label = "Background / Class 0"
            elif clean_desc:
                label = f"{clean_desc} {raw_val}"
            else:
                label = f"Class {raw_val}"

            # 2. Color priority: explicit > explicit palette > embedded colormap > ESA/canonical > bg white > default palette
            if raw_val in colors_override:
                color = colors_override[raw_val]
            elif is_bg:
                color = _BACKGROUND_COLOR
            elif explicit_palette:
                color = resolve_palette_color(palette, fg_idx, total=fg_total)
                fg_idx += 1
            elif raw_val in cmap and len(cmap[raw_val]) >= 3:
                color = (int(cmap[raw_val][0]), int(cmap[raw_val][1]), int(cmap[raw_val][2]))
            elif is_esa:
                color = ESA_WORLDCOVER_CLASSES[raw_val][1]
            else:
                canonical = _match_canonical_color(label)
                if canonical is not None:
                    color = canonical
                else:
                    color = resolve_palette_color("default", fg_idx, total=fg_total)
                    fg_idx += 1

            self.classes.append(ClassSpec(id=out_id, name=label, color=color))

    def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Map ``(B, H, W)`` or ``(B, 1, H, W)`` integer tiles to uint8 output classes + zero confidence."""
        arr = tiles[:, 0] if tiles.ndim == 4 and tiles.shape[1] == 1 else tiles
        if arr.ndim != 3:
            raise ValueError(f"Expected (B, H, W) categorical tiles, got {tiles.shape}")

        if self._identity:
            out = arr.astype(np.uint8, copy=False)
        else:
            out = np.full(arr.shape, NODATA_VALUE, dtype=np.uint8)
            for raw_val, out_id in self.raw_to_out.items():
                out[arr == raw_val] = out_id

        zeros = np.zeros(out.shape, dtype=np.uint8)
        return out, zeros
