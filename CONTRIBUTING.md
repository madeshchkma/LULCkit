# Contributing to LULCkit

Thank you for helping improve `LULCkit`!

## Development Setup

```bash
python -m venv --system-site-packages .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

pip install -e ".[dev]"
```

## Running Tests & Linter

All unit and integration tests run completely offline without downloading external model weights:

```bash
pytest -v
ruff check src tests
```

## Coding Guidelines

- Keep `cli.py` and `bands.py` free of top-level `torch` or `transformers` imports so `lulc inspect`, `lulc bands`, `lulc clip`, and `lulc models` stay fast.
- Preserve streaming windowed I/O (`O(1)` RAM) for all full-resolution raster reads and writes so multi-gigabyte GeoTIFFs never exhaust memory.
- Keep `src/lulckit/models/` adapters inheriting from `BaseLULCModel` with explicit `ClassSpec` entries.
- Add tests in `tests/test_pipeline.py` for every new flag, model adapter, or output format.

## Pull Request Checklist

1. `pytest -v` passes completely.
2. `ruff check src tests` reports no errors.
3. Update `README.md` and `CHANGELOG.md` when adding user-facing commands or flags.
