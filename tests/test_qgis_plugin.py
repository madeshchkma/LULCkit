"""Tests for the LULCkit QGIS plugin package, CLI runner bridge, and ZIP builder."""

from __future__ import annotations

import configparser
import importlib
import json
import sys
import types
import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PKG_DIR = ROOT / "qgis_plugin" / "lulckit_qgis"


def _write_sample_rasters(tmp_path: Path) -> tuple[Path, Path, Path]:
    transform = from_origin(89.0, 25.0, 10.0, 10.0)

    cat_path = tmp_path / "cat.tif"
    cat_arr = np.array(
        [
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [0, 0, 2, 2],
            [0, 0, 1, 1],
        ],
        dtype=np.uint8,
    )
    with rasterio.open(
        cat_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:32645",
        transform=transform,
    ) as dst:
        dst.write(cat_arr, 1)

    ms_path = tmp_path / "ms.tif"
    ms_arr = np.zeros((4, 4, 4), dtype=np.uint16)
    ms_arr[0] = 500   # Blue
    ms_arr[1] = 800   # Green
    ms_arr[2] = 600   # Red
    ms_arr[3] = 2400  # NIR
    with rasterio.open(
        ms_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=4,
        dtype="uint16",
        crs="EPSG:32645",
        transform=transform,
    ) as dst:
        for i, desc in enumerate(["B2", "B3", "B4", "B8"], start=1):
            dst.write(ms_arr[i - 1], i)
            dst.set_band_description(i, desc)

    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "clip"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[89.0, 24.9997], [89.0, 25.0], [89.0 + 40.0, 25.0], [89.0 + 40.0, 24.9997], [89.0, 24.9997]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return cat_path, ms_path, aoi_path


def test_qgis_metadata_and_icon() -> None:
    meta_path = PLUGIN_PKG_DIR / "metadata.txt"
    icon_path = PLUGIN_PKG_DIR / "icon.png"
    license_path = PLUGIN_PKG_DIR / "LICENSE"
    assert meta_path.is_file()
    assert icon_path.is_file()
    assert license_path.is_file()
    license_text = license_path.read_text(encoding="utf-8", errors="replace")
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 2" in license_text

    cfg = configparser.ConfigParser()
    cfg.read(meta_path, encoding="utf-8")
    assert cfg.has_section("general")
    sec = cfg["general"]
    assert sec["name"] == "LULCkit"
    assert sec["qgisMinimumVersion"] == "3.22"
    assert sec["supportsQt6"] == "True"
    assert sec["hasProcessingProvider"] == "yes"
    assert sec["version"] == "0.1.1"
    assert sec["icon"] == "icon.png"
    assert "assert " not in (PLUGIN_PKG_DIR / "runner.py").read_text(encoding="utf-8")

    with Image.open(icon_path) as im:
        assert im.size == (64, 64)


def test_runner_cli_end_to_end(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "qgis_plugin"))
    try:
        from lulckit_qgis import runner
    finally:
        sys.path.pop(0)

    assert runner.strip_ansi("\x1b[32mOK\x1b[0m\r\n") == "OK\n"
    assert runner.LULCKIT_PACKAGE_URL.startswith("https://")
    assert not runner.LULCKIT_PACKAGE_URL.startswith("git+")
    resolved = runner.resolve_lulckit_command(sys.executable)
    assert resolved == [sys.executable, "-m", "lulckit"]

    cat_tif, ms_tif, _ = _write_sample_rasters(tmp_path)

    class _Feedback:
        def __init__(self) -> None:
            self.logs: list[str] = []

        def pushInfo(self, msg: str) -> None:
            self.logs.append(msg)

        def isCanceled(self) -> bool:
            return False

    fb = _Feedback()

    inspect_json = tmp_path / "inspect.json"
    code, _ = runner.run_lulckit(runner.build_inspect_args(cat_tif, inspect_json), configured_path=sys.executable, feedback=fb)
    assert code == 0
    assert inspect_json.is_file()
    assert fb.logs

    ndvi_tif = tmp_path / "ndvi.tif"
    code, _ = runner.run_lulckit(
        runner.build_bands_args(ms_tif, output_path=ndvi_tif, mode="index", index_name="ndvi"),
        configured_path=sys.executable,
        feedback=fb,
    )
    assert code == 0
    assert ndvi_tif.is_file()

    # GeoJSON polygon inside ms_tif bounds in EPSG:32645
    clip_poly = tmp_path / "clip_utm.geojson"
    clip_poly.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:32645"}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[99.0, 5.0], [119.0, 5.0], [119.0, 25.0], [99.0, 25.0], [99.0, 5.0]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    clipped_tif = tmp_path / "clipped.tif"
    code, _ = runner.run_lulckit(
        runner.build_clip_args(cat_tif, clip_poly, clipped_tif),
        configured_path=sys.executable,
        feedback=fb,
    )
    assert code == 0
    assert clipped_tif.is_file()

    map_dir = tmp_path / "map_out"
    code, _ = runner.run_lulckit(
        runner.build_map_args(cat_tif, output_dir=map_dir, name="sample", model="categorical", vector=True, html=True),
        configured_path=sys.executable,
        feedback=fb,
    )
    assert code == 0
    for suffix in ("_lulc.tif", "_preview.png", "_summary.csv", "_report.json", "_lulc.geojson", "_map.html"):
        assert (map_dir / f"sample{suffix}").is_file(), f"Missing output sample{suffix}"


