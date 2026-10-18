"""Where it is grown: regional crop production in Europe (methodology, "Where it is grown").

Eurostat apro_cpshr (harvested production at EU standard humidity, by NUTS region) over the FBS
window, matched to GISCO NUTS 2024 (else 2021) boundaries. Writes

    data/processed/regions.parquet     iso3, group, code, name, level, kt, share, density, coverage
    web/public/data/regions.json       per country and food: regions, shares, kt, t per km²
    web/public/data/regions.geojson    the shown regions' outlines (code, name, iso3)
"""

from __future__ import annotations

import json
import logging
import math

import numpy as np
import pandas as pd

from . import config

log = logging.getLogger(__name__)

SRC = config.RAW / "eurostat" / "apro_cpshr.tsv.gz"
NUTS = {y: config.RAW / "gisco" / f"NUTS_RG_20M_{y}_4326.geojson" for y in (2024, 2021)}
OUT = "regions.parquet"
STRUCPRO = "HPRD_HUMD_EU_THS_T"
CROPS = {"cereals": ["C0000"], "potatoes_roots": ["R1000"], "sugar": ["R2000"], "pulses": ["P0000"],
         "oilseeds": ["I1110", "I1120", "I1130"]}
MIN_COVERAGE = 0.9
EARTH_KM = 6371.0088


def read(years: tuple[int, int]) -> pd.DataFrame:
    """Long rows: geo, crop, year, kt (missing values dropped)."""
    d = pd.read_csv(SRC, sep="\t", dtype=str)
    key = d.columns[0]
    d[["freq", "crop", "strucpro", "geo"]] = d[key].str.split(",", expand=True)
    d.columns = [c.strip() for c in d.columns]
    wanted = {c for cs in CROPS.values() for c in cs}
    d = d[(d["strucpro"] == STRUCPRO) & d["crop"].isin(wanted)]
    ys = [str(y) for y in range(years[0], years[1] + 1)]
    long = d.melt(id_vars=["geo", "crop"], value_vars=ys, var_name="year", value_name="raw")
    # values like "123.4 p" carry a flag after the number; ":" is missing
    long["kt"] = pd.to_numeric(long["raw"].str.strip().str.split(" ").str[0], errors="coerce")
    return long.dropna(subset=["kt"]).drop(columns="raw").assign(year=lambda x: x["year"].astype(int))


