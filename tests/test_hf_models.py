"""Offline tests for HF AutoModel segmentation, TTA, caching, tile sieve, and Spaces upgrades."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import torch
from rasterio.transform import from_origin

from lulckit.inspect import inspect_tiff
from lulckit.models.base import BaseLULCModel, ClassSpec
from lulckit.models.hf_segformer import _HF_MODEL_CACHE, HFSegFormerModel
from lulckit.models.s2_dw import _DW_MODEL_CACHE, DynamicWorldModel
from lulckit.tiling import run_tiled_inference

ROOT = Path(__file__).resolve().parent.parent


class _FakeProcessor:
    def __init__(self, *, use_post_process: bool = False) -> None:
        self.do_resize = True
        self.use_post_process = use_post_process

    def __call__(self, images: list[np.ndarray], return_tensors: str = "pt") -> dict[str, torch.Tensor]:
        assert return_tensors == "pt"
        arr = np.stack(images, axis=0).astype(np.float32) / 255.0
        return {"pixel_values": torch.from_numpy(np.transpose(arr, (0, 3, 1, 2)))}

    def post_process_semantic_segmentation(
        self,
        outputs: Any,
        target_sizes: list[tuple[int, int]],
    ) -> list[torch.Tensor]:
        assert self.use_post_process
        return [torch.ones(sz, dtype=torch.int64) for sz in target_sizes]


class _FakeDenseModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = types.SimpleNamespace(id2label={0: "background", 1: "vegetation", 2: "water"})

    def forward(self, pixel_values: torch.Tensor) -> Any:
        b, _, h, w = pixel_values.shape
        # Produce logits whose class 1 dominates left half, class 2 right half;
        # horizontal flip flips logits naturally through pixel_values[:, 0].
        green = pixel_values[:, 1:2, :, :]
        blue = pixel_values[:, 2:3, :, :]
        bg = torch.full((b, 1, h, w), 0.1, dtype=pixel_values.dtype, device=pixel_values.device)
        logits = torch.cat([bg, green * 3.0, blue * 3.0], dim=1)
        return types.SimpleNamespace(logits=logits)


class _FakeQueryModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = types.SimpleNamespace(id2label={0: "bg", 1: "crop"})

    def forward(self, pixel_values: torch.Tensor) -> Any:
        return types.SimpleNamespace(class_queries_logits=torch.zeros((pixel_values.shape[0], 2, 2)))


def test_hf_automodel_cache_tta_and_query_fallback(monkeypatch: Any) -> None:
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

    _HF_MODEL_CACHE.clear()
    load_calls = {"proc": 0, "auto": 0}

    def _load_proc(repo_id: str, **_: Any) -> _FakeProcessor:
        load_calls["proc"] += 1
        return _FakeProcessor(use_post_process="mask2former" in repo_id)

    def _load_model(repo_id: str, **_: Any) -> torch.nn.Module:
        load_calls["auto"] += 1
        return _FakeQueryModel() if "mask2former" in repo_id else _FakeDenseModel()

    monkeypatch.setattr(AutoImageProcessor, "from_pretrained", staticmethod(_load_proc))
    monkeypatch.setattr(AutoModelForSemanticSegmentation, "from_pretrained", staticmethod(_load_model))

    m1 = HFSegFormerModel("dummy/upernet-lulc", device="cpu", tta=False)
    assert m1.processor.do_resize is False
    assert [c.name for c in m1.classes] == ["background", "vegetation", "water"]
    m1.classes[0] = ClassSpec(id=0, name="mutated", color=(1, 2, 3))

    # Second load reuses cache without mutating cached ClassSpec defaults.
    m2 = HFSegFormerModel("dummy/upernet-lulc", device="cpu", tta=True)
    assert load_calls == {"proc": 1, "auto": 1}
    assert [c.name for c in m2.classes] == ["background", "vegetation", "water"]

    tiles = np.zeros((1, 8, 8, 3), dtype=np.uint8)
    tiles[:, :, :4, 1] = 220  # green left
    tiles[:, :, 4:, 2] = 220  # blue right
    pred_plain, conf_plain = m1.predict_batch(tiles)
    pred_tta, conf_tta = m2.predict_batch(tiles)
    assert pred_plain.shape == (1, 8, 8)
    assert np.all(pred_plain[:, :, :4] == 1) and np.all(pred_plain[:, :, 4:] == 2)
    assert np.array_equal(pred_plain, pred_tta)
    assert np.all((conf_tta >= 50) & (conf_tta <= 100))
    assert conf_plain.dtype == np.uint8

    # Query-based head without `.logits` falls back to post_process_semantic_segmentation
    m3 = HFSegFormerModel("dummy/mask2former-lulc", device="cpu", tta=False)
    pred_q, conf_q = m3.predict_batch(tiles)
    assert pred_q.shape == (1, 8, 8) and np.all(pred_q == 1)
    assert np.all(conf_q == 100)


def test_dynamic_world_tta_and_cache(tmp_path: Path, monkeypatch: Any) -> None:
    import lulckit.models.s2_dw as s2_mod

    _DW_MODEL_CACHE.clear()
    dummy_weights = tmp_path / "dw.pt"
    dummy_weights.write_bytes(b"0" * 120_000)

    class _DummyDW(torch.nn.Module):
        def load_state_dict(self, state: Any, strict: bool = True) -> None:
            return None

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            b, _, h, w = x.shape
            out = torch.zeros((b, 9, h, w), dtype=x.dtype, device=x.device)
            out[:, 4, :, :] = 3.0  # crops
            return out

    monkeypatch.setattr(s2_mod, "_build_dynamic_world_module", lambda: _DummyDW)
    monkeypatch.setattr(torch, "load", lambda *a, **kw: {})

    m = DynamicWorldModel(device="cpu", weights_path=dummy_weights, tta=True)
    m_cached = DynamicWorldModel(device="cpu", weights_path=dummy_weights, tta=True)
    assert m.model is m_cached.model

    tiles = np.full((1, 9, 8, 8), 1000.0, dtype=np.float32)
    pred, conf = m.predict_batch(tiles)
    assert pred.shape == (1, 8, 8) and np.all(pred == 4)
    assert conf.shape == (1, 8, 8) and np.all(conf > 50)


def test_sieve_removes_isolated_speckle(tmp_path: Path) -> None:
    in_tif = tmp_path / "rgb.tif"
    arr = np.full((3, 64, 64), 100, dtype=np.uint8)
    with rasterio.open(
        in_tif,
        "w",
        driver="GTiff",
        height=64,
        width=64,
        count=3,
        dtype="uint8",
        crs="EPSG:32645",
        transform=from_origin(500000.0, 2700000.0, 10.0, 10.0),
    ) as dst:
        dst.write(arr)

    class _SpeckleModel(BaseLULCModel):
        name = "speckle"
        description = "test"
        expected_bands = 3
        optimal_gsd_m = "1m"
        classes = [
            ClassSpec(id=0, name="water", color=(0, 0, 255)),
            ClassSpec(id=1, name="trees", color=(0, 150, 0)),
        ]

        def predict_batch(self, tiles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            b, h, w, _ = tiles.shape
            pred = np.ones((b, h, w), dtype=np.uint8)
            pred[:, h // 2, w // 2] = 0  # isolated 1-pixel speckle inside core
            conf = np.full((b, h, w), 95, dtype=np.uint8)
            return pred, conf

    prof = inspect_tiff(in_tif)
    out_tif = tmp_path / "sieved.tif"
    stats = run_tiled_inference(
        in_tif,
        prof,
        _SpeckleModel(),
        [1, 2, 3],
        "rgb",
        out_tif,
        tile_size=64,
        overlap=0,
        batch_size=1,
        sieve_size=4,
    )
    assert stats.class_pixels.get(0, 0) == 0
    assert stats.class_pixels.get(1, 0) == 64 * 64


def test_spaces_v02_cog_and_quality_options(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("lulckit_space_app_v02", ROOT / "spaces" / "app.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lulckit_space_app_v02"] = mod
    spec.loader.exec_module(mod)

    cat_tif = tmp_path / "cat.tif"
    with rasterio.open(
        cat_tif,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="uint8",
        crs="EPSG:32645",
        transform=from_origin(500000.0, 2700000.0, 10.0, 10.0),
    ) as dst:
        dst.write(np.ones((8, 8), dtype=np.uint8), 1)

    prev_png, out_tif, _, _, _, _, report = mod.run_map_space(
        str(cat_tif),
        model="categorical",
        tta=True,
        sieve_size=2,
        export_html=False,
    )
    assert prev_png and Path(prev_png).is_file()
    assert out_tif and Path(f"{out_tif}.aux.xml").is_file()
    assert report["inference"]["model"] == "categorical"

    ms_tif = tmp_path / "LC09_test.tif"
    ms_arr = np.zeros((6, 8, 8), dtype=np.uint16)
    ms_arr[0], ms_arr[1], ms_arr[2], ms_arr[3], ms_arr[4], ms_arr[5] = 500, 900, 700, 2600, 1500, 1100
    with rasterio.open(
        ms_tif,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=6,
        dtype="uint16",
        crs="EPSG:32645",
        transform=from_origin(500000.0, 2700000.0, 30.0, 30.0),
    ) as dst:
        for i, d in enumerate(["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"], start=1):
            dst.write(ms_arr[i - 1], i)
            dst.set_band_description(i, d)

    prev_nbr, tif_nbr, msg_nbr = mod.run_bands_space(str(ms_tif), mode="Spectral Index", index_name="nbr")
    assert prev_nbr and Path(prev_nbr).is_file() and Path(tif_nbr).is_file()
    assert "NBR" in msg_nbr

    prev_sub, tif_sub, msg_sub = mod.run_bands_space(str(ms_tif), mode="Multi-Band Subset COG", rgb_bands="3,2,1,4")
    assert prev_sub is None and Path(tif_sub).is_file() and "4-band COG" in msg_sub
    with rasterio.open(tif_sub) as src:
        assert src.count == 4

    prev_vis, tif_vis, msg_vis = mod.run_bands_space(str(ms_tif), mode="Visual 8-bit RGB COG", rgb_bands="3,2,1")
    assert prev_vis and Path(prev_vis).is_file() and Path(tif_vis).is_file() and "visual RGBA COG" in msg_vis
