"""Hugging Face semantic segmentation adapter for RGB land-cover mapping."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import nullcontext
from typing import Any

import numpy as np

from lulckit.models.base import BaseLULCModel, ClassSpec, color_for_label

# ponytail: bounded 2-entry in-memory model cache prevents reload overhead across
# ZeroGPU/Spaces requests while bounding GPU/host memory; increase or swap to LRU by bytes if needed.
_HF_MODEL_CACHE: OrderedDict[tuple[str, str], tuple[Any, Any, tuple[ClassSpec, ...]]] = OrderedDict()
_MAX_CACHE_ITEMS = 2


def _autocast_ctx(torch_mod: Any, device: Any) -> Any:
    if device.type == "cuda":
        dtype = torch_mod.bfloat16 if torch_mod.cuda.is_bf16_supported() else torch_mod.float16
        return torch_mod.amp.autocast("cuda", dtype=dtype)
    return nullcontext()


class HFSegFormerModel(BaseLULCModel):
    """Semantic segmentation model loaded from Hugging Face Hub (SegFormer, UPerNet, Mask2Former, etc.)."""

    def __init__(
        self,
        repo_id: str,
        model_name: str = "rgb-oem",
        device: str = "cpu",
        description: str = "",
        optimal_gsd_m: str = "0.25-2.0m",
        tta: bool = False,
    ) -> None:
        import torch
        from transformers import (
            AutoImageProcessor,
            AutoModelForSemanticSegmentation,
            SegformerForSemanticSegmentation,
            SegformerImageProcessor,
        )

        self._torch = torch
        self.repo_id = repo_id
        self.name = model_name
        self.description = description or f"Hugging Face Segmentation ({repo_id})"
        self.expected_bands = 3
        self.optimal_gsd_m = optimal_gsd_m
        self.tta = bool(tta)
        self.device = torch.device(device)

        cache_key = (repo_id, str(self.device))
        if cache_key in _HF_MODEL_CACHE:
            _HF_MODEL_CACHE.move_to_end(cache_key)
            self.processor, self.model, default_classes = _HF_MODEL_CACHE[cache_key]
            self.classes = list(default_classes)
            return

        try:
            processor = AutoImageProcessor.from_pretrained(repo_id)
        except Exception:
            processor = SegformerImageProcessor(
                do_resize=False,
                do_rescale=True,
                do_normalize=True,
                image_mean=[0.485, 0.456, 0.406],
                image_std=[0.229, 0.224, 0.225],
            )
        if hasattr(processor, "do_resize"):
            processor.do_resize = False

        try:
            model = AutoModelForSemanticSegmentation.from_pretrained(repo_id)
        except Exception:
            model = SegformerForSemanticSegmentation.from_pretrained(repo_id)

        model.to(self.device)
        model.eval()

        id2label = getattr(model.config, "id2label", None) or {}
        if id2label:
            sorted_items = sorted(((int(k), str(v)) for k, v in id2label.items()), key=lambda x: x[0])
        else:
            num_labels = int(getattr(model.config, "num_labels", 2))
            sorted_items = [(i, f"class_{i}") for i in range(num_labels)]

        default_classes = tuple(
            ClassSpec(id=cid, name=label, color=color_for_label(label, cid))
            for cid, label in sorted_items
        )

        _HF_MODEL_CACHE[cache_key] = (processor, model, default_classes)
        while len(_HF_MODEL_CACHE) > _MAX_CACHE_ITEMS:
            _HF_MODEL_CACHE.popitem(last=False)

        self.processor = processor
        self.model = model
        self.classes = list(default_classes)

    def _forward_logits_or_outputs(self, tiles: np.ndarray) -> Any:
        inputs = self.processor(images=list(tiles), return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with self._torch.inference_mode(), _autocast_ctx(self._torch, self.device):
            return self.model(pixel_values=pixel_values)

    def _predict_probs(self, tiles: np.ndarray) -> Any:
        import torch.nn.functional as F

        b, h, w, _ = tiles.shape
        outputs = self._forward_logits_or_outputs(tiles)
        logits = getattr(outputs, "logits", None)
        if logits is None:
            return None
        up = F.interpolate(
            logits.float(),
            size=(h, w),
            mode="bilinear",
            align_corners=False,
        )
        return up.softmax(dim=1)

    def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict class IDs and integer confidence ``0..100`` for ``(B, H, W, 3)`` uint8."""
        if tiles.ndim != 4 or tiles.shape[-1] != 3:
            raise ValueError(f"Expected (B, H, W, 3) uint8 tiles, got {tiles.shape}")

        b, h, w, _ = tiles.shape
        probs = self._predict_probs(tiles)
        if probs is None:
            # Fallback for query-based HF heads (e.g. Mask2Former) without dense logits.
            outputs = self._forward_logits_or_outputs(tiles)
            post_fn = getattr(self.processor, "post_process_semantic_segmentation", None)
            if post_fn is None:
                raise RuntimeError(f"Model {self.repo_id!r} returned neither dense logits nor post-processor.")
            seg_maps = post_fn(outputs, target_sizes=[(h, w)] * b)
            labels_np = np.stack([m.detach().cpu().numpy() for m in seg_maps], axis=0).astype(np.uint8)
            conf_np = np.full(labels_np.shape, 100, dtype=np.uint8)
            return labels_np, conf_np

        if self.tta:
            aug_specs = (
                (lambda a: a[:, :, ::-1, :], lambda p: self._torch.flip(p, dims=(-1,))),
                (lambda a: a[:, ::-1, :, :], lambda p: self._torch.flip(p, dims=(-2,))),
                (lambda a: a[:, ::-1, ::-1, :], lambda p: self._torch.flip(p, dims=(-2, -1))),
            )
            acc = probs
            for fwd, inv in aug_specs:
                aug_probs = self._predict_probs(np.ascontiguousarray(fwd(tiles)))
                if aug_probs is not None:
                    acc = acc + inv(aug_probs)
            probs = acc / 4.0

        conf, pred = probs.max(dim=1)
        labels_np = pred.cpu().numpy().astype(np.uint8)
        conf_np = (conf * 100.0).round().clamp(0, 100).cpu().numpy().astype(np.uint8)
        return labels_np, conf_np
