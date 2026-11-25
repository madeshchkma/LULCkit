"""QGIS Plugin lifecycle, toolbar, menu integration, and Settings dialog for LULCkit."""

from __future__ import annotations

from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QThread, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

try:  # Qt6 (QGIS 4 / QGISQt6) places QAction in QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 (QGIS 3.x) places QAction in QtWidgets
    from qgis.PyQt.QtWidgets import QAction

from .provider import LulckitProvider
from .runner import SETTING_KEY, install_into_user_venv, probe_lulckit_version


class _InstallWorker(QThread):
    log_line = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            venv_py = install_into_user_venv(feedback_cb=self.log_line.emit)
            self.finished_ok.emit(str(venv_py))
        except Exception as exc:
            self.failed.emit(str(exc))


class LulckitSettingsDialog(QDialog):
    """Configure or install the backing LULCkit Python/CLI environment."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LULCkit — Settings & Environment")
        self.resize(560, 340)
        self._worker: _InstallWorker | None = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Checking LULCkit environment...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        path_label = QLabel("Python or lulc/lulckit executable (leave blank for auto-detection):")
        layout.addWidget(path_label)

        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("e.g. C:\\path\\to\\.venv\\Scripts\\python.exe or lulc.exe")
        self.browse_btn = QPushButton("Browse…")
        row.addWidget(self.path_edit)
        row.addWidget(self.browse_btn)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("Install LULCkit into User Venv (~/.lulckit-qgis-venv)")
        self.save_btn = QPushButton("Save & Verify")
        self.close_btn = QPushButton("Close")
        btn_row.addWidget(self.install_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Installation / verification output appears here.")
        layout.addWidget(self.log_box)

        self.browse_btn.clicked.connect(self._browse)
        self.install_btn.clicked.connect(self._install_venv)
        self.save_btn.clicked.connect(self._save_and_verify)
        self.close_btn.clicked.connect(self.accept)

        self._load_current()

    def _load_current(self) -> None:
        from processing.core.ProcessingConfig import ProcessingConfig

        cur = ProcessingConfig.getSetting(SETTING_KEY) or ""
        self.path_edit.setText(str(cur))
        self._refresh_probe(cur)

    def _refresh_probe(self, configured: str) -> None:
        ok, detail = probe_lulckit_version(configured)
        prefix = "Status: Connected — " if ok else "Status: Not Found — "
        self.status_label.setText(f"{prefix}{detail}")

    def _browse(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select Python or lulc executable",
            "",
            "Executables (*.exe *.bat *.cmd *);;All Files (*)",
        )
        if chosen:
            self.path_edit.setText(chosen)

    def _save_and_verify(self) -> None:
        from processing.core.ProcessingConfig import ProcessingConfig

        val = self.path_edit.text().strip()
        ProcessingConfig.setSettingValue(SETTING_KEY, val)
        self._refresh_probe(val)

    def _install_venv(self) -> None:
        self.install_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.log_box.appendPlainText("Starting user-venv installation...")
        self._worker = _InstallWorker(self)
        self._worker.log_line.connect(self.log_box.appendPlainText)
        self._worker.finished_ok.connect(self._on_install_ok)
        self._worker.failed.connect(self._on_install_err)
        self._worker.start()

    def _on_install_ok(self, venv_py: str) -> None:
        self.install_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.path_edit.setText(venv_py)
        self._save_and_verify()
        QMessageBox.information(self, "LULCkit", f"LULCkit installed successfully:\n{venv_py}")

    def _on_install_err(self, msg: str) -> None:
        self.install_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.log_box.appendPlainText(f"Error: {msg}")
        QMessageBox.warning(self, "LULCkit Installation Error", msg)


class LulckitPlugin:
    """Main QGIS plugin controller registering menus, toolbar, and Processing provider."""

    MENU_NAME = "&LULCkit"

    def __init__(self, iface) -> None:
        self.iface = iface
        self.provider: LulckitProvider | None = None
        self.actions: list[QAction] = []
        self.toolbar = None

    def initProcessing(self) -> None:  # noqa: N802
        self.provider = LulckitProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self) -> None:  # noqa: N802 - QGIS plugin lifecycle method
        self.initProcessing()
        icon = QIcon(str(Path(__file__).resolve().parent / "icon.png"))
        self.toolbar = self.iface.addToolBar("LULCkit")
        self.toolbar.setObjectName("LulckitToolbar")

        menu_specs = [
            ("LULC Classification && Cartographic Map…", lambda: self._run_alg("lulckit:map"), True),
            ("Spectral Indices && Band Composites…", lambda: self._run_alg("lulckit:bands"), False),
            ("Inspect GeoTIFF Metadata…", lambda: self._run_alg("lulckit:inspect"), False),
            ("Clip GeoTIFF to Polygon…", lambda: self._run_alg("lulckit:clip"), False),
            ("Settings && Environment…", self._open_settings, False),
            ("Open Browser GeoTIFF Studio", self._open_web_studio, False),
        ]

        for idx, (label, callback, add_toolbar) in enumerate(menu_specs):
            if idx == 4:
                sep = QAction(self.iface.mainWindow())
                sep.setSeparator(True)
                self.iface.addPluginToMenu(self.MENU_NAME, sep)
                self.actions.append(sep)
            action = QAction(icon, label, self.iface.mainWindow())
            action.triggered.connect(callback)
            self.iface.addPluginToMenu(self.MENU_NAME, action)
            if add_toolbar and self.toolbar is not None:
                self.toolbar.addAction(action)
            self.actions.append(action)

    def unload(self) -> None:
        for action in self.actions:
            self.iface.removePluginMenu(self.MENU_NAME, action)
        self.actions.clear()
        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def _run_alg(self, alg_id: str) -> None:
        import processing

        processing.execAlgorithmDialog(alg_id, {})

    def _open_settings(self) -> None:
        dlg = LulckitSettingsDialog(self.iface.mainWindow())
        dlg.exec()

    def _open_web_studio(self) -> None:
        QDesktopServices.openUrl(QUrl("https://madeshchkma.github.io/LULCkit/"))
