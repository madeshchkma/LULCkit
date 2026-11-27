"""PyTorch Dynamic World 10m Sentinel-2 LULC model adapter.

Adapted from `calebrob6/dynamic_world_pytorch` (Apache License 2.0), a bit-exact
PyTorch port of Google's Dynamic World model (Brown et al., 2022).
"""

from __future__ import annotations

import os
import urllib.request
from collections import OrderedDict
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np

from lulckit.models.base import BaseLULCModel, ClassSpec, color_for_label, get_cache_dir

_DW_MODEL_CACHE: OrderedDict[tuple[str, str], Any] = OrderedDict()
_MAX_DW_CACHE = 2


SENTINEL2_BANDS = ("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12")

CLASS_NAMES = (
    "water",
    "trees",
    "grass",
    "flooded_vegetation",
    "crops",
    "shrub_and_scrub",
    "built_area",
    "bare_ground",
    "snow_and_ice",
)

WEIGHTS_URL = (
    "https://raw.githubusercontent.com/calebrob6/dynamic_world_pytorch/main/weights/dynamic_world.pt"
)

NORM_PERCENTILES = np.array(
    [
        [1.7417268007636313, 2.023298706048351],
        [1.7261204997060209, 2.038905204308012],
        [1.6798346251414997, 2.179592821212937],
        [1.7734969472909623, 2.2890068333026603],
        [2.289154079164943, 2.6171674549378166],
        [2.382939712192371, 2.773418590375327],
        [2.3828939530384052, 2.7578332604178284],
        [2.1952484264967844, 2.789092484314204],
        [1.554812948247501, 2.4140534947492487],
    ],
    dtype=np.float32,
)


def default_weights_path() -> Path:
    """Return local cache path for Dynamic World PyTorch weights."""
    return get_cache_dir() / "models" / "dynamic_world.pt"


def ensure_dynamic_world_weights(weights_path: Path | None = None) -> Path:
    """Ensure ``dynamic_world.pt`` is present locally, downloading atomically if missing."""
    target = weights_path or default_weights_path()
    if target.is_file() and target.stat().st_size > 100_000:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".pt.tmp")
    with urllib.request.urlopen(WEIGHTS_URL, timeout=60) as resp:
        data = resp.read()
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target


def normalize_sentinel2(stack: np.ndarray, scale_reflectance: bool = False) -> np.ndarray:
    """Apply Dynamic World log-percentile normalization to ``(9, H, W)`` or ``(B, 9, H, W)``."""
    x = np.nan_to_num(stack.astype(np.float32, copy=False), nan=0.0, posinf=0.0, neginf=0.0)
    if scale_reflectance:
        x = x * 10000.0
    x = np.clip(x, 0.0, None)
    x = np.log(x * 0.005 + 1.0)
    if x.ndim == 3:
        mean = NORM_PERCENTILES[:, 0, None, None]
        std = NORM_PERCENTILES[:, 1, None, None]
    elif x.ndim == 4:
        mean = NORM_PERCENTILES[None, :, 0, None, None]
        std = NORM_PERCENTILES[None, :, 1, None, None]
    else:
        raise ValueError(f"Expected 3D or 4D Sentinel-2 array, got shape {x.shape}")
    x = (x - mean) / std
    x = np.exp(np.clip(x * 5.0 - 1.0, -30.0, 30.0))
    return (x / (x + 1.0)).astype(np.float32, copy=False)


