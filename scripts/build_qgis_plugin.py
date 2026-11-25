"""Build and optionally install the QGIS plugin ZIP archive from qgis_plugin/lulckit_qgis/."""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SRC = ROOT / "qgis_plugin" / "lulckit_qgis"
SKIP_NAMES = {"__pycache__", ".DS_Store"}


def plugin_version() -> str:
    """Read plugin version from ``qgis_plugin/lulckit_qgis/metadata.txt``."""
    cfg = configparser.ConfigParser()
    cfg.read(PLUGIN_SRC / "metadata.txt", encoding="utf-8")
    return cfg["general"]["version"].strip()


DEFAULT_OUT = ROOT / "out" / f"lulckit_qgis_v{plugin_version()}.zip"


def build_plugin_zip(output_zip: Path = DEFAULT_OUT) -> Path:
    """Package ``qgis_plugin/lulckit_qgis`` with top-level ``lulckit_qgis/`` root."""
    if not (PLUGIN_SRC / "metadata.txt").is_file():
        raise FileNotFoundError(f"Missing plugin metadata.txt in {PLUGIN_SRC}")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PLUGIN_SRC.rglob("*")):
            if any(part in SKIP_NAMES or part.endswith(".pyc") for part in path.parts):
                continue
            if path.is_file():
                arcname = Path("lulckit_qgis") / path.relative_to(PLUGIN_SRC)
                zf.write(path, arcname=str(arcname).replace("\\", "/"))
    return output_zip


def default_qgis_plugins_dir() -> Path:
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return appdata / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
    if os.uname().sysname == "Darwin":  # pragma: no cover
        return Path.home() / "Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins"
    return Path.home() / ".local/share/QGIS/QGIS3/profiles/default/python/plugins"


def install_plugin_to_qgis(target_dir: Path | None = None) -> Path:
    """Copy ``lulckit_qgis`` into the active QGIS user profile plugins directory."""
    plugins_root = target_dir or default_qgis_plugins_dir()
    dest = plugins_root / "lulckit_qgis"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PLUGIN_SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Package LULCkit QGIS plugin ZIP.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT, help="Output ZIP path.")
    parser.add_argument("--install", action="store_true", help="Copy plugin into local QGIS default profile.")
    args = parser.parse_args()

    out = build_plugin_zip(args.output)
    print(f"Built QGIS plugin archive: {out}")
    if args.install:
        installed = install_plugin_to_qgis()
        print(f"Installed plugin to: {installed}")


if __name__ == "__main__":
    main()
