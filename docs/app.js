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
  };

  const PAGE_SIZES = {
    a4: [11.69, 8.27],
    a5: [8.27, 5.83],
    a3: [16.54, 11.69],
    letter: [11.0, 8.5],
    square: [10.0, 10.0],
  };

  const BASEMAP_TILES = {
    positron: {
      tiles: ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    },
    osm: {
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      attribution: "&copy; OpenStreetMap contributors",
    },
    esri: {
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Tiles &copy; Esri",
    },
  };

  const BOGURA_LABELS = {
    0: "Non Boro",
    1: "Early/Normal Boro Rice",
    2: "Late-Transplanted Boro Rice",
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
    const isBogura = (state.fileName || "").toLowerCase().includes("bogura_boro");
    state.classes.forEach((cls) => {
      if (cls.id === 0) {
        cls.rgb = [255, 255, 255];
      } else {
        cls.rgb = [...pal[cidx % pal.length]];
        cidx++;
      }
      if (!cls.userEdited && isBogura && BOGURA_LABELS[cls.id]) {
        cls.name = BOGURA_LABELS[cls.id];
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
      row.innerHTML = `
        <code>${cls.id}</code>
        <input type="color" value="${hex}" data-id="${cls.id}" />
        <input type="text" value="${cls.name}" data-id="${cls.id}" />
      `;
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

  async function loadGeoTIFF(source, fileName, fileSizeBytes) {
    $("statusText").textContent = `Reading ${fileName}...`;
    const tiff = source instanceof Blob ? await GeoTIFF.fromBlob(source) : await GeoTIFF.fromArrayBuffer(source);
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

    const sf = image.getSampleFormat ? image.getSampleFormat() : [1];
    const isFloat = sf && (sf[0] === 3);

    const rasters = await image.readRasters({
      width: readW,
      height: readH,
      resampleMethod: bandsCount === 1 && !isFloat ? "nearest" : "bilinear",
    });

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
          userEdited: false,
        }));
        applyPaletteToClasses($("paletteSelect").value);
      }
    }

    // Configure smart mode defaults
    const stem = fileName.replace(/\.(tiff?|tif)$/i, "");
    $("titleInput").value = fileName.toLowerCase().includes("bogura_boro")
      ? "Boro Area Mapping for Bogura - 2026"
      : stem;
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
      $("modeSelect").value = "index";
    }

    renderClassEditorRows();
    updateControlVisibility();
    renderAll();
    $("downloadPngBtn").disabled = false;
    $("downloadCsvBtn").disabled = false;
    $("downloadJsonBtn").disabled = false;
  }

  function updateControlVisibility() {
    const mode = $("modeSelect").value;
    $("categoricalControls").classList.toggle("hidden", mode !== "categorical");
    $("rgbControls").classList.toggle("hidden", mode !== "rgb");
    $("indexControls").classList.toggle("hidden", mode !== "index");
  }

  function colormapLookup(name, t) {
    const u = Math.max(0, Math.min(1, t));
    if (name === "Blues") {
      return [Math.round(247 - 239 * u), Math.round(251 - 203 * u), Math.round(255 - 148 * u)];
    }
    if (name === "RdBu") {
      if (u < 0.5) {
        const k = u * 2;
        return [Math.round(178 + 69 * k), Math.round(24 + 223 * k), Math.round(43 + 204 * k)];
      }
      const k = (u - 0.5) * 2;
      return [Math.round(247 - 214 * k), Math.round(247 - 145 * k), Math.round(247 - 75 * k)];
    }
    if (name === "Viridis") {
      return [
        Math.round(68 + 185 * Math.pow(u, 1.5)),
        Math.round(1 + 230 * Math.sin(u * Math.PI * 0.5)),
        Math.round(84 + 100 * (1 - Math.abs(2 * u - 1)) - 47 * u),
      ];
    }
    // RdYlGn default
    if (u < 0.5) {
      const k = u * 2;
      return [Math.round(165 + 90 * k), Math.round(0 + 255 * k), Math.round(38 + 153 * k)];
    }
    const k = (u - 0.5) * 2;
    return [Math.round(255 - 255 * k), Math.round(255 - 151 * k), Math.round(191 - 136 * k)];
  }

  function computePercentileRange(arr, nodata) {
    const step = Math.max(1, Math.floor(arr.length / 80000));
    const sample = [];
    for (let i = 0; i < arr.length; i += step) {
      const v = arr[i];
      if ((nodata === null || v !== nodata) && Number.isFinite(v)) sample.push(v);
    }
    if (!sample.length) return [0, 255];
    sample.sort((a, b) => a - b);
    const lo = sample[Math.floor(0.02 * (sample.length - 1))];
    const hi = sample[Math.floor(0.98 * (sample.length - 1))];
    return hi > lo ? [lo, hi] : [lo, lo + 1];
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

    if (mode === "categorical" && state.classes.length) {
      const band = state.rasters[0];
      const lut = new Map();
      const counts = new Map();
      state.classes.forEach((c) => {
        lut.set(c.id, c.rgb);
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
          px[p] = rgb[0];
          px[p + 1] = rgb[1];
          px[p + 2] = rgb[2];
          px[p + 3] = 255;
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
    } else if (mode === "rgb") {
      const bi = ["bandR", "bandG", "bandB"].map((id) =>
        Math.max(0, Math.min(state.bandsCount - 1, (parseInt($(id).value, 10) || 1) - 1))
      );
      const bands = bi.map((idx) => state.rasters[idx]);
      const ranges = bands.map((b) => computePercentileRange(b, state.nodata));
      for (let i = 0; i < rw * rh; i++) {
        const p = i * 4;
        let masked = false;
        for (let c = 0; c < 3; c++) {
          const v = bands[c][i];
          if ((state.nodata !== null && v === state.nodata) || !Number.isFinite(v)) {
            masked = true;
            break;
          }
          const [lo, hi] = ranges[c];
          px[p + c] = Math.max(0, Math.min(255, Math.round(((v - lo) / (hi - lo)) * 255)));
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
        const rgb = colormapLookup(cmap, (val + 1) / 2);
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
    if (mode === "categorical" && state.classes.length) {
      const shown = state.classes.slice(0, 10);
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
    } else if (mode === "index") {
      const lx = padL + 18;
      const ly = padT + boxH - 70;
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fillRect(lx, ly, 230, 52);
      ctx.strokeStyle = "#64748b";
      ctx.strokeRect(lx, ly, 230, 52);
      ctx.fillStyle = "#0f172a";
      ctx.font = "bold 12.5px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText($("indexType").value.toUpperCase(), lx + 10, ly + 8);
      const cmap = $("idxCmap").value;
      for (let x = 0; x < 200; x++) {
        const rgb = colormapLookup(cmap, x / 199);
        ctx.fillStyle = rgbToHex(rgb);
        ctx.fillRect(lx + 14 + x, ly + 28, 2, 12);
      }
      ctx.font = "11px monospace";
      ctx.fillStyle = "#0f172a";
      ctx.fillText("-1.0", lx + 14, ly + 42);
      ctx.fillText("0.0", lx + 104, ly + 42);
      ctx.fillText("+1.0", lx + 190, ly + 42);
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
    } else {
      wrap.innerHTML = `<div style="font-size:13.5px;color:#475569;">RGB Composite preview rendered from bands [${$("bandR").value}, ${$("bandG").value}, ${$("bandB").value}] with 2%–98% linear stretch.</div>`;
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
    };
  }

  function syncWebMap() {
    if ($("webMapView").classList.contains("hidden")) return;
    if (!state.boundsWgs84 || !state.overlayDataUrl) {
      $("mapCoords").textContent = "Raster is not georeferenced with known CRS/EPSG";
      return;
    }
    const [w, s, e, n] = state.boundsWgs84;
    const coords = [[w, n], [e, n], [e, s], [w, s]];
    const bkey = $("basemapSelect").value;
    const bm = BASEMAP_TILES[bkey] || BASEMAP_TILES.positron;

    if (!state.map) {
      state.map = new maplibregl.Map({
        container: "webMap",
        style: {
          version: 8,
          sources: {
            basemap: { type: "raster", tiles: bm.tiles, tileSize: 256, attribution: bm.attribution },
            lulc: { type: "image", url: state.overlayDataUrl, coordinates: coords },
          },
          layers: [
            { id: "basemap-layer", type: "raster", source: "basemap" },
            {
              id: "lulc-layer",
              type: "raster",
              source: "lulc",
              paint: { "raster-opacity": Number($("opacitySlider").value) / 100, "raster-resampling": "nearest" },
            },
          ],
        },
        center: [(w + e) / 2, (s + n) / 2],
        zoom: 9,
      });
      state.map.addControl(new maplibregl.NavigationControl(), "top-right");
      state.map.on("load", () => state.map.fitBounds([[w, s], [e, n]], { padding: 30, duration: 0 }));
      state.map.on("mousemove", (ev) => {
        $("mapCoords").textContent = `Lon: ${ev.lngLat.lng.toFixed(5)}°, Lat: ${ev.lngLat.lat.toFixed(5)}°`;
      });
    } else {
      const src = state.map.getSource("lulc");
      if (src) src.updateImage({ url: state.overlayDataUrl, coordinates: coords });
      state.map.resize();
      state.map.fitBounds([[w, s], [e, n]], { padding: 30, duration: 300 });
    }
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

  $("loadSampleBtn").addEventListener("click", async () => {
    const btn = $("loadSampleBtn");
    btn.disabled = true;
    btn.textContent = "Loading Bogura COG...";
    try {
      let resp = await fetch("demo/Bogura_Boro_Map_10m_2026.tif");
      if (!resp.ok) resp = await fetch("../examples/bogura_boro_2026/Bogura_Boro_Map_10m_2026.tif");
      const buf = await resp.arrayBuffer();
      await loadGeoTIFF(buf, "Bogura_Boro_Map_10m_2026.tif", buf.byteLength);
    } catch (err) {
      $("statusText").textContent = `Could not fetch sample GeoTIFF: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Load Bogura 2026 Sample (10m COG)";
    }
  });

  $("modeSelect").addEventListener("change", () => {
    updateControlVisibility();
    renderAll();
  });
  $("paletteSelect").addEventListener("change", () => {
    applyPaletteToClasses($("paletteSelect").value);
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
    "titleInput", "bandR", "bandG", "bandB", "indexType", "idxBandA", "idxBandB", "idxCmap",
    "pageSizeSelect", "orientationSelect", "arrowStyleSelect", "scalebarStyleSelect", "gridCheck",
  ].forEach((id) => {
    $(id).addEventListener("input", renderAll);
    $(id).addEventListener("change", renderAll);
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

  $("basemapSelect").addEventListener("change", () => {
    if (!state.map) return;
    const bm = BASEMAP_TILES[$("basemapSelect").value] || BASEMAP_TILES.positron;
    state.map.getSource("basemap").setTiles(bm.tiles);
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
    } else {
      csv = `file_name,width,height,bands\n"${state.fileName}",${state.width},${state.height},${state.bandsCount}\n`;
    }
    downloadBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), `${stem}_summary.csv`);
  });

  $("downloadJsonBtn").addEventListener("click", () => {
    const stem = (state.fileName || "lulckit").replace(/\.(tiff?|tif)$/i, "");
    downloadBlob(
      new Blob([JSON.stringify(state.lastReport, null, 2)], { type: "application/json" }),
      `${stem}_report.json`
    );
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

  const ghStars = $("ghStars");
  if (ghStars && typeof AbortController !== "undefined") {
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 3500);
    fetch("https://api.github.com/repos/madeshchkma/LULCkit", { signal: ac.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && typeof data.stargazers_count === "number") {
          ghStars.textContent = `GitHub ★ ${data.stargazers_count}`;
        }
      })
      .catch(() => {});
  }
})();