def _build_dynamic_world_module():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ConvBNMish(nn.Module):
        def __init__(
            self,
            in_ch: int,
            out_ch: int,
            kernel_size: int = 1,
            stride: int = 1,
            padding: int | str = 0,
            groups: int = 1,
            bias: bool = True,
            bn_eps: float = 1e-3,
        ):
            super().__init__()
            self.conv = nn.Conv2d(
                in_ch, out_ch, kernel_size, stride, padding, groups=groups, bias=bias
            )
            self.bn = nn.BatchNorm2d(out_ch, eps=bn_eps, momentum=0.01)
            self.act = nn.Mish()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.act(self.bn(self.conv(x)))

    class DWMish(nn.Module):
        def __init__(self, ch: int, bn_eps: float = 1e-3):
            super().__init__()
            self.dw = nn.Conv2d(ch, ch, 3, padding=1, groups=ch, bias=True)
            self.bn = nn.BatchNorm2d(ch, eps=bn_eps, momentum=0.01)
            self.act = nn.Mish()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.act(self.bn(self.dw(x)))

    class ResidualBlock(nn.Module):
        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.pw1 = ConvBNMish(in_ch, out_ch, kernel_size=1)
            self.dw1 = DWMish(out_ch)
            self.pw2 = ConvBNMish(out_ch, out_ch, kernel_size=1)
            self.dw2 = DWMish(out_ch)
            self.pw3 = ConvBNMish(out_ch, out_ch, kernel_size=1)
            self.dw3 = DWMish(out_ch)
            self.shortcut = ConvBNMish(in_ch, out_ch, kernel_size=1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            main = self.dw3(self.pw3(self.dw2(self.pw2(self.dw1(self.pw1(x))))))
            return main + self.shortcut(x)

    class SkipBranch(nn.Module):
        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.pw = ConvBNMish(in_ch, out_ch, kernel_size=1)
            self.dw = DWMish(out_ch)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.dw(self.pw(x))

    class DynamicWorld(nn.Module):
        def __init__(
            self,
            in_ch: int = 9,
            num_classes: int = 9,
            m: float = 1.5,
            b: float = 2.0,
            base: int = 32,
            scale_factor: float = 2.0,
        ):
            super().__init__()
            self.in_ch = in_ch
            self.num_classes = num_classes
            self.scale_factor = scale_factor

            stem_c = int(round(b * base))
            skip_c = int(round(m * base))
            mid_c = int(round(b * m * base))
            high_c = int(round(b * m * m * base))

            self.stem = ConvBNMish(in_ch, stem_c, kernel_size=3, padding=1)
            self.skip = SkipBranch(stem_c, skip_c)
            self.block1 = ResidualBlock(stem_c, mid_c)
            self.block2 = ResidualBlock(mid_c, high_c)
            self.block3 = ResidualBlock(high_c + skip_c, high_c)
            self.classifier = nn.Conv2d(high_c, num_classes, kernel_size=1, bias=True)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h, w = x.shape[-2:]
            x = self.stem(x)
            down_size = (int(h / self.scale_factor), int(w / self.scale_factor))
            x_down = F.interpolate(
                x,
                size=down_size,
                mode="bilinear",
                align_corners=False,
                antialias=True,
            )
            skip_out = self.skip(x_down)
            b1 = self.block1(x_down)
            b2 = self.block2(b1)
            cat = torch.cat([b2, skip_out], dim=1)
            b3 = self.block3(cat)
            up = F.interpolate(b3, size=(h, w), mode="bilinear", align_corners=False)
            normed = F.normalize(up, p=2, dim=1, eps=1e-12)
            return self.classifier(normed)

    return DynamicWorld


class DynamicWorldModel(BaseLULCModel):
    """Sentinel-2 10m 9-class Dynamic World classifier."""

    def __init__(
        self,
        device: str = "cpu",
        scale_reflectance: bool = False,
        weights_path: Path | None = None,
        tta: bool = False,
    ) -> None:
        import torch

        self._torch = torch
        self.name = "s2-dw"
        self.description = "Google Dynamic World v1 PyTorch (9-band Sentinel-2)"
        self.expected_bands = 9
        self.optimal_gsd_m = "10m"
        self.scale_reflectance = scale_reflectance
        self.tta = bool(tta)
        self.device = torch.device(device)
        self.classes = [
            ClassSpec(id=i, name=name, color=color_for_label(name, i))
            for i, name in enumerate(CLASS_NAMES)
        ]

        resolved_weights = ensure_dynamic_world_weights(weights_path)
        cache_key = (str(resolved_weights), str(self.device))
        if cache_key in _DW_MODEL_CACHE:
            _DW_MODEL_CACHE.move_to_end(cache_key)
            self.model = _DW_MODEL_CACHE[cache_key]
            return

        dw_cls = _build_dynamic_world_module()
        model = dw_cls()
        state = torch.load(resolved_weights, map_location=self.device, weights_only=True)
        model.load_state_dict(state)
        model.to(self.device)
        model.eval()
        _DW_MODEL_CACHE[cache_key] = model
        while len(_DW_MODEL_CACHE) > _MAX_DW_CACHE:
            _DW_MODEL_CACHE.popitem(last=False)
        self.model = model

    def _predict_probs(self, normed: np.ndarray) -> Any:
        tensor = self._torch.from_numpy(normed).to(self.device)
        if self.device.type == "cuda":
            dtype = self._torch.bfloat16 if self._torch.cuda.is_bf16_supported() else self._torch.float16
            ctx = self._torch.amp.autocast("cuda", dtype=dtype)
        else:
            ctx = nullcontext()
        with self._torch.inference_mode(), ctx:
            logits = self.model(tensor)
            return logits.float().softmax(dim=1)

    def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict class IDs and integer confidence ``0..100`` for ``(B, 9, H, W)`` float32."""
        if tiles.ndim != 4 or tiles.shape[1] != 9:
            raise ValueError(f"Expected (B, 9, H, W) Sentinel-2 tiles, got {tiles.shape}")

        normed = normalize_sentinel2(tiles, scale_reflectance=self.scale_reflectance)
        probs = self._predict_probs(normed)
        if self.tta:
            aug_specs = (
                (lambda a: a[:, :, :, ::-1], lambda p: self._torch.flip(p, dims=(-1,))),
                (lambda a: a[:, :, ::-1, :], lambda p: self._torch.flip(p, dims=(-2,))),
                (lambda a: a[:, :, ::-1, ::-1], lambda p: self._torch.flip(p, dims=(-2, -1))),
            )
            acc = probs
            for fwd, inv in aug_specs:
                acc = acc + inv(self._predict_probs(np.ascontiguousarray(fwd(normed))))
            probs = acc / 4.0

        conf, pred = probs.max(dim=1)
        labels_np = pred.cpu().numpy().astype(np.uint8)
        conf_np = (conf * 100.0).round().clamp(0, 100).cpu().numpy().astype(np.uint8)
        return labels_np, conf_np