def ring_area_km2(ring: list) -> float:
    """Area of a lon/lat ring on the sphere (km², absolute)."""
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        a += math.radians(x2 - x1) * (2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
    return abs(a) * EARTH_KM ** 2 / 2


def geometry_area_km2(geom: dict) -> float:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return sum(ring_area_km2(p[0]) - sum(ring_area_km2(h) for h in p[1:]) for p in polys)


def boundaries() -> dict[str, dict]:
    """NUTS code -> feature, 2024 boundaries first, 2021 for codes 2024 does not have."""
    out: dict[str, dict] = {}
    for y in (2024, 2021):
        for f in json.loads(NUTS[y].read_text(encoding="utf-8"))["features"]:
            out.setdefault(f["properties"]["NUTS_ID"], f)
    return out


def eurostat_iso3() -> dict[str, str]:
    from .harmonise import load_countries

    c = load_countries()
    c = c[c["eurostat"].notna()]
    return dict(zip(c["eurostat"], c["iso3"], strict=True))


def compute(years: tuple[int, int]) -> pd.DataFrame:
    long = read(years)
    feats = boundaries()
    iso = eurostat_iso3()
    long["ctry"] = long["geo"].str[:2]
    long["level"] = long["geo"].str.len() - 2
    rows = []
    for group, crops in CROPS.items():
        g = long[long["crop"].isin(crops)]
        # a region's food = the sum of the crops it reports, per year; then the window mean
        g = g.groupby(["ctry", "geo", "level", "year"], as_index=False)["kt"].sum()
        g = g.groupby(["ctry", "geo", "level"], as_index=False)["kt"].mean()
        for ctry, sub in g.groupby("ctry"):
            if ctry not in iso:
                continue
            national = sub.loc[sub["level"] == 0, "kt"].sum()
            for level in (2, 1):
                regs = sub[(sub["level"] == level) & sub["geo"].isin(feats) & ~sub["geo"].str.endswith("Z")]
                if len(regs) > 1:
                    break
            else:
                continue
            total = regs["kt"].sum()
            if not (national > 0 and total > 0) or total / national < MIN_COVERAGE:
                continue
            for r in regs.itertuples():
                f = feats[r.geo]
                area = geometry_area_km2(f["geometry"])
                rows.append({"iso3": iso[ctry], "group": group, "code": r.geo,
                             "name": f["properties"].get("NAME_LATN") or r.geo, "level": level,
                             "kt": r.kt, "share": 100 * r.kt / total, "density": 1000 * r.kt / area,
                             "coverage": total / national})
    out = pd.DataFrame(rows)
    # the EU: all its members' shown regions, shares of their sum
    eu = out[out["iso3"].isin(config.EU27)].copy()
    eu["share"] = 100 * eu["kt"] / eu.groupby("group")["kt"].transform("sum")
    eu = eu.assign(iso3="EU27", coverage=np.nan)
    return pd.concat([out, eu], ignore_index=True)


def nice(x: float) -> float:
    """Two significant digits."""
    if x <= 0:
        return 0.0
    p = 10 ** (math.floor(math.log10(x)) - 1)
    return round(x / p) * p


def breaks(r: pd.DataFrame) -> dict[str, list[float]]:
    """Per food: the 20/40/60/80th percentiles of the shown regions' densities above 0 (not the EU
    rows, which repeat the members'); regions without any are drawn as none."""
    base = r[(r["iso3"] != "EU27") & (r["density"] > 0)]
    return {g: [nice(float(np.percentile(sub["density"], q))) for q in (20, 40, 60, 80)]
            for g, sub in base.groupby("group")}


def run() -> None:
    from .trade import fbs_window

    if not SRC.exists() or not all(p.exists() for p in NUTS.values()):
        log.warning("no regional crop data; run `atlas download --source eurostat boundaries`")
        (config.PROCESSED / OUT).unlink(missing_ok=True)
        return
    r = compute(fbs_window())
    r.to_parquet(config.PROCESSED / OUT, index=False)
    log.info("wrote %s (%d countries, %d regions)", OUT, r["iso3"].nunique(), r["code"].nunique())


def export() -> None:
    """regions.json and regions.geojson for the web."""
    src = config.PROCESSED / OUT
    dj, dg = config.WEB_DATA / "regions.json", config.WEB_DATA / "regions.geojson"
    if not src.exists():
        dj.unlink(missing_ok=True)
        dg.unlink(missing_ok=True)
        return
    r = pd.read_parquet(src)
    countries: dict = {}
    for (iso3, group), sub in r.groupby(["iso3", "group"]):
        sub = sub.sort_values("kt", ascending=False)
        countries.setdefault(iso3, {})[group] = {
            "coverage": None if iso3 == "EU27" else round(float(sub["coverage"].iloc[0]) * 100),
            "regions": [[c, round(k), round(s, 1), round(d)] for c, k, s, d in
                        zip(sub["code"], sub["kt"], sub["share"], sub["density"], strict=True)],
        }
    from .trade import fbs_window

    y0, y1 = fbs_window()
    out = {"meta": {"source": "eurostat_apro_cpshr", "years": f"{y0}-{y1}",
                    "columns": ["code", "kt", "share", "t_per_km2"], "breaks": breaks(r)},
           "names": dict(zip(r["code"], r["name"], strict=False)),
           "countries": countries}
    dj.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    feats = boundaries()
    used = r.drop_duplicates("code").set_index("code")

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 3), round(c[1], 3)]

    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": code,
         "properties": {"code": code, "iso3": used.at[code, "iso3"] if used.at[code, "iso3"] != "EU27" else None},
         "geometry": {"type": feats[code]["geometry"]["type"], "coordinates": rnd(feats[code]["geometry"]["coordinates"])}}
        for code in used.index]}
    # a region's country (EU rows repeat members' regions)
    member = r[r["iso3"] != "EU27"].drop_duplicates("code").set_index("code")["iso3"]
    for f in fc["features"]:
        f["properties"]["iso3"] = member.get(f["id"])
    dg.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%.0f KB) and %s (%.0f KB)", dj.name, dj.stat().st_size / 1024, dg.name,
             dg.stat().st_size / 1024)
