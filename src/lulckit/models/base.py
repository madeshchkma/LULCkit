"""Base classes, canonical GIS color palettes, and cache path helpers."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np


NODATA_VALUE = 255


def get_cache_dir() -> Path:
    """Return local cache directory for downloaded weights."""
    override = os.environ.get("LULC_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "lulckit"


@dataclass(frozen=True)
class ClassSpec:
    """Single LULC class ID, display name, and RGB color."""

    id: int
    name: str
    color: tuple[int, int, int]

    @property
    def hex(self) -> str:
        return f"#{self.color[0]:02X}{self.color[1]:02X}{self.color[2]:02X}"


# Canonical GIS colors keyed by normalized lowercase label name
CANONICAL_CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    # Shared / background / unknown
    "background": (44, 44, 44),
    "ignore": (44, 44, 44),
    "unknown": (110, 110, 110),
    "nodata": (0, 0, 0),
    # Dynamic World official palette
    "water": (65, 155, 223),              # #419BDF
    "trees": (57, 125, 73),               # #397D49
    "tree": (57, 125, 73),
    "forest": (57, 125, 73),
    "forest_land": (57, 125, 73),
    "grass": (136, 176, 83),              # #88B053
    "rangeland": (136, 176, 83),
    "flooded_vegetation": (122, 135, 198), # #7A87C6
    "crops": (228, 150, 53),              # #E49635
    "agriculture": (228, 150, 53),
    "agricultural": (228, 150, 53),
    "agriculture land": (228, 150, 53),
    "agriculture_land": (228, 150, 53),
    "shrub_and_scrub": (223, 195, 90),    # #DFC35A
    "built_area": (196, 40, 27),          # #C4281B
    "building": (196, 40, 27),
    "buildings": (196, 40, 27),
    "urban_land": (196, 40, 27),
    "developed space": (158, 158, 158),
    "road": (74, 74, 74),
    "bare_ground": (165, 155, 143),       # #A59B8F
    "bareland": (165, 155, 143),
    "barren": (165, 155, 143),
    "barren_land": (165, 155, 143),
    "snow_and_ice": (179, 159, 225),      # #B39FE1
}

_FALLBACK_PALETTE: tuple[tuple[int, int, int], ...] = (
    (31, 119, 180),
    (44, 160, 44),
    (255, 127, 14),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
    (227, 119, 194),
    (127, 127, 127),
    (188, 189, 34),
    (23, 190, 207),
)


def color_for_label(label: str, class_id: int) -> tuple[int, int, int]:
    """Return a consistent RGB color for a class label."""
    norm = label.strip().lower().replace("-", " ")
    if norm in CANONICAL_CLASS_COLORS:
        return CANONICAL_CLASS_COLORS[norm]
    norm_under = norm.replace(" ", "_")
    if norm_under in CANONICAL_CLASS_COLORS:
        return CANONICAL_CLASS_COLORS[norm_under]
    return _FALLBACK_PALETTE[class_id % len(_FALLBACK_PALETTE)]


class BaseLULCModel(ABC):
    """Abstract interface for tiled LULC semantic segmentation models."""

    name: str
    description: str
    classes: list[ClassSpec]
    expected_bands: int
    optimal_gsd_m: str

    @abstractmethod
    def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Run inference on a batch of tiles.

        Returns ``(labels_bhw_uint8, confidence_pct_bhw_uint8)`` where confidence
        is rounded to integer ``0..100``.
        """
