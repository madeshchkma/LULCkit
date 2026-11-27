"""Build and validate the RustGIS process plugin archive (.rgplugin) and registry entry."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SRC = ROOT / "rustgis_plugin"
PKG_SRC = ROOT / "src" / "lulckit"
DEFAULT_OUT_DIR = ROOT / "out"
ZIP_TIME = (2024, 1, 1, 0, 0, 0)
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
SKIP_SRC_NAMES = {"cli.py", "__main__.py"}
SKIP_DIR_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".DS_Store"}
CATEGORIES = ["Raster", "Imagery", "Analysis", "Cartography"]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def collect_plugin_entries(
    plugin_dir: Path = PLUGIN_SRC,
    lulckit_src_dir: Path = PKG_SRC,
) -> list[tuple[str, bytes]]:
    """Collect ``(archive_path, file_bytes)`` pairs in deterministic sorted order."""
    entries: dict[str, bytes] = {}

    for path in sorted(plugin_dir.rglob("*")):
        if any(part in SKIP_DIR_PARTS or part.endswith(".pyc") for part in path.parts):
            continue
        if path.is_file():
            arc = path.relative_to(plugin_dir).as_posix()
            entries[arc] = path.read_bytes()

    for path in sorted(lulckit_src_dir.rglob("*.py")):
        if any(part in SKIP_DIR_PARTS for part in path.parts) or path.name in SKIP_SRC_NAMES:
            continue
        arc = (Path("lulckit") / path.relative_to(lulckit_src_dir)).as_posix()
        if arc in entries:
            raise ValueError(f"Duplicate archive entry: {arc}")
        entries[arc] = path.read_bytes()

    return sorted(entries.items(), key=lambda kv: kv[0])


def check_local(manifest: dict, archive_names: set[str], tag: str | None = None) -> list[str]:
    """Run local structural checks matching RustGIS registry rules."""
    problems: list[str] = []
    version = str(manifest.get("version", ""))
    if not VERSION_RE.match(version):
        problems.append(f"version must be X.Y.Z, got {version!r}")
    if tag and tag.removeprefix("v") != version:
        problems.append(f"tag {tag!r} does not match plugin.json version {version!r}")
    if manifest.get("runtime") != "process":
        problems.append('plugin.json must set "runtime": "process"')
    if "entry" in manifest:
        problems.append('process plugins must not declare "entry"')
    for required in ("plugin.json", "main.py", "rustgis_plugin.py", "requirements.txt", "lulckit/__init__.py"):
        if required not in archive_names:
            problems.append(f"missing required package file: {required}")
    for excluded in ("lulckit/cli.py", "lulckit/__main__.py"):
        if excluded in archive_names:
            problems.append(f"excluded CLI file present in package: {excluded}")
    return problems


def run_registry_checks(data: bytes, script_path: Path) -> list[str]:
    """Run ``opengeos/rustgis-plugins/scripts/build.py`` validation functions against ``data``."""
    spec = importlib.util.spec_from_file_location("rustgis_registry_build", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load registry check script: {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.problems.clear()

    loaded = mod.read_package(data, "lulckit")
    if loaded is not None:
        manifest, _ = loaded
        where = f"{manifest.get('id', 'lulckit')} {manifest.get('version', '')}"
        mod.check_manifest(manifest, where)
        mod.check_tab(manifest, where)
        mod.check_panel(manifest, where)
        mod.check_process(data, manifest, where)
    found = list(mod.problems)
    mod.problems.clear()
    return found


def build_rustgis_package(
    output_dir: Path = DEFAULT_OUT_DIR,
    *,
    tag: str | None = None,
    url: str | None = None,
    registry_script: Path | None = None,
) -> tuple[Path, Path, str]:
    """Build ``<output_dir>/<id>-<version>.rgplugin`` and ``<output_dir>/<id>.json``."""
    manifest = json.loads((PLUGIN_SRC / "plugin.json").read_text(encoding="utf-8"))
    plugin_id = manifest["id"]
    version = manifest["version"]

    entries = collect_plugin_entries()
    names = {arc for arc, _ in entries}
    problems = check_local(manifest, names, tag=tag)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arc, content in entries:
            info = zipfile.ZipInfo(arc, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            zf.writestr(info, content)
    data = buf.getvalue()

    if len(data) > MAX_PACKAGE_BYTES:
        problems.append(f"package size {len(data):,} exceeds 64 MB limit")

    if registry_script is not None:
        problems.extend(run_registry_checks(data, registry_script))

    if problems:
        raise RuntimeError("RustGIS plugin validation failed:\n- " + "\n- ".join(problems))

    output_dir.mkdir(parents=True, exist_ok=True)
    pkg_name = f"{plugin_id}-{version}.rgplugin"
    pkg_path = output_dir / pkg_name
    pkg_path.write_bytes(data)

    sha256 = hashlib.sha256(data).hexdigest()
    homepage = str(manifest.get("homepage") or "").rstrip("/")
    release_url = url or f"{homepage}/releases/download/v{version}/{pkg_name}"
    entry = {
        "id": plugin_id,
        "source": {"url": release_url, "sha256": sha256},
        "categories": CATEGORIES,
    }
    json_path = output_dir / f"{plugin_id}.json"
    json_path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return pkg_path, json_path, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description="Package LULCkit RustGIS plugin (.rgplugin).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory (default: out).")
    parser.add_argument("--tag", help="Release tag (e.g. v0.1.0) that must match plugin.json version.")
    parser.add_argument("--url", help="Override download URL in <id>.json.")
    parser.add_argument("--check", action="store_true", help="Run validation checks (always run during build).")
    parser.add_argument("--registry-script", type=Path, help="Optional path to rustgis-plugins/scripts/build.py.")
    args = parser.parse_args()

    try:
        pkg_path, json_path, sha = build_rustgis_package(
            output_dir=args.output_dir,
            tag=args.tag,
            url=args.url,
            registry_script=args.registry_script,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Built RustGIS plugin: {pkg_path} ({pkg_path.stat().st_size:,} bytes, sha256={sha})")
    print(f"Registry entry:       {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