def _verify_plugin_with_qgis_stubs(monkeypatch: pytest.MonkeyPatch, *, strict_qt6: bool) -> None:
    """Verify QGIS provider/algorithm/plugin registration using lightweight PyQGIS stubs."""

    class _DummyBase:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs
            self._flags = 0
            self.params: list = []
            self.algorithms: list = []

        def tr(self, s: str) -> str:
            return s

        def flags(self) -> int:
            return self._flags

        def setFlags(self, f: int) -> None:
            self._flags = f

        def addParameter(self, p) -> None:
            self.params.append(p)

        def addAlgorithm(self, alg) -> None:
            self.algorithms.append(alg)

        def refreshAlgorithms(self) -> None:
            self.loadAlgorithms()

    if strict_qt6:
        _DummyBase.Flag = types.SimpleNamespace(FlagAdvanced=1)
    else:
        _DummyBase.FlagAdvanced = 1

    class _Registry:
        def __init__(self) -> None:
            self.providers: list = []

        def addProvider(self, prov) -> bool:
            prov.load()
            self.providers.append(prov)
            return True

        def removeProvider(self, prov) -> None:
            if prov in self.providers:
                prov.unload()
                self.providers.remove(prov)

    reg = _Registry()

    class _Setting:
        FILE = "FILE"

        def __init__(self, *args, **kwargs) -> None:
            pass

    class _ProcessingConfig:
        settingIcons: dict = {}
        settings: dict = {}

        @classmethod
        def addSetting(cls, s) -> None:
            cls.settings["LULCKIT_EXECUTABLE"] = s

        @classmethod
        def removeSetting(cls, k: str) -> None:
            cls.settings.pop(k, None)

        @classmethod
        def readSettings(cls) -> None:
            pass

        @classmethod
        def getSetting(cls, k: str):
            return None

    class _QAction:
        def __init__(self, *args) -> None:
            self.triggered = types.SimpleNamespace(connect=lambda cb: None)

        def setSeparator(self, _v: bool) -> None:
            pass

    class _QThread:
        def __init__(self, *args) -> None:
            pass

    class _QDialog:
        def __init__(self, *args) -> None:
            pass

    qgis_mod = types.ModuleType("qgis")
    qgis_core = types.ModuleType("qgis.core")
    qgis_core.QgsApplication = types.SimpleNamespace(processingRegistry=lambda: reg)
    qgis_core.QgsProcessing = (
        types.SimpleNamespace(SourceType=types.SimpleNamespace(TypeVectorPolygon=2))
        if strict_qt6
        else types.SimpleNamespace(TypeVectorPolygon=2)
    )
    qgis_core.QgsProcessingAlgorithm = _DummyBase
    qgis_core.QgsProcessingProvider = _DummyBase
    qgis_core.QgsProcessingContext = types.SimpleNamespace(LayerDetails=_DummyBase)
    qgis_core.QgsProcessingException = RuntimeError
    qgis_core.QgsProcessingParameterDefinition = _DummyBase

    class _ParamNumber(_DummyBase):
        pass

    if strict_qt6:
        _ParamNumber.Type = types.SimpleNamespace(Integer=0)
    else:
        _ParamNumber.Integer = 0

    for cname in (
        "QgsProcessingParameterBoolean",
        "QgsProcessingParameterEnum",
        "QgsProcessingParameterFeatureSource",
        "QgsProcessingParameterFileDestination",
        "QgsProcessingParameterFolderDestination",
        "QgsProcessingParameterRasterDestination",
        "QgsProcessingParameterRasterLayer",
        "QgsProcessingParameterString",
    ):
        setattr(qgis_core, cname, _DummyBase)
    qgis_core.QgsProcessingParameterNumber = _ParamNumber
    qgis_core.QgsProcessingUtils = _DummyBase
    qgis_core.QgsCoordinateReferenceSystem = _DummyBase
    qgis_core.QgsCoordinateTransform = _DummyBase
    qgis_core.QgsWkbTypes = (
        types.SimpleNamespace(GeometryType=types.SimpleNamespace(PolygonGeometry=2))
        if strict_qt6
        else types.SimpleNamespace(PolygonGeometry=2)
    )

    pyqt = types.ModuleType("qgis.PyQt")
    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    qtcore.QCoreApplication = types.SimpleNamespace(translate=lambda _ctx, s: s)
    qtcore.QThread = _QThread
    qtcore.QUrl = lambda u: u
    qtcore.pyqtSignal = lambda *a: types.SimpleNamespace(connect=lambda cb: None, emit=lambda *x: None)
    qtgui = types.ModuleType("qgis.PyQt.QtGui")
    qtgui.QIcon = lambda p="": p
    qtgui.QDesktopServices = types.SimpleNamespace(openUrl=lambda _u: True)
    qtgui.QAction = _QAction
    qtwidgets = types.ModuleType("qgis.PyQt.QtWidgets")
    for wname in (
        "QFileDialog",
        "QHBoxLayout",
        "QLabel",
        "QLineEdit",
        "QMessageBox",
        "QPlainTextEdit",
        "QPushButton",
        "QVBoxLayout",
    ):
        setattr(qtwidgets, wname, _DummyBase)
    qtwidgets.QDialog = _QDialog

    proc_mod = types.ModuleType("processing")
    proc_core = types.ModuleType("processing.core")
    proc_cfg_mod = types.ModuleType("processing.core.ProcessingConfig")
    proc_cfg_mod.ProcessingConfig = _ProcessingConfig
    proc_cfg_mod.Setting = _Setting

    for k, mod in (
        ("qgis", qgis_mod),
        ("qgis.core", qgis_core),
        ("qgis.PyQt", pyqt),
        ("qgis.PyQt.QtCore", qtcore),
        ("qgis.PyQt.QtGui", qtgui),
        ("qgis.PyQt.QtWidgets", qtwidgets),
        ("processing", proc_mod),
        ("processing.core", proc_core),
        ("processing.core.ProcessingConfig", proc_cfg_mod),
    ):
        monkeypatch.setitem(sys.modules, k, mod)

    monkeypatch.syspath_prepend(str(ROOT / "qgis_plugin"))
    for loaded in list(sys.modules):
        if loaded == "lulckit_qgis" or loaded.startswith("lulckit_qgis."):
            monkeypatch.delitem(sys.modules, loaded, raising=False)

    pkg = importlib.import_module("lulckit_qgis")

    class _DummyToolbar:
        def __init__(self) -> None:
            self.actions: list = []

        def setObjectName(self, _n: str) -> None:
            pass

        def addAction(self, a) -> None:
            self.actions.append(a)

        def deleteLater(self) -> None:
            pass

    class _DummyIface:
        def __init__(self) -> None:
            self.menus: list = []

        def mainWindow(self):
            return None

        def addToolBar(self, _name: str):
            return _DummyToolbar()

        def addPluginToMenu(self, menu: str, act) -> None:
            self.menus.append((menu, act))

        def removePluginMenu(self, menu: str, act) -> None:
            pass

    iface = _DummyIface()
    plugin = pkg.classFactory(iface)
    plugin.initGui()
    assert len(reg.providers) == 1
    prov = reg.providers[0]
    assert prov.id() == "lulckit"
    assert [a.name() for a in prov.algorithms] == ["map", "bands", "inspect", "clip"]
    for alg in prov.algorithms:
        alg.initAlgorithm()
        assert len(alg.params) >= 2

    assert len(iface.menus) == 7  # 4 tools + 1 separator + settings + browser studio
    plugin.unload()
    assert len(reg.providers) == 0


def test_qgis_provider_algorithms_and_plugin_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify QGIS provider/algorithm/plugin registration using Qt5 PyQGIS stubs."""
    _verify_plugin_with_qgis_stubs(monkeypatch, strict_qt6=False)


def test_qgis_qt6_strict_enums(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify algorithms import and initialize cleanly with Qt6 scoped PyQGIS enums only."""
    _verify_plugin_with_qgis_stubs(monkeypatch, strict_qt6=True)


def test_build_qgis_plugin_zip(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_qgis_plugin
    finally:
        sys.path.pop(0)

    zip_path = build_qgis_plugin.build_plugin_zip(tmp_path / f"lulckit_qgis_v{build_qgis_plugin.plugin_version()}.zip")
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    for req in (
        "lulckit_qgis/LICENSE",
        "lulckit_qgis/metadata.txt",
        "lulckit_qgis/__init__.py",
        "lulckit_qgis/plugin.py",
        "lulckit_qgis/provider.py",
        "lulckit_qgis/algorithms.py",
        "lulckit_qgis/runner.py",
        "lulckit_qgis/icon.png",
    ):
        assert req in names, f"Missing {req} in plugin ZIP"
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
