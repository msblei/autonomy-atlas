"""Fields: where each food's crops grow, at 2 km (methodology, "Fields: the crop map at 2 km").

JRC's crop proportions on land from EUCROPMAP 2018 (one 2 km raster per crop class, EPSG:3035),
summed per food, reprojected to Web Mercator and drawn in five shades as one transparent PNG per
food, for MapLibre's image source:

    web/public/data/cropmap_<group>.png
    web/public/data/cropmap.json   {meta, groups: {group: {file, coordinates, classes}}}
"""

from __future__ import annotations

import json
import logging

import numpy as np

from . import config

log = logging.getLogger(__name__)

RAW = config.RAW / "eucropmap"
BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/DRLL/CropDiversity/CropProportionLand/"
FILE = "crop_percent_on_land_{c}_2km.tif"
GROUPS = {
    "cereals": [211, 212, 213, 214, 215, 216, 217, 218, 219],
    "potatoes_roots": [221],
    "sugar": [222],
    "oilseeds": [232, 233],
    "pulses": [240],
}
# Shades by share of the land (lower bounds); under the first is transparent.
STEPS = [0.02, 0.10, 0.20, 0.35, 0.50]
COLORS = [(232, 239, 228), (188, 214, 184), (134, 180, 138), (79, 138, 97), (42, 94, 64)]
PIXEL_M = 2000.0  # Web Mercator metres per pixel (equator scale)


# Checked against Eurostat (methodology, "Fields", "Checked against the statistics"): per country
# and food, the map's area (share x land of every cell in the country) against Eurostat's crop area
# for the map's year (apro_cpshr, AR_THS_HA). Outside AREA_BAND the country is left out of that
# food's image: EUCROPMAP 2018 finds 7% of Romania's potato area, 6% of Spain's sugar beet.
YEAR = 2018
EUROSTAT_CROPS = {"cereals": ["C0000", "G3000"],  # the map's maize includes maize cut green
                  "potatoes_roots": ["R1000"], "sugar": ["R2000"], "oilseeds": ["I1110", "I1130"],
                  "pulses": ["P0000"]}
AREA_BAND = (0.5, 2.0)
COVERS = set(config.EU27) | {"GBR"}


def inputs() -> list:
    return [RAW / FILE.format(c=c) for cs in GROUPS.values() for c in cs]


def country_cells(transform, crs, shape) -> tuple[np.ndarray, dict[int, str]]:
    """Each 2 km cell's country (index into the returned {index: iso3}; 0 = none), from the GISCO
    countries file, for the countries the map covers (COVERS: EUCROPMAP 2018 maps the EU and the
    United Kingdom)."""
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom

    src = config.RAW / "gisco" / f"CNTR_RG_{config.GISCO_NUTS_SCALE}_{config.GISCO_COUNTRIES_YEAR}_4326.geojson"
    want = COVERS
    shapes, names = [], {}
    for f in json.loads(src.read_text(encoding="utf-8"))["features"]:
        iso3 = f.get("properties", {}).get("ISO3_CODE")
        if iso3 in want:
            k = len(names) + 1
            names[k] = iso3
            shapes.append((transform_geom("EPSG:4326", crs, f["geometry"]), k))
    return rasterize(shapes, out_shape=shape, transform=transform, fill=0, dtype="int32"), names


def area_check(group: str, v: np.ndarray, transform, cells: np.ndarray, names: dict[int, str]) -> dict:
    """iso3 -> {map_kha, eurostat_kha, ratio} for countries with Eurostat's area of the food."""
    import pandas as pd

    from .harmonise import load_countries

    code = load_countries().dropna(subset=["eurostat"]).set_index("iso3")["eurostat"]
    d = pd.read_parquet(config.INTERIM / "eurostat_apro_cpshr.parquet")
    d = d[(d["strucpro"] == "AR_THS_HA") & (d["year"] == YEAR) & d["crops"].isin(EUROSTAT_CROPS[group])]
    ref = d.groupby("geo")["value"].sum(min_count=1)
    kha = abs(transform.a * transform.e) / 1e7  # a whole cell, in thousand hectares
    by = np.bincount(cells.ravel(), weights=np.nan_to_num(v).ravel(), minlength=len(names) + 1) * kha
    out = {}
    for k, iso3 in names.items():
        e = ref.get(code.get(iso3))
        if e is None or pd.isna(e) or e <= 0:
            continue
        out[iso3] = {"map_kha": round(float(by[k]), 1), "eurostat_kha": round(float(e), 1),
                     "ratio": round(float(by[k] / e), 2)}
    return out


