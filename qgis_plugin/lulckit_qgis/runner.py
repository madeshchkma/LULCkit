"""Pure-Python CLI/subprocess bridge between QGIS Processing and LULCkit."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

SETTING_KEY = "LULCKIT_EXECUTABLE"
DEFAULT_VENV_DIR = Path.home() / ".lulckit-qgis-venv"
LULCKIT_PACKAGE_URL = "https://github.com/madeshchkma/LULCkit/archive/refs/heads/main.zip"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes and carriage returns for clean QGIS Processing logs."""
    return _ANSI_RE.sub("", text)


def _looks_like_python(path: Path) -> bool:
    return path.stem.lower().startswith("python")


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def _probe_python_has_lulckit(py_exe: Path) -> bool:
    if not py_exe.is_file():
        return False
    sibling_cli = py_exe.parent / ("lulc.exe" if os.name == "nt" else "lulc")
    if sibling_cli.is_file():
        return True
    try:
        res = subprocess.run(
            [str(py_exe), "-c", "import lulckit"],
            capture_output=True,
            text=True,
            timeout=8,
            env=_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_lulckit_command(configured_path: str | None = None) -> list[str] | None:
    """Resolve an executable invocation prefix (``[lulc]`` or ``[python, -m, lulckit]``)."""
    cfg = str(configured_path or "").strip()
    if cfg:
        p = Path(cfg).expanduser()
        if p.is_file():
            return [str(p), "-m", "lulckit"] if _looks_like_python(p) else [str(p)]

    for exe_name in ("lulc", "lulckit"):
        found = shutil.which(exe_name)
        if found:
            return [found]

    user_py = _venv_python(DEFAULT_VENV_DIR)
    if _probe_python_has_lulckit(user_py):
        return [str(user_py), "-m", "lulckit"]

    cur_py = Path(sys.executable)
    if _looks_like_python(cur_py) and importlib.util.find_spec("lulckit") is not None:
        return [str(cur_py), "-m", "lulckit"]

    return None


def find_system_python() -> str | None:
    """Locate a standalone Python interpreter suitable for creating ``~/.lulckit-qgis-venv``."""
    cur = Path(sys.executable)
    if _looks_like_python(cur) and cur.is_file():
        return str(cur)
    for candidate in (
        Path(sys.prefix) / ("python.exe" if os.name == "nt" else "bin/python"),
        cur.parent / ("python.exe" if os.name == "nt" else "python"),
    ):
        if _looks_like_python(candidate) and candidate.is_file():
            return str(candidate)
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found and _looks_like_python(Path(found)):
            return found
    return None


def run_lulckit(
    args: list[str],
    configured_path: str | None = None,
    feedback=None,
) -> tuple[int, str]:
    """Execute ``lulckit`` with live QGIS feedback streaming and cancellation support."""
    base_cmd = resolve_lulckit_command(configured_path)
    if base_cmd is None:
        raise RuntimeError(
            "LULCkit CLI/Python environment was not found. "
            "Open Plugins -> LULCkit -> Settings & Environment to install LULCkit "
            "or select your Python/lulc executable."
        )

    cmd = [*base_cmd, *args]
    if feedback is not None and hasattr(feedback, "pushInfo"):
        feedback.pushInfo(f"Running: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_subprocess_env(),
        creationflags=_CREATE_NO_WINDOW,
    )

    output_lines: list[str] = []
    assert proc.stdout is not None
    try:
        for raw_line in proc.stdout:
            if feedback is not None and hasattr(feedback, "isCanceled") and feedback.isCanceled():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RuntimeError("LULCkit execution canceled by user.")
            clean = strip_ansi(raw_line.rstrip("\r\n"))
            if clean:
                output_lines.append(clean)
                if feedback is not None and hasattr(feedback, "pushInfo"):
                    feedback.pushInfo(clean)
    finally:
        proc.stdout.close()

    code = proc.wait()
    joined = "\n".join(output_lines)
    if code != 0:
        tail = "\n".join(output_lines[-25:])
        raise RuntimeError(f"LULCkit exited with code {code}:\n{tail}")
    return code, joined


def probe_lulckit_version(configured_path: str | None = None) -> tuple[bool, str]:
    """Check whether LULCkit responds cleanly to ``--version`` (or ``--help``)."""
    base_cmd = resolve_lulckit_command(configured_path)
    if base_cmd is None:
        return False, "Not configured / not found on PATH"
    try:
        res = subprocess.run(
            [*base_cmd, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            env=_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        if res.returncode == 0:
            return True, f"Ready ({' '.join(base_cmd)})"
        msg = strip_ansi((res.stderr or res.stdout or "").strip())
        return False, f"Exit {res.returncode}: {msg[:200]}"
    except Exception as exc:  # pragma: no cover - defensive guard
        return False, str(exc)


def install_into_user_venv(
    python_exe: str | None = None,
    feedback_cb: Callable[[str], None] | None = None,
) -> Path:
    """Create ``~/.lulckit-qgis-venv`` and install LULCkit from GitHub."""
    host_py = python_exe or find_system_python()
    if not host_py:
        raise RuntimeError("Could not locate a standalone python executable on this system.")

    log = feedback_cb or (lambda _m: None)
    venv_dir = DEFAULT_VENV_DIR
    venv_py = _venv_python(venv_dir)
    if not venv_py.is_file():
        log(f"Creating virtual environment at {venv_dir} ...")
        subprocess.run(
            [host_py, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            text=True,
            creationflags=_CREATE_NO_WINDOW,
        )

    log(f"Installing lulckit into {venv_dir} ...")
    subprocess.run(
        [str(venv_py), "-m", "pip", "install", "--upgrade", "pip", LULCKIT_PACKAGE_URL],
        check=True,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        creationflags=_CREATE_NO_WINDOW,
    )
    log("Installation complete.")
    return venv_py


def build_inspect_args(tiff_path: Path | str, output_json: Path | str | None = None) -> list[str]:
    args = ["inspect", str(tiff_path)]
    if output_json:
        args.extend(["--output", str(output_json)])
    return args


def build_clip_args(
    tiff_path: Path | str,
    boundary_geojson: Path | str,
    output_tif: Path | str,
    *,
    crop: bool = True,
    nodata: float | None = None,
) -> list[str]:
    args = [
        "clip",
        str(tiff_path),
        str(boundary_geojson),
        "-o",
        str(output_tif),
        "--crop" if crop else "--no-crop",
    ]
    if nodata is not None:
        args.extend(["--nodata", str(nodata)])
    return args


def build_bands_args(
    tiff_path: Path | str,
    *,
    output_path: Path | str,
    mode: str,
    composite: str | None = None,
    rgb_bands: str | None = None,
    single_band: int | None = None,
    index_name: str | None = None,
    palette: str | None = None,
    title: str | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
    arrow_style: str = "compass",
    scalebar_style: str = "arcgis",
    grid: bool = True,
    preview_out: Path | str | None = None,
) -> list[str]:
    args = ["bands", str(tiff_path), "-o", str(output_path)]
    if mode == "composite" and composite:
        args.extend(["--composite", composite])
    elif mode == "rgb" and rgb_bands:
        args.extend(["--rgb-bands", rgb_bands])
    elif mode == "band" and single_band is not None:
        args.extend(["--band", str(single_band)])
    elif mode == "index" and index_name:
        args.extend(["--index", index_name])

    if palette:
        args.extend(["--palette", palette])
    if preview_out:
        args.extend(["--preview-out", str(preview_out)])
    if title:
        args.extend(["--title", title])
    args.extend(
        [
            "--page-size",
            page_size,
            "--orientation",
            orientation,
            "--arrow-style",
            arrow_style,
            "--scalebar-style",
            scalebar_style,
            "--grid" if grid else "--no-grid",
        ]
    )
    return args


def build_map_args(
    tiff_path: Path | str,
    *,
    output_dir: Path | str,
    name: str,
    model: str = "auto",
    palette: str = "default",
    title: str | None = None,
    class_labels: str | None = None,
    class_colors: str | None = None,
    nodata_value: int | None = None,
    page_size: str = "a4",
    orientation: str = "auto",
    arrow_style: str = "compass",
    scalebar_style: str = "arcgis",
    grid: bool = True,
    vector: bool = False,
    html: bool = False,
    boundary_geojson: Path | str | None = None,
    boundary_label: str | None = None,
    device: str = "auto",
) -> list[str]:
    args = [
        "map",
        str(tiff_path),
        "-o",
        str(output_dir),
        "--name",
        name,
        "--model",
        model,
        "--palette",
        palette,
        "--page-size",
        page_size,
        "--orientation",
        orientation,
        "--arrow-style",
        arrow_style,
        "--scalebar-style",
        scalebar_style,
        "--device",
        device,
        "--grid" if grid else "--no-grid",
        "--vector" if vector else "--no-vector",
        "--html" if html else "--no-html",
    ]
    if title:
        args.extend(["--title", title])
    if class_labels:
        args.extend(["--class-labels", class_labels])
    if class_colors:
        args.extend(["--class-colors", class_colors])
    if nodata_value is not None:
        args.extend(["--nodata-value", str(nodata_value)])
    if boundary_geojson:
        args.extend(["--boundary", str(boundary_geojson)])
    if boundary_label:
        args.extend(["--boundary-label", boundary_label])
    return args
