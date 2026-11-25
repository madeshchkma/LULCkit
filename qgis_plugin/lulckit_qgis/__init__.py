"""QGIS Plugin entry point for LULCkit."""

from __future__ import annotations


def classFactory(iface):  # noqa: N802 - Required QGIS plugin entrypoint name
    from .plugin import LulckitPlugin

    return LulckitPlugin(iface)
