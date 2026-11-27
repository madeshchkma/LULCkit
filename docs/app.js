/* LULCkit Browser GeoTIFF Studio (100% client-side, zero backend required) */
(() => {
  "use strict";

  const PALETTES = {
    "arcgis-crop": [
      [56, 168, 0],
      [230, 0, 0],
      [255, 170, 0],
      [0, 112, 255],
      [168, 112, 0],
      [169, 0, 230],
      [0, 230, 169],
    ],
    default: [
      [27, 138, 90],
      [231, 111, 81],
      [43, 123, 186],
      [233, 196, 106],
      [142, 94, 162],
      [214, 40, 40],
      [72, 202, 228],
      [141, 110, 99],
    ],
    vivid: [
      [0, 158, 115],
      [213, 94, 0],
      [0, 114, 178],
      [240, 228, 66],
      [204, 121, 167],
      [86, 180, 233],
      [230, 159, 0],
    ],
    earth: [
      [45, 106, 79],
      [212, 163, 115],
      [69, 123, 157],
      [149, 213, 178],
      [188, 71, 73],
      [233, 196, 106],
    ],
    pastel: [
      [102, 194, 165],
      [252, 141, 98],
      [141, 160, 203],
      [231, 138, 195],
      [166, 216, 84],
      [255, 217, 47],
    ],
    colorblind: [
      [0, 114, 178],
      [230, 159, 0],
      [0, 158, 115],
      [213, 94, 0],
      [204, 121, 167],
      [86, 180, 233],
      [240, 228, 66],
    ],
    "esa-worldcover": [
      [0, 100, 0],
      [255, 187, 34],
      [255, 255, 76],
      [240, 150, 255],
      [250, 0, 0],
      [180, 180, 180],
      [240, 240, 240],
      [0, 100, 200],
      [0, 150, 160],
      [0, 207, 117],
    ],
    "esri-lulc": [
      [26, 91, 171],
      [53, 130, 33],
      [135, 209, 158],
      [255, 219, 92],
      [237, 2, 42],
      [237, 233, 228],
      [242, 250, 255],
      [200, 200, 200],
      [198, 173, 141],
    ],
    "dynamic-world": [
      [65, 155, 223],
      [57, 125, 73],
      [136, 176, 83],
      [122, 135, 198],
      [228, 150, 53],
      [223, 195, 90],
      [196, 40, 27],
      [165, 155, 143],
      [179, 159, 225],
    ],
    nlcd: [
      [70, 107, 159],
      [217, 146, 130],
      [104, 171, 95],
      [28, 95, 44],
      [204, 184, 121],
      [220, 217, 57],
      [171, 108, 40],
      [184, 217, 235],
    ],
    corine: [
      [230, 0, 77],
      [255, 255, 168],
      [77, 230, 0],
      [204, 242, 77],
      [204, 204, 204],
      [166, 166, 255],
      [0, 204, 242],
    ],
    "qgis-spectral": [
      [215, 25, 28],
      [240, 124, 74],
      [254, 201, 128],
      [255, 255, 191],
      [199, 233, 173],
      [128, 191, 171],
      [43, 131, 186],
      [94, 79, 162],
    ],
    "arcgis-topo": [
      [45, 106, 79],
      [82, 183, 136],
      [149, 213, 178],
      [233, 196, 106],
      [244, 162, 97],
      [193, 124, 71],
      [141, 110, 99],
      [74, 144, 226],
    ],
    "urban-heat": [
      [43, 131, 186],
      [171, 221, 164],
      [255, 255, 191],
      [253, 174, 97],
      [244, 109, 67],
      [215, 25, 28],
      [128, 0, 38],
    ],
    hydrology: [
      [8, 48, 107],
      [8, 81, 156],
      [33, 113, 181],
      [66, 146, 198],
      [107, 174, 214],
      [158, 202, 225],
      [56, 168, 0],
      [217, 179, 130],
    ],
    "ag-phenology": [
      [243, 244, 246],
      [167, 243, 208],
      [52, 211, 153],
      [16, 185, 129],
      [4, 120, 87],
      [245, 158, 11],
      [220, 38, 38],
      [124, 45, 18],
    ],
  };

  const PAGE_SIZES = {
    a4: [11.69, 8.27],
    a5: [8.27, 5.83],
    a3: [16.54, 11.69],
    letter: [11.0, 8.5],
    legal: [14.0, 8.5],
    square: [10.0, 10.0],
  };

  const BASEMAP_TILES = {
    esri_street: {
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Tiles &copy; Esri",
    },
    esri: {
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Tiles &copy; Esri",
    },
    osm: {
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      attribution: "&copy; OpenStreetMap contributors",
    },
    esri_topo: {
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Tiles &copy; Esri",
    },
    esri_light: {
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Tiles &copy; Esri",
    },
    esri_dark: {
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Tiles &copy; Esri",
    },
    opentopo: {
      tiles: ["https://a.tile.opentopomap.org/{z}/{x}/{y}.png"],
      attribution: "&copy; OpenStreetMap &copy; OpenTopoMap",
    },
  };

  const BOGURA_LABELS = {
    0: "Non Boro",
    1: "Early/Normal Boro Rice",
    2: "Late-Transplanted Boro Rice",
  };

  const BANGLADESH_LABELS = {
    0: "Background / Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded Vegetation",
    4: "Crops",
    5: "Shrub & Scrub",
    6: "Built Area",
    7: "Bare Ground",
    8: "Snow & Ice",
  };

  const BANGLADESH_COLORS = {
    0: [255, 255, 255],
    1: [57, 125, 73],
    2: [136, 176, 83],
    3: [122, 135, 198],
    4: [228, 150, 53],
    5: [223, 195, 90],
    6: [196, 40, 27],
    7: [165, 155, 143],
    8: [179, 159, 225],
  };

  const state = {
    fileName: null,
    fileSizeBytes: 0,
    width: 0,
    height: 0,
    readW: 0,
    readH: 0,
    bandsCount: 0,
    rasters: null,
    nodata: null,
    epsg: null,
    crsLabel: "Unknown / Unprojected",
    isProjected: false,
    isGeographic: false,
    boundsNative: null,
    boundsWgs84: null,
    gsdX: null,
    gsdY: null,
    pixelAreaM2: null,
    isCategorical: false,
    classes: [],
    statsRows: [],
    indexStats: null,
    sbStats: null,
    lastPrintBox: null,
    gisTool: "identify",
    measurePoints: [],
    overlayDataUrl: null,
    map: null,
    lastReport: null,
  };

  const $ = (id) => document.getElementById(id);
  const canvas = $("printCanvas");
  const ctx = canvas.getContext("2d");

  function rgbToHex(rgb) {
    return (
      "#" +
      rgb
        .map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, "0"))
        .join("")
        .toUpperCase()
    );
  }

  function hexToRgb(hex) {
    const clean = (hex || "#888888").replace("#", "");
    return [
      parseInt(clean.slice(0, 2), 16) || 0,
      parseInt(clean.slice(2, 4), 16) || 0,
      parseInt(clean.slice(4, 6), 16) || 0,
    ];
  }

  function formatBytes(n) {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let val = n;
    let i = 0;
    while (val >= 1024 && i < units.length - 1) {
      val /= 1024;
      i++;
    }
    return `${val.toFixed(2)} ${units[i]}`;
  }

  function ensureProjDef(epsg) {
    if (!epsg || typeof proj4 === "undefined") return null;
    const code = `EPSG:${epsg}`;
    if (epsg === 4326 || epsg === 3857) return code;
    if (proj4.defs(code)) return code;
    if (epsg >= 32601 && epsg <= 32660) {
      const zone = epsg - 32600;
      proj4.defs(code, `+proj=utm +zone=${zone} +datum=WGS84 +units=m +no_defs`);
      return code;
    }
    if (epsg >= 32701 && epsg <= 32760) {
      const zone = epsg - 32700;
      proj4.defs(code, `+proj=utm +zone=${zone} +south +datum=WGS84 +units=m +no_defs`);
      return code;
    }
    return null;
  }

  function extractSpatialMeta(image) {
    const w = image.getWidth();
    const h = image.getHeight();
    const geoKeys = image.getGeoKeys() || {};
    const epsg = geoKeys.ProjectedCSTypeGeoKey || geoKeys.GeographicTypeGeoKey || null;
    let origin = null;
    let res = null;
    try {
      origin = image.getOrigin();
      res = image.getResolution();
    } catch (_) {
      origin = null;
      res = null;
    }

    let boundsNative = null;
    let boundsWgs84 = null;
    let isProjected = false;
    let isGeographic = false;
    let gsdX = null;
    let gsdY = null;
    let pixelAreaM2 = null;
    let crsLabel = "Pixel Coordinates (Unreferenced)";

    if (origin && res && epsg) {
      const x0 = origin[0];
      const y1 = origin[1];
      const rx = res[0];
      const ry = res[1];
      const x1 = x0 + w * rx;
      const y0 = y1 + h * ry;
      boundsNative = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];

      if (epsg === 4326) {
        isGeographic = true;
        crsLabel = "EPSG:4326 (WGS 84 Geographic)";
        boundsWgs84 = [...boundsNative];
        const midLat = (boundsWgs84[1] + boundsWgs84[3]) / 2;
        const mPerDegLat = 111132.92;
        const mPerDegLon = 111319.49 * Math.cos((midLat * Math.PI) / 180);
        gsdX = Math.abs(rx) * mPerDegLon;
        gsdY = Math.abs(ry) * mPerDegLat;
        pixelAreaM2 = gsdX * gsdY;
      } else {
        isProjected = true;
        crsLabel =
          epsg >= 32601 && epsg <= 32660
            ? `EPSG:${epsg} (UTM Zone ${epsg - 32600}N)`
            : epsg >= 32701 && epsg <= 32760
              ? `EPSG:${epsg} (UTM Zone ${epsg - 32700}S)`
              : `EPSG:${epsg}`;
        gsdX = Math.abs(rx);
        gsdY = Math.abs(ry);
        pixelAreaM2 = gsdX * gsdY;
        const def = ensureProjDef(epsg);
        if (def) {
          const sw = proj4(def, "EPSG:4326", [boundsNative[0], boundsNative[1]]);
          const ne = proj4(def, "EPSG:4326", [boundsNative[2], boundsNative[3]]);
          boundsWgs84 = [sw[0], sw[1], ne[0], ne[1]];
        }
      }
    } else {
      boundsNative = [0, 0, w, h];
    }

    return { epsg, crsLabel, isProjected, isGeographic, boundsNative, boundsWgs84, gsdX, gsdY, pixelAreaM2 };
  }

  function applyPaletteToClasses(paletteName) {
    const pal = PALETTES[paletteName] || PALETTES["arcgis-crop"];
    let cidx = 0;
    const lowerName = (state.fileName || "").toLowerCase();
    const isBogura = lowerName.includes("bogura_boro");
    const isBangladesh = lowerName.includes("bangladesh_lulc");
    state.classes.forEach((cls) => {
      if (isBangladesh && paletteName === "dynamic-world" && BANGLADESH_COLORS[cls.id]) {
        cls.rgb = [...BANGLADESH_COLORS[cls.id]];
      } else if (cls.id === 0) {
        cls.rgb = [255, 255, 255];
      } else {
        cls.rgb = [...pal[cidx % pal.length]];
        cidx++;
      }
      if (!cls.userEdited && isBogura && BOGURA_LABELS[cls.id]) {
        cls.name = BOGURA_LABELS[cls.id];
      } else if (!cls.userEdited && isBangladesh && BANGLADESH_LABELS[cls.id]) {
        cls.name = BANGLADESH_LABELS[cls.id];
      }
    });
  }

  function renderClassEditorRows() {
    const wrap = $("classEditors");
    wrap.innerHTML = "";
    if (!state.classes.length) {
      wrap.innerHTML = '<div style="font-size:12px;color:#64748b;">No categorical classes found (switch to RGB or Spectral Index mode).</div>';
      return;
    }
    state.classes.forEach((cls) => {
      const row = document.createElement("div");
      row.className = "class-editor-row";
      const hex = rgbToHex(cls.rgb);
      const vis = cls.visible !== false;
      row.innerHTML = `
        <input type="checkbox" ${vis ? "checked" : ""} title="Toggle class visibility" />
        <code>${cls.id}</code>
        <input type="color" value="${hex}" data-id="${cls.id}" />
        <input type="text" value="${cls.name}" data-id="${cls.id}" />
      `;
      row.querySelector('input[type="checkbox"]').addEventListener("change", (e) => {
        cls.visible = e.target.checked;
        renderAll();
      });
      row.querySelector('input[type="color"]').addEventListener("input", (e) => {
        cls.rgb = hexToRgb(e.target.value);
        renderAll();
      });
      row.querySelector('input[type="text"]').addEventListener("input", (e) => {
        cls.name = e.target.value || `Class ${cls.id}`;
        cls.userEdited = true;
        renderAll();
      });
      wrap.appendChild(row);
    });
  }

  const loaderAnim = {
    rafId: null,
    active: false,
    currentPct: 0,
    targetPct: 0,
    creepCeil: 0,
    startTime: 0,
    metaText: "",
  };

  function yieldFrame() {
    return new Promise((resolve) => requestAnimationFrame(resolve));
  }

  function _paintLoaderUi() {
    const rounded = Math.max(0, Math.min(100, Math.round(loaderAnim.currentPct)));
    if ($("loaderBarFill")) $("loaderBarFill").style.width = `${loaderAnim.currentPct.toFixed(1)}%`;
    if ($("loaderPct")) $("loaderPct").textContent = `${rounded}%`;
    if ($("loaderMeta")) {
      const elapsed = ((performance.now() - loaderAnim.startTime) / 1000).toFixed(1);
      $("loaderMeta").textContent = loaderAnim.metaText ? `${loaderAnim.metaText} · ${elapsed}s` : `Elapsed ${elapsed}s`;
    }
  }

  function _tickLoader() {
    if (!loaderAnim.active) return;
    if (loaderAnim.targetPct < loaderAnim.creepCeil) {
      loaderAnim.targetPct += (loaderAnim.creepCeil - loaderAnim.targetPct) * 0.018;
    }
    loaderAnim.currentPct += (loaderAnim.targetPct - loaderAnim.currentPct) * 0.16;
    _paintLoaderUi();
    loaderAnim.rafId = requestAnimationFrame(_tickLoader);
  }

  function startStudioLoader(title, stage) {
    const loader = $("studioLoader");
    loaderAnim.active = true;
    loaderAnim.currentPct = 2;
    loaderAnim.targetPct = 8;
    loaderAnim.creepCeil = 28;
    loaderAnim.startTime = performance.now();
    loaderAnim.metaText = "Starting pipeline";
    if (loader) {
      loader.classList.remove("hidden", "is-fading");
      if (title && $("loaderTitle")) $("loaderTitle").textContent = title;
      if (stage && $("loaderStage")) $("loaderStage").textContent = stage;
      document.querySelectorAll("#studioLoader .loader-step").forEach((el) => {
        const s = Number(el.dataset.step || 0);
        el.classList.remove("is-done");
        el.classList.toggle("is-active", s === 1);
      });
    }
    if ($("dropzone")) $("dropzone").classList.add("is-loading");
    if (loaderAnim.rafId) cancelAnimationFrame(loaderAnim.rafId);
    _paintLoaderUi();
    loaderAnim.rafId = requestAnimationFrame(_tickLoader);
  }

  function setStudioLoaderProgress(stage, targetPct, creepCeil, stepIndex, metaText = null) {
    if (!loaderAnim.active) return;
    if (stage && $("loaderStage")) $("loaderStage").textContent = stage;
    if (typeof targetPct === "number") loaderAnim.targetPct = Math.max(loaderAnim.targetPct, targetPct);
    if (typeof creepCeil === "number") loaderAnim.creepCeil = Math.max(loaderAnim.targetPct, creepCeil);
    if (metaText !== null) loaderAnim.metaText = metaText;
    if (stepIndex) {
      document.querySelectorAll("#studioLoader .loader-step").forEach((el) => {
        const s = Number(el.dataset.step || 0);
        el.classList.toggle("is-done", s < stepIndex);
        el.classList.toggle("is-active", s === stepIndex);
      });
    }
  }

  async function finishStudioLoader() {
    if (!loaderAnim.active) return;
    loaderAnim.creepCeil = 100;
    loaderAnim.targetPct = 100;
    setStudioLoaderProgress("Complete — workspace ready", 100, 100, 5);
    await new Promise((r) => setTimeout(r, 240));
    loaderAnim.currentPct = 100;
    _paintLoaderUi();
    const loader = $("studioLoader");
    if (loader) loader.classList.add("is-fading");
    await new Promise((r) => setTimeout(r, 260));
    abortStudioLoader();
  }

  function abortStudioLoader() {
    loaderAnim.active = false;
    if (loaderAnim.rafId) {
      cancelAnimationFrame(loaderAnim.rafId);
      loaderAnim.rafId = null;
    }
    if ($("studioLoader")) {
      $("studioLoader").classList.add("hidden");
      $("studioLoader").classList.remove("is-fading");
    }
    if ($("dropzone")) $("dropzone").classList.remove("is-loading");
  }

  function readFileWithProgress(file, onProgress) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onprogress = (ev) => {
        if (ev.lengthComputable && onProgress) onProgress(ev.loaded, ev.total);
      };
      reader.onerror = () => reject(reader.error || new Error("Failed reading local file"));
      reader.onload = () => {
        if (onProgress) onProgress(file.size, file.size);
        resolve(reader.result);
      };
      reader.readAsArrayBuffer(file);
    });
  }

  async function pickDecodeImage(tiff, fullWidth, targetWidth) {
    try {
      const count = await tiff.getImageCount();
      let bestImg = await tiff.getImage(0);
      let bestW = fullWidth;
      for (let i = 1; i < Math.min(count, 8); i++) {
        const cand = await tiff.getImage(i);
        const cw = cand.getWidth();
        if (cw >= targetWidth && cw < bestW) {
          bestImg = cand;
          bestW = cw;
        }
      }
      return bestImg;
    } catch (_) {
      return tiff.getImage(0);
    }
  }

  async function loadGeoTIFF(source, fileName, fileSizeBytes, loaderStarted = false) {
    let ok = false;
    try {
      $("statusText").textContent = `Processing ${fileName}...`;
      if (!loaderStarted) {
        startStudioLoader(`Processing ${fileName}`, "Reading GeoTIFF binary stream...");
      }

      let bufferOrSource = source;
      if (source instanceof Blob) {
        bufferOrSource = await readFileWithProgress(source, (loaded, total) => {
          const frac = total > 0 ? loaded / total : 0.5;
          setStudioLoaderProgress(
            "Streaming local GeoTIFF into browser memory...",
            6 + frac * 38,
            44,
            1,
            `${formatBytes(loaded)} / ${formatBytes(total)}`
          );
        });
      }

      setStudioLoaderProgress("Parsing GeoTIFF header & IFD directory...", 48, 56, 2, formatBytes(fileSizeBytes));
      await yieldFrame();

      const tiff = bufferOrSource instanceof ArrayBuffer
        ? await GeoTIFF.fromArrayBuffer(bufferOrSource)
        : await GeoTIFF.fromBlob(bufferOrSource);
      const image = await tiff.getImage(0);
      const width = image.getWidth();
      const height = image.getHeight();
      const bandsCount = image.getSamplesPerPixel();
      const nodataRaw = image.getGDALNoData();
      const nodata = nodataRaw !== null && nodataRaw !== undefined ? Number(nodataRaw) : null;
      const sp = extractSpatialMeta(image);

      const maxPreviewW = 1400;
      const readW = Math.min(width, maxPreviewW);
      const readH = Math.max(1, Math.round(height * (readW / width)));

      setStudioLoaderProgress(
        `Inspecting CRS (${sp.crsLabel}) & selecting COG pyramid overview...`,
        58,
        66,
        2,
        `${width.toLocaleString()} × ${height.toLocaleString()} px`
      );
      await yieldFrame();

      const decodeImg = width > maxPreviewW ? await pickDecodeImage(tiff, width, readW) : image;
      const sf = image.getSampleFormat ? image.getSampleFormat() : [1];
      const isFloat = sf && (sf[0] === 3);

      setStudioLoaderProgress(
        `Decoding ${bandsCount} band(s) at ${readW} × ${readH} preview resolution...`,
        68,
        88,
        3,
        `${bandsCount} band(s) · ${formatBytes(fileSizeBytes)}`
      );
      await yieldFrame();

      const rasters = await decodeImg.readRasters({
        width: readW,
        height: readH,
        resampleMethod: bandsCount === 1 && !isFloat ? "nearest" : "bilinear",
      });

      const isBangladesh = fileName.toLowerCase().includes("bangladesh_lulc");
      const isBogura = fileName.toLowerCase().includes("bogura_boro");

      Object.assign(state, {
        fileName,
        fileSizeBytes,
        width,
        height,
        readW,
        readH,
        bandsCount,
        rasters,
        nodata,
        ...sp,
      });

      if (isBangladesh) {
        $("paletteSelect").value = "dynamic-world";
      } else if (isBogura) {
        $("paletteSelect").value = "arcgis-crop";
      }

      // Detect categorical raster (1 band integer, <= 32 unique classes)
      state.classes = [];
      state.isCategorical = false;
      if (bandsCount === 1 && !isFloat) {
        const band0 = rasters[0];
        const uniq = new Set();
        let overflow = false;
        for (let i = 0; i < band0.length; i++) {
          const v = band0[i];
          if (nodata !== null && v === nodata) continue;
          if (!Number.isFinite(v)) continue;
          const iv = Math.round(v);
          if (!uniq.has(iv)) {
            uniq.add(iv);
            if (uniq.size > 32) {
              overflow = true;
              break;
            }
          }
        }
        if (!overflow && uniq.size >= 1) {
          state.isCategorical = true;
          const sorted = Array.from(uniq).sort((a, b) => a - b);
          state.classes = sorted.map((cid) => ({
            id: cid,
            name: `Class ${cid}`,
            rgb: [120, 120, 120],
            visible: true,
            userEdited: false,
          }));
          applyPaletteToClasses($("paletteSelect").value);
        }
      }

      setStudioLoaderProgress("Rendering cartographic canvas & area analytics...", 92, 98, 4);
      await yieldFrame();

      // Configure smart mode defaults
      const stem = fileName.replace(/\.(tiff?|tif)$/i, "");
      $("titleInput").value = isBogura
        ? "Boro Area Mapping for Bogura - 2026"
        : isBangladesh
          ? "Bangladesh Land Use / Land Cover - 2025"
          : stem;
      $("sbBand").max = bandsCount;
      $("bandR").max = bandsCount;
      $("bandG").max = bandsCount;
      $("bandB").max = bandsCount;
      $("idxBandA").max = bandsCount;
      $("idxBandB").max = bandsCount;

      if (bandsCount >= 3) {
        $("modeSelect").value = "rgb";
        if (bandsCount >= 8) {
          $("bandR").value = 4;
          $("bandG").value = 3;
          $("bandB").value = 2;
          $("idxBandA").value = 8;
          $("idxBandB").value = 4;
        } else {
          $("bandR").value = 1;
          $("bandG").value = 2;
          $("bandB").value = 3;
          $("idxBandA").value = 1;
          $("idxBandB").value = 2;
        }
      } else if (state.isCategorical) {
        $("modeSelect").value = "categorical";
      } else {
        $("modeSelect").value = "singleband";
      }

      state.measurePoints = [];
      renderClassEditorRows();
      updateControlVisibility();
      renderAll();
      $("downloadPngBtn").disabled = false;
      $("downloadCsvBtn").disabled = false;
      $("downloadJsonBtn").disabled = false;
      $("downloadQmlBtn").disabled = false;
      $("downloadSldBtn").disabled = false;
      ok = true;
      await finishStudioLoader();
    } catch (err) {
      $("statusText").textContent = `Could not decode ${fileName}: ${err.message}`;
      abortStudioLoader();
      if (!ok) return;
    }
  }

  function updateControlVisibility() {
    const mode = $("modeSelect").value;
    $("categoricalControls").classList.toggle("hidden", mode !== "categorical");
    $("singlebandControls").classList.toggle("hidden", mode !== "singleband");
    $("rgbControls").classList.toggle("hidden", mode !== "rgb");
    $("indexControls").classList.toggle("hidden", mode !== "index");
    if ($("sbCustomRange")) {
      $("sbCustomRange").classList.toggle("hidden", $("sbStretch").value !== "custom");
    }
  }

  const COLOR_RAMPS = {
    RdYlGn: [[165, 0, 38], [244, 109, 67], [254, 224, 139], [217, 239, 139], [102, 189, 99], [0, 104, 55]],
    Blues: [[247, 251, 255], [198, 219, 239], [107, 174, 214], [33, 113, 181], [8, 48, 107]],
    RdBu: [[178, 24, 43], [239, 138, 98], [247, 247, 247], [103, 169, 207], [33, 102, 172]],
    Viridis: [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
    Plasma: [[13, 8, 135], [126, 3, 168], [204, 71, 120], [248, 149, 64], [240, 249, 33]],
    Inferno: [[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]],
    Magma: [[0, 0, 4], [81, 18, 124], [183, 55, 121], [252, 137, 97], [252, 253, 191]],
    Turbo: [[48, 18, 59], [40, 188, 235], [164, 252, 60], [251, 126, 33], [122, 4, 3]],
    Terrain: [[51, 51, 153], [0, 153, 102], [204, 204, 102], [153, 102, 51], [255, 255, 255]],
    Spectral: [[158, 1, 66], [244, 109, 67], [255, 255, 191], [102, 194, 165], [94, 79, 162]],
    BrBG: [[84, 48, 5], [191, 129, 45], [245, 245, 245], [53, 151, 143], [0, 60, 48]],
    YlOrRd: [[255, 255, 204], [254, 217, 118], [253, 141, 60], [227, 26, 28], [128, 0, 38]],
    Grayscale: [[15, 15, 15], [128, 128, 128], [245, 245, 245]],
  };

  function colormapLookup(name, t, invert = false) {
    let u = Math.max(0, Math.min(1, t));
    if (invert) u = 1 - u;
    const stops = COLOR_RAMPS[name] || COLOR_RAMPS.RdYlGn;
    const scaled = u * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(scaled));
    const f = scaled - i;
    const a = stops[i];
    const b = stops[i + 1];
    return [
      Math.round(a[0] + (b[0] - a[0]) * f),
      Math.round(a[1] + (b[1] - a[1]) * f),
      Math.round(a[2] + (b[2] - a[2]) * f),
    ];
  }

  function computeBandStatsAndStretch(arr, nodata, stretchMode = "p2_98", customMin = NaN, customMax = NaN) {
    const step = Math.max(1, Math.floor(arr.length / 80000));
    const sample = [];
    let sum = 0;
    let mn = Infinity;
    let mx = -Infinity;
    for (let i = 0; i < arr.length; i += step) {
      const v = arr[i];
      if ((nodata === null || v !== nodata) && Number.isFinite(v)) {
        sample.push(v);
        sum += v;
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
    if (!sample.length) return { lo: 0, hi: 255, min: 0, max: 0, mean: 0, std: 0, count: 0 };
    const mean = sum / sample.length;
    let sq = 0;
    for (let i = 0; i < sample.length; i++) sq += (sample[i] - mean) * (sample[i] - mean);
    const std = Math.sqrt(sq / sample.length);

    let lo = mn;
    let hi = mx;
    if (stretchMode === "custom" && Number.isFinite(customMin) && Number.isFinite(customMax) && customMax > customMin) {
      lo = customMin;
      hi = customMax;
    } else if (stretchMode === "stddev2" && std > 0) {
      lo = Math.max(mn, mean - 2 * std);
      hi = Math.min(mx, mean + 2 * std);
    } else if (stretchMode === "p2_98") {
      sample.sort((a, b) => a - b);
      lo = sample[Math.floor(0.02 * (sample.length - 1))];
      hi = sample[Math.floor(0.98 * (sample.length - 1))];
    }
    if (!(hi > lo)) hi = lo + 1;
    return { lo, hi, min: mn, max: mx, mean, std, count: sample.length };
  }

  function buildRasterOffscreen() {
    const mode = $("modeSelect").value;
    const rw = state.readW;
    const rh = state.readH;
    const off = document.createElement("canvas");
    off.width = rw;
    off.height = rh;
    const octx = off.getContext("2d");
    const imgData = octx.createImageData(rw, rh);
    const px = imgData.data;

    state.statsRows = [];
    state.indexStats = null;
    state.sbStats = null;

    if (mode === "categorical" && state.classes.length) {
      const band = state.rasters[0];
      const lut = new Map();
      const visLut = new Map();
      const counts = new Map();
      state.classes.forEach((c) => {
        lut.set(c.id, c.rgb);
        visLut.set(c.id, c.visible !== false);
        counts.set(c.id, 0);
      });

      let validSample = 0;
      for (let i = 0; i < band.length; i++) {
        const v = Math.round(band[i]);
        const rgb = lut.get(v);
        const p = i * 4;
        if (rgb) {
          counts.set(v, (counts.get(v) || 0) + 1);
          validSample++;
          if (visLut.get(v)) {
            px[p] = rgb[0];
            px[p + 1] = rgb[1];
            px[p + 2] = rgb[2];
            px[p + 3] = 255;
          } else {
            px[p + 3] = 0;
          }
        } else {
          px[p] = 255;
          px[p + 1] = 255;
          px[p + 2] = 255;
          px[p + 3] = 0;
        }
      }

      const fullScale = (state.width * state.height) / (rw * rh);
      state.statsRows = state.classes.map((c) => {
        const rawN = counts.get(c.id) || 0;
        const estPixels = Math.round(rawN * fullScale);
        const pct = validSample > 0 ? (rawN / validSample) * 100 : 0;
        const areaM2 = state.pixelAreaM2 ? estPixels * state.pixelAreaM2 : null;
        return {
          id: c.id,
          name: c.name,
          hex: rgbToHex(c.rgb),
          rgb: c.rgb,
          pixels: estPixels,
          percent: Number(pct.toFixed(4)),
          area_m2: areaM2 !== null ? Number(areaM2.toFixed(2)) : null,
          area_ha: areaM2 !== null ? Number((areaM2 / 10000).toFixed(2)) : null,
          area_km2: areaM2 !== null ? Number((areaM2 / 1e6).toFixed(4)) : null,
        };
      });
    } else if (mode === "singleband") {
      const bi = Math.max(0, Math.min(state.bandsCount - 1, (parseInt($("sbBand").value, 10) || 1) - 1));
      const band = state.rasters[bi];
      const stretch = $("sbStretch").value;
      const cMin = parseFloat($("sbMin").value);
      const cMax = parseFloat($("sbMax").value);
      const cmap = $("sbCmap").value;
      const invert = $("sbInvertCheck").checked;
      const st = computeBandStatsAndStretch(band, state.nodata, stretch, cMin, cMax);
      for (let i = 0; i < rw * rh; i++) {
        const v = band[i];
        const p = i * 4;
        if ((state.nodata !== null && v === state.nodata) || !Number.isFinite(v)) {
          px[p + 3] = 0;
          continue;
        }
        const rgb = colormapLookup(cmap, (v - st.lo) / (st.hi - st.lo), invert);
        px[p] = rgb[0];
        px[p + 1] = rgb[1];
        px[p + 2] = rgb[2];
        px[p + 3] = 255;
      }
      state.sbStats = {
        band: bi + 1,
        stretch,
        cmap,
        invert,
        lo: Number(st.lo.toFixed(4)),
        hi: Number(st.hi.toFixed(4)),
        min: Number(st.min.toFixed(4)),
        max: Number(st.max.toFixed(4)),
        mean: Number(st.mean.toFixed(4)),
        std: Number(st.std.toFixed(4)),
      };
    } else if (mode === "rgb") {
      const bi = ["bandR", "bandG", "bandB"].map((id) =>
        Math.max(0, Math.min(state.bandsCount - 1, (parseInt($(id).value, 10) || 1) - 1))
      );
      const stretch = $("rgbStretch") ? $("rgbStretch").value : "p2_98";
      const gamma = $("rgbGamma") ? Math.max(0.2, parseFloat($("rgbGamma").value) || 1.0) : 1.0;
      const invGamma = 1 / gamma;
      const bands = bi.map((idx) => state.rasters[idx]);
      const ranges = bands.map((b) => computeBandStatsAndStretch(b, state.nodata, stretch));
      for (let i = 0; i < rw * rh; i++) {
        const p = i * 4;
        let masked = false;
        for (let c = 0; c < 3; c++) {
          const v = bands[c][i];
          if ((state.nodata !== null && v === state.nodata) || !Number.isFinite(v)) {
            masked = true;
            break;
          }
          const { lo, hi } = ranges[c];
          const norm = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
          px[p + c] = Math.round(Math.pow(norm, invGamma) * 255);
        }
        px[p + 3] = masked ? 0 : 255;
      }
    } else {
      // Spectral Index mode
      const ia = Math.max(0, Math.min(state.bandsCount - 1, (parseInt($("idxBandA").value, 10) || 1) - 1));
      const ib = Math.max(0, Math.min(state.bandsCount - 1, (parseInt($("idxBandB").value, 10) || 1) - 1));
      const bA = state.rasters[ia];
      const bB = state.rasters[ib];
      const cmap = $("idxCmap").value;
      const invert = $("idxInvertCheck") ? $("idxInvertCheck").checked : false;
      let sum = 0;
      let cnt = 0;
      let mn = Infinity;
      let mx = -Infinity;

      for (let i = 0; i < rw * rh; i++) {
        const va = bA[i];
        const vb = bB[i];
        const p = i * 4;
        const den = va + vb;
        if (!Number.isFinite(va) || !Number.isFinite(vb) || Math.abs(den) < 1e-9) {
          px[p + 3] = 0;
          continue;
        }
        const val = Math.max(-1, Math.min(1, (va - vb) / den));
        sum += val;
        cnt++;
        if (val < mn) mn = val;
        if (val > mx) mx = val;
        const rgb = colormapLookup(cmap, (val + 1) / 2, invert);
        px[p] = rgb[0];
        px[p + 1] = rgb[1];
        px[p + 2] = rgb[2];
        px[p + 3] = 255;
      }
      state.indexStats = {
        index: $("indexType").value.toUpperCase(),
        bandA: ia + 1,
        bandB: ib + 1,
        valid_pixels: cnt,
        min: cnt ? Number(mn.toFixed(4)) : null,
        max: cnt ? Number(mx.toFixed(4)) : null,
        mean: cnt ? Number((sum / cnt).toFixed(4)) : null,
      };
    }

    octx.putImageData(imgData, 0, 0);
    state.overlayDataUrl = off.toDataURL("image/png");
    return off;
  }

  function resolvePagePixels() {
    const ps = $("pageSizeSelect").value;
    const ori = $("orientationSelect").value;
    const [a, b] = PAGE_SIZES[ps] || PAGE_SIZES.a4;
    const dataAspect = state.width / Math.max(1, state.height);
    let wIn = a;
    let hIn = b;
    if (ori === "portrait") {
      wIn = Math.min(a, b);
      hIn = Math.max(a, b);
    } else if (ori === "landscape") {
      wIn = Math.max(a, b);
      hIn = Math.min(a, b);
    } else if (dataAspect < 0.95) {
      wIn = Math.min(a, b);
      hIn = Math.max(a, b);
    }
    const baseScale = 160;
    return [Math.round(wIn * baseScale), Math.round(hIn * baseScale)];
  }

  function drawNorthArrow(cx, cy, radius, style) {
    if (style === "none") return;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.strokeStyle = "#111827";
    ctx.fillStyle = "#111827";

    if (style === "compass") {
      ctx.font = `bold ${Math.round(radius * 0.42)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("N", 0, -radius * 1.15);
      ctx.fillText("S", 0, radius * 1.15);
      ctx.fillText("E", radius * 1.15, 0);
      ctx.fillText("W", -radius * 1.15, 0);
      const pts = 8;
      for (let i = 0; i < pts; i++) {
        const ang = (i * Math.PI) / 4 - Math.PI / 2;
        const rTip = i % 2 === 0 ? radius * 0.85 : radius * 0.56;
        const aL = ang - Math.PI / 8;
        const aR = ang + Math.PI / 8;
        const rIn = radius * 0.2;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(Math.cos(aL) * rIn, Math.sin(aL) * rIn);
        ctx.lineTo(Math.cos(ang) * rTip, Math.sin(ang) * rTip);
        ctx.closePath();
        ctx.fillStyle = "#111827";
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(Math.cos(ang) * rTip, Math.sin(ang) * rTip);
        ctx.lineTo(Math.cos(aR) * rIn, Math.sin(aR) * rIn);
        ctx.closePath();
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(0, 0, radius * 0.6, 0, Math.PI * 2);
      ctx.lineWidth = 1.4;
      ctx.stroke();
    } else if (style === "classic") {
      ctx.font = `bold ${Math.round(radius * 0.48)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("N", 0, -radius * 0.82);
      ctx.beginPath();
      ctx.moveTo(0, -radius * 0.65);
      ctx.lineTo(-radius * 0.42, radius * 0.65);
      ctx.lineTo(0, radius * 0.35);
      ctx.closePath();
      ctx.fillStyle = "#111827";
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(0, -radius * 0.65);
      ctx.lineTo(radius * 0.42, radius * 0.65);
      ctx.lineTo(0, radius * 0.35);
      ctx.closePath();
      ctx.fillStyle = "#ffffff";
      ctx.fill();
      ctx.stroke();
    } else if (style === "fancy") {
      ctx.font = `bold ${Math.round(radius * 0.45)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("N", 0, -radius * 0.9);
      const rTip = radius * 0.72;
      const rMid = radius * 0.2;
      for (let i = 0; i < 4; i++) {
        ctx.save();
        ctx.rotate((i * Math.PI) / 2);
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(-rMid, -rMid);
        ctx.lineTo(0, -rTip);
        ctx.closePath();
        ctx.fillStyle = "#111827";
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(0, -rTip);
        ctx.lineTo(rMid, -rMid);
        ctx.closePath();
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }
    } else {
      ctx.font = `bold ${Math.round(radius * 0.48)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("N", 0, -radius * 0.8);
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.moveTo(0, radius * 0.65);
      ctx.lineTo(0, -radius * 0.55);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, -radius * 0.65);
      ctx.lineTo(-radius * 0.25, -radius * 0.2);
      ctx.lineTo(radius * 0.25, -radius * 0.2);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }

  function drawScaleBar(xCenter, yBase, boxW, style) {
    if (style === "none" || !state.gsdX) return;
    const totalM = state.width * state.gsdX;
    const targetM = totalM * 0.35;
    const niceStepsM = [50000, 40000, 30000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100];
    let totalBarM = niceStepsM.find((s) => s <= targetM) || Math.max(100, Math.round(targetM / 100) * 100);
    const barPx = (totalBarM / totalM) * boxW;
    const useKm = totalBarM >= 1000;
    const unit = useKm ? "Kilometers" : "Meters";
    const factor = useKm ? 1000 : 1;

    ctx.save();
    ctx.strokeStyle = "#111827";
    ctx.fillStyle = "#111827";
    ctx.lineWidth = 1.4;
    ctx.font = "bold 13px sans-serif";

    const barH = 11;
    const x0 = xCenter - barPx / 2;

    if (style === "arcgis") {
      // Negative split + 4 main divisions matching CLI ArcGIS bar
      const divs = [0, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0];
      const labels = [
        Math.round((0.2 * totalBarM) / factor),
        Math.round((0.1 * totalBarM) / factor),
        0,
        Math.round((0.2 * totalBarM) / factor),
        Math.round((0.4 * totalBarM) / factor),
        Math.round((0.6 * totalBarM) / factor),
        Math.round((0.8 * totalBarM) / factor),
      ];
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(x0, yBase - barH, barPx, barH);
      ctx.strokeRect(x0, yBase - barH, barPx, barH);
      ctx.beginPath();
      ctx.moveTo(x0, yBase - barH / 2);
      ctx.lineTo(x0 + barPx, yBase - barH / 2);
      ctx.stroke();

      ctx.textAlign = "center";
      ctx.fillStyle = "#111827";
      divs.forEach((f, idx) => {
        const tx = x0 + f * barPx;
        ctx.beginPath();
        ctx.moveTo(tx, yBase - barH - 4);
        ctx.lineTo(tx, yBase);
        ctx.stroke();
        ctx.fillText(String(labels[idx]), tx, yBase - barH - 9);
      });
      ctx.textAlign = "left";
      ctx.fillText(unit, x0 + barPx + 10, yBase - 1);
    } else if (style === "alternating") {
      const segs = 4;
      const segW = barPx / segs;
      for (let i = 0; i < segs; i++) {
        ctx.fillStyle = i % 2 === 0 ? "#111827" : "#ffffff";
        ctx.fillRect(x0 + i * segW, yBase - barH, segW, barH);
        ctx.strokeRect(x0 + i * segW, yBase - barH, segW, barH);
      }
      ctx.fillStyle = "#111827";
      ctx.textAlign = "center";
      ctx.fillText("0", x0, yBase - barH - 7);
      ctx.fillText(`${Math.round(totalBarM / (2 * factor))}`, x0 + barPx / 2, yBase - barH - 7);
      ctx.fillText(`${Math.round(totalBarM / factor)} ${unit}`, x0 + barPx, yBase - barH - 7);
    } else {
      ctx.beginPath();
      ctx.moveTo(x0, yBase - 8);
      ctx.lineTo(x0, yBase);
      ctx.lineTo(x0 + barPx, yBase);
      ctx.lineTo(x0 + barPx, yBase - 8);
      ctx.stroke();
      ctx.textAlign = "center";
      ctx.fillText("0", x0, yBase - 12);
      ctx.fillText(`${Math.round(totalBarM / factor)} ${unit}`, x0 + barPx, yBase - 12);
    }
    ctx.restore();
  }

  function renderPrintCanvas(offscreen) {
    const [cw, ch] = resolvePagePixels();
    canvas.width = cw;
    canvas.height = ch;

    const showGrid = $("gridCheck").checked;
    const padL = showGrid ? 115 : 32;
    const padR = 32;
    const padT = 32;
    const padB = showGrid ? 72 : 32;
    const boxW = cw - padL - padR;
    const boxH = ch - padT - padB;

    // White page
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, cw, ch);

    // Clip to neatline box and draw raster centered with equal aspect
    ctx.save();
    ctx.beginPath();
    ctx.rect(padL, padT, boxW, boxH);
    ctx.clip();

    const reserveTop = 58;
    const reserveBot = 48;
    const availH = boxH - reserveTop - reserveBot;
    const imgRatio = offscreen.width / offscreen.height;
    let drawW = boxW * 0.92;
    let drawH = drawW / imgRatio;
    if (drawH > availH) {
      drawH = availH;
      drawW = drawH * imgRatio;
    }
    const imgX = padL + (boxW - drawW) / 2;
    const imgY = padT + reserveTop + (availH - drawH) / 2;
    state.lastPrintBox = { imgX, imgY, drawW, drawH };
    ctx.imageSmoothingEnabled = $("modeSelect").value !== "categorical";
    ctx.drawImage(offscreen, imgX, imgY, drawW, drawH);

    // Gridlines & coordinate ticks
    if (showGrid && state.boundsNative) {
      const [bx0, by0, bx1, by1] = state.boundsNative;
      ctx.strokeStyle = "rgba(100,116,139,0.28)";
      ctx.setLineDash([5, 5]);
      ctx.lineWidth = 1;
      for (let i = 1; i <= 4; i++) {
        const gx = padL + (boxW * i) / 5;
        const gy = padT + (boxH * i) / 5;
        ctx.beginPath();
        ctx.moveTo(gx, padT);
        ctx.lineTo(gx, padT + boxH);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(padL, gy);
        ctx.lineTo(padL + boxW, gy);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.restore();

      // Axis labels & ticks outside neatline
      ctx.fillStyle = "#1e293b";
      ctx.strokeStyle = "#1e293b";
      ctx.font = "12px monospace";
      const isDeg = state.isGeographic;
      const unitPx = !state.isProjected && !state.isGeographic;

      ctx.textAlign = "center";
      for (let i = 0; i <= 4; i++) {
        const frac = (i + 0.5) / 5;
        const tx = padL + boxW * frac;
        const valX = bx0 + (bx1 - bx0) * frac;
        const lblX = isDeg ? `${valX.toFixed(2)}°` : Math.round(valX).toLocaleString();
        ctx.beginPath();
        ctx.moveTo(tx, padT + boxH);
        ctx.lineTo(tx, padT + boxH + 5);
        ctx.stroke();
        ctx.fillText(lblX, tx, padT + boxH + 20);
      }

      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let i = 0; i <= 4; i++) {
        const frac = (i + 0.5) / 5;
        const ty = padT + boxH * frac;
        const valY = by1 - (by1 - by0) * frac;
        const lblY = isDeg ? `${valY.toFixed(2)}°` : Math.round(valY).toLocaleString();
        ctx.beginPath();
        ctx.moveTo(padL - 5, ty);
        ctx.lineTo(padL, ty);
        ctx.stroke();
        ctx.fillText(lblY, padL - 9, ty);
      }

      ctx.font = "bold 13.5px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(isDeg ? "Longitude (°)" : unitPx ? "Column (px)" : "Easting (m)", padL + boxW / 2, ch - 18);

      ctx.save();
      ctx.translate(22, padT + boxH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(isDeg ? "Latitude (°)" : unitPx ? "Row (px)" : "Northing (m)", 0, 0);
      ctx.restore();
    } else {
      ctx.restore();
    }

    // Crisp outer neatline border
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 2;
    ctx.strokeRect(padL, padT, boxW, boxH);

    // Map Title
    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 24px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText($("titleInput").value || state.fileName || "LULC Map", padL + boxW / 2, padT + 18);

    // North Arrow
    drawNorthArrow(padL + boxW - 76, padT + 86, 36, $("arrowStyleSelect").value);

    // Scale Bar
    drawScaleBar(padL + boxW / 2, padT + boxH - 18, boxW, $("scalebarStyleSelect").value);

    // Bottom-left Legend card
    const mode = $("modeSelect").value;
    const visClasses = state.classes.filter((c) => c.visible !== false);
    if (mode === "categorical" && visClasses.length) {
      const shown = visClasses.slice(0, 10);
      const legW = 250;
      const rowH = 24;
      const legH = 38 + shown.length * rowH;
      const lx = padL + 18;
      const ly = padT + boxH - legH - 18;
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(lx, ly, legW, legH);
      ctx.strokeStyle = "#64748b";
      ctx.lineWidth = 1;
      ctx.strokeRect(lx, ly, legW, legH);

      ctx.fillStyle = "#0f172a";
      ctx.font = "bold 14px sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText("Legend", lx + 12, ly + 10);

      ctx.font = "12.5px sans-serif";
      shown.forEach((cls, idx) => {
        const ry = ly + 36 + idx * rowH;
        ctx.fillStyle = rgbToHex(cls.rgb);
        ctx.fillRect(lx + 12, ry, 24, 15);
        ctx.strokeStyle = "#475569";
        ctx.strokeRect(lx + 12, ry, 24, 15);
        ctx.fillStyle = "#0f172a";
        ctx.fillText(cls.name.slice(0, 26), lx + 44, ry + 1);
      });
    } else if (mode === "index" || mode === "singleband") {
      const lx = padL + 18;
      const ly = padT + boxH - 70;
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(lx, ly, 230, 52);
      ctx.strokeStyle = "#64748b";
      ctx.strokeRect(lx, ly, 230, 52);
      ctx.fillStyle = "#0f172a";
      ctx.font = "bold 12.5px sans-serif";
      ctx.textAlign = "left";
      const isSb = mode === "singleband" && state.sbStats;
      const titleTxt = isSb ? `BAND ${state.sbStats.band}` : $("indexType").value.toUpperCase();
      ctx.fillText(titleTxt, lx + 10, ly + 8);
      const cmap = isSb ? state.sbStats.cmap : $("idxCmap").value;
      const invert = isSb ? state.sbStats.invert : ($("idxInvertCheck") ? $("idxInvertCheck").checked : false);
      for (let x = 0; x < 200; x++) {
        const rgb = colormapLookup(cmap, x / 199, invert);
        ctx.fillStyle = rgbToHex(rgb);
        ctx.fillRect(lx + 14 + x, ly + 28, 2, 12);
      }
      ctx.font = "11px monospace";
      ctx.fillStyle = "#0f172a";
      const loLbl = isSb ? state.sbStats.lo.toFixed(1) : "-1.0";
      const midLbl = isSb ? ((state.sbStats.lo + state.sbStats.hi) / 2).toFixed(1) : "0.0";
      const hiLbl = isSb ? state.sbStats.hi.toFixed(1) : "+1.0";
      ctx.fillText(loLbl, lx + 14, ly + 42);
      ctx.fillText(midLbl, lx + 98, ly + 42);
      ctx.fillText(hiLbl, lx + 184, ly + 42);
    }
  }

  function renderMetaAndAnalytics() {
    const profileLabel = state.isCategorical
      ? "categorical-classified"
      : state.bandsCount >= 3
        ? "optical-multispectral"
        : "single-band";
    $("profileBadge").innerHTML = `<code>${profileLabel}</code>`;
    $("statusText").innerHTML = `<strong>${state.fileName}</strong> loaded (${state.width.toLocaleString()} × ${state.height.toLocaleString()} px, rendered client-side at ${state.readW} × ${state.readH})`;

    const gsdText = state.gsdX ? `${state.gsdX.toFixed(2)} × ${state.gsdY.toFixed(2)} m` : "N/A";
    const totalHa = state.pixelAreaM2 ? ((state.width * state.height * state.pixelAreaM2) / 10000).toLocaleString(undefined, { maximumFractionDigits: 2 }) + " ha" : "N/A";
    const cards = [
      ["Dimensions", `${state.width.toLocaleString()} × ${state.height.toLocaleString()} px`],
      ["Bands / Size", `${state.bandsCount} band(s) · ${formatBytes(state.fileSizeBytes)}`],
      ["CRS", state.crsLabel],
      ["GSD / Area", `${gsdText} · ${totalHa}`],
    ];
    $("metaGrid").innerHTML = cards
      .map(([k, v]) => `<div class="meta-item"><span>${k}</span><strong>${v}</strong></div>`)
      .join("");

    const wrap = $("analyticsWrap");
    if (state.statsRows.length) {
      wrap.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Label</th><th>Color</th>
              <th class="num">Pixels (est.)</th><th class="num">Share %</th>
              <th class="num">Area (ha)</th><th class="num">Area (km²)</th>
            </tr>
          </thead>
          <tbody>
            ${state.statsRows
              .map(
                (r) => `<tr>
                  <td><code>${r.id}</code></td>
                  <td>${r.name}</td>
                  <td><span class="swatch-pill"><span class="swatch-box" style="background:${r.hex}"></span>${r.hex}</span></td>
                  <td class="num">${r.pixels.toLocaleString()}</td>
                  <td class="num">${r.percent.toFixed(2)}%</td>
                  <td class="num">${r.area_ha !== null ? r.area_ha.toLocaleString() : "—"}</td>
                  <td class="num">${r.area_km2 !== null ? r.area_km2.toLocaleString() : "—"}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>`;
    } else if (state.indexStats) {
      const s = state.indexStats;
      wrap.innerHTML = `<div style="font-size:13.5px;"><strong>${s.index}</strong> (Bands ${s.bandA}, ${s.bandB}) · Min: <code>${s.min}</code> · Max: <code>${s.max}</code> · Mean: <code>${s.mean}</code></div>`;
    } else if (state.sbStats) {
      const s = state.sbStats;
      wrap.innerHTML = `<div style="font-size:13.5px;"><strong>Singleband Pseudocolor — Band ${s.band}</strong> (<code>${s.stretch}</code>, ${s.cmap}) · Min: <code>${s.min}</code> · Max: <code>${s.max}</code> · Mean: <code>${s.mean}</code> · σ: <code>${s.std}</code></div>`;
    } else {
      wrap.innerHTML = `<div style="font-size:13.5px;color:#475569;">RGB Composite preview rendered from bands [${$("bandR").value}, ${$("bandG").value}, ${$("bandB").value}] (${$("rgbStretch")?.value || "p2_98"}, γ=${$("rgbGamma")?.value || "1.00"}).</div>`;
    }

    state.lastReport = {
      tool: "LULCkit Browser Studio",
      file_name: state.fileName,
      file_size_bytes: state.fileSizeBytes,
      width: state.width,
      height: state.height,
      bands: state.bandsCount,
      epsg: state.epsg,
      crs: state.crsLabel,
      gsd_m: state.gsdX ? [Number(state.gsdX.toFixed(4)), Number(state.gsdY.toFixed(4))] : null,
      bounds_wgs84: state.boundsWgs84,
      classes: state.statsRows,
      spectral_index: state.indexStats,
      singleband: state.sbStats,
    };
  }

  function escapeXml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function haversineMeters(p1, p2) {
    const R = 6371008.8;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(p2[1] - p1[1]);
    const dLon = toRad(p2[0] - p1[0]);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(p1[1])) * Math.cos(toRad(p2[1])) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  function geodesicAreaM2(pts) {
    if (pts.length < 3) return 0;
    const R = 6371008.8;
    const toRad = (d) => (d * Math.PI) / 180;
    let total = 0;
    for (let i = 0; i < pts.length; i++) {
      const [lon1, lat1] = pts[i];
      const [lon2, lat2] = pts[(i + 1) % pts.length];
      total += toRad(lon2 - lon1) * (2 + Math.sin(toRad(lat1)) + Math.sin(toRad(lat2)));
    }
    return Math.abs((total * R * R) / 2);
  }

  function identifyAtColRow(col, row, lonLat = null) {
    if (!state.rasters || col < 0 || row < 0 || col >= state.readW || row >= state.readH) return;
    const idx = row * state.readW + col;
    const fullC = Math.round((col / state.readW) * state.width);
    const fullR = Math.round((row / state.readH) * state.height);
    const mode = $("modeSelect").value;
    const posStr = lonLat ? `${lonLat[0].toFixed(5)}°, ${lonLat[1].toFixed(5)}° · ` : "";
    let info = "";
    if (mode === "categorical") {
      const val = Math.round(state.rasters[0][idx]);
      const cls = state.classes.find((c) => c.id === val);
      info = cls ? `Class ${val} (${cls.name})` : `Value ${val}`;
    } else if (mode === "singleband") {
      const bi = Math.max(0, Math.min(state.bandsCount - 1, (parseInt($("sbBand").value, 10) || 1) - 1));
      const v = state.rasters[bi][idx];
      info = `Band ${bi + 1} = ${Number.isFinite(v) ? v.toFixed(4) : "nodata"}`;
    } else if (mode === "rgb") {
      const bi = ["bandR", "bandG", "bandB"].map((id) =>
        Math.max(0, Math.min(state.bandsCount - 1, (parseInt($(id).value, 10) || 1) - 1))
      );
      const vals = bi.map((b) => state.rasters[b][idx]);
      info = `RGB=[${vals.map((v) => (Number.isFinite(v) ? Number(v.toFixed(2)) : "na")).join(", ")}]`;
    } else {
      const ia = Math.max(0, Math.min(state.bandsCount - 1, (parseInt($("idxBandA").value, 10) || 1) - 1));
      const ib = Math.max(0, Math.min(state.bandsCount - 1, (parseInt($("idxBandB").value, 10) || 1) - 1));
      const va = state.rasters[ia][idx];
      const vb = state.rasters[ib][idx];
      const val = Math.abs(va + vb) < 1e-9 ? NaN : (va - vb) / (va + vb);
      info = `${$("indexType").value.toUpperCase()} = ${Number.isFinite(val) ? val.toFixed(4) : "nodata"}`;
    }
    $("identifyBar").textContent = `${posStr}px(${fullC}, ${fullR}): ${info}`;
  }

  function updateMeasureOverlay() {
    const pts = state.measurePoints;
    const feats = pts.map((c) => ({ type: "Feature", geometry: { type: "Point", coordinates: c } }));
    if (state.gisTool === "distance" && pts.length >= 2) {
      feats.push({ type: "Feature", geometry: { type: "LineString", coordinates: pts } });
      let dist = 0;
      for (let i = 1; i < pts.length; i++) dist += haversineMeters(pts[i - 1], pts[i]);
      $("identifyBar").textContent = `Distance (${pts.length} pts): ${dist >= 1000 ? `${(dist / 1000).toFixed(3)} km` : `${dist.toFixed(1)} m`}`;
    } else if (state.gisTool === "area" && pts.length >= 3) {
      feats.push({ type: "Feature", geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } });
      const m2 = geodesicAreaM2(pts);
      const ha = m2 / 10000;
      $("identifyBar").textContent = `Area (${pts.length} vertices): ${ha.toFixed(2)} ha (${(m2 / 1e6).toFixed(4)} km²)`;
    } else if (pts.length >= 1) {
      $("identifyBar").textContent = `${state.gisTool === "area" ? "Area" : "Distance"}: click next point (${pts.length} placed)`;
    }
    if (state.map && state.map.getSource("measure-src")) {
      state.map.getSource("measure-src").setData({ type: "FeatureCollection", features: feats });
    }
  }

  function setGisTool(tool) {
    state.gisTool = tool;
    state.measurePoints = [];
    ["toolIdentifyBtn", "toolDistBtn", "toolAreaBtn"].forEach((id, i) => {
      const k = ["identify", "distance", "area"][i];
      $(id).classList.toggle("active", k === tool);
    });
    updateMeasureOverlay();
    if (tool === "identify") {
      $("identifyBar").textContent = "Identify active — click Print Map or Web Map to inspect pixel values";
    } else {
      if ($("webMapView").classList.contains("hidden")) $("tabWebMapBtn").click();
      $("identifyBar").textContent = `Measure ${tool} active — click points on the Interactive Web Map`;
    }
  }

  function syncMapLegend() {
    const leg = $("mapLegend");
    if (!leg) return;
    if (!state.rasters || !state.boundsWgs84) {
      leg.classList.add("hidden");
      return;
    }
    const mode = $("modeSelect").value;
    if (mode === "categorical" && state.classes.length) {
      const items = state.classes.filter((c) => c.visible !== false).slice(0, 10);
      leg.innerHTML =
        `<strong>${escapeXml($("titleInput").value || "Legend")}</strong>` +
        items
          .map(
            (c) =>
              `<div class="map-legend-item"><span class="map-legend-swatch" style="background:${rgbToHex(c.rgb)}"></span><span>${escapeXml(c.name)}</span></div>`
          )
          .join("");
      leg.classList.remove("hidden");
    } else if (mode === "index" && state.indexStats) {
      leg.innerHTML = `<strong>${state.indexStats.index}</strong><div>${state.indexStats.min} to ${state.indexStats.max} (mean ${state.indexStats.mean})</div>`;
      leg.classList.remove("hidden");
    } else if (mode === "singleband" && state.sbStats) {
      leg.innerHTML = `<strong>Band ${state.sbStats.band}</strong><div>${state.sbStats.lo} to ${state.sbStats.hi} (${state.sbStats.cmap})</div>`;
      leg.classList.remove("hidden");
    } else {
      leg.classList.add("hidden");
    }
  }

  function applyRasterLayerToMap() {
    if (!state.map || !state.boundsWgs84 || !state.overlayDataUrl) return;
    const [w, s, e, n] = state.boundsWgs84;
    const coords = [[w, n], [e, n], [e, s], [w, s]];
    const resamp = $("resampleSelect") ? $("resampleSelect").value : "nearest";
    const vis = !$("layerVisCheck") || $("layerVisCheck").checked ? "visible" : "none";
    const opacity = Number($("opacitySlider").value) / 100;

    const existing = state.map.getSource("lulc");
    if (existing) {
      existing.updateImage({ url: state.overlayDataUrl, coordinates: coords });
    } else {
      state.map.addSource("lulc", { type: "image", url: state.overlayDataUrl, coordinates: coords });
      const beforeId = state.map.getLayer("measure-fill") ? "measure-fill" : undefined;
      state.map.addLayer(
        {
          id: "lulc-layer",
          type: "raster",
          source: "lulc",
          layout: { visibility: vis },
          paint: { "raster-opacity": opacity, "raster-resampling": resamp },
        },
        beforeId
      );
    }
    if (state.map.getLayer("lulc-layer")) {
      state.map.setLayoutProperty("lulc-layer", "visibility", vis);
      state.map.setPaintProperty("lulc-layer", "raster-opacity", opacity);
      state.map.setPaintProperty("lulc-layer", "raster-resampling", resamp);
    }
  }

  function syncWebMap() {
    if ($("webMapView").classList.contains("hidden")) return;
    const hasRaster = Boolean(state.boundsWgs84 && state.overlayDataUrl);
    const bkey = $("basemapSelect").value;
    const bm = BASEMAP_TILES[bkey] || BASEMAP_TILES.esri_street;
    const projType = $("projSelect") ? $("projSelect").value : "globe";

    if (!state.map) {
      const center = hasRaster
        ? [(state.boundsWgs84[0] + state.boundsWgs84[2]) / 2, (state.boundsWgs84[1] + state.boundsWgs84[3]) / 2]
        : [90.34, 23.68];
      const zoom = hasRaster ? 6 : 2.3;

      state.map = new maplibregl.Map({
        container: "webMap",
        style: {
          version: 8,
          sources: {
            basemap: { type: "raster", tiles: bm.tiles, tileSize: 256, attribution: bm.attribution },
            "measure-src": { type: "geojson", data: { type: "FeatureCollection", features: [] } },
          },
          layers: [
            { id: "basemap-layer", type: "raster", source: "basemap" },
            {
              id: "measure-fill",
              type: "fill",
              source: "measure-src",
              filter: ["==", "$type", "Polygon"],
              paint: { "fill-color": "#0284c7", "fill-opacity": 0.25 },
            },
            {
              id: "measure-line",
              type: "line",
              source: "measure-src",
              paint: { "line-color": "#0ea5e9", "line-width": 2.5 },
            },
            {
              id: "measure-pts",
              type: "circle",
              source: "measure-src",
              filter: ["==", "$type", "Point"],
              paint: { "circle-radius": 4.5, "circle-color": "#ffffff", "circle-stroke-color": "#0284c7", "circle-stroke-width": 2 },
            },
          ],
        },
        center,
        zoom,
      });

      state.map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
      if (typeof maplibregl.GlobeControl === "function") {
        state.map.addControl(new maplibregl.GlobeControl(), "top-right");
      }
      if (typeof maplibregl.FullscreenControl === "function") {
        state.map.addControl(new maplibregl.FullscreenControl(), "top-right");
      }
      if (typeof maplibregl.GeolocateControl === "function") {
        state.map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), "top-right");
      }
      state.map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

      state.map.on("style.load", () => {
        if (typeof state.map.setProjection === "function") {
          state.map.setProjection({ type: projType });
        }
        if (hasRaster) applyRasterLayerToMap();
      });

      state.map.on("load", () => {
        if (hasRaster) {
          applyRasterLayerToMap();
          const [w, s, e, n] = state.boundsWgs84;
          state.map.fitBounds([[w, s], [e, n]], { padding: 30, duration: 500 });
        }
      });

      state.map.on("mousemove", (ev) => {
        const z = state.map.getZoom().toFixed(2);
        const modeLbl = $("projSelect")?.value === "mercator" ? "2D" : "3D Globe";
        $("mapCoords").textContent = `Lon: ${ev.lngLat.lng.toFixed(5)}°, Lat: ${ev.lngLat.lat.toFixed(5)}° · Z${z} · ${modeLbl}`;
      });

      state.map.on("click", (ev) => {
        const pt = [ev.lngLat.lng, ev.lngLat.lat];
        if (state.gisTool === "distance" || state.gisTool === "area") {
          state.measurePoints.push(pt);
          updateMeasureOverlay();
        } else if (state.boundsWgs84) {
          const [bw, bs, be, bn] = state.boundsWgs84;
          const col = Math.floor(((pt[0] - bw) / (be - bw)) * state.readW);
          const row = Math.floor(((bn - pt[1]) / (bn - bs)) * state.readH);
          identifyAtColRow(col, row, pt);
        } else {
          $("identifyBar").textContent = `World Coordinates: ${pt[0].toFixed(5)}°, ${pt[1].toFixed(5)}° (load a GeoTIFF to identify pixels)`;
        }
      });
    } else {
      state.map.resize();
      if (hasRaster) {
        applyRasterLayerToMap();
        const [w, s, e, n] = state.boundsWgs84;
        state.map.fitBounds([[w, s], [e, n]], { padding: 30, duration: 450 });
      }
    }
    syncMapLegend();
  }

  function renderAll() {
    if (!state.rasters) return;
    const off = buildRasterOffscreen();
    renderPrintCanvas(off);
    renderMetaAndAnalytics();
    syncWebMap();
  }

  // Event bindings
  $("copyInstallBtn").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("installCmd").textContent);
    $("copyInstallBtn").textContent = "Copied!";
    setTimeout(() => ($("copyInstallBtn").textContent = "Copy"), 1500);
  });

  $("dropzone").addEventListener("click", () => $("fileInput").click());
  $("dropzone").addEventListener("dragover", (e) => {
    e.preventDefault();
    $("dropzone").classList.add("drag");
  });
  $("dropzone").addEventListener("dragleave", () => $("dropzone").classList.remove("drag"));
  $("dropzone").addEventListener("drop", (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("drag");
    const f = e.dataTransfer.files[0];
    if (f) loadGeoTIFF(f, f.name, f.size);
  });
  $("fileInput").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) loadGeoTIFF(f, f.name, f.size);
  });

  async function fetchAndLoadSample(urls, fileName, btn, idleLabel, busyLabel) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = busyLabel;
    }
    try {
      startStudioLoader(`Loading ${fileName}`, `Connecting to ${fileName}...`);
      await yieldFrame();
      let resp = null;
      for (const u of urls) {
        const candidate = await fetch(u);
        if (candidate.ok) {
          resp = candidate;
          break;
        }
      }
      if (!resp) throw new Error("Sample GeoTIFF unavailable");

      let buf;
      const totalBytes = Number(resp.headers.get("Content-Length") || 0);
      if (resp.body && typeof resp.body.getReader === "function") {
        const reader = resp.body.getReader();
        const chunks = [];
        let received = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.byteLength;
          const frac = totalBytes > 0 ? Math.min(1, received / totalBytes) : Math.min(0.9, received / 3_200_000);
          setStudioLoaderProgress(
            `Downloading sample COG (${formatBytes(received)})...`,
            6 + frac * 38,
            44,
            1,
            totalBytes > 0 ? `${formatBytes(received)} / ${formatBytes(totalBytes)}` : formatBytes(received)
          );
        }
        const merged = new Uint8Array(received);
        let offset = 0;
        for (const c of chunks) {
          merged.set(c, offset);
          offset += c.byteLength;
        }
        buf = merged.buffer;
      } else {
        buf = await resp.arrayBuffer();
      }
      await loadGeoTIFF(buf, fileName, buf.byteLength, true);
    } catch (err) {
      $("statusText").textContent = `Could not fetch sample GeoTIFF: ${err.message}`;
      abortStudioLoader();
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = idleLabel;
      }
    }
  }

  $("loadSampleBtn").addEventListener("click", () =>
    fetchAndLoadSample(
      ["demo/Bogura_Boro_Map_10m_2026.tif", "../examples/bogura_boro_2026/Bogura_Boro_Map_10m_2026.tif"],
      "Bogura_Boro_Map_10m_2026.tif",
      $("loadSampleBtn"),
      "Load Bogura 2026 (10m COG)",
      "Loading Bogura COG..."
    )
  );

  if ($("loadBangladeshBtn")) {
    $("loadBangladeshBtn").addEventListener("click", () =>
      fetchAndLoadSample(
        ["demo/Bangladesh_LULC_2025.tif", "../examples/bangladesh_lulc_2025/Bangladesh_LULC_2025.tif"],
        "Bangladesh_LULC_2025.tif",
        $("loadBangladeshBtn"),
        "Load Bangladesh 2025 LULC (COG)",
        "Loading Bangladesh COG..."
      )
    );
  }

  $("modeSelect").addEventListener("change", () => {
    updateControlVisibility();
    renderAll();
  });
  $("sbStretch").addEventListener("change", () => {
    updateControlVisibility();
    renderAll();
  });
  $("rgbGamma").addEventListener("input", () => {
    $("rgbGammaVal").textContent = Number($("rgbGamma").value).toFixed(2);
    renderAll();
  });
  $("paletteSelect").addEventListener("change", () => {
    applyPaletteToClasses($("paletteSelect").value);
    renderClassEditorRows();
    renderAll();
  });
  $("invertPalBtn").addEventListener("click", () => {
    if (state.classes.length < 2) return;
    const cols = state.classes.map((c) => c.rgb).reverse();
    state.classes.forEach((c, i) => {
      c.rgb = cols[i];
    });
    renderClassEditorRows();
    renderAll();
  });
  $("randomPalBtn").addEventListener("click", () => {
    state.classes.forEach((c) => {
      if (c.id !== 0) {
        c.rgb = [
          Math.floor(40 + Math.random() * 195),
          Math.floor(40 + Math.random() * 195),
          Math.floor(40 + Math.random() * 195),
        ];
      }
    });
    renderClassEditorRows();
    renderAll();
  });
  $("rgbPresetSelect").addEventListener("change", () => {
    const v = $("rgbPresetSelect").value;
    if (v !== "custom") {
      const [r, g, b] = v.split(",").map(Number);
      $("bandR").value = r;
      $("bandG").value = g;
      $("bandB").value = b;
      renderAll();
    }
  });

  [
    "titleInput", "sbBand", "sbStretch", "sbMin", "sbMax", "sbCmap", "sbInvertCheck",
    "bandR", "bandG", "bandB", "rgbStretch", "indexType", "idxBandA", "idxBandB", "idxCmap",
    "idxInvertCheck", "pageSizeSelect", "orientationSelect", "arrowStyleSelect",
    "scalebarStyleSelect", "gridCheck",
  ].forEach((id) => {
    $(id).addEventListener("input", renderAll);
    $(id).addEventListener("change", renderAll);
  });

  canvas.addEventListener("click", (ev) => {
    if (!state.lastPrintBox || !state.rasters) return;
    const rect = canvas.getBoundingClientRect();
    const cx = ((ev.clientX - rect.left) * canvas.width) / rect.width;
    const cy = ((ev.clientY - rect.top) * canvas.height) / rect.height;
    const { imgX, imgY, drawW, drawH } = state.lastPrintBox;
    if (cx < imgX || cx > imgX + drawW || cy < imgY || cy > imgY + drawH) return;
    const fx = (cx - imgX) / drawW;
    const fy = (cy - imgY) / drawH;
    const col = Math.floor(fx * state.readW);
    const row = Math.floor(fy * state.readH);
    let lonLat = null;
    if (state.boundsWgs84) {
      const [w, s, e, n] = state.boundsWgs84;
      lonLat = [w + fx * (e - w), n - fy * (n - s)];
    }
    identifyAtColRow(col, row, lonLat);
  });

  $("toolIdentifyBtn").addEventListener("click", () => setGisTool("identify"));
  $("toolDistBtn").addEventListener("click", () => setGisTool("distance"));
  $("toolAreaBtn").addEventListener("click", () => setGisTool("area"));
  $("toolClearMeasureBtn").addEventListener("click", () => {
    state.measurePoints = [];
    updateMeasureOverlay();
    $("identifyBar").textContent = "Measurements cleared";
  });

  $("tabPrintBtn").addEventListener("click", () => {
    $("tabPrintBtn").classList.add("active");
    $("tabWebMapBtn").classList.remove("active");
    $("printView").classList.remove("hidden");
    $("webMapView").classList.add("hidden");
  });
  $("tabWebMapBtn").addEventListener("click", () => {
    $("tabWebMapBtn").classList.add("active");
    $("tabPrintBtn").classList.remove("active");
    $("webMapView").classList.remove("hidden");
    $("printView").classList.add("hidden");
    syncWebMap();
  });

  $("projSelect")?.addEventListener("change", () => {
    if (state.map && typeof state.map.setProjection === "function") {
      state.map.setProjection({ type: $("projSelect").value });
    }
  });
  $("basemapSelect").addEventListener("change", () => {
    if (!state.map) return;
    const bm = BASEMAP_TILES[$("basemapSelect").value] || BASEMAP_TILES.esri_street;
    state.map.getSource("basemap").setTiles(bm.tiles);
  });
  $("layerVisCheck")?.addEventListener("change", () => {
    if (state.map && state.map.getLayer("lulc-layer")) {
      state.map.setLayoutProperty("lulc-layer", "visibility", $("layerVisCheck").checked ? "visible" : "none");
    }
  });
  $("resampleSelect").addEventListener("change", () => {
    if (state.map && state.map.getLayer("lulc-layer")) {
      state.map.setPaintProperty("lulc-layer", "raster-resampling", $("resampleSelect").value);
    }
  });
  $("zoomWorldBtn")?.addEventListener("click", () => {
    if (state.map) {
      state.map.flyTo({ center: [20, 20], zoom: 1.6, pitch: 0, bearing: 0, duration: 900 });
    }
  });
  $("zoomLayerBtn").addEventListener("click", () => {
    if (state.map && state.boundsWgs84) {
      const [w, s, e, n] = state.boundsWgs84;
      state.map.fitBounds([[w, s], [e, n]], { padding: 30, duration: 500 });
    }
  });
  $("mapSearchForm")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const q = ($("mapSearchInput")?.value || "").trim();
    if (!q || !state.map) return;
    const coordMatch = q.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
    if (coordMatch) {
      const a = Number(coordMatch[1]);
      const b = Number(coordMatch[2]);
      const [lat, lon] = Math.abs(a) > 90 && Math.abs(b) <= 90 ? [b, a] : [a, b];
      if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        state.map.flyTo({ center: [lon, lat], zoom: 9, duration: 900 });
        $("identifyBar").textContent = `Flew to ${lon.toFixed(4)}°, ${lat.toFixed(4)}°`;
        return;
      }
    }
    try {
      $("identifyBar").textContent = `Searching "${q}"...`;
      const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`);
      const rows = await res.json();
      if (!rows.length) {
        $("identifyBar").textContent = `No place found for "${q}"`;
        return;
      }
      const hit = rows[0];
      const lon = Number(hit.lon);
      const lat = Number(hit.lat);
      state.map.flyTo({ center: [lon, lat], zoom: 8, duration: 1000 });
      $("identifyBar").textContent = `Found: ${hit.display_name.split(",").slice(0, 2).join(",")} (${lon.toFixed(3)}°, ${lat.toFixed(3)}°)`;
    } catch (err) {
      $("identifyBar").textContent = `Search failed: ${err.message}`;
    }
  });
  $("opacitySlider").addEventListener("input", () => {
    const op = Number($("opacitySlider").value);
    $("opacityVal").textContent = `${op}%`;
    if (state.map && state.map.getLayer("lulc-layer")) {
      state.map.setPaintProperty("lulc-layer", "raster-opacity", op / 100);
    }
  });

  function downloadBlob(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  }

  $("downloadPngBtn").addEventListener("click", () => {
    const stem = (state.fileName || "lulckit").replace(/\.(tiff?|tif)$/i, "");
    canvas.toBlob((blob) => blob && downloadBlob(blob, `${stem}_preview.png`), "image/png");
    window.dispatchEvent(new CustomEvent("lulckit:export", { detail: { format: "png" } }));
  });

  $("downloadCsvBtn").addEventListener("click", () => {
    const stem = (state.fileName || "lulckit").replace(/\.(tiff?|tif)$/i, "");
    let csv = "";
    if (state.statsRows.length) {
      csv = "class_id,class_name,hex_color,pixels,percent,area_m2,area_ha,area_km2\n" +
        state.statsRows
          .map((r) => `${r.id},"${r.name.replace(/"/g, '""')}",${r.hex},${r.pixels},${r.percent},${r.area_m2 ?? ""},${r.area_ha ?? ""},${r.area_km2 ?? ""}`)
          .join("\n");
    } else if (state.indexStats) {
      const s = state.indexStats;
      csv = `index,band_a,band_b,valid_pixels,min,max,mean\n${s.index},${s.bandA},${s.bandB},${s.valid_pixels},${s.min},${s.max},${s.mean}\n`;
    } else if (state.sbStats) {
      const s = state.sbStats;
      csv = `band,stretch,cmap,min,max,mean,std\n${s.band},${s.stretch},${s.cmap},${s.min},${s.max},${s.mean},${s.std}\n`;
    } else {
      csv = `file_name,width,height,bands\n"${state.fileName}",${state.width},${state.height},${state.bandsCount}\n`;
    }
    downloadBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), `${stem}_summary.csv`);
    window.dispatchEvent(new CustomEvent("lulckit:export", { detail: { format: "csv" } }));
  });

  $("downloadJsonBtn").addEventListener("click", () => {
    const stem = (state.fileName || "lulckit").replace(/\.(tiff?|tif)$/i, "");
    downloadBlob(
      new Blob([JSON.stringify(state.lastReport, null, 2)], { type: "application/json" }),
      `${stem}_report.json`
    );
    window.dispatchEvent(new CustomEvent("lulckit:export", { detail: { format: "json" } }));
  });

  $("downloadQmlBtn").addEventListener("click", () => {
    const stem = (state.fileName || "lulckit").replace(/\.(tiff?|tif)$/i, "");
    let qml = "";
    if ($("modeSelect").value === "categorical" && state.classes.length) {
      const rows = state.classes
        .map((c) => `        <paletteEntry value="${c.id}" color="${rgbToHex(c.rgb).toLowerCase()}" alpha="${c.visible !== false ? 255 : 0}" label="${escapeXml(c.name)}"/>`)
        .join("\n");
      qml = `<!DOCTYPE qgis PUBLIC "http://mrcc.com/qgis.dtd" "SYSTEM">\n<qgis version="3.34.0" styleCategories="Symbology">\n  <pipe>\n    <rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1">\n      <colorPalette>\n${rows}\n      </colorPalette>\n    </rasterrenderer>\n  </pipe>\n</qgis>\n`;
    } else {
      const isSb = $("modeSelect").value === "singleband" && state.sbStats;
      const lo = isSb ? state.sbStats.lo : -1;
      const hi = isSb ? state.sbStats.hi : 1;
      const cmap = isSb ? state.sbStats.cmap : $("idxCmap").value;
      const inv = isSb ? state.sbStats.invert : $("idxInvertCheck").checked;
      const band = isSb ? state.sbStats.band : 1;
      const items = [0, 0.25, 0.5, 0.75, 1]
        .map((t) => {
          const val = (lo + (hi - lo) * t).toFixed(4);
          return `          <item value="${val}" color="${rgbToHex(colormapLookup(cmap, t, inv)).toLowerCase()}" alpha="255" label="${val}"/>`;
        })
        .join("\n");
      qml = `<!DOCTYPE qgis PUBLIC "http://mrcc.com/qgis.dtd" "SYSTEM">\n<qgis version="3.34.0" styleCategories="Symbology">\n  <pipe>\n    <rasterrenderer type="singlebandpseudocolor" band="${band}" classificationMin="${lo}" classificationMax="${hi}" opacity="1">\n      <rastershader>\n        <colorrampshader colorRampType="INTERPOLATED">\n${items}\n        </colorrampshader>\n      </rastershader>\n    </rasterrenderer>\n  </pipe>\n</qgis>\n`;
    }
    downloadBlob(new Blob([qml], { type: "application/xml;charset=utf-8" }), `${stem}.qml`);
  });

  $("downloadSldBtn").addEventListener("click", () => {
    const stem = (state.fileName || "lulckit").replace(/\.(tiff?|tif)$/i, "");
    const safeStem = escapeXml(stem);
    let entries = "";
    let cmType = "values";
    if ($("modeSelect").value === "categorical" && state.classes.length) {
      entries = state.classes
        .map((c) => `            <ColorMapEntry color="${rgbToHex(c.rgb)}" quantity="${c.id}" label="${escapeXml(c.name)}" opacity="${c.visible !== false ? "1.0" : "0.0"}"/>`)
        .join("\n");
    } else {
      cmType = "ramp";
      const isSb = $("modeSelect").value === "singleband" && state.sbStats;
      const lo = isSb ? state.sbStats.lo : -1;
      const hi = isSb ? state.sbStats.hi : 1;
      const cmap = isSb ? state.sbStats.cmap : $("idxCmap").value;
      const inv = isSb ? state.sbStats.invert : $("idxInvertCheck").checked;
      entries = [0, 0.25, 0.5, 0.75, 1]
        .map((t) => {
          const val = (lo + (hi - lo) * t).toFixed(4);
          return `            <ColorMapEntry color="${rgbToHex(colormapLookup(cmap, t, inv))}" quantity="${val}" label="${val}" opacity="1.0"/>`;
        })
        .join("\n");
    }
    const sld = `<?xml version="1.0" encoding="UTF-8"?>\n<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld">\n  <NamedLayer>\n    <Name>${safeStem}</Name>\n    <UserStyle>\n      <Title>${safeStem}</Title>\n      <FeatureTypeStyle>\n        <Rule>\n          <RasterSymbolizer>\n            <ColorMap type="${cmType}">\n${entries}\n            </ColorMap>\n          </RasterSymbolizer>\n        </Rule>\n      </FeatureTypeStyle>\n    </UserStyle>\n  </NamedLayer>\n</StyledLayerDescriptor>\n`;
    downloadBlob(new Blob([sld], { type: "application/xml;charset=utf-8" }), `${stem}.sld`);
  });

  // --- Website UI Polish: Theme Toggle, Multi-Tab Install, Interactive Terminal, Compare Slider, GitHub Stars ---
  const themeBtn = $("themeToggle");
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    if (themeBtn) themeBtn.textContent = t === "dark" ? "Light" : "Dark";
    try { localStorage.setItem("lulckit-theme", t); } catch (_) {}
  }
  let savedTheme = "light";
  try { savedTheme = localStorage.getItem("lulckit-theme") || "light"; } catch (_) {}
  applyTheme(savedTheme);
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
      applyTheme(cur === "dark" ? "light" : "dark");
    });
  }

  document.querySelectorAll(".install-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".install-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $("installCmd").textContent = btn.dataset.cmd || "";
    });
  });

  const TERM_SCENARIOS = {
    inspect: {
      cmd: "lulc inspect examples/bogura_boro_2026/Bogura_Boro_Map_10m_2026.tif",
      html: `<span class="t-prompt">$</span> <span class="t-cmd">lulc inspect examples/bogura_boro_2026/Bogura_Boro_Map_10m_2026.tif</span>
<span class="t-dim">───────────── TIFF Profile: Bogura_Boro_Map_10m_2026.tif ─────────────</span>
  Size               2.56 MB (GTiff, LZW, COG overviews=[2,4,8,16,32])
  Dimensions         <span class="t-cyan">7,937 × 6,470 px</span> (51,352,390 px), 1 band (uint8)
  CRS / GSD          <span class="t-cyan">EPSG:32645 (WGS 84 / UTM zone 45N)</span> · 10.000 m/px
  Valid Area         <span class="t-green">513,523.9000 ha</span> (5,135.239 km²)
  WGS84 Centroid     [89.3576176, 24.830086]
  Detected Profile   <span class="t-green">categorical-classified</span> → model: <span class="t-amber">categorical</span>`,
    },
    map: {
      cmd: 'lulc map Bogura_Boro_Map_10m_2026.tif -o ./out/bogura --title "Boro Area Mapping for Bogura - 2026" --palette arcgis-crop --page-size a4 --html',
      html: `<span class="t-prompt">$</span> <span class="t-cmd">lulc map Bogura_Boro_Map_10m_2026.tif -o ./out/bogura --palette arcgis-crop --page-size a4 --html</span>
Running categorical (56 tiles) ━━━━━━━━━━━━━━━━━━━━━━ 56/56 0:00:01
  <span class="t-green">✔ Styled GeoTIFF</span>     out/bogura/Bogura_Boro_Map_10m_2026_lulc.tif (palette + overviews)
  <span class="t-green">✔ A4 Print Map</span>       out/bogura/Bogura_Boro_Map_10m_2026_preview.png (300 DPI)
  <span class="t-green">✔ Interactive HTML</span>   out/bogura/Bogura_Boro_Map_10m_2026_map.html (MapLibre GL JS)

  ID   Class Name                    Share     Area (ha)
  <span class="t-dim">0</span>    Non Boro                      79.42%    407,858.54 ha
  <span class="t-green">1</span>    Early/Normal Boro Rice         1.69%      8,661.46 ha
  <span class="t-amber">2</span>    Late-Transplanted Boro Rice   18.89%     97,003.90 ha`,
    },
    bands: {
      cmd: "lulc bands sentinel2.tif --index ndvi -o ./out/ndvi.tif --preview-out ./out/ndvi.png",
      html: `<span class="t-prompt">$</span> <span class="t-cmd">lulc bands sentinel2.tif --index ndvi -o ./out/ndvi.tif --preview-out ./out/ndvi.png</span>
<span class="t-dim">Streaming 1024×1024 windows · (NIR - Red) / (NIR + Red)</span>
  <span class="t-green">Computed NDVI</span> → ./out/ndvi.tif (float32, DEFLATE)
  Valid pixels: 100.0% | min=-0.412 | max=0.894 | mean=0.386
  <span class="t-cyan">Rendered A4 Print Map</span> → ./out/ndvi.png (RdYlGn colorbar + UTM grid)`,
    },
    clip: {
      cmd: "lulc clip Bogura_Boro_Map_10m_2026.tif bogura_district.geojson -o bogura_clip.tif",
      html: `<span class="t-prompt">$</span> <span class="t-cmd">lulc clip Bogura_Boro_Map_10m_2026.tif bogura_district.geojson -o bogura_clip.tif</span>
  Input Size     7,937 × 6,470 px (EPSG:32645)
  Clipped Size   5,214 × 4,890 px (1 band, GDAL ColorTable preserved)
  <span class="t-green">✔ Saved clipped GeoTIFF</span> → bogura_clip.tif`,
    },
  };

  let activeTermKey = "inspect";
  function renderTerminal(key) {
    activeTermKey = key in TERM_SCENARIOS ? key : "inspect";
    const out = $("termOutput");
    if (out) out.innerHTML = TERM_SCENARIOS[activeTermKey].html;
  }
  renderTerminal("inspect");

  document.querySelectorAll(".term-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".term-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderTerminal(btn.dataset.term);
    });
  });

  const copyTermBtn = $("copyTermBtn");
  if (copyTermBtn) {
    copyTermBtn.addEventListener("click", async () => {
      const cmd = TERM_SCENARIOS[activeTermKey]?.cmd || "";
      if (navigator.clipboard) await navigator.clipboard.writeText(cmd);
      copyTermBtn.textContent = "Copied!";
      setTimeout(() => (copyTermBtn.textContent = "Copy cmd"), 1500);
    });
  }

  const SHOWCASES = {
    bogura: {
      heading: "Bogura District Boro Rice Mapping (10m COG)",
      sub: "Scrub between the unstyled 1-band input GeoTIFF (<code>7,937 × 6,470 px</code>, <code>EPSG:32645</code>, <code>513,523.90 ha</code>) and the automated LULCkit print map &amp; MapLibre viewer.",
      dlHref: "demo/Bogura_Boro_Map_10m_2026.tif",
      dlText: "Download Sample GeoTIFF (2.56 MB)",
      after: "demo/Bogura_Boro_Map_10m_2026_preview.png",
      afterFallback: "../examples/bogura_boro_2026/outputs/Bogura_Boro_Map_10m_2026_preview.png",
      before: "demo/Bogura_Boro_Map_10m_2026_input_preview.png",
      beforeFallback: "../examples/bogura_boro_2026/Bogura_Boro_Map_10m_2026_input_preview.png",
      mapHtml: "demo/Bogura_Boro_Map_10m_2026_map.html",
    },
    bangladesh: {
      heading: "Bangladesh National Land Use / Land Cover — 2025 (COG)",
      sub: "Scrub between the 9-class input GeoTIFF (<code>4,333 × 5,481 px</code>, <code>EPSG:4326</code>, <code>31,171,629 ha</code>) and the LULCkit Dynamic World print map &amp; MapLibre viewer.",
      dlHref: "demo/Bangladesh_LULC_2025.tif",
      dlText: "Download Bangladesh COG (3.00 MB)",
      after: "demo/Bangladesh_LULC_2025_preview.png",
      afterFallback: "../examples/bangladesh_lulc_2025/outputs/Bangladesh_LULC_2025_preview.png",
      before: "demo/Bangladesh_LULC_2025_input_preview.png",
      beforeFallback: "../examples/bangladesh_lulc_2025/Bangladesh_LULC_2025_input_preview.png",
      mapHtml: "demo/Bangladesh_LULC_2025_map.html",
    },
  };

  function selectShowcase(key) {
    const s = SHOWCASES[key] || SHOWCASES.bogura;
    if ($("exTabBogura")) $("exTabBogura").classList.toggle("active", key === "bogura");
    if ($("exTabBangladesh")) $("exTabBangladesh").classList.toggle("active", key === "bangladesh");
    if ($("exampleHeading")) $("exampleHeading").textContent = s.heading;
    if ($("exampleSub")) $("exampleSub").innerHTML = s.sub;
    if ($("exampleDownloadBtn")) {
      $("exampleDownloadBtn").href = s.dlHref;
      $("exampleDownloadBtn").textContent = s.dlText;
    }
    if ($("compareAfterImg")) {
      $("compareAfterImg").onerror = function () {
        this.onerror = null;
        this.src = s.afterFallback;
      };
      $("compareAfterImg").src = s.after;
    }
    if ($("compareBeforeImg")) {
      $("compareBeforeImg").onerror = function () {
        this.onerror = null;
        this.src = s.beforeFallback;
      };
      $("compareBeforeImg").src = s.before;
    }
    if ($("exampleMapLink")) $("exampleMapLink").href = s.mapHtml;
    if ($("exampleMapIframe")) $("exampleMapIframe").src = s.mapHtml;
  }

  if ($("exTabBogura")) $("exTabBogura").addEventListener("click", () => selectShowcase("bogura"));
  if ($("exTabBangladesh")) $("exTabBangladesh").addEventListener("click", () => selectShowcase("bangladesh"));

  const compareRange = $("compareRange");
  const compareBefore = $("compareBefore");
  const compareDivider = $("compareDivider");
  if (compareRange && compareBefore && compareDivider) {
    const updateSplit = () => {
      const pct = Number(compareRange.value);
      compareBefore.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
      compareDivider.style.left = `${pct}%`;
    };
    compareRange.addEventListener("input", updateSplit);
    updateSplit();
  }

  const promoVideo = $("promoVideo");
  const videoPlayerBox = $("videoPlayerBox");
  const videoPlayOverlay = $("videoPlayOverlay");
  const chapterBtns = Array.from(document.querySelectorAll(".chapter-btn"));
  if (promoVideo && videoPlayerBox) {
    // Keep clean poster + custom play pill unobstructed until playback begins
    promoVideo.controls = false;

    const enableControls = () => {
      promoVideo.controls = true;
    };
    const syncOverlay = () => {
      const playing = !promoVideo.paused && !promoVideo.ended;
      videoPlayerBox.classList.toggle("is-playing", playing);
      if (playing) enableControls();
    };
    const syncActiveChapter = () => {
      if (!chapterBtns.length) return;
      const now = promoVideo.currentTime || 0;
      let activeBtn = chapterBtns[0];
      for (const btn of chapterBtns) {
        if (Number(btn.dataset.seek || 0) <= now + 0.25) activeBtn = btn;
      }
      chapterBtns.forEach((b) => b.classList.toggle("active", b === activeBtn));
    };

    if (videoPlayOverlay) {
      videoPlayOverlay.addEventListener("click", () => {
        enableControls();
        promoVideo.play().catch(() => {});
      });
    }
    promoVideo.addEventListener("play", syncOverlay);
    promoVideo.addEventListener("ended", () => {
      videoPlayerBox.classList.remove("is-playing");
      promoVideo.controls = false;
    });
    promoVideo.addEventListener("timeupdate", syncActiveChapter);

    chapterBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        enableControls();
        const target = Number(btn.dataset.seek || 0);
        promoVideo.currentTime = target;
        chapterBtns.forEach((b) => b.classList.toggle("active", b === btn));
        promoVideo.play().catch(() => {});
      });
    });
    syncActiveChapter();
  }
})();