def share(group: str):
    """The food's share of land per 2 km cell (EPSG:3035): array, transform, crs."""
    import rasterio

    total = None
    for c in GROUPS[group]:
        with rasterio.open(RAW / FILE.format(c=c)) as r:
            a = r.read(1).astype("float64")
            nod = r.nodata
            transform, crs = r.transform, r.crs
        a = np.where(a == nod, np.nan, a) if nod is not None else a
        total = a if total is None else np.where(np.isnan(total), a, total + np.nan_to_num(a))
    return np.clip(total, 0, 1), transform, crs


def to_mercator(a, transform, crs):
    """Reproject to EPSG:3857 at PIXEL_M, nearest cell (no invented in-between values at field
    edges); returns array, transform."""
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    h, w = a.shape
    left, top = transform.c, transform.f
    right, bottom = left + w * transform.a, top + h * transform.e
    dst_t, dw, dh = calculate_default_transform(crs, "EPSG:3857", w, h, left, bottom, right, top,
                                                resolution=PIXEL_M)
    out = np.full((dh, dw), np.nan)
    reproject(a, out, src_transform=transform, src_crs=crs, dst_transform=dst_t, dst_crs="EPSG:3857",
              resampling=Resampling.nearest, src_nodata=np.nan, dst_nodata=np.nan)
    return out, dst_t


def shade(v: np.ndarray) -> np.ndarray:
    """Share of land -> shade index 0-4, -1 = transparent."""
    idx = np.full(v.shape, -1, dtype=np.int8)
    for i, lo in enumerate(STEPS):
        idx[np.nan_to_num(v, nan=-1) >= lo] = i
    return idx


def corners(transform, w: int, h: int) -> list:
    """Image corners as [lon, lat]: top-left, top-right, bottom-right, bottom-left."""
    from rasterio.warp import transform as tr

    xs = [transform.c, transform.c + w * transform.a, transform.c + w * transform.a, transform.c]
    ys = [transform.f, transform.f, transform.f + h * transform.e, transform.f + h * transform.e]
    lon, lat = tr("EPSG:3857", "EPSG:4326", xs, ys)
    return [[round(x, 5), round(y, 5)] for x, y in zip(lon, lat, strict=True)]


def write_png(idx: np.ndarray, path) -> None:
    import warnings

    import rasterio
    from rasterio.errors import NotGeoreferencedWarning

    h, w = idx.shape
    rgba = np.zeros((4, h, w), dtype=np.uint8)
    for i, (r, g, b) in enumerate(COLORS):
        m = idx == i
        rgba[0][m], rgba[1][m], rgba[2][m], rgba[3][m] = r, g, b, 235
    with warnings.catch_warnings():  # a plain picture: its corners are in cropmap.json
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path, "w", driver="PNG", width=w, height=h, count=4, dtype="uint8") as dst:
            dst.write(rgba)


def run() -> None:
    dest = config.WEB_DATA / "cropmap.json"
    if not all(p.exists() for p in inputs()):
        log.warning("no crop map rasters; run `atlas download --source cropmap`")
        dest.unlink(missing_ok=True)
        return
    groups = {}
    cells = names = None
    for group, classes in GROUPS.items():
        v, t, crs = share(group)
        if cells is None:
            cells, names = country_cells(t, crs, v.shape)
        check = area_check(group, v, t, cells, names)
        out_of = sorted(i for i, c in check.items() if not AREA_BAND[0] <= c["ratio"] <= AREA_BAND[1])
        k_out = [k for k, i in names.items() if i in out_of]
        v = np.where(np.isin(cells, k_out), np.nan, v)
        m, mt = to_mercator(v, t, crs)
        idx = shade(m)
        rows, cols = np.nonzero(idx >= 0)
        r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
        idx = idx[r0:r1, c0:c1]
        ct = mt * mt.translation(c0, r0)
        name = f"cropmap_{group}.png"
        write_png(idx, config.WEB_DATA / name)
        groups[group] = {"file": name, "coordinates": corners(ct, idx.shape[1], idx.shape[0]),
                         "classes": classes, "size": [int(idx.shape[1]), int(idx.shape[0])],
                         # countries whose map area is outside AREA_BAND of Eurostat's: not drawn
                         "left_out": {i: check[i] for i in out_of}}
        log.info("wrote %s (%d x %d px, %.0f KB)", name, idx.shape[1], idx.shape[0],
                 (config.WEB_DATA / name).stat().st_size / 1024)
        (config.WEB_DATA / (name + ".aux.xml")).unlink(missing_ok=True)
    out = {"meta": {"source": "jrc_eucropmap_2018", "year": YEAR, "steps": STEPS, "area_band": AREA_BAND,
                    "check": "eurostat_apro_cpshr",
                    "colors": [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in COLORS], "pixel_m": PIXEL_M},
           "groups": groups}
    dest.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
