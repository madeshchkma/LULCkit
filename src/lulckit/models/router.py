"""Model registry, device resolution, cache inspection, and automatic model routing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lulckit.models.base import BaseLULCModel, ClassSpec

if TYPE_CHECKING:
    from lulckit.inspect import TiffProfile


class UnsupportedRasterError(ValueError):
    """Raised when a TIFF cannot be mapped with the selected or auto-detected model."""


MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "rgb-oem": {
        "name": "rgb-oem",
        "repo_id": "nave1616/SegFormer-landcover-FT",
        "architecture": "SegFormer-B4 (Hugging Face)",
        "classes": "9 classes (OpenEarthMap + background)",
        "expected_bands": 3,
        "optimal_gsd_m": "0.25-2.0m",
        "description": "High-resolution RGB/aerial/drone/satellite land cover segmentation (OpenEarthMap taxonomy).",
    },
    "rgb-fast": {
        "name": "rgb-fast",
        "repo_id": "florian-morel22/segformer-b0-deepglobe-land-cover",
        "architecture": "SegFormer-B0 (Hugging Face)",
        "classes": "7 classes (DeepGlobe)",
        "expected_bands": 3,
        "optimal_gsd_m": "0.5-2.0m",
        "description": "Lightweight, fast CPU-friendly RGB land cover segmentation (DeepGlobe taxonomy).",
    },
    "s2-dw": {
        "name": "s2-dw",
        "repo_id": "calebrob6/dynamic_world_pytorch",
        "architecture": "Dynamic World FCN (PyTorch)",
        "classes": "9 classes (Dynamic World)",
        "expected_bands": 9,
        "optimal_gsd_m": "10m",
        "description": "Sentinel-2 9-band (B2-B8, B11, B12) 10m global land cover segmentation.",
    },
    "categorical": {
        "name": "categorical",
        "repo_id": "built-in (pass-through)",
        "architecture": "Direct Categorical Pass-Through (No ML)",
        "classes": "Dynamic (1-32 discrete classes)",
        "expected_bands": 1,
        "optimal_gsd_m": "any",
        "description": "Pre-classified integer GeoTIFF pass-through: assigns colormap, calculates areas, and renders maps.",
    },
}


def _is_hf_repo_cached(repo_id: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        cfg = try_to_load_from_cache(repo_id, "config.json")
        if not isinstance(cfg, str):
            return False
        w_safe = try_to_load_from_cache(repo_id, "model.safetensors")
        w_bin = try_to_load_from_cache(repo_id, "pytorch_model.bin")
        return isinstance(w_safe, str) or isinstance(w_bin, str)
    except Exception:
        return False


def list_models() -> list[dict[str, Any]]:
    """Return registered models with local cache status without importing PyTorch."""
    from lulckit.models.s2_dw import default_weights_path

    dw_path = default_weights_path()
    dw_cached = dw_path.is_file() and dw_path.stat().st_size > 100_000

    rows: list[dict[str, Any]] = []
    for key, meta in MODEL_REGISTRY.items():
        if key == "categorical":
            cached = True
        elif key == "s2-dw":
            cached = dw_cached
        else:
            cached = _is_hf_repo_cached(meta["repo_id"])
        rows.append({**meta, "cached": cached})
    return rows


def resolve_device(device: str = "auto") -> str:
    """Resolve ``auto`` into ``cuda``, ``mps``, or ``cpu``."""
    import torch

    req = device.strip().lower()
    if req != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _validate_band_indices(indices: list[int], expected: int, band_count: int, label: str) -> None:
    if len(indices) != expected:
        raise ValueError(f"{label} requires exactly {expected} band indices, got {len(indices)}: {indices}")
    invalid = [i for i in indices if i < 1 or i > band_count]
    if invalid:
        raise ValueError(f"{label} band indices out of range [1..{band_count}]: {invalid}")


def _apply_class_overrides(
    model: BaseLULCModel,
    palette: str,
    class_labels: dict[int, str] | None,
    class_colors: dict[int, tuple[int, int, int]] | None,
) -> None:
    use_palette = palette.strip().lower() != "default"
    if not use_palette and not class_labels and not class_colors:
        return
    from lulckit.cartography import resolve_palette_color

    labels_ov = class_labels or {}
    colors_ov = class_colors or {}
    total = max(1, len(model.classes))
    updated: list[ClassSpec] = []
    for idx, c in enumerate(model.classes):
        name = labels_ov.get(c.id, c.name)
        if c.id in colors_ov:
            col = colors_ov[c.id]
        elif use_palette:
            col = resolve_palette_color(palette, idx, total=total)
        else:
            col = c.color
        updated.append(ClassSpec(id=c.id, name=name, color=col))
    model.classes = updated


def select_model(
    profile: TiffProfile,
    model_name: str = "auto",
    device: str = "auto",
    rgb_bands: list[int] | None = None,
    s2_bands: list[int] | None = None,
    hf_model: str | None = None,
    class_labels: dict[int, str] | None = None,
    class_colors: dict[int, tuple[int, int, int]] | None = None,
    nodata_value: int | None = None,
    palette: str = "default",
) -> tuple[BaseLULCModel, list[int], str, list[str]]:
    """Select and instantiate the appropriate model, input band indices, and preprocess mode."""
    warnings_out = list(profile.warnings)

    req = model_name.strip().lower()
    if hf_model and req == "auto":
        req = "rgb-oem"

    if req == "auto":
        if profile.recommended_model is None:
            reason = profile.warnings[0] if profile.warnings else f"Unsupported raster profile: {profile.detected_profile}"
            raise UnsupportedRasterError(reason)
        req = profile.recommended_model

    if req == "categorical":
        from lulckit.models.categorical import CategoricalPassThroughModel

        if not profile.non_alpha_bands:
            raise UnsupportedRasterError("Categorical pass-through requires at least 1 non-alpha band.")
        target_band = profile.non_alpha_bands[0]
        band_info = profile.bands[target_band - 1]
        if "int" not in band_info.dtype:
            raise UnsupportedRasterError(
                f"Categorical pass-through requires an integer band, got dtype '{band_info.dtype}'."
            )
        if not profile.unique_values:
            raise UnsupportedRasterError(
                "Raster does not appear to be a discrete categorical map (<= 32 unique integer classes)."
            )

        cmap_dict = None
        if profile.embedded_colormap:
            import warnings
            import rasterio
            from rasterio.errors import NotGeoreferencedWarning

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NotGeoreferencedWarning)
                with rasterio.open(profile.path) as src:
                    try:
                        cmap_dict = src.colormap(target_band)
                    except ValueError:
                        cmap_dict = None

        model = CategoricalPassThroughModel(
            unique_values=profile.unique_values,
            band_description=band_info.description,
            embedded_colormap_dict=cmap_dict,
            class_labels=class_labels,
            class_colors=class_colors,
            nodata_value=nodata_value,
            zero_is_background=profile.zero_is_background,
            palette=palette,
        )
        return model, [target_band], "categorical", warnings_out

    resolved_dev = resolve_device(device)

    if req == "s2-dw":
        from lulckit.models.s2_dw import DynamicWorldModel

        chosen_s2 = s2_bands if s2_bands is not None else profile.s2_bands
        if chosen_s2 is None:
            if len(profile.non_alpha_bands) == 9:
                chosen_s2 = list(profile.non_alpha_bands)
                warnings_out.append(
                    "Using the 9 non-alpha bands in file order as B2,B3,B4,B5,B6,B7,B8,B11,B12."
                )
            else:
                raise UnsupportedRasterError(
                    "Model 's2-dw' requires 9 Sentinel-2 bands (B2,B3,B4,B5,B6,B7,B8,B11,B12). "
                    f"Detected {len(profile.non_alpha_bands)} non-alpha bands without S2 metadata; "
                    "pass --s2-bands b2,b3,b4,b5,b6,b7,b8,b11,b12 to map them explicitly."
                )
        _validate_band_indices(chosen_s2, 9, profile.band_count, "s2-dw")

        selected_infos = [profile.bands[i - 1] for i in chosen_s2]
        scale_refl = all(
            (b.p98 is not None and b.p98 <= 2.0) and (b.max is None or b.max <= 2.5)
            for b in selected_infos
        ) and any("float" in b.dtype for b in selected_infos)
        if scale_refl:
            warnings_out.append(
                "Detected Sentinel-2 float reflectance in [0..2]; scaling by 10000x for Dynamic World normalization."
            )
        model = DynamicWorldModel(device=resolved_dev, scale_reflectance=scale_refl)
        _apply_class_overrides(model, palette, class_labels, class_colors)
        return model, chosen_s2, "s2", warnings_out

    if req in ("rgb-oem", "rgb-fast"):
        from lulckit.models.hf_segformer import HFSegFormerModel

        chosen_rgb = rgb_bands if rgb_bands is not None else profile.rgb_bands
        if chosen_rgb is None:
            raise UnsupportedRasterError(
                f"Cannot run RGB model '{req}' on '{profile.detected_profile}' ({profile.band_count} band(s)). "
                + (profile.warnings[0] if profile.warnings else "")
            )
        _validate_band_indices(chosen_rgb, 3, profile.band_count, req)

        meta = MODEL_REGISTRY[req]
        repo_id = hf_model or meta["repo_id"]
        display_name = f"hf:{hf_model}" if hf_model else req
        model = HFSegFormerModel(
            repo_id=repo_id,
            model_name=display_name,
            device=resolved_dev,
            description=meta["description"],
            optimal_gsd_m=meta["optimal_gsd_m"],
        )
        _apply_class_overrides(model, palette, class_labels, class_colors)
        return model, chosen_rgb, "rgb", warnings_out

    raise ValueError(f"Unknown model '{model_name}'. Available models: auto, {', '.join(MODEL_REGISTRY)}")
