"""QGIS Processing Provider for LULCkit."""

from __future__ import annotations

from pathlib import Path

from processing.core.ProcessingConfig import ProcessingConfig, Setting
from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms import (
    LulckitBandsAlgorithm,
    LulckitClipAlgorithm,
    LulckitInspectAlgorithm,
    LulckitMapAlgorithm,
)
from .runner import SETTING_KEY


class LulckitProvider(QgsProcessingProvider):
    """Registers LULCkit classification, spectral index, inspect, and clip tools in QGIS."""

    def load(self) -> bool:
        ProcessingConfig.settingIcons[self.name()] = self.icon()
        ProcessingConfig.addSetting(
            Setting(
                self.name(),
                SETTING_KEY,
                self.tr("LULCkit Python or CLI executable (leave blank for auto-detect)"),
                "",
                valuetype=Setting.FILE,
            )
        )
        ProcessingConfig.readSettings()
        self.refreshAlgorithms()
        return True

    def unload(self) -> None:
        ProcessingConfig.removeSetting(SETTING_KEY)

    def loadAlgorithms(self) -> None:  # noqa: N802 - QGIS C++ virtual method
        for alg in (
            LulckitMapAlgorithm(),
            LulckitBandsAlgorithm(),
            LulckitInspectAlgorithm(),
            LulckitClipAlgorithm(),
        ):
            self.addAlgorithm(alg)

    def id(self) -> str:
        return "lulckit"

    def name(self) -> str:
        return "LULCkit"

    def longName(self) -> str:  # noqa: N802
        return "LULCkit — GeoTIFF to LULC & Remote Sensing Cartography"

    def icon(self) -> QIcon:
        return QIcon(str(Path(__file__).resolve().parent / "icon.png"))
