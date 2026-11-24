"""Hugging Face SegFormer adapter for RGB land-cover semantic segmentation."""

from __future__ import annotations

import numpy as np

from lulckit.models.base import BaseLULCModel, ClassSpec, color_for_label


class HFSegFormerModel(BaseLULCModel):
    """SegFormer semantic segmentation model loaded from Hugging Face Hub."""

    def __init__(
        self,
        repo_id: str,
        model_name: str = "rgb-oem",
        device: str = "cpu",
        description: str = "",
        optimal_gsd_m: str = "0.25-2.0m",
    ) -> None:
        import torch
        from transformers import (
            AutoImageProcessor,
            SegformerForSemanticSegmentation,
            SegformerImageProcessor,
        )

        self._torch = torch
        self.repo_id = repo_id
        self.name = model_name
        self.description = description or f"Hugging Face SegFormer ({repo_id})"
        self.expected_bands = 3
        self.optimal_gsd_m = optimal_gsd_m
        self.device = torch.device(device)

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
        self.processor = processor

        self.model = SegformerForSemanticSegmentation.from_pretrained(repo_id)
        self.model.to(self.device)
        self.model.eval()

        id2label = getattr(self.model.config, "id2label", None) or {}
        if id2label:
            sorted_items = sorted(((int(k), str(v)) for k, v in id2label.items()), key=lambda x: x[0])
        else:
            num_labels = int(getattr(self.model.config, "num_labels", 2))
            sorted_items = [(i, f"class_{i}") for i in range(num_labels)]

        self.classes = [
            ClassSpec(id=cid, name=label, color=color_for_label(label, cid))
            for cid, label in sorted_items
        ]

    def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict class IDs and integer confidence ``0..100`` for ``(B, H, W, 3)`` uint8."""
        import torch.nn.functional as F

        if tiles.ndim != 4 or tiles.shape[-1] != 3:
            raise ValueError(f"Expected (B, H, W, 3) uint8 tiles, got {tiles.shape}")

        _, h, w, _ = tiles.shape
        inputs = self.processor(images=list(tiles), return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)

        with self._torch.inference_mode():
            outputs = self.model(pixel_values=pixel_values)
            logits = F.interpolate(
                outputs.logits,
                size=(h, w),
                mode="bilinear",
                align_corners=False,
            )
            probs = logits.softmax(dim=1)
            conf, pred = probs.max(dim=1)

        labels_np = pred.cpu().numpy().astype(np.uint8)
        conf_np = (conf * 100.0).round().clamp(0, 100).cpu().numpy().astype(np.uint8)
        return labels_np, conf_np
