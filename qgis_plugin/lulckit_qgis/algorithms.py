"""QGIS Processing Algorithms backed by the LULCkit CLI/Python engine."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingUtils,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

from .runner import (
    SETTING_KEY,
    build_bands_args,
    build_clip_args,
    build_inspect_args,
    build_map_args,
    run_lulckit,
)

MODEL_OPTIONS = ["auto", "categorical", "rgb-oem", "rgb-fast", "s2-dw"]
PALETTE_OPTIONS = [
    "default",
    "arcgis-crop",
    "esa-worldcover",
    "esri-lulc",
    "dynamic-world",
    "nlcd",
    "corine",
    "qgis-spectral",
    "arcgis-topo",
    "urban-heat",
    "hydrology",
    "ag-phenology",
    "vivid",
    "earth",
    "pastel",
    "colorblind",
    "viridis",
    "RdYlGn",
]
PAGE_SIZE_OPTIONS = ["a4", "a5", "a3", "letter", "legal", "square", "auto"]
ORIENTATION_OPTIONS = ["auto", "landscape", "portrait"]
ARROW_OPTIONS = ["compass", "classic", "fancy", "minimal", "none"]
SCALEBAR_OPTIONS = ["arcgis", "alternating", "simple", "none"]
DEVICE_OPTIONS = ["auto", "cpu", "cuda", "mps"]

BAND_MODES = ["index", "composite", "rgb", "band"]
INDEX_OPTIONS = ["ndvi", "ndwi", "ndbi", "savi", "evi"]
COMPOSITE_OPTIONS = ["true-color", "false-color-nir", "agriculture", "swir"]
INDEX_CMAP_OPTIONS = [
    "",
    "RdYlGn",
    "Blues",
    "RdBu",
    "viridis",
    "plasma",
    "inferno",
    "turbo",
    "terrain",
    "Spectral",
    "BrBG",
    "YlOrRd",
    "gray",
]


def _resolve_enum(cls: Any, group: str, member: str) -> Any:
    """Resolve PyQGIS scoped Qt6 enum first, falling back to Qt5 unscoped attribute."""
    scoped = getattr(cls, group, None)
    if scoped is not None and hasattr(scoped, member):
        return getattr(scoped, member)
    return getattr(cls, member)


def _resolve_polygon_geometry() -> Any:
    import qgis.core as qc

    qgis_cls = getattr(qc, "Qgis", None)
    if qgis_cls is not None:
        geom_type = getattr(qgis_cls, "GeometryType", None)
        if geom_type is not None and hasattr(geom_type, "Polygon"):
            return geom_type.Polygon
    return _resolve_enum(QgsWkbTypes, "GeometryType", "PolygonGeometry")


_FLAG_ADVANCED = _resolve_enum(QgsProcessingParameterDefinition, "Flag", "FlagAdvanced")
_TYPE_VECTOR_POLYGON = _resolve_enum(QgsProcessing, "SourceType", "TypeVectorPolygon")
_POLYGON_GEOMETRY = _resolve_polygon_geometry()
_NUMBER_INTEGER = _resolve_enum(QgsProcessingParameterNumber, "Type", "Integer")


def _tr(text: str) -> str:
    return QCoreApplication.translate("LULCkit", text)


def _plugin_icon() -> QIcon:
    return QIcon(str(Path(__file__).resolve().parent / "icon.png"))


def _get_configured_executable() -> str | None:
    try:
        from processing.core.ProcessingConfig import ProcessingConfig

        return ProcessingConfig.getSetting(SETTING_KEY)
    except Exception:
        return None


def _mark_advanced(param: QgsProcessingParameterDefinition) -> QgsProcessingParameterDefinition:
    param.setFlags(param.flags() | _FLAG_ADVANCED)
    return param


def _layer_source_path(layer) -> Path:
    if layer is None:
        raise QgsProcessingException(_tr("Please select a valid raster layer."))
    raw = layer.source()
    if "|" in raw:
        raw = raw.split("|", 1)[0]
    path = Path(raw)
    if not path.is_file():
        raise QgsProcessingException(
            _tr(f"Raster source must be a local GeoTIFF/TIFF file, got: {raw}")
        )
    return path


def _export_vector_source_to_geojson(source, context, stem: str) -> Path:
    if source is None:
        raise QgsProcessingException(_tr("Please provide a polygon vector layer."))
    temp_dir = Path(QgsProcessingUtils.tempFolder())
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_path = temp_dir / f"{stem}_{uuid.uuid4().hex[:8]}.geojson"

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    src_crs = source.sourceCrs()
    xform = None
    if src_crs.isValid() and src_crs != wgs84:
        xform = QgsCoordinateTransform(src_crs, wgs84, context.transformContext())

    features = []
    for feat in source.getFeatures():
        geom = feat.geometry()
        if geom.isNull() or geom.isEmpty():
            continue
        geom_copy = geom.__class__(geom)
        if xform is not None:
            geom_copy.transform(xform)
        if geom_copy.type() != _POLYGON_GEOMETRY:
            continue
        geojson_geom = json.loads(geom_copy.asJson())
        props = {}
        for field in feat.fields():
            val = feat[field.name()]
            props[field.name()] = val if isinstance(val, (int, float, bool, str)) else (None if val is None else str(val))
        features.append({"type": "Feature", "geometry": geojson_geom, "properties": props})

    if not features:
        raise QgsProcessingException(_tr("Boundary layer contains no valid polygon geometries."))

    out_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    return out_path


class LulckitMapAlgorithm(QgsProcessingAlgorithm):
    """Run LULC classification/styling and generate GeoTIFF, print map, CSV, JSON, GeoJSON, and HTML."""

    INPUT_RASTER = "INPUT_RASTER"
    MODEL = "MODEL"
    PALETTE = "PALETTE"
    TITLE = "TITLE"
    CLASS_LABELS = "CLASS_LABELS"
    CLASS_COLORS = "CLASS_COLORS"
    NODATA_VALUE = "NODATA_VALUE"
    PAGE_SIZE = "PAGE_SIZE"
    ORIENTATION = "ORIENTATION"
    ARROW_STYLE = "ARROW_STYLE"
    SCALEBAR_STYLE = "SCALEBAR_STYLE"
    SHOW_GRID = "SHOW_GRID"
    BOUNDARY = "BOUNDARY"
    VECTOR_OUT = "VECTOR_OUT"
    HTML_OUT = "HTML_OUT"
    DEVICE = "DEVICE"
    OUTPUT_DIR = "OUTPUT_DIR"

    OUTPUT_RASTER = "OUTPUT_RASTER"
    OUTPUT_PREVIEW = "OUTPUT_PREVIEW"
    OUTPUT_CSV = "OUTPUT_CSV"
    OUTPUT_JSON = "OUTPUT_JSON"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_HTML = "OUTPUT_HTML"

    def name(self) -> str:
        return "map"

    def displayName(self) -> str:  # noqa: N802
        return _tr("LULC Classification & Cartographic Map")

    def group(self) -> str:
        return _tr("LULC & Cartography")

    def groupId(self) -> str:  # noqa: N802
        return "lulc_cartography"

    def icon(self) -> QIcon:
        return _plugin_icon()

    def shortHelpString(self) -> str:  # noqa: N802
        return _tr(
            "Automatically classifies or styles any optical/categorical GeoTIFF into a GIS-ready LULC GeoTIFF "
            "(embedded GDAL colormap), publication 300 DPI print map, CSV/JSON area analytics, and optional "
            "GeoJSON polygons + MapLibre HTML web map."
        )

    def createInstance(self) -> QgsProcessingAlgorithm:  # noqa: N802
        return LulckitMapAlgorithm()

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:  # noqa: N802
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_RASTER, _tr("Input GeoTIFF / TIFF")))
        self.addParameter(
            QgsProcessingParameterEnum(self.MODEL, _tr("Classification Model"), options=MODEL_OPTIONS, defaultValue=0)
        )
        self.addParameter(
            QgsProcessingParameterEnum(self.PALETTE, _tr("Color Palette"), options=PALETTE_OPTIONS, defaultValue=0)
        )
        self.addParameter(
            QgsProcessingParameterString(self.TITLE, _tr("Map Title (optional)"), optional=True, defaultValue="")
        )
        self.addParameter(
            QgsProcessingParameterBoolean(self.VECTOR_OUT, _tr("Export Vector LULC Polygons (.geojson)"), defaultValue=False)
        )
        self.addParameter(
            QgsProcessingParameterBoolean(self.HTML_OUT, _tr("Export Interactive MapLibre Web Map (.html)"), defaultValue=False)
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BOUNDARY,
                _tr("Optional Boundary Overlay (Polygons)"),
                types=[_TYPE_VECTOR_POLYGON],
                optional=True,
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterString(
                    self.CLASS_LABELS,
                    _tr("Custom Class Labels (e.g. 0:Non Boro,1:Early,2:Late)"),
                    optional=True,
                    defaultValue="",
                )
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterString(
                    self.CLASS_COLORS,
                    _tr("Custom Class Colors (e.g. 0:#FFFFFF,1:#38A800)"),
                    optional=True,
                    defaultValue="",
                )
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterString(
                    self.NODATA_VALUE,
                    _tr("Categorical Nodata Value (integer, optional)"),
                    optional=True,
                    defaultValue="",
                )
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterEnum(self.PAGE_SIZE, _tr("Print Page Size"), options=PAGE_SIZE_OPTIONS, defaultValue=0)
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterEnum(self.ORIENTATION, _tr("Page Orientation"), options=ORIENTATION_OPTIONS, defaultValue=0)
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterEnum(self.ARROW_STYLE, _tr("North Arrow Style"), options=ARROW_OPTIONS, defaultValue=0)
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterEnum(self.SCALEBAR_STYLE, _tr("Scale Bar Style"), options=SCALEBAR_OPTIONS, defaultValue=0)
            )
        )
        self.addParameter(
            _mark_advanced(QgsProcessingParameterBoolean(self.SHOW_GRID, _tr("Show Coordinate Axes & Gridlines"), defaultValue=True))
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterEnum(self.DEVICE, _tr("Compute Device"), options=DEVICE_OPTIONS, defaultValue=0)
            )
        )
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_DIR, _tr("Output Folder")))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        tiff_path = _layer_source_path(layer)
        out_dir = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = tiff_path.stem

        model = MODEL_OPTIONS[self.parameterAsEnum(parameters, self.MODEL, context)]
        palette = PALETTE_OPTIONS[self.parameterAsEnum(parameters, self.PALETTE, context)]
        title = self.parameterAsString(parameters, self.TITLE, context).strip() or None
        class_labels = self.parameterAsString(parameters, self.CLASS_LABELS, context).strip() or None
        class_colors = self.parameterAsString(parameters, self.CLASS_COLORS, context).strip() or None
        nodata_raw = self.parameterAsString(parameters, self.NODATA_VALUE, context).strip()
        nodata_val = int(nodata_raw) if nodata_raw else None

        page_size = PAGE_SIZE_OPTIONS[self.parameterAsEnum(parameters, self.PAGE_SIZE, context)]
        orientation = ORIENTATION_OPTIONS[self.parameterAsEnum(parameters, self.ORIENTATION, context)]
        arrow_style = ARROW_OPTIONS[self.parameterAsEnum(parameters, self.ARROW_STYLE, context)]
        scalebar_style = SCALEBAR_OPTIONS[self.parameterAsEnum(parameters, self.SCALEBAR_STYLE, context)]
        show_grid = self.parameterAsBoolean(parameters, self.SHOW_GRID, context)
        device = DEVICE_OPTIONS[self.parameterAsEnum(parameters, self.DEVICE, context)]
        vector_enabled = self.parameterAsBoolean(parameters, self.VECTOR_OUT, context)
        html_enabled = self.parameterAsBoolean(parameters, self.HTML_OUT, context)

        boundary_geojson = None
        if self.BOUNDARY in parameters and parameters[self.BOUNDARY] is not None:
            bsrc = self.parameterAsSource(parameters, self.BOUNDARY, context)
            if bsrc is not None:
                boundary_geojson = _export_vector_source_to_geojson(bsrc, context, "boundary")

        args = build_map_args(
            tiff_path,
            output_dir=out_dir,
            name=stem,
            model=model,
            palette=palette,
            title=title,
            class_labels=class_labels,
            class_colors=class_colors,
            nodata_value=nodata_val,
            page_size=page_size,
            orientation=orientation,
            arrow_style=arrow_style,
            scalebar_style=scalebar_style,
            grid=show_grid,
            vector=vector_enabled,
            html=html_enabled,
            boundary_geojson=boundary_geojson,
            device=device,
        )
        run_lulckit(args, configured_path=_get_configured_executable(), feedback=feedback)

        lulc_tif = out_dir / f"{stem}_lulc.tif"
        results: dict[str, Any] = {
            self.OUTPUT_RASTER: str(lulc_tif),
            self.OUTPUT_PREVIEW: str(out_dir / f"{stem}_preview.png"),
            self.OUTPUT_CSV: str(out_dir / f"{stem}_summary.csv"),
            self.OUTPUT_JSON: str(out_dir / f"{stem}_report.json"),
        }
        if lulc_tif.is_file():
            context.addLayerToLoadOnCompletion(
                str(lulc_tif),
                QgsProcessingContext.LayerDetails(f"{stem}_lulc", context.project(), self.OUTPUT_RASTER),
            )
        if vector_enabled:
            vec_path = out_dir / f"{stem}_lulc.geojson"
            results[self.OUTPUT_VECTOR] = str(vec_path)
            if vec_path.is_file():
                context.addLayerToLoadOnCompletion(
                    str(vec_path),
                    QgsProcessingContext.LayerDetails(f"{stem}_lulc_polygons", context.project(), self.OUTPUT_VECTOR),
                )
        if html_enabled:
            results[self.OUTPUT_HTML] = str(out_dir / f"{stem}_map.html")
        return results


class LulckitBandsAlgorithm(QgsProcessingAlgorithm):
    """Compute NDVI/NDWI/NDBI/SAVI/EVI spectral indices or RGB band composites."""

    INPUT_RASTER = "INPUT_RASTER"
    MODE = "MODE"
    INDEX_NAME = "INDEX_NAME"
    COMPOSITE = "COMPOSITE"
    RGB_BANDS = "RGB_BANDS"
    SINGLE_BAND = "SINGLE_BAND"
    PALETTE = "PALETTE"
    TITLE = "TITLE"
    OUTPUT_RASTER = "OUTPUT_RASTER"
    OUTPUT_PREVIEW = "OUTPUT_PREVIEW"

    def name(self) -> str:
        return "bands"

    def displayName(self) -> str:  # noqa: N802
        return _tr("Spectral Indices & Band Composites")

    def group(self) -> str:
        return _tr("Bands & Indices")

    def groupId(self) -> str:  # noqa: N802
        return "bands_indices"

    def icon(self) -> QIcon:
        return _plugin_icon()

    def shortHelpString(self) -> str:  # noqa: N802
        return _tr(
            "Computes float32 spectral index GeoTIFFs (NDVI, NDWI, NDBI, SAVI, EVI) or renders uint8 3-band RGB "
            "composites (true-color, false-color-nir, agriculture, swir, or custom bands) and optional print map."
        )

    def createInstance(self) -> QgsProcessingAlgorithm:  # noqa: N802
        return LulckitBandsAlgorithm()

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:  # noqa: N802
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_RASTER, _tr("Input GeoTIFF / TIFF")))
        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                _tr("Operation Mode"),
                options=["Spectral Index (NDVI/NDWI/NDBI/SAVI/EVI)", "Composite Preset", "Custom 3-Band RGB", "Single Band"],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(self.INDEX_NAME, _tr("Spectral Index (when Mode = Spectral Index)"), options=INDEX_OPTIONS, defaultValue=0)
        )
        self.addParameter(
            QgsProcessingParameterEnum(self.COMPOSITE, _tr("Composite Preset (when Mode = Composite Preset)"), options=COMPOSITE_OPTIONS, defaultValue=0)
        )
        self.addParameter(
            QgsProcessingParameterString(self.RGB_BANDS, _tr("Custom RGB Bands (e.g. 4,3,2 when Mode = Custom RGB)"), optional=True, defaultValue="1,2,3")
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SINGLE_BAND, _tr("Band Number (when Mode = Single Band)"), type=_NUMBER_INTEGER, defaultValue=1, minValue=1
            )
        )
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterEnum(self.PALETTE, _tr("Preview Colormap (optional)"), options=INDEX_CMAP_OPTIONS, defaultValue=0)
            )
        )
        self.addParameter(
            _mark_advanced(QgsProcessingParameterString(self.TITLE, _tr("Preview Map Title (optional)"), optional=True, defaultValue=""))
        )
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_RASTER, _tr("Output GeoTIFF")))
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_PREVIEW, _tr("Optional Print Map (.png/.pdf/.svg)"), fileFilter="PNG (*.png);;PDF (*.pdf);;SVG (*.svg)", optional=True
            )
        )

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        tiff_path = _layer_source_path(layer)

        mode_idx = self.parameterAsEnum(parameters, self.MODE, context)
        mode = BAND_MODES[mode_idx]
        idx_name = INDEX_OPTIONS[self.parameterAsEnum(parameters, self.INDEX_NAME, context)]
        comp = COMPOSITE_OPTIONS[self.parameterAsEnum(parameters, self.COMPOSITE, context)]
        rgb_bands = self.parameterAsString(parameters, self.RGB_BANDS, context).strip() or "1,2,3"
        single_band = self.parameterAsInt(parameters, self.SINGLE_BAND, context)
        palette = INDEX_CMAP_OPTIONS[self.parameterAsEnum(parameters, self.PALETTE, context)] or None
        title = self.parameterAsString(parameters, self.TITLE, context).strip() or None

        out_tif = self.parameterAsOutputLayer(parameters, self.OUTPUT_RASTER, context)
        preview_out = self.parameterAsFileOutput(parameters, self.OUTPUT_PREVIEW, context) or None

        args = build_bands_args(
            tiff_path,
            output_path=out_tif,
            mode=mode,
            composite=comp,
            rgb_bands=rgb_bands,
            single_band=single_band,
            index_name=idx_name,
            palette=palette,
            title=title,
            preview_out=preview_out,
        )
        run_lulckit(args, configured_path=_get_configured_executable(), feedback=feedback)
        res = {self.OUTPUT_RASTER: out_tif}
        if preview_out:
            res[self.OUTPUT_PREVIEW] = preview_out
        return res


class LulckitInspectAlgorithm(QgsProcessingAlgorithm):
    """Profile GeoTIFF CRS, GSD, sensor type, and per-band percentiles."""

    INPUT_RASTER = "INPUT_RASTER"
    OUTPUT_JSON = "OUTPUT_JSON"

    def name(self) -> str:
        return "inspect"

    def displayName(self) -> str:  # noqa: N802
        return _tr("Inspect GeoTIFF Metadata & Sensor Profile")

    def group(self) -> str:
        return _tr("Inspection & Clipping")

    def groupId(self) -> str:  # noqa: N802
        return "inspection_clipping"

    def icon(self) -> QIcon:
        return _plugin_icon()

    def shortHelpString(self) -> str:  # noqa: N802
        return _tr(
            "Inspects CRS, GSD in meters, WGS84 extent, COG overviews, detected spectral bands, sensor fingerprint, "
            "and per-band percentiles without modifying the raster."
        )

    def createInstance(self) -> QgsProcessingAlgorithm:  # noqa: N802
        return LulckitInspectAlgorithm()

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:  # noqa: N802
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_RASTER, _tr("Input GeoTIFF / TIFF")))
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_JSON, _tr("Optional Metadata JSON Report"), fileFilter="JSON (*.json)", optional=True
            )
        )

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        tiff_path = _layer_source_path(layer)
        out_json = self.parameterAsFileOutput(parameters, self.OUTPUT_JSON, context) or None

        args = build_inspect_args(tiff_path, output_json=out_json)
        _, output = run_lulckit(args, configured_path=_get_configured_executable(), feedback=feedback)
        res: dict[str, Any] = {"REPORT_TEXT": output}
        if out_json:
            res[self.OUTPUT_JSON] = out_json
        return res


class LulckitClipAlgorithm(QgsProcessingAlgorithm):
    """Clip a GeoTIFF cleanly to any QGIS polygon vector layer preserving colormaps."""

    INPUT_RASTER = "INPUT_RASTER"
    BOUNDARY = "BOUNDARY"
    CROP = "CROP"
    NODATA = "NODATA"
    OUTPUT_RASTER = "OUTPUT_RASTER"

    def name(self) -> str:
        return "clip"

    def displayName(self) -> str:  # noqa: N802
        return _tr("Clip GeoTIFF to Polygon Layer")

    def group(self) -> str:
        return _tr("Inspection & Clipping")

    def groupId(self) -> str:  # noqa: N802
        return "inspection_clipping"

    def icon(self) -> QIcon:
        return _plugin_icon()

    def shortHelpString(self) -> str:  # noqa: N802
        return _tr(
            "Clips any georeferenced TIFF/GeoTIFF to a polygon vector layer (supports selected features, Shapefiles, "
            "GeoPackages, or memory layers) while preserving embedded GDAL colormaps."
        )

    def createInstance(self) -> QgsProcessingAlgorithm:  # noqa: N802
        return LulckitClipAlgorithm()

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:  # noqa: N802
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_RASTER, _tr("Input GeoTIFF / TIFF")))
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BOUNDARY, _tr("Clipping Polygon Layer"), types=[_TYPE_VECTOR_POLYGON]
            )
        )
        self.addParameter(QgsProcessingParameterBoolean(self.CROP, _tr("Crop Raster Extent to Polygon Bounds"), defaultValue=True))
        self.addParameter(
            _mark_advanced(
                QgsProcessingParameterString(self.NODATA, _tr("Override Nodata Value (optional)"), optional=True, defaultValue="")
            )
        )
        self.addParameter(QgsProcessingParameterRasterDestination(self.OUTPUT_RASTER, _tr("Clipped GeoTIFF")))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        tiff_path = _layer_source_path(layer)
        bsrc = self.parameterAsSource(parameters, self.BOUNDARY, context)
        boundary_geojson = _export_vector_source_to_geojson(bsrc, context, "clip_aoi")

        crop = self.parameterAsBoolean(parameters, self.CROP, context)
        nodata_raw = self.parameterAsString(parameters, self.NODATA, context).strip()
        nodata_val = float(nodata_raw) if nodata_raw else None
        out_tif = self.parameterAsOutputLayer(parameters, self.OUTPUT_RASTER, context)

        args = build_clip_args(tiff_path, boundary_geojson, out_tif, crop=crop, nodata=nodata_val)
        run_lulckit(args, configured_path=_get_configured_executable(), feedback=feedback)
        return {self.OUTPUT_RASTER: out_tif}
