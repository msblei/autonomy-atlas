"""Independent re-derivation of every number in web/public/data/{ssr,items,trade}.json.

Written from docs/methodology.md, CLAUDE.md and the mapping files only; it never imports or reads
pipeline/ code. See verify/README.md for scope and for every spec ambiguity and the reading chosen.

Run:  .venv/bin/python -I verify/recompute.py
Out:  verify/recompute_report.json (exit 1 on any mismatch);
      verify/.cache/ holds the streamed trade-matrix extract and the uncapped mismatch list.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pcsv
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tm_cache  # noqa: E402  (verify/tm_cache.py: streams the trade matrix out of its zip)

T0 = time.time()
ROOT = HERE.parent
MAP = ROOT / "pipeline/mappings"
FBS_ZIP = ROOT / "data/raw/faostat/FoodBalanceSheets_E_All_Data_(Normalized).zip"
TM_ZIP = tm_cache.TM_ZIP
JRC_CSV = ROOT / "data/raw/jrc/bal/Dataset_EU_estimated_agricultural_balance_sheets.csv"
USDA_ZIP = ROOT / "data/raw/usda/psd_alldata_csv.zip"
COMEXT_GZ = ROOT / "data/raw/comext/DS-045409_food.csv.gz"
EUMOFA_XLSX = ROOT / "data/raw/eumofa/conversion_factors_cn8.xlsx"
OUT_DIR = ROOT / "web/public/data"
REPORT = HERE / "recompute_report.json"
FULL_MISMATCHES = HERE / ".cache" / "mismatches_full.json"

BAL = ["P", "M", "X", "S", "D"]
USES = ["food", "feed", "seed", "losses", "processing", "other_uses", "tourist", "residuals"]
PERCAP = ["kcal", "protein"]
ELEMENTS = {5511: "P", 5611: "M", 5911: "X", 5072: "S", 5301: "D", 5142: "food", 5521: "feed",
            5527: "seed", 5123: "losses", 5131: "processing", 5154: "other_uses",
            5171: "tourist", 5170: "residuals", 664: "kcal", 674: "protein"}
COMP_KEY = {"production": "P", "imports": "M", "exports": "X", "supply": "D",
            "stock_variation": "S"}
JRC_FOODS = {"tomatoes": "Tomatoes and products", "olive oil": "Olive Oil", "wine": "Wine"}

# Primary reading of the spec, and alternative readings used only to *explain* mismatches.
PRIMARY = {"avg": "country_years_zero", "eu_percap": "eu_population",
           "jrc_negative_production": "clip0", "jrc_no_fao_supply": "nonpositive"}
ALTERNATIVES = {  # earlier pipeline behaviours / other readings, used only to tag mismatches
    "avg=item_years_skipna": {**PRIMARY, "avg": "item_years_skipna"},
    "eu_percap=reporting_members_population": {**PRIMARY, "eu_percap": "reporting_population"},
    "jrc_negative_production=as_published": {**PRIMARY, "jrc_negative_production": "as_published"},
    "jrc_no_fao_supply=missing_or_zero_only": {**PRIMARY, "jrc_no_fao_supply": "missing_or_zero"},
}


def log(msg):
    print(f"[{time.time()-T0:6.1f}s] {msg}", file=sys.stderr)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def nz(v) -> float:
    return 0.0 if isnan(v) else v


# --------------------------------------------------------------------------------------------
# Mappings (input data, allowed)
# --------------------------------------------------------------------------------------------
def read_csv_comments(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        lines = [l for l in fh if not l.startswith("#")]
    return list(csv.DictReader(lines))


WORLD = {r["m49"].zfill(3): r["iso3"] for r in read_csv_comments(MAP / "world.csv")}
TRADE_ONLY = {r["m49"].zfill(3): r["iso3"] for r in read_csv_comments(MAP / "trade_only.csv")}
ALL_ISO = {**WORLD, **TRADE_ONLY}
EUROPE = yaml.safe_load(open(MAP / "countries.yaml"))
EU = sorted(c["iso3"] for c in EUROPE if c["group"] == "EU27")
EUROSTAT = {c["eurostat"]: c["iso3"] for c in EUROPE}
REGION = {c["iso3"]: c["group"] for c in EUROPE}
PRODUCTS = yaml.safe_load(open(MAP / "products.yaml"))["groups"]
TRADE_ITEMS = {int(r["item_code"]): r["group"] for r in read_csv_comments(MAP / "trade_items.csv")
               if r["group"].strip()}
# Methodology, "Withheld by review": groups withheld after a human review (iso3, group) -> note
REVIEWED = {(r["iso3"], r["group"]): r["note"] for r in read_csv_comments(MAP / "withheld_by_review.csv")}
# Methodology, "Trade partners": partner lists in the FBS basis where trade_items.csv gives a factor
# (dairy in milk equivalent); the EU-bloc shares stay in product weight.
TO_PRIMARY = {int(r["item_code"]): float(r["to_primary"]) for r in read_csv_comments(MAP / "trade_items.csv")
              if r.get("to_primary")}
assert len(EU) == 27


# --------------------------------------------------------------------------------------------
# Raw inputs
# --------------------------------------------------------------------------------------------
def load_fbs():
    z = zipfile.ZipFile(FBS_ZIP)
    name = next(n for n in z.namelist() if "All_Data" in n)
    cols = ["Area Code (M49)", "Item Code", "Item", "Element Code", "Year", "Value"]
    types = {"Area Code (M49)": pa.string(), "Item Code": pa.int32(), "Element Code": pa.int32(),
             "Year": pa.int32(), "Value": pa.float64(), "Item": pa.string()}
    with z.open(name) as fh:
        t = pcsv.read_csv(fh, convert_options=pcsv.ConvertOptions(include_columns=cols,
                                                                    column_types=types))
    d = t.to_pandas()
    d["m49"] = d["Area Code (M49)"].str.lstrip("'").str.zfill(3)
    d["iso3"] = d["m49"].map(WORLD)
    d = d[d["iso3"].notna()]
    pop = (d[(d["Item Code"] == 2501) & (d["Element Code"] == 511)]
           .groupby(["iso3", "Year"])["Value"].sum())
    # leaf items: code < 2900, Population excluded (methodology "All food")
    leaf = d[(d["Item Code"] < 2900) & (d["Item Code"] != 2501)]
    names = leaf[["Item Code", "Item"]].drop_duplicates().set_index("Item Code")["Item"]
    leaf = leaf[leaf["Element Code"].isin(ELEMENTS)]
    leaf = leaf.assign(el=leaf["Element Code"].map(ELEMENTS))
    wide = leaf.pivot_table(index=["iso3", "Item Code", "Year"], columns="el", values="Value",
                            aggfunc="sum")
    for c in BAL + USES + PERCAP:
        if c not in wide:
            wide[c] = np.nan
    wide.index.names = ["iso3", "item", "year"]
    return wide[BAL + USES + PERCAP], pop.rename_axis(["iso3", "year"]), names


DAIRY_PRODUCTS = ["DRINKING MILK", "ACIDIFIED MILK", "CREAM FOR DIRECT CONSUMPTION", "BUTTERMILK",
                  "TOTAL BUTTER", "TOTAL CHEESE", "SKIMMED MILK POWDER", "WHOLE MILK POWDER",
                  "WHEY POWDER"]


def load_jrc():
    """-> ({(iso3|'EU27', food, year): {P, M, X, D}} in kt (milk eq. for dairy, hl*0.1 for
    wine), {(iso3, year): (raw milk production, raw milk apparent use)})."""
    d = pd.read_csv(JRC_CSV, encoding="utf-8-sig", low_memory=False)
    d["iso3"] = d["Country (NUTS Code)"].map(lambda c: "EU27" if c == "EU" else EUROSTAT.get(c))
    d = d[d["iso3"].notna()]
    out, rawmilk = {}, {}
    for (iso, yr), g in d.groupby(["iso3", "Year"]):
        g = g.set_index("Commodity")
        if "RAW MILK" in g.index:  # for jrc_published_ssr (not in the spec, see README)
            rp, ru = g.at["RAW MILK", "Production (THOUSAND TONNES)"], g.at["RAW MILK", "Apparent use (THOUSAND TONNES)"]
            if not isnan(rp) and not isnan(ru):
                rawmilk[(iso, int(yr))] = (rp, ru)
        is_eu = iso == "EU27"

        def flow(com, fl, unit, scale=1.0):
            if com not in g.index:
                return math.nan
            ex = g.at[com, f"{fl} (Extra-EU) ({unit})"]
            if is_eu:  # EU27 = extra-EU trade only
                return ex * scale
            return (ex + g.at[com, f"{fl} (Intra-EU) ({unit})"]) * scale  # members: intra + extra

        rec = {}
        if "TOMATOES" in g.index:
            P = g.at["TOMATOES", "Production (THOUSAND TONNES)"]
            M, X = flow("TOMATOES", "Imports", "THOUSAND TONNES"), flow("TOMATOES", "Exports", "THOUSAND TONNES")
            rec["tomatoes"] = (P, M, X, P + M - X)  # supply = P + M - X
        if "TOTAL OLIVE OIL" in g.index:
            c = "TOTAL OLIVE OIL"
            rec["olive oil"] = (g.at[c, "Production (THOUSAND TONNES)"],
                                flow(c, "Imports", "THOUSAND TONNES"),
                                flow(c, "Exports", "THOUSAND TONNES"),
                                g.at[c, "Apparent use (THOUSAND TONNES)"])  # supply = apparent use
        if "WINE" in g.index:
            hl = "THOUSAND HECTOLITRES"
            rec["wine"] = (g.at["WINE", f"Production ({hl})"] * 0.1,
                           flow("WINE", "Imports", hl, 0.1), flow("WINE", "Exports", hl, 0.1),
                           g.at["WINE", f"Apparent use ({hl})"] * 0.1)
        if "RAW MILK" in g.index and all(p in g.index for p in DAIRY_PRODUCTS):
            me = "THOUSAND TONNES (MILK EQ.)"
            P = g.at["RAW MILK", f"Production ({me})"]
            M = sum(flow(p, "Imports", me) for p in DAIRY_PRODUCTS)
            X = sum(flow(p, "Exports", me) for p in DAIRY_PRODUCTS)
            rec["dairy"] = (P, M, X, P + M - X)
        for food, (P, M, X, D) in rec.items():
            if any(isnan(v) for v in (P, M, X, D)):
                continue
            # A year with apparent use <= 0 does not count as covered (see README: the
            # methodology's Portugal example implies it). Negative production is kept as published.
            if D <= 0:
                continue
            out[(iso, food, int(yr))] = {"P": P, "M": M, "X": X, "D": D}
    return out, rawmilk


# --------------------------------------------------------------------------------------------
# Methodology, "Comext": EU members' fish trade in live weight (EUMOFA factor per CN8 and year)
# --------------------------------------------------------------------------------------------
FISH_HEADINGS = ("0301", "0302", "0303", "0304", "0305", "0306", "0307", "0308", "0309", "1604", "1605")
COMEXT_ISO = {r["comext"]: r["iso3"] for r in read_csv_comments(MAP / "comext_partners.csv")}
INTRA_UNNAMED = {"QR", "QV", "QY"}


_COMEXT = None


def comext_raw():
    global _COMEXT
    if _COMEXT is None:
        _COMEXT = pd.read_csv(COMEXT_GZ, dtype=str, compression="gzip", keep_default_na=False)  # NA = Namibia
    return _COMEXT


def eumofa_codes():
    """CN8 codes with an EUMOFA factor above 0 in some year."""
    cf = pd.read_excel(EUMOFA_XLSX, sheet_name="List of CF", dtype=str)
    return set(cf.loc[pd.to_numeric(cf["CF"], errors="coerce") > 0, "CN-8"].str.replace(" ", "", regex=False))


def comext_value(years):
    """Methodology "Value basis": out[c][group][flow] = {partner: EUR a year}, members (named
    partners, no self-trade) and EU27 (members to non-members); "all" = every group but fish."""
    hs = {(int(r["version"]), r["hs"]): r for r in read_csv_comments(MAP / "hs_items.csv") if r["group"]}
    cn8 = {r["cn8"]: r["group"] for r in read_csv_comments(MAP / "cn8_items.csv")}
    fish = eumofa_codes()
    d = comext_raw()
    d = d[(d["indicators"] == "VALUE_IN_EUROS") & d["partner"].isin(COMEXT_ISO)]
    d = d[d["TIME_PERIOD"].astype(int).isin(years)]
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
    for rep_, par, prod, flow, year, val in zip(d["reporter"], d["partner"], d["product"], d["flow"],
                                                d["TIME_PERIOD"], d["OBS_VALUE"]):
        if not val:
            continue
        y = int(year)
        if len(prod) == 8:
            if prod.startswith(FISH_HEADINGS):
                g = "fish" if prod in fish else None
            else:
                g = cn8.get(prod)
        else:
            r = hs.get((2017 if y <= 2021 else 2022, prod))
            g = r["group"] if r and r["group"] != "fish" and r["to_primary"] != "cn8" else None
        c, p = COMEXT_ISO[rep_], COMEXT_ISO[par]
        if g is None or c == p:
            continue
        f = {"1": "imports", "2": "exports"}[flow]
        v = float(val) / len(years)
        out[c][g][f][p] += v
        if g != "fish":
            out[c]["all"][f][p] += v
        if c in EU and p not in EU:
            out["EU27"][g][f][p] += v
            if g != "fish":
                out["EU27"]["all"][f][p] += v
    return out


def load_comext_fish():
    """-> [c, partner, named, flow, year, t] with t in tonnes live weight; c = ISO3 of the member,
    partner = ISO3 or Comext's own code (named = it is a country)."""
    cf = pd.read_excel(EUMOFA_XLSX, sheet_name="List of CF", dtype=str)[["Year", "CN-8", "CF"]]
    cf.columns = ["year", "cn8", "cf"]
    cf["cn8"] = cf["cn8"].str.replace(" ", "", regex=False)
    cf["year"] = cf["year"].astype(int)
    cf["cf"] = pd.to_numeric(cf["cf"], errors="coerce")
    cf = cf[cf["cf"] > 0]
    by_code = {c: dict(zip(g["year"], g["cf"])) for c, g in cf.groupby("cn8")}

    def factor(code, year):
        ys = by_code.get(code)
        if not ys:
            return math.nan
        if year in ys:
            return ys[year]
        return ys[min(ys, key=lambda y: (abs(y - year), y))]

    d = comext_raw()
    d = d[(d["partner"].str.len() == 2) & (d["product"].str.len() == 8)  # no WORLD, EXT_EU, ...
          & d["product"].str.startswith(FISH_HEADINGS)
          & (d["indicators"] == "QUANTITY_IN_100KG")]
    d = d.assign(year=d["TIME_PERIOD"].astype(int), q=pd.to_numeric(d["OBS_VALUE"]))
    fac = {k: factor(*k) for k in set(zip(d["product"], d["year"]))}
    d["t"] = d["q"] / 10 * [fac[k] for k in zip(d["product"], d["year"])]
    d = d[d["t"].notna()]
    d["c"] = d["reporter"].map(COMEXT_ISO)
    d["named"] = d["partner"].isin(COMEXT_ISO)
    d["partner"] = d["partner"].map(COMEXT_ISO).fillna(d["partner"])
    d["flow"] = d["flow"].map({"1": "imports", "2": "exports"})
    d = d[d["c"] != d["partner"]]
    # methodology "BACI": the EU's own mix per HS 2017 code and year, all partners
    conv = {(int(r["version"]), r["hs"]): r["hs2017"] for r in read_csv_comments(MAP / "hs_items.csv")}
    m = d[d["q"] > 0].assign(hs=[conv.get((2017 if y <= 2021 else 2022, p[:6]))
                                  for y, p in zip(d.loc[d["q"] > 0, "year"], d.loc[d["q"] > 0, "product"])])
    m = m[m["hs"].notna()].assign(w=lambda x: x["q"] / 10)
    sums = m.groupby(["hs", "year"])[["t", "w"]].sum()
    global FISH_MIX
    FISH_MIX = (sums["t"] / sums["w"]).to_dict()
    return d.groupby(["c", "partner", "named", "flow", "year"], as_index=False)["t"].sum()


FISH_MIX = {}


# --------------------------------------------------------------------------------------------
# Methodology, "Seasons": crop calendars per country, from the raw grids
# --------------------------------------------------------------------------------------------
SEASON_CROPS = {  # GGCMI code: (land-use variable or "wheat", FBS item, group, label)
    "wwh": ("wheat", "Wheat and products", "cereals", "Wheat"),
    "swh": ("wheat", "Wheat and products", "cereals", "Wheat"),
    "mai": ("maize", "Maize and products", "cereals", "Maize"),
    "ri1": ("rice", "Rice and products", "cereals", "Rice"),
    "bar": ("temperate_cereals", "Barley and products", "cereals", "Barley"),
    "rye": ("temperate_cereals", "Rye and products", "cereals", "Rye"),
    "mil": ("tropical_cereals", "Millet and products", "cereals", "Millet"),
    "sor": ("tropical_cereals", "Sorghum and products", "cereals", "Sorghum"),
    "pot": ("temperate_roots", "Potatoes and products", "potatoes_roots", "Potatoes"),
    "sgb": ("temperate_roots", "Sugar beet", "sugar", "Sugar beet"),
    "pea": ("pulses", "Peas", "pulses", "Peas"),
    "bea": ("pulses", "Beans", "pulses", "Beans"),
    "soy": ("oil_crops_soybean", "Soyabeans", "oilseeds", "Soybeans"),
    "sun": ("oil_crops_sunflower", "Sunflower seed", "oilseeds", "Sunflower"),
    "rap": ("oil_crops_rapeseed", "Rape and Mustardseed", "oilseeds", "Rapeseed"),
    "nut": ("oil_crops_groundnut", "Groundnuts", "oilseeds", "Groundnuts"),
}


def season_calendars():
    """{(iso3, crop label): (weight, sown[12], growing[12], harvest[12]) in %}; wheat = both kinds."""
    import h5py

    def grid(path, var, sl=None):
        with h5py.File(path) as f:
            a = np.array(f[var][sl] if sl is not None else f[var][...], dtype="float64")
        a[a > 1e19] = np.nan
        return a

    raw = ROOT / "data/raw"
    with h5py.File(raw / "isimip/countrymasks-fractional_30arcmin.nc") as f:
        names = [k[2:] for k in f if k.startswith("m_") and k != "m_world"]
        M = np.stack([np.nan_to_num(np.array(f["m_" + k][...], dtype="float64")) for k in names])
        lat = np.array(f["lat"][...])
    M[M > 1e19] = 0
    M = np.concatenate([M, M[[i for i, k in enumerate(names) if k in EU]].sum(axis=0)[None]])
    names = names + ["EU27"]
    area = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, 720))
    starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]

    def month(d):
        out = np.full(d.shape, -1)
        for k, s0 in enumerate(starts):
            out[(d >= s0) & ~np.isnan(d)] = k
        return out

    acc = {}
    for crop, (wvar, _, _, label) in SEASON_CROPS.items():
        for ws, long in (("rf", "rainfed"), ("ir", "irrigated")):
            cal = raw / f"ggcmi/{crop}_{ws}_ggcmi_crop_calendar_phase3_v1.01.nc4"
            p, h = month(grid(cal, "planting_day")), month(grid(cal, "maturity_day"))
            if wvar == "wheat":
                w = np.nan_to_num(grid(raw / "ggcmi/winter_and_spring_wheat_areas_v1_180627.nc4", f"{crop}_{ws}_area"))
            else:
                lu = raw / "isimip/landuse-15crops_histsoc_annual_1901_2021.nc"
                w = np.nan_to_num(grid(lu, f"{wvar}_{long}", np.s_[-3:, :, :])).mean(axis=0) * area
            w = np.where((p >= 0) & (h >= 0), w, 0.0)
            for k in range(12):
                inside = np.where(h >= p, (k >= p) & (k <= h), (k >= p) | (k <= h))
                for name, grid_ in (("s", (p == k) * w), ("h", (h == k) * w), ("g", inside * w)):
                    v = M.reshape(len(names), -1) @ grid_.ravel()
                    for i, iso in enumerate(names):
                        acc.setdefault((iso, label), {}).setdefault(name, np.zeros(12))[k] += v[i]
            tot = M.reshape(len(names), -1) @ w.ravel()
            for i, iso in enumerate(names):
                a = acc.setdefault((iso, label), {})
                a["w"] = a.get("w", 0.0) + tot[i]
    out = {}
    for key, a in acc.items():
        if a.get("w", 0) > 0:
            out[key] = (a["w"], *(100 * a[n] / a["w"] for n in ("s", "g", "h")))
    return out


# --------------------------------------------------------------------------------------------
# Methodology, "Where it is grown": regional production from Eurostat apro_cpshr
# --------------------------------------------------------------------------------------------
REGION_CROPS = {"cereals": ["C0000"], "potatoes_roots": ["R1000"], "sugar": ["R2000"], "pulses": ["P0000"],
                "oilseeds": ["I1110", "I1120", "I1130"]}


def region_rows(WIN):
    """{iso: {group: {"coverage": %, "regions": {code: (kt, share, t_per_km2)}}}} and the breaks."""
    raw = ROOT / "data/raw"
    t = pd.read_csv(raw / "eurostat/apro_cpshr.tsv.gz", sep="\t", dtype=str)
    t.columns = [c.strip() for c in t.columns]
    keys = t.iloc[:, 0].str.split(",", expand=True)
    t = t.assign(crop=keys[1], unit=keys[2], geo=keys[3])
    t = t[t["unit"] == "HPRD_HUMD_EU_THS_T"]
    feats = {}
    for y in (2024, 2021):
        for f in json.load(open(raw / f"gisco/NUTS_RG_20M_{y}_4326.geojson"))["features"]:
            feats.setdefault(f["properties"]["NUTS_ID"], f["geometry"])

    def area(geom):  # spherical polygon area, km2
        R = 6371.0088
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        tot = 0.0
        for poly in polys:
            for k, ring in enumerate(poly):
                a = 0.0
                for j in range(len(ring)):
                    x1, y1 = ring[j]
                    x2, y2 = ring[(j + 1) % len(ring)]
                    a += math.radians(x2 - x1) * (2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
                tot += (-1 if k else 1) * abs(a) * R * R / 2
        return tot

    iso = {c["eurostat"]: c["iso3"] for c in EUROPE if c.get("eurostat")}
    out, dens = {}, defaultdict(list)
    for g, crops in REGION_CROPS.items():
        x = t[t["crop"].isin(crops)]
        vals = defaultdict(dict)  # geo -> year -> summed kt
        for _, r in x.iterrows():
            for y in WIN:
                v = str(r.get(str(y), ":")).strip().split(" ")[0]
                try:
                    vals[r["geo"]][y] = vals[r["geo"]].get(y, 0.0) + float(v)
                except ValueError:
                    pass
        mean = {geo: sum(ys.values()) / len(ys) for geo, ys in vals.items() if ys}
        for ctry in sorted({geo[:2] for geo in mean}):
            if ctry not in iso:
                continue
            national = mean.get(ctry, 0.0)
            chosen = None
            for lvl in (2, 1):
                regs = {geo: v for geo, v in mean.items()
                        if geo[:2] == ctry and len(geo) == 2 + lvl and geo in feats and not geo.endswith("Z")}
                if len(regs) > 1:
                    chosen = regs
                    break
            if not chosen:
                continue
            total = sum(chosen.values())
            if national <= 0 or total <= 0 or total / national < 0.9:
                continue
            rows = {}
            for geo, kt in chosen.items():
                d = 1000 * kt / area(feats[geo])
                rows[geo] = (kt, 100 * kt / total, d)
                if d > 0:
                    dens[g].append(d)
            out.setdefault(iso[ctry], {})[g] = {"coverage": round(100 * total / national), "regions": rows}
        eu = {geo: v for c, gs in out.items() if c in EU and g in gs for geo, v in gs[g]["regions"].items()}
        if eu:
            tot = sum(v[0] for v in eu.values())
            out.setdefault("EU27", {})[g] = {"coverage": None,
                                             "regions": {geo: (v[0], 100 * v[0] / tot, v[2]) for geo, v in eu.items()}}

    def nice(v):
        if v <= 0:
            return 0.0
        p = 10 ** (math.floor(math.log10(v)) - 1)
        return round(v / p) * p
    breaks = {g: [nice(float(np.percentile(d, q))) for q in (20, 40, 60, 80)] for g, d in dens.items()}
    return out, breaks


FRESH_HEADINGS = ("0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709",
                  "0803", "0804", "0805", "0806", "0807", "0808", "0809", "0810")


def import_months(WIN):
    """Methodology "When it comes from abroad": {iso: {group: [(hs4, share[12], top[12])]}}."""
    hs = {(int(r["version"]), r["hs"]): r for r in read_csv_comments(MAP / "hs_items.csv")
          if r["group"] in ("fruit", "vegetables", "potatoes_roots")}
    d = pd.read_csv(ROOT / "data/raw/comext/DS-045409_monthly_imports.csv.gz", dtype=str,
                    keep_default_na=False, compression="gzip")
    d = d[(d["partner"].str.len() == 2) & (d["OBS_VALUE"] != "") & d["product"].str[:4].isin(FRESH_HEADINGS)]
    acc = defaultdict(lambda: defaultdict(float))  # (iso, group, hs4, month) -> partner -> t
    for rep_, par, prod, per, val in zip(d["reporter"], d["partner"], d["product"], d["TIME_PERIOD"], d["OBS_VALUE"]):
        y, mo = int(per[:4]), int(per[5:7])
        if y not in WIN:
            continue
        r = hs.get((2017 if y <= 2021 else 2022, prod))
        if r is None:
            continue
        c, p = COMEXT_ISO[rep_], COMEXT_ISO.get(par, par)
        if c == p:
            continue
        t = float(val) / 10 * (float(r["to_primary"]) if r["to_primary"] else 1.0)
        acc[(c, r["group"], prod[:4], mo)][p] += t
        if p not in EU and p not in INTRA_UNNAMED:
            acc[("EU27", r["group"], prod[:4], mo)][p] += t
    named_iso = set(COMEXT_ISO.values())
    tot = defaultdict(float)
    for (c, g, h, mo), x in acc.items():
        tot[(c, g, h)] += sum(x.values())
    out = {}
    for c, g in {(k[0], k[1]) for k in tot}:
        heads = sorted(((v, h) for (cc, gg, h), v in tot.items() if cc == c and gg == g), reverse=True)
        gtot = sum(v for v, _ in heads)
        rows = []
        for v, h in heads:
            if gtot <= 0 or 100 * v / gtot < 5 or len(rows) == 4:
                continue
            share, top = [], []
            for mo in range(1, 13):
                x = acc.get((c, g, h, mo), {})
                mt = sum(x.values())
                share.append(100 * mt / v)
                named = {p: t for p, t in x.items() if p in named_iso}
                if mt > 0 and named:
                    p = max(named, key=named.get)
                    top.append([p, 100 * named[p] / mt])
                else:
                    top.append(None)
            rows.append((h, share, top))
        if rows:
            out.setdefault(c, {})[g] = rows
    return out


CROPMAP_CLASSES = {"cereals": [211, 212, 213, 214, 215, 216, 217, 218, 219], "potatoes_roots": [221],
                   "sugar": [222], "oilseeds": [232, 233], "pulses": [240]}


def cropmap_check(cm, n=4000):
    """Methodology "Fields": for n sampled image pixels, the shade of the summed class shares at
    the pixel's centre (nearest 2 km cell). -> {group: (exact share, worst step difference)}."""
    import rasterio
    from rasterio.warp import transform as tr

    steps = cm["meta"]["steps"]
    colors = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in cm["meta"]["colors"]]
    R = 6378137.0
    rng = np.random.default_rng(20261018)
    out = {}
    for g, info in cm["groups"].items():
        tot = None
        for c in CROPMAP_CLASSES[g]:
            with rasterio.open(ROOT / f"data/raw/eucropmap/crop_percent_on_land_{c}_2km.tif") as r:
                a = r.read(1).astype("float64")
                a[a == r.nodata] = np.nan
                inv = ~r.transform
            tot = a if tot is None else np.where(np.isnan(tot), a, tot + np.nan_to_num(a))
        with rasterio.open(OUT_DIR / info["file"]) as im:
            px = im.read()
        h, w = px.shape[1], px.shape[2]
        (lon0, lat0), (lon1, _), (_, lat1) = info["coordinates"][0], info["coordinates"][1], info["coordinates"][2]
        mx = lambda lon: math.radians(lon) * R  # noqa: E731
        my = lambda lat: R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))  # noqa: E731
        x0, x1, y0, y1 = mx(lon0), mx(lon1), my(lat0), my(lat1)
        rows, cols = rng.integers(0, h, n), rng.integers(0, w, n)
        xs = x0 + (cols + 0.5) * (x1 - x0) / w
        ys = y0 + (rows + 0.5) * (y1 - y0) / h
        ex, ey = tr("EPSG:3857", "EPSG:3035", xs.tolist(), ys.tolist())
        exact, worst = 0, 0
        for k in range(n):
            cc, rr = inv * (ex[k], ey[k])
            ci, ri = int(math.floor(cc)), int(math.floor(rr))
            v = tot[ri, ci] if 0 <= ri < tot.shape[0] and 0 <= ci < tot.shape[1] else np.nan
            want = -1
            for i, lo in enumerate(steps):
                if not np.isnan(v) and min(v, 1) >= lo:
                    want = i
            p = px[:, rows[k], cols[k]]
            got = -1 if p[3] == 0 else colors.index(tuple(int(x) for x in p[:3]))
            exact += got == want
            worst = max(worst, abs(got - want))
        out[g] = (exact / n, worst)
    return out


def feed_rows(res, D):
    """Methodology "Feed": {iso: (imported %, top [[item, %]], meat SSR, eggs SSR, items %)}."""
    items = {int(r["item_code"]): (r["item"], float(r["protein_pct"]) / 100, int(r["parent"]) if r["parent"] else None)
             for r in read_csv_comments(MAP / "feed_items.csv")}
    codes = set(items) | {v[2] for v in items.values() if v[2]}
    z = zipfile.ZipFile(ROOT / "data/raw/faostat/SUA_Crops_Livestock_E_All_Data_(Normalized).zip")
    with z.open("SUA_Crops_Livestock_E_All_Data_(Normalized).csv") as fh:
        t = pcsv.read_csv(fh, read_options=pcsv.ReadOptions(encoding="latin-1"), convert_options=pcsv.ConvertOptions(
            include_columns=["Area Code (M49)", "Item Code", "Element", "Year", "Unit", "Value"],
            column_types={"Area Code (M49)": pa.string(), "Item Code": pa.int64(), "Year": pa.int64(),
                          "Value": pa.float64()})).to_pandas()
    WIN = D.WIN
    t = t[t["Year"].isin(WIN) & t["Item Code"].isin(codes) & (t["Unit"] == "t")
          & t["Element"].isin(["Production", "Import quantity", "Feed"])]
    t["iso"] = t["Area Code (M49)"].str.lstrip("'").str.zfill(3).map(ALL_ISO)
    t = t[t["iso"].notna() & t["iso"].isin({c for c in WORLD.values()} | {e["iso3"] for e in EUROPE})]
    el = {"Production": "P", "Import quantity": "M", "Feed": "F"}
    t["el"] = t["Element"].map(el)
    # EU: members' imports from outside the EU, per item and year, from the trade matrix
    tm = D.tm[D.tm["r"].isin(EU) & (D.tm["flow"] == "imports") & D.tm["p"].notna() & D.tm["item"].isin(codes)
              & D.tm["year"].isin(WIN)]
    ext = tm[~tm["p"].isin(EU)].groupby(["item", "year"])["t"].sum()
    alls = tm.groupby(["item", "year"])["t"].sum()
    share = (ext.reindex(alls.index).fillna(0) / alls).where(alls > 0).to_dict()
    eu = t[t["iso"].isin(EU)].copy()
    mm = eu["el"] == "M"
    eu.loc[mm, "Value"] = [v * (share.get((i, y)) if share.get((i, y)) is not None and not isnan(share.get((i, y))) else 1.0)
                           for v, i, y in zip(eu.loc[mm, "Value"], eu.loc[mm, "Item Code"], eu.loc[mm, "Year"])]
    eu["iso"] = "EU27"
    t = pd.concat([t, eu], ignore_index=True)
    w = t.groupby(["iso", "Item Code", "el"])["Value"].sum().div(len(WIN)).unstack("el").reindex(
        columns=["P", "M", "F"]).fillna(0.0)
    out = {}
    for iso, sub in w.groupby(level="iso"):
        sub = sub.droplevel("iso")

        def own(code, sub=sub):
            if code not in sub.index:
                return 1.0
            p_, m_ = sub.at[code, "P"], sub.at[code, "M"]
            return 1.0 if p_ + m_ <= 0 else min(1.0, max(0.0, p_ / (p_ + m_)))
        fed = [c for c in sub.index if sub.at[c, "F"] > 0 and c in items]
        tot_t = sub.loc[sub["F"] > 0, "F"].sum()
        if not fed:
            continue
        prot = {c: sub.at[c, "F"] * items[c][1] for c in fed}
        imp = {c: prot[c] * (1 - own(c) * (own(items[c][2]) if items[c][2] else 1.0)) for c in fed}
        if sum(prot.values()) <= 0:
            continue
        f = sum(imp.values()) / sum(prot.values())
        ti = sum(imp.values())
        top = [[items[c][0], round(100 * v / ti)] for c, v in sorted(imp.items(), key=lambda kv: -kv[1])[:3]
               if ti > 0 and v / ti >= 0.05]
        r = res.get(iso, {})
        gr = r.get("groups", {})
        bal = r.get("item_bal") or {}
        code_of = {nm: c for c, nm in D.item_names.items()}

        def p_item(nm):
            c = code_of.get(nm)
            return nz(bal[c]["P"]) if c in bal else 0.0

        def ssr(g, num):
            x = gr.get(g)
            if not x or x["reason"] or not x["comp"]["D"] > 0:
                return math.nan
            return 100 * num / x["comp"]["D"]
        meat = ssr("meat", nz(gr["meat"]["comp"]["P"]) - f * (p_item("Pigmeat") + p_item("Poultry Meat"))) \
            if "meat" in gr else math.nan
        eggs = ssr("eggs", (1 - f) * nz(gr["eggs"]["comp"]["P"])) if "eggs" in gr else math.nan
        out[iso] = (100 * f, top, meat, eggs, 100 * sum(sub.at[c, "F"] for c in fed) / tot_t if tot_t > 0 else math.nan)
    return out


def scenario_rows(res, D, trade, hidden):
    """Methodology "Scenario": {iso: {group: lack %}}; all = protein-weighted."""
    out = {}
    code_of = {}
    for c, nm in D.item_names.items():
        code_of.setdefault(nm, c)
    for iso, r in res.items():
        if iso in ("RUS", "UKR") or "groups" not in r:
            continue
        rows = {}
        for g, gr in r["groups"].items():
            if gr["reason"] or (iso, g, "imports") in hidden:
                continue
            P, M, Dd = gr["comp"]["P"], gr["comp"]["M"], gr["comp"]["D"]
            if isnan(Dd) or Dd <= 0:
                continue
            if isnan(M) or M <= 0:
                rows[g] = 0.0
                continue
            parts = trade.get(iso, {}).get(g, {}).get("imports" if g == "fish" else "grown", {})
            tot = sum(parts.values())
            if tot <= 0:
                continue
            s_ = (parts.get("RUS", 0.0) + parts.get("UKR", 0.0)) / tot
            rows[g] = 100 * M * s_ / (max(nz(P), 0.0) + M)
        bal = r.get("item_bal") or {}
        num = den = 0.0
        for g, v in rows.items():
            pr = sum(nz(bal[code_of[nm]]["protein"]) for nm in PRODUCTS[g]["items"]
                     if nm in code_of and code_of[nm] in bal)
            if pr > 0:
                num, den = num + v * pr, den + pr
        if den > 0:
            rows["all"] = num / den
        if rows:
            out[iso] = rows
    return out


def season_rows(res, D):
    """Methodology "Seasons", "What a food page shows": {iso: {group: [rows]}}."""
    cal = season_calendars()
    name_code = {}
    for code, nm in D.item_names.items():
        name_code.setdefault(nm, code)
    out = {}
    for iso, r in res.items():
        bal = r.get("item_bal") or {}
        groups = r.get("groups") or {}

        def prod(item):
            c = name_code.get(item)
            return nz(bal[c]["P"]) if c in bal else 0.0

        for g in ("cereals", "potatoes_roots", "sugar", "pulses", "oilseeds"):
            if g not in groups or groups[g]["reason"]:
                continue
            members = ["Sugar beet", "Sugar cane"] if g == "sugar" else PRODUCTS[g]["items"]
            gp = sum(prod(i) for i in members)
            if gp <= 0:
                continue
            seen, rows = set(), []
            for crop, (_, item, grp, label) in SEASON_CROPS.items():
                if grp != g or label in seen or (iso, label) not in cal:
                    continue
                seen.add(label)
                share = 100 * prod(item) / gp
                if share >= 5:
                    _, s_, g_, h_ = cal[(iso, label)]
                    rows.append({"label": label, "share": round(share), "sown": [round(x) for x in s_],
                                 "growing": [round(x) for x in g_], "harvest": [round(x) for x in h_]})
            if rows:
                rows.sort(key=lambda x: -x["share"])
                out.setdefault(iso, {})[g] = rows[:4]
    return out
BACI_ZIP = ROOT / "data/raw/baci/BACI_HS17_V202601.zip"


def load_baci_fish(years):
    """Methodology "BACI": fish flows between countries in live weight, -> [c, partner, flow, t]
    summed over `years` (both directions of every flow)."""
    fish6 = sorted({r["hs"] for r in read_csv_comments(MAP / "hs_items.csv")
                    if r["version"] == "2017" and r["group"] == "fish"})
    cf = pd.read_excel(EUMOFA_XLSX, sheet_name="List of CF", dtype=str)[["Year", "CN-8", "CF"]]
    cf.columns = ["year", "cn8", "cf"]
    cf["cn8"] = cf["cn8"].str.replace(" ", "", regex=False)
    cf["year"] = cf["year"].astype(int)
    cf["cf"] = pd.to_numeric(cf["cf"], errors="coerce")
    cf = cf[cf["cf"] > 0]
    fac = {}
    for k in fish6:
        for y in years:
            f = FISH_MIX.get((k, y))
            if f is None:
                c = cf[(cf["cn8"].str[:6] == k) & (cf["year"] == y)]["cf"]
                f = float(c.median()) if len(c) else None
            fac[(k, y)] = f
        have = {y: fac[(k, y)] for y in years if fac[(k, y)] is not None}
        for y in years:
            if fac[(k, y)] is None:
                fac[(k, y)] = have[min(have, key=lambda z: (abs(z - y), z))] if have else 1.0
    z = zipfile.ZipFile(BACI_ZIP)
    cc = pd.read_csv(z.open("country_codes_V202601.csv"), dtype=str)
    known = set(ALL_ISO.values())
    iso = {int(c): ("TWN" if i == "S19" else i) for c, i in zip(cc["country_code"], cc["country_iso3"])}
    iso = {c: i for c, i in iso.items() if i in known}
    rows = []
    for y in years:
        t = pd.read_csv(z.open(f"BACI_HS17_Y{y}_V202601.csv"), dtype={"k": str})
        t = t[t["k"].isin(fish6) & t["q"].notna()]
        t = t.assign(e=t["i"].map(iso), m=t["j"].map(iso))
        t = t[t["e"].notna() & t["m"].notna() & (t["e"] != t["m"])]
        t["t"] = t["q"] * [fac[(k, y)] for k in t["k"]]
        rows.append(t[["e", "m", "t"]])
    b = pd.concat(rows, ignore_index=True)
    ex = b.rename(columns={"e": "c", "m": "partner"}).assign(flow="exports")
    im = b.rename(columns={"m": "c", "e": "partner"}).assign(flow="imports")
    return pd.concat([ex, im], ignore_index=True).groupby(["c", "partner", "flow"], as_index=False)["t"].sum()


def load_tm():
    p = tm_cache.build(SHAS["trade_matrix_zip"])
    t = pd.read_parquet(p)
    t = t[t["rep"] != t["par"]]
    t["r"] = t["rep"].map(ALL_ISO)
    t["p"] = t["par"].map(ALL_ISO)
    return t


def bilateral(tm, years, factors=None):
    """Reporter first; mirror (partners' opposite flow) where a country reported nothing at all
    for that flow and year. -> [c, partner, flow, year, group, t, src]. `factors`: item -> kg of
    primary product per kg traded (partner lists); None = product weight (EU-bloc shares)."""
    t = tm[tm["year"].isin(years)]
    if factors:
        t = t.assign(t=t["t"] * t["item"].map(factors).fillna(1.0))
    rep_set = set(map(tuple, t.loc[t["r"].notna(), ["r", "flow", "year"]].drop_duplicates()
                      .to_numpy()))
    t = t.assign(group=t["item"].map(TRADE_ITEMS))
    t = t[t["group"].notna() & t["r"].notna() & t["p"].notna()]
    own = t[["r", "p", "flow", "year", "group", "t"]].rename(columns={"r": "c", "p": "partner"})
    own = own.assign(src="reported")
    opp = {"imports": "exports", "exports": "imports"}
    mir = t[["p", "r", "flow", "year", "group", "t"]].rename(columns={"p": "c", "r": "partner"})
    mir = mir.assign(flow=mir["flow"].map(opp), src="mirror")
    keep = [(c, f, y) not in rep_set for c, f, y in zip(mir["c"], mir["flow"], mir["year"])]
    return pd.concat([own, mir[keep]], ignore_index=True)


# --------------------------------------------------------------------------------------------
# Balance arithmetic
# --------------------------------------------------------------------------------------------
def verdict(P, M, X, S, D, food=None):
    """Methodology 'Withheld' table (items and groups, on their own figures), first match wins.
    food=None skips the food test (JRC dairy)."""
    if isnan(D):
        return "supply_missing"
    if D <= 0:
        return "supply_nonpositive"
    if not isnan(X) and X > (nz(P) + nz(M) - nz(S)) * 1.02 + 1:
        return "exports_exceed_available"
    if food is not None and not isnan(food) and food > D * 1.25 + 1:
        return "food_exceeds_supply"
    return None


def ratio(num, den):
    if isnan(den) or den <= 0 or isnan(num):
        return math.nan
    return num / den * 100


class Data:
    pass


def load_all() -> Data:
    D = Data()
    D.fbs, D.pop, D.item_names = load_fbs()
    log(f"FBS loaded: {len(D.fbs):,} country-item-years")
    years_all = sorted(D.fbs.index.get_level_values("year").unique())
    D.WIN = years_all[-3:]
    D.TREND = [y for y in years_all if y >= 2010]
    name_to_code = {}
    for code, nm in sorted(D.item_names.items()):
        name_to_code.setdefault(nm, code)  # leaf codes only (< 2900) are in item_names
    D.GROUP_ITEMS = {g: [name_to_code[n] for n in s["items"]] for g, s in PRODUCTS.items()}
    D.ITEM_GROUP = {c: g for g, cs in D.GROUP_ITEMS.items() for c in cs}
    D.JRC_CODE = {f: name_to_code[n] for f, n in JRC_FOODS.items()}
    D.DAIRY = D.GROUP_ITEMS["dairy"]
    D.FISH = set(D.GROUP_ITEMS["fish"])
    D.jrc, D.jrc_rawmilk = load_jrc()
    log(f"JRC loaded: {len(D.jrc)} country-food-years")
    D.tm = load_tm()
    log(f"trade matrix extract loaded: {len(D.tm):,} rows")
    # extra-EU shares per member, flow, year, group (+ all-food), product weight
    b = bilateral(D.tm, D.TREND)
    b = b[b["c"].isin(EU)].assign(extra=lambda x: ~x["partner"].isin(EU))
    tot = b.groupby(["c", "flow", "year", "group"])["t"].sum()
    ext = b[b["extra"]].groupby(["c", "flow", "year", "group"])["t"].sum()
    D.share_g = (ext.reindex(tot.index).fillna(0) / tot).where(tot > 0).to_dict()
    tot = b.groupby(["c", "flow", "year"])["t"].sum()
    ext = b[b["extra"]].groupby(["c", "flow", "year"])["t"].sum()
    D.share_a = (ext.reindex(tot.index).fillna(0) / tot).where(tot > 0).to_dict()
    # fish: extra-EU shares from Comext, live weight, over all partners (unnamed ones outside the
    # EU except Comext's intra-EU codes)
    D.fish = load_comext_fish()
    f = D.fish.assign(extra=~(D.fish["partner"].isin(EU) | D.fish["partner"].isin(INTRA_UNNAMED)))
    tot = f.groupby(["c", "flow", "year"])["t"].sum()
    ext = f[f["extra"]].groupby(["c", "flow", "year"])["t"].sum()
    for (c, flow, y), v in (ext.reindex(tot.index).fillna(0) / tot).where(tot > 0).items():
        D.share_g[(c, flow, y, "fish")] = v
    log(f"Comext fish loaded: {len(D.fish):,} rows")
    countries = sorted(D.fbs.index.get_level_values("iso3").unique())
    D.yearly = {}
    for iso in countries:
        sub = D.fbs.loc[iso]
        D.yearly[iso] = {(int(i), int(y)): r for (i, y), r in zip(sub.index, sub.to_dict("records"))}
    D.popd = D.pop.to_dict()
    # a country "reports" a year when it has a Population row (methodology "Time averaging")
    D.country_years = {iso: {y for (c, y), v in D.popd.items() if c == iso and not isnan(v)}
                       for iso in D.yearly}
    return D


def eu_share(D, c, flow, year, item):
    g = D.ITEM_GROUP.get(item)
    s = D.share_g.get((c, flow, year, g)) if g else None
    if isnan(s):
        s = D.share_a.get((c, flow, year))  # items outside the groups / no group trade
    return 1.0 if isnan(s) else s


def build_eu27(D, opts):
    """EU27 per-year item balances from FAO members, trade = members' trade x extra-EU share."""
    eu_years = [y for y in D.TREND if all(y in D.country_years[m] for m in EU)]
    tab, pops = {}, {}
    for y in eu_years:
        popy = {m: D.popd.get((m, y), math.nan) for m in EU}
        pop_eu = sum(popy.values())
        pops[y] = pop_eu
        items = {i for m in EU for (i, yy) in D.yearly[m] if yy == y}
        for i in items:
            rows = [(m, D.yearly[m][(i, y)]) for m in EU if (i, y) in D.yearly[m]]
            r = {}
            for k in ("P", "S"):
                vals = [x[k] for _, x in rows if not isnan(x[k])]
                r[k] = sum(vals) if vals else math.nan
            sumD = sum(nz(x["D"]) for _, x in rows)
            r["M"] = sum(nz(x["M"]) * eu_share(D, m, "imports", y, i) for m, x in rows)
            r["X"] = sum(nz(x["X"]) * eu_share(D, m, "exports", y, i) for m, x in rows)
            r["D"] = nz(r["P"]) + r["M"] - r["X"] - nz(r["S"])
            f = r["D"] / sumD if sumD else math.nan
            for u in USES:  # uses: members' sums scaled to D_EU
                vals = [x[u] for _, x in rows if not isnan(x[u])]
                r[u] = sum(vals) * f if vals else math.nan
            for pc in PERCAP:  # per-person: population-weighted over members
                num = [(x[pc] * popy[m], popy[m]) for m, x in rows if not isnan(x[pc])]
                if not num:
                    r[pc] = math.nan
                elif opts["eu_percap"] == "eu_population":
                    r[pc] = sum(a for a, _ in num) / pop_eu
                else:
                    r[pc] = sum(a for a, _ in num) / sum(b for _, b in num)
            tab[(i, y)] = r
    return tab, eu_years, pops


def compute_balances(D, opts):
    """Window + trend results for every country (and EU27) under one reading of the spec."""
    yearly = dict(D.yearly)
    country_years = dict(D.country_years)
    popd = dict(D.popd)
    eu_tab, eu_years, eu_pops = build_eu27(D, opts)
    yearly["EU27"] = eu_tab
    country_years["EU27"] = set(eu_years)
    for y, p in eu_pops.items():
        popd[("EU27", y)] = p
    GI, DAIRY, JRC_CODE = D.GROUP_ITEMS, D.DAIRY, D.JRC_CODE

    def apply_jrc_item(r, j):
        r = dict(r)
        f = j["D"] / r["D"] if not isnan(r["D"]) and r["D"] != 0 else math.nan
        for u in USES:  # uses scaled with supply; per-person figures left as FAO's
            r[u] = r[u] * f
        r.update(P=j["P"], M=j["M"], X=j["X"], D=j["D"])
        r["S"] = j["P"] + j["M"] - j["X"] - j["D"]
        return r

    def fao_supply(iso, food, y):
        codes = DAIRY if food == "dairy" else [JRC_CODE[food]]
        rows = [yearly[iso][(c, y)] for c in codes if (c, y) in yearly[iso]]
        vals = [r["D"] for r in rows if not isnan(r["D"])]
        return sum(vals) if vals else math.nan

    def jrc_get(iso, food, y):
        j = D.jrc.get((iso, food, y))
        if j is None:  # production missing or apparent use <= 0: not covered (load_jrc)
            return None
        if opts["jrc_negative_production"] == "clip0" and j["P"] < 0:
            j = {**j, "P": 0.0}
        # Edge rule: not applied where FAO has no supply for the food at all
        fd = fao_supply(iso, food, y)
        if opts["jrc_no_fao_supply"] == "missing_or_zero":
            if isnan(fd) or fd == 0:
                return None
        elif isnan(fd) or fd <= 0:
            return None
        return j

    def balances(iso, years):
        tab = yearly[iso]
        jrc_ok = {}
        for food in list(JRC_CODE) + ["dairy"]:
            js = [jrc_get(iso, food, y) for y in years]
            jrc_ok[food] = js if all(j is not None for j in js) else None  # one source per avg
        per_item = defaultdict(dict)
        for yi, y in enumerate(years):
            for (i, yy), r in tab.items():
                if yy != y:
                    continue
                for food, code in JRC_CODE.items():
                    if i == code and jrc_ok[food]:
                        r = apply_jrc_item(r, jrc_ok[food][yi])
                per_item[i][y] = r
        # divisor: window years the country reports at all (Population row)
        n_years = sum(1 for y in years if y in country_years[iso]) or 1
        items = {}
        for i, by_year in per_item.items():
            rs = list(by_year.values())
            row = {}
            for k in BAL + USES + PERCAP:
                present = [x[k] for x in rs if not isnan(x[k])]
                if opts["avg"] == "country_years_zero":
                    # inside a published balance a missing element is 0 in that year, for every
                    # component. Only D never reported stays missing (the supply_missing test).
                    if present:
                        row[k] = sum(present) / n_years
                    else:
                        row[k] = math.nan if k == "D" else 0.0
                else:  # item_years_skipna (the pipeline's earlier behaviour)
                    if k in ("P", "M", "X", "D"):
                        row[k] = (sum(present) / len(rs)) if present else (
                            0.0 if k != "D" else math.nan)
                    else:
                        row[k] = (sum(present) / len(present)) if present else math.nan
            items[i] = row
        dairy = None
        if jrc_ok["dairy"]:
            js = jrc_ok["dairy"]
            dairy = {k: sum(j[k] for j in js) / len(js) for k in ("P", "M", "X", "D")}
            for u in USES:  # FAO dairy uses scaled year by year to the JRC supply
                tot, seen = 0.0, False
                for yi, y in enumerate(years):
                    rows = [tab[(c, y)] for c in DAIRY if (c, y) in tab]
                    fd = sum(nz(r["D"]) for r in rows)
                    vals = [r[u] for r in rows if not isnan(r[u])]
                    if vals and fd:
                        seen = True
                        tot += sum(vals) * js[yi]["D"] / fd
                dairy[u] = tot / n_years  # never-reported use = 0 (Time averaging)
            pubs = [D.jrc_rawmilk.get((iso, y)) for y in years]
            if all(p is not None for p in pubs):
                dairy["published_ssr"] = ratio(sum(p[0] for p in pubs), sum(p[1] for p in pubs))
        used = {f for f in JRC_CODE if jrc_ok[f] and JRC_CODE[f] in items}
        return items, used, dairy

    def item_result(r, food_test=True):
        reason = verdict(r["P"], r["M"], r["X"], r["S"], r["D"], r["food"] if food_test else None)
        if reason:
            return reason, math.nan, math.nan
        return None, ratio(r["P"], r["D"]), ratio(r["M"], r["D"])

    def d_adj(r):
        return max(nz(r["D"]), nz(r["food"]), 0.0)

    def differ(a, b):
        """A and B differ by more than max(10 points, 10% of B) (or one undefined)."""
        if isnan(a) or isnan(b):
            return True
        return abs(a - b) > max(10.0, 0.1 * abs(b))

    def group_result(g, items, dairy):
        codes = [c for c in GI[g] if c in items]
        if not codes and not (g == "dairy" and dairy):
            return None
        comp = {}
        for k in BAL + USES:
            vals = [items[c][k] for c in codes if not isnan(items[c][k])]
            comp[k] = sum(vals) if vals else math.nan
        jrc_dairy = g == "dairy" and dairy is not None
        if jrc_dairy:
            comp.update({k: v for k, v in dairy.items() if k != "published_ssr"})
            comp["S"] = dairy["P"] + dairy["M"] - dairy["X"] - dairy["D"]
        # own figures; JRC dairy: no food test (its food line is FAO's)
        reason = verdict(comp["P"], comp["M"], comp["X"], comp["S"], comp["D"],
                         None if jrc_dairy else comp["food"])
        # parts sensitivity (JRC dairy items are not judged one by one): ssr_pub over the
        # published D, ssr_adj with flagged items' D raised to max(D, food, 0)
        flagged = [] if jrc_dairy else [c for c in codes if item_result(items[c])[0]]
        pub = ratio(comp["P"], comp["D"])
        adj = ratio(sum(nz(items[c]["P"]) for c in codes),
                    sum(d_adj(items[c]) if c in flagged else nz(items[c]["D"]) for c in codes)
                    ) if flagged else pub
        if reason is None and flagged and differ(pub, adj):
            reason = "parts_contradict"
        if reason is None and (iso, g) in REVIEWED:
            reason = "reviewed"
        rng = None  # exported for every withheld group
        if reason == "reviewed":
            rng = "null"  # nothing contradicts itself: no two readings
        elif reason:
            if not isnan(pub) and not isnan(adj):
                rng = [min(pub, adj), max(pub, adj)]
            elif not isnan(pub) or not isnan(adj):  # one undefined: [defined, null]
                rng = [adj if isnan(pub) else pub, math.nan]
            else:
                rng = "null"
        res = {"comp": comp, "reason": reason, "range": rng,
               "ssr": math.nan if reason else ratio(comp["P"], comp["D"]),
               "idr": math.nan if reason else ratio(comp["M"], comp["D"]),
               "uses_withheld": (not reason and not isnan(comp["residuals"])
                                 and abs(comp["residuals"]) > 0.25 * comp["D"]
                                 and abs(comp["residuals"]) > 1),
               "kcal_ssr": math.nan, "kcal_idr": math.nan,
               "kcal_flag": "jrc_group_only" if jrc_dairy else reason,
               "published_ssr": dairy.get("published_ssr", math.nan) if jrc_dairy else math.nan}
        if not reason and not jrc_dairy:
            num = numi = den = 0.0
            for c in codes:
                fl, s, m = item_result(items[c])
                w = items[c]["kcal"]
                if fl or isnan(s) or isnan(w) or w <= 0:
                    continue
                num, den, numi = num + s * w, den + w, numi + m * w  # m NaN -> NaN (unknown)
            if den > 0:
                res["kcal_ssr"], res["kcal_idr"] = num / den, numi / den
        return res

    def all_food(items, dairy):
        A, B = [], []  # (ssr, protein, kcal)
        n_withheld = 0
        for c, r in items.items():
            if dairy and c in DAIRY:
                continue
            fl, s, _ = item_result(r)
            w = (nz(r["protein"]), nz(r["kcal"]))
            if not fl and not isnan(s):
                A.append((s, *w))
                B.append((s, *w))
            else:
                if w[0] > 0:
                    n_withheld += 1
                sb = ratio(nz(r["P"]), d_adj(r))  # reading B
                if not isnan(sb):
                    B.append((sb, *w))
        if dairy:
            dc = [c for c in DAIRY if c in items]  # JRC dairy: one food, summed weights
            w = (sum(nz(items[c]["protein"]) for c in dc), sum(nz(items[c]["kcal"]) for c in dc))
            if not verdict(dairy["P"], dairy["M"], dairy["X"], None, dairy["D"]):
                A.append((dairy["P"] / dairy["D"] * 100, *w))
                B.append(A[-1])
            elif w[0] > 0:
                n_withheld += 1

        def wmean(foods, w, cap):
            den = sum(f[w] for f in foods)
            if den <= 0:
                return math.nan
            return sum((min(f[0], 100) if cap else f[0]) * f[w] for f in foods) / den

        out = {}
        for name, w in (("protein", 1), ("kcal", 2)):
            sa, sb = wmean(A, w, True), wmean(B, w, True)
            ua, ub = wmean(A, w, False), wmean(B, w, False)
            withheld = differ(sa, sb) or differ(ua, ub)
            out[name] = {"share": math.nan if withheld else sa, "ssr": math.nan if withheld else ua,
                         "reason": "parts_contradict" if withheld else None,
                         "range": [min(ua, ub), max(ua, ub)],
                         "share_range": [min(sa, sb), max(sa, sb)]}
        out["n_foods"] = sum(1 for f in A if f[1] > 0)  # SSR and protein > 0
        out["n_withheld"] = n_withheld
        # per-person totals over every leaf item, withheld ones included
        out["g_per_day"] = sum(nz(r["protein"]) for r in items.values())
        out["per_day"] = sum(nz(r["kcal"]) for r in items.values())
        return out

    res = {}
    for iso in sorted(yearly):
        eu = iso == "EU27"
        trend = {g: [] for g in ["all"] + list(PRODUCTS)}
        for y in D.TREND:
            if y not in country_years[iso]:
                for g in trend:
                    trend[g].append(math.nan)
                continue
            items, _, dairy = balances(iso, [y])
            for g in PRODUCTS:
                gr = group_result(g, items, dairy)
                trend[g].append(math.nan if gr is None else gr["ssr"])
            trend["all"].append(all_food(items, dairy)["protein"]["ssr"])  # null if withheld
        out = {"trend": trend}
        if all(y in country_years[iso] for y in D.WIN):
            items, used, dairy = balances(iso, D.WIN)
            groups = {}
            for g in PRODUCTS:
                gr = group_result(g, items, dairy)
                if gr is None:
                    continue
                gr["jrc_items"] = [f for f in JRC_CODE if f in used and JRC_CODE[f] in GI[g]]
                eu_trade = ("+eurostat_comext" if g == "fish" else "+fao_tm") if eu else ""
                gr["source"] = ("jrc_bal" if g == "dairy" and dairy else
                                "fao_fbs" + eu_trade + ("+jrc_bal" if gr["jrc_items"] else ""))
                groups[g] = gr
            af = all_food(items, dairy)
            af["source"] = ("fao_fbs" + ("+fao_tm+eurostat_comext" if eu else "") +
                            ("+jrc_bal" if (used or dairy) else ""))
            pops = [popd.get((iso, y)) for y in D.WIN]
            pops = [p for p in pops if not isnan(p)]
            item_rows = {}
            for g in PRODUCTS:
                rows = {}
                for c in GI[g]:
                    if c not in items:
                        continue
                    nm = D.item_names[c]
                    if g == "dairy" and dairy:
                        rows[nm] = {"flag": "jrc_group_only", "ssr": math.nan, "supply_kt": math.nan}
                        continue
                    fl, s, _ = item_result(items[c])
                    rows[nm] = {"flag": fl, "ssr": s, "supply_kt": items[c]["D"]}
                if rows:
                    item_rows[g] = rows
            out.update(groups=groups, all=af, items=item_rows, item_bal=items, dairy=dairy,
                       population_k=sum(pops) / len(pops) if pops else math.nan)
        res[iso] = out
    return res


# --------------------------------------------------------------------------------------------
# Flatten recomputed results into comparable paths: path -> (value, decimals)
# --------------------------------------------------------------------------------------------
def flatten(res):
    flat = {}
    for iso, r in res.items():
        for g, series in r["trend"].items():
            for k, v in enumerate(series):
                flat[f"ssr|{iso}|trend|{g}|{k}"] = (v, 1)
        if "groups" not in r:
            continue
        flat[f"ssr|{iso}|population_k"] = (r["population_k"], 0)
        a = r["all"]
        for b in ("protein", "kcal"):
            ab = a[b]
            flat[f"ssr|{iso}|all|{b}.share"] = (ab["share"], 1)
            flat[f"ssr|{iso}|all|{b}.ssr"] = (ab["ssr"], 1)
            flat[f"ssr|{iso}|all|{b}.withheld.reason"] = (ab["reason"], None)
            if ab["reason"]:
                for key in ("range", "share_range"):
                    for k in (0, 1):
                        flat[f"ssr|{iso}|all|{b}.withheld.{key}.{k}"] = (ab[key][k], 1)
        flat[f"ssr|{iso}|all|protein.g_per_day"] = (a["g_per_day"], 1)
        flat[f"ssr|{iso}|all|kcal.per_day"] = (a["per_day"], 0)
        flat[f"ssr|{iso}|all|n_foods"] = (a["n_foods"], 0)
        flat[f"ssr|{iso}|all|n_withheld"] = (a["n_withheld"], 0)
        flat[f"ssr|{iso}|all|source"] = (a["source"], None)
        for g, gr in r["groups"].items():
            p = f"ssr|{iso}|{g}|"
            flat[p + "tonnes.ssr"] = (gr["ssr"], 1)
            flat[p + "tonnes.idr"] = (gr["idr"], 1)
            flat[p + "kcal.ssr"] = (gr["kcal_ssr"], 1)
            flat[p + "kcal.idr"] = (gr["kcal_idr"], 1)
            flat[p + "kcal.flag"] = (gr["kcal_flag"], None)
            flat[p + "withheld.reason"] = (gr["reason"], None)
            if gr["range"] == "null":
                flat[p + "withheld.range"] = ("null", None)
            elif gr["range"]:
                for k in (0, 1):
                    flat[p + f"withheld.range.{k}"] = (gr["range"][k], 1)
            flat[p + "uses_withheld"] = (bool(gr["uses_withheld"]), None)
            flat[p + "source"] = (gr["source"], None)
            flat[p + "jrc_items"] = (sorted(gr["jrc_items"]), None)
            flat[p + "jrc_published_ssr"] = (gr["published_ssr"], 1)
            for k, v in gr["comp"].items():
                name = {v_: k_ for k_, v_ in COMP_KEY.items()}.get(k, k)
                flat[p + "components_kt." + name] = (v, 1)
        for g, rows in r["items"].items():
            for nm, row in rows.items():
                p = f"items|{iso}|{g}|{nm}|"
                flat[p + "flag"] = (row["flag"], None)
                flat[p + "ssr"] = (row["ssr"], 1)
                flat[p + "supply_kt"] = (row["supply_kt"], 0)
    return flat


def flatten_export(ssr, items, TREND):
    flat = {}
    for iso, v in ssr["countries"].items():
        for g, series in v.get("trend", {}).items():
            for k, val in enumerate(series):
                flat[f"ssr|{iso}|trend|{g}|{k}"] = val
        if "indicators" not in v:
            continue
        flat[f"ssr|{iso}|population_k"] = v.get("population_k")
        a = v["indicators"]["all"]
        for b in ("protein", "kcal"):
            ab = a.get(b, {})
            flat[f"ssr|{iso}|all|{b}.share"] = ab.get("share")
            flat[f"ssr|{iso}|all|{b}.ssr"] = ab.get("ssr")
            wh = ab.get("withheld", {})
            flat[f"ssr|{iso}|all|{b}.withheld.reason"] = wh.get("reason")
            for key in ("range", "share_range"):
                for k, val in enumerate(wh.get(key, [])):
                    flat[f"ssr|{iso}|all|{b}.withheld.{key}.{k}"] = val
        flat[f"ssr|{iso}|all|protein.g_per_day"] = a.get("protein", {}).get("g_per_day")
        flat[f"ssr|{iso}|all|kcal.per_day"] = a.get("kcal", {}).get("per_day")
        flat[f"ssr|{iso}|all|n_foods"] = a.get("n_foods")
        # absent when 0; an explicit 0 is flagged as -1 so it shows up as a mismatch
        flat[f"ssr|{iso}|all|n_withheld"] = (-1 if a.get("n_withheld", None) == 0 else
                                             a.get("n_withheld", 0))
        flat[f"ssr|{iso}|all|source"] = a.get("source")
        for g, gi in v["indicators"].items():
            if g == "all":
                continue
            p = f"ssr|{iso}|{g}|"
            for b in ("tonnes", "kcal"):
                for f in ("ssr", "idr"):
                    flat[p + f"{b}.{f}"] = gi.get(b, {}).get(f)
            if gi.get("kcal", {}).get("flag"):  # flag absent = no kcal key at all: not compared
                flat[p + "kcal.flag"] = gi["kcal"]["flag"]
            wh = gi.get("withheld", {})
            flat[p + "withheld.reason"] = wh.get("reason")
            if wh and wh.get("range") is None:
                # spec: `null` when neither reading is defined; an absent key reads the same
                flat[p + "withheld.range"] = "null"
            for k, val in enumerate(wh.get("range") or []):
                flat[p + f"withheld.range.{k}"] = val
            flat[p + "uses_withheld"] = bool(gi.get("uses_withheld"))
            flat[p + "source"] = gi.get("source")
            flat[p + "jrc_items"] = sorted(gi.get("jrc_items", []))
            if "jrc_published_ssr" in gi:
                flat[p + "jrc_published_ssr"] = gi["jrc_published_ssr"]
            comps = gi.get("components_kt") or wh.get("components_kt", {})
            for k, val in comps.items():
                flat[p + "components_kt." + k] = val
            if gi.get("uses_withheld") and any(k in USES for k in gi.get("components_kt", {})):
                flat[p + "uses_left_out"] = False
    for iso, groups in items.items():
        for g, rows in groups.items():
            for row in rows:
                p = f"items|{iso}|{g}|{row['item']}|"
                flat[p + "flag"] = row.get("flag")
                if row.get("flag") != "jrc_group_only":
                    flat[p + "ssr"] = row.get("ssr")
                    flat[p + "supply_kt"] = row.get("supply_kt")
    return flat


def category(path):
    parts = path.split("|")
    if parts[0] == "items":
        return {"ssr": "item_ssr", "supply_kt": "item_supply", "flag": "item_flag"}[parts[-1]]
    field = parts[-1] if parts[2] != "trend" else "trend"
    if field == "trend":
        return "trend"
    if field == "population_k":
        return "population"
    if parts[2] == "all":
        if field in ("protein.g_per_day", "kcal.per_day"):
            return "per_person"
        if ".withheld." in field:
            return "all_food_withheld"
        return "labels" if field == "source" else "all_food"
    if field.startswith("components_kt."):
        return "components"
    if field.startswith("tonnes."):
        return "group_ratio"
    if field in ("kcal.ssr", "kcal.idr"):
        return "group_ratio_kcal"
    if field.startswith("withheld.") or field in ("uses_withheld", "uses_left_out", "kcal.flag"):
        return "withheld"
    if field == "jrc_published_ssr":
        return "jrc_published_ssr"
    return "labels"


def describe(path, TREND):
    parts = path.split("|")
    if parts[0] == "items":
        return {"file": "items.json", "country": parts[1], "group": parts[2], "item": parts[3],
                "field": parts[4]}
    if parts[2] == "trend":
        return {"file": "ssr.json", "country": parts[1], "group": parts[3],
                "field": f"trend.{TREND[int(parts[4])]}"}
    if len(parts) == 3:
        return {"file": "ssr.json", "country": parts[1], "field": parts[2]}
    return {"file": "ssr.json", "country": parts[1], "group": parts[2], "field": parts[3]}


def same(exp, rec, dp, rel=1e-6):
    e_null, r_null = exp is None, (isnan(rec) if not isinstance(rec, (str, list, bool)) else False)
    if dp is None:  # labels
        return exp == rec
    if e_null and r_null:
        return True
    if e_null or r_null:
        return False
    return abs(exp - rec) <= 0.6 * 10 ** (-dp) + rel * abs(rec)


# --------------------------------------------------------------------------------------------
# FAO against USDA PSD (methodology "FAO against USDA")
# --------------------------------------------------------------------------------------------
# PSD commodity -> FBS item: the 23 pairs of methodology "FAO against USDA", "Exact rules".
PSD_ITEMS = {
    "Wheat": "Wheat and products", "Rice, Milled": "Rice and products",
    "Barley": "Barley and products", "Corn": "Maize and products", "Rye": "Rye and products",
    "Oats": "Oats", "Millet": "Millet and products", "Sorghum": "Sorghum and products",
    "Oilseed, Soybean": "Soyabeans", "Oilseed, Rapeseed": "Rape and Mustardseed",
    "Oilseed, Sunflowerseed": "Sunflower seed", "Oilseed, Peanut": "Groundnuts",
    "Oil, Soybean": "Soyabean Oil", "Oil, Rapeseed": "Rape and Mustard Oil",
    "Oil, Sunflowerseed": "Sunflowerseed Oil", "Oil, Olive": "Olive Oil", "Oil, Palm": "Palm Oil",
    "Sugar, Centrifugal": "Sugar (Raw Equivalent)",
    "Meat, Beef and Veal": "Bovine Meat", "Meat, Swine": "Pigmeat",
    "Meat, Chicken": "Poultry Meat", "Dairy, Butter": "Butter, Ghee",
    "Coffee, Green": "Coffee and products",
}


def load_usda(WIN):
    """-> {(iso3, fbs item name): (production kt, domestic use kt)}, window means."""
    usda_map = {r["psd_name"]: r["iso3"].strip() for r in read_csv_comments(MAP / "usda_countries.csv")}
    z = zipfile.ZipFile(USDA_ZIP)
    d = pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith(".csv"))),
                    usecols=["Commodity_Description", "Country_Name", "Market_Year",
                             "Attribute_Description", "Unit_Description", "Value"])
    d = d[d["Market_Year"].isin(WIN) & d["Commodity_Description"].isin(PSD_ITEMS)]
    use_attr = d["Commodity_Description"].map(
        lambda c: "Total Disappearance" if c == "Sugar, Centrifugal" else "Domestic Consumption")
    d = d[(d["Attribute_Description"] == "Production") | (d["Attribute_Description"] == use_attr)]
    d = d.assign(kt=d["Value"] * np.where(d["Unit_Description"].str.contains("60 KG BAGS"), 0.06, 1.0),
                 attr=np.where(d["Attribute_Description"] == "Production", "P", "U"),
                 iso3=d["Country_Name"].map(usda_map))
    unmapped = sorted(set(d.loc[d["iso3"].isna(), "Country_Name"].dropna()))
    d = d[d["iso3"].notna() & (d["iso3"] != "")]
    d = d.assign(iso3=d["iso3"].replace({"EU27": "EU27"}))
    # window mean of the components: sum over the window years / number of window years
    g = d.groupby(["iso3", "Commodity_Description", "attr"])["kt"].sum() / len(WIN)
    out = {}
    for (iso, com, attr), v in g.items():
        out.setdefault((iso, PSD_ITEMS[com]), {})[attr] = v
    return {k: (v.get("P", 0.0), v.get("U", math.nan)) for k, v in out.items()}, unmapped


def usda_flags(D, res, usda, use_rule="either"):
    """-> {(iso, group): {item: (fao_ssr, usda_ssr)}} for the export's `usda` arrays."""
    name_to_code = {n: c for c, n in D.item_names.items()}
    out = defaultdict(dict)
    for (iso, item), (up, uu) in usda.items():
        r = res.get(iso)
        if not r or "item_bal" not in r or iso in EU:  # members: PSD has only the EU
            continue
        code = name_to_code[item]
        b = r["item_bal"].get(code)
        if b is None:
            continue
        g = D.ITEM_GROUP.get(code)
        if verdict(b["P"], b["M"], b["X"], b["S"], b["D"], b["food"]):
            continue  # no FAO SSR
        fao, us = ratio(b["P"], b["D"]), ratio(up, uu)
        if isnan(fao) or isnan(us):
            continue
        # "use >= 50 kt" on either source's domestic use (Exact rules); "both" kept as alternative
        if (min if use_rule == "both" else max)(b["D"], uu) < 50:
            continue
        if abs(fao - us) <= max(20.0, 0.2 * min(fao, us)):
            continue
        gd = r["groups"][g]["comp"]["D"] if g in r["groups"] else math.nan
        # methodology "FAO against USDA", Use: >= 10% of the group's supply, or share x |gap| >= 5
        if not isnan(gd) and gd > 0 and (b["D"] >= 0.1 * gd or b["D"] / gd * abs(fao - us) >= 5):
            out[(iso, g)][item] = (fao, us)
    return out


# --------------------------------------------------------------------------------------------
# Trade partners + Kastner tracing
# --------------------------------------------------------------------------------------------
def fill_underreported(bil, res, n):
    """Methodology, "Trade partners", "Under-reported food groups": per country x group x flow over
    the window, partners' reports replace the flows above when they are > 3x those, >= 20 kt a
    year, and <= 1.5x the country's FBS flow (no limit without a balance)."""
    opp = {"imports": "exports", "exports": "imports"}
    rep = bil[bil["src"] == "reported"]
    theirs = rep.rename(columns={"c": "partner", "partner": "c"})
    theirs = theirs.assign(flow=theirs["flow"].map(opp), src="mirror")
    used = bil.groupby(["c", "group", "flow"])["t"].sum()
    swap = set()
    for (c, g, flow), th in theirs.groupby(["c", "group", "flow"])["t"].sum().items():
        if th <= 3 * used.get((c, g, flow), 0.0) or th < 20_000 * n:
            continue
        b = res.get(c, {}).get("groups", {}).get(g, {}).get("comp", {}).get("M" if flow == "imports" else "X")
        if b is not None and not isnan(b) and th / n / 1000 > 1.5 * b:
            continue
        swap.add((c, g, flow))
    keep = [k not in swap for k in zip(bil["c"], bil["group"], bil["flow"])]
    take = [k in swap for k in zip(theirs["c"], theirs["group"], theirs["flow"])]
    return pd.concat([bil[keep], theirs[take]], ignore_index=True)


def build_trade(D, res, min_origin_t=0.0):
    WIN, n = D.WIN, len(D.WIN)
    bil = fill_underreported(bilateral(D.tm, WIN, TO_PRIMARY), res, n)
    out = defaultdict(lambda: defaultdict(dict))  # out[c][group][flow] = {partner: t}
    for (c, flow, g, p), v in (bil.groupby(["c", "flow", "group", "partner"])["t"].sum() / n).items():
        out[c][g].setdefault(flow, {})[p] = v
    # fish (methodology "Comext"): members' named partners, window mean, live weight
    fish = D.fish[D.fish["year"].isin(WIN) & D.fish["named"]].assign(group="fish")
    fish = fish.rename(columns={"t": "t"})[["c", "partner", "flow", "year", "group", "t"]]
    for (c, flow, p), v in (fish.groupby(["c", "flow", "partner"])["t"].sum() / n).items():
        out[c]["fish"].setdefault(flow, {})[p] = v
    # fish elsewhere (methodology "BACI"): every country outside the EU
    bf = load_baci_fish(WIN)
    bf = bf[~bf["c"].isin(EU)]
    for c, flow, p, v in zip(bf["c"], bf["flow"], bf["partner"], bf["t"]):
        out[c]["fish"].setdefault(flow, {})[p] = v / n
    eu = pd.concat([bil, fish], ignore_index=True)
    eu = eu[eu["c"].isin(EU) & ~eu["partner"].isin(EU)]
    for (flow, g, p), v in (eu.groupby(["flow", "group", "partner"])["t"].sum() / n).items():
        out["EU27"][g].setdefault(flow, {})[p] = v
    # mirror bookkeeping: countries with any flow-year filled from partners
    mirror = set(bil.loc[bil["src"] == "mirror", "c"])

    # grown: Kastner et al. (2011) per group on window-mean matrices, kt
    imp = bil[bil["flow"] == "imports"].groupby(["group", "partner", "c"])["t"].sum() / n
    countries = sorted(set(ALL_ISO.values()))
    idx = {c: k for k, c in enumerate(countries)}
    N = len(countries)
    eu_idx = np.array([idx[c] for c in EU])
    grown = defaultdict(dict)
    for g in PRODUCTS:
        if g == "fish" or g not in imp.index.get_level_values(0):
            continue
        Z = np.zeros((N, N))
        for (i, j), v in imp.loc[g].items():
            Z[idx[i], idx[j]] += v / 1000.0
        Pv = np.zeros(N)
        for c, r in res.items():
            if c == "EU27" or c not in idx or g not in r.get("groups", {}):
                continue
            comp = r["groups"][g]["comp"]  # national balance as published (incl. JRC)
            Pv[idx[c]] = nz(comp["P"])
            col = Z[:, idx[c]].sum()
            if col > 0:
                Z[:, idx[c]] *= nz(comp["M"]) / col  # splits scaled to the FBS import total
        x = np.maximum(Pv + Z.sum(axis=0), Z.sum(axis=1))
        with np.errstate(divide="ignore", invalid="ignore"):
            A = np.where(x[:, None] > 0, Z / x[:, None], 0.0)
        L = np.linalg.inv(np.eye(N) - A)
        O = Pv[:, None] * (L @ A)  # origin[k, j] = sum_i C[k,i]/x_i Z[i,j], C = diag(P) L
        for c in countries:
            j = idx[c]
            col = O[:, j].copy()
            col[j] = 0  # re-imports dropped
            parts = {countries[k]: col[k] * 1000 for k in np.nonzero(col > 0)[0]
                     if col[k] * 1000 >= min_origin_t}
            if parts:
                grown[c][g] = parts
        Zeu = Z[:, eu_idx].sum(axis=1)
        Zeu[eu_idx] = 0  # members' imports from non-members only
        xi = np.where(x > 0, 1 / np.where(x > 0, x, 1), 0.0)
        Oeu = Pv * (L @ (xi * Zeu))
        Oeu[eu_idx] = 0  # non-EU origins only
        parts = {countries[k]: Oeu[k] * 1000 for k in np.nonzero(Oeu > 0)[0]
                 if Oeu[k] * 1000 >= min_origin_t}
        if parts:
            grown["EU27"][g] = parts
    for c, gs in grown.items():
        for g, parts in gs.items():
            out[c][g]["grown"] = parts
    for c in list(out):  # "all" = all groups added up by weight, fish left out
        allf = {}
        for g, fl in list(out[c].items()):
            if g == "fish":
                continue
            for flow, parts in fl.items():
                d = allf.setdefault(flow, {})
                for p, v in parts.items():
                    d[p] = d.get(p, 0) + v
        out[c]["all"] = allf
    return out, mirror, grown


# --------------------------------------------------------------------------------------------
# Methodology, "Trade records against the food balance": flows withheld from trade.json
# --------------------------------------------------------------------------------------------
def trade_withheld(trade, res):
    """[iso3, group, flow, T, B] (kt, whole) for every flow whose trade records are more than 3x
    their food group's typical ratio to the balance and more than 1.5x the balance itself."""
    pairs = defaultdict(list)  # (group, flow) -> [(iso3, T kt, B kt)]
    for iso, r in res.items():
        if iso == "EU27" or "groups" not in r:
            continue
        for flow, key in (("imports", "M"), ("exports", "X")):
            b_all, have_b = 0.0, False
            for g, gr in r["groups"].items():
                b = gr["comp"].get(key)
                if b is None or isnan(b):
                    continue
                if g != "fish":  # all food: without fish, as its trade total
                    b_all, have_b = b_all + b, True
                parts = trade.get(iso, {}).get(g, {}).get(flow)
                if parts:
                    pairs[(g, flow)].append((iso, sum(parts.values()) / 1000, b))
            parts = trade.get(iso, {}).get("all", {}).get(flow)
            if parts and have_b:
                pairs[("all", flow)].append((iso, sum(parts.values()) / 1000, b_all))
    out = []
    for (g, flow), rows in pairs.items():
        rows = [(i, t, b) for i, t, b in rows if b > 0 and (b > 20 or t > 20)]
        if not rows:
            continue
        typical = float(np.median([t / b for _, t, b in rows]))
        out += [[i, g, flow, round(t), round(b)] for i, t, b in rows
                if t / b > 3 * typical and t / b > 1.5]
    return sorted(out)


# Methodology, "Trends": a year more than 3x, or under a third of, both neighbours (all >= 5%).
def unusual_years(series, years):
    out = []
    for k in range(1, len(series) - 1):
        a, b, c = series[k - 1], series[k], series[k + 1]
        if any(v is None or isnan(v) for v in (a, b, c)) or min(a, b, c) < 5:
            continue
        if b > 3 * max(a, c) or 3 * b < min(a, c):
            out.append(years[k])
    return out


def intra_eu_dairy_claim(D):
    """FAO members' dairy trade with other members, window mean, Mt (members' imports x
    (1 - extra-EU share)), the methodology's 'members report buying far more ...' comparison."""
    tot = {"imports": 0.0, "exports": 0.0}
    for m in EU:
        for y in D.WIN:
            for c in D.DAIRY:
                r = D.yearly[m].get((c, y))
                if r is None:
                    continue
                tot["imports"] += nz(r["M"]) * (1 - eu_share(D, m, "imports", y, c))
                tot["exports"] += nz(r["X"]) * (1 - eu_share(D, m, "exports", y, c))
    return {k: v / len(D.WIN) / 1000 for k, v in tot.items()}


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------
SHAS = {}


def main():
    for k, p in {"fbs_zip": FBS_ZIP, "trade_matrix_zip": TM_ZIP, "jrc_csv": JRC_CSV}.items():
        SHAS[k] = sha256(p)
    SHAS["usda_psd_zip"] = sha256(USDA_ZIP)
    SHAS["comext_gz"] = sha256(COMEXT_GZ)
    SHAS["eumofa_xlsx"] = sha256(EUMOFA_XLSX)
    SHAS["baci_zip"] = sha256(BACI_ZIP)
    for k in ("ssr.json", "items.json", "trade.json", "seasons.json", "regions.json", "import_months.json",
              "cropmap.json", "scenario.json"):
        SHAS["export:" + k] = sha256(OUT_DIR / k)
    log("hashed inputs")
    D = load_all()
    res = compute_balances(D, PRIMARY)
    log(f"balances (primary reading) for {sum('groups' in r for r in res.values())} countries")
    alt_res = {name: compute_balances(D, o) for name, o in ALTERNATIVES.items()}
    alts = {name: flatten(r) for name, r in alt_res.items()}
    log("alternative readings computed")
    usda, usda_unmapped = load_usda(D.WIN)
    usda_rec = usda_flags(D, res, usda)
    usda_alt = usda_flags(D, res, usda, "both")
    log(f"USDA PSD: {len(usda)} country-commodity pairs, {len(usda_rec)} groups flagged")
    trade, mirror, _ = build_trade(D, res)
    trade_alts = {
        "grown: origins < 0.5 t dropped": build_trade(D, res, 0.5)[0],
        "grown: origins < 0.5 t dropped + avg=item_years_skipna":
            build_trade(D, alt_res["avg=item_years_skipna"], 0.5)[0],
    }
    log("trade recomputed")

    ssr = json.load(open(OUT_DIR / "ssr.json"))
    items = json.load(open(OUT_DIR / "items.json"))
    tr = json.load(open(OUT_DIR / "trade.json"))
    counts, nmis, mism = defaultdict(int), defaultdict(int), []

    def record(cat, where, exp, rec, explained=None):
        nmis[cat] += 1
        m = {"category": cat, **where, "exported": exp,
             "recomputed": round(rec, 4) if isinstance(rec, float) and not isnan(rec) else
             (None if isinstance(rec, float) else rec)}
        if explained:
            m["explained_by_alternative_reading"] = explained
        mism.append(m)

    # ---- meta ----
    m = ssr["meta"]
    for field, exp, rec in (("years", m["years"], f"{D.WIN[0]}-{D.WIN[-1]}"),
                            ("trend_years", m["trend_years"], D.TREND),
                            ("eu_members", sorted(m["eu_members"]), EU)):
        counts["meta"] += 1
        if exp != rec:
            record("meta", {"file": "ssr.json", "field": field}, exp, rec)
    # averages: food kg/person (sum food / sum population) and population-weighted protein
    for key, isos in (("europe_avg", [c["iso3"] for c in EUROPE]),
                      ("world_avg", [i for i in res if i != "EU27"])):
        isos = [i for i in isos if "groups" in res.get(i, {})]
        tp = sum(res[i]["population_k"] for i in isos)
        for g, v in m.get(key, {}).items():
            if g == "all":
                rec = sum(res[i]["all"]["g_per_day"] * res[i]["population_k"] for i in isos) / tp
                exp, field = v.get("protein_g"), f"{key}.all.protein_g"
            else:
                rec = sum(nz(res[i]["groups"][g]["comp"]["food"]) for i in isos
                          if g in res[i]["groups"]) * 1000 / tp
                exp, field = v.get("food_kg_pc"), f"{key}.{g}.food_kg_pc"
            counts["averages"] += 1
            if not same(exp, rec, 1):
                record("averages", {"file": "ssr.json", "field": field}, exp, rec)
    claim = intra_eu_dairy_claim(D)
    for k, exp in m.get("claims", {}).get("eu_intra_dairy_mt", {}).items():
        counts["claims"] += 1
        if not same(exp, claim[k], 0):
            record("claims", {"file": "ssr.json", "field": f"claims.eu_intra_dairy_mt.{k}"},
                   exp, claim[k])

    # ---- country set / labels ----
    want = set(WORLD.values()) | {"EU27"}
    counts["country_set"] += 2
    if set(ssr["countries"]) != want:
        record("country_set", {"file": "ssr.json", "field": "countries"},
               sorted(set(ssr["countries"]) - want), sorted(want - set(ssr["countries"])))
    has_win = {i for i, r in res.items() if "groups" in r}
    exp_win = {i for i, v in ssr["countries"].items() if "indicators" in v}
    if exp_win != has_win:
        record("country_set", {"file": "ssr.json", "field": "countries with indicators"},
               sorted(exp_win - has_win), sorted(has_win - exp_win))
    for iso, v in ssr["countries"].items():
        for field, rec in (("region", "EU27" if iso == "EU27" else REGION.get(iso, "World")),
                           ("europe", iso == "EU27" or iso in REGION),
                           ("view", "eu_bloc" if iso == "EU27" else "national")):
            counts["labels"] += 1
            if v.get(field) != rec:
                record("labels", {"file": "ssr.json", "country": iso, "field": field},
                       v.get(field), rec)
        if "indicators" in v and iso in res and "groups" in res[iso]:
            exp_g = sorted(g for g in v["indicators"] if g != "all")
            counts["country_set"] += 1
            if exp_g != sorted(res[iso]["groups"]):
                record("country_set", {"file": "ssr.json", "country": iso, "field": "groups"},
                       exp_g, sorted(res[iso]["groups"]))
    counts["country_set"] += 1
    rec_items_c = sorted(i for i, r in res.items() if "items" in r)
    if sorted(items) != rec_items_c:
        record("country_set", {"file": "items.json", "field": "countries"}, sorted(items),
               rec_items_c)
    for iso, groups in items.items():
        for g, rows in groups.items():
            counts["item_set"] += 1
            mine = sorted(res.get(iso, {}).get("items", {}).get(g, {}))
            if sorted(r["item"] for r in rows) != mine:
                record("item_set", {"file": "items.json", "country": iso, "group": g, "field": "items"},
                       sorted(r["item"] for r in rows), mine)

    # ---- every exported number in ssr.json / items.json ----
    exp_flat = flatten_export(ssr, items, D.TREND)
    rec_flat = flatten(res)
    paths = set(exp_flat)
    # ratios/trends the export leaves out but the recompute has are mismatches too
    for p, (v, dp) in rec_flat.items():
        if p in paths or dp is None or isnan(v) or "components_kt" in p:
            continue
        iso_ok = p.split("|")[1] in exp_win or "|trend|" in p
        if iso_ok and (("|trend|" in p and p.split("|")[1] in ssr["countries"]) or
                       p.endswith(("tonnes.ssr", "tonnes.idr", "kcal.ssr", "kcal.idr", "|ssr"))):
            paths.add(p)
    for p in sorted(paths):
        exp = exp_flat.get(p)
        rec, dp = rec_flat.get(p, (math.nan, 1))
        if dp is None and rec is math.nan:
            rec = None
        cat = category(p)
        counts[cat] += 1
        if same(exp, rec, dp):
            continue
        explained = [name for name, af in alts.items()
                     if same(exp, af.get(p, (math.nan, dp))[0], dp)]
        record(cat, describe(p, D.TREND), exp, rec, explained)
    # FAO against USDA: the per-group `usda` arrays
    exp_usda = {(iso, g): {x["item"]: x for x in gi.get("usda", [])}
                for iso, v in ssr["countries"].items()
                for g, gi in v.get("indicators", {}).items() if g != "all" and gi.get("usda")}
    for key in sorted(set(exp_usda) | set(usda_rec)):
        iso, g = key
        e, r_ = exp_usda.get(key, {}), usda_rec.get(key, {})
        w = {"file": "ssr.json", "country": iso, "group": g}
        counts["usda_items"] += 1
        if sorted(e) != sorted(r_):
            why = (["usda use >= 50 kt on both sources"]
                   if sorted(e) == sorted(usda_alt.get(key, {})) else [])
            record("usda_items", {**w, "field": "usda[].item"}, sorted(e), sorted(r_), why)
        for item in set(e) & set(r_):
            for k, idx in (("fao", 0), ("usda", 1)):
                counts["usda_values"] += 1
                if not same(e[item].get(k), r_[item][idx], 1):
                    record("usda_values", {**w, "field": f"usda[{item}].{k}"}, e[item].get(k),
                           r_[item][idx])
    # withheld balances must have null ratios
    for iso, v in ssr["countries"].items():
        for g, gi in v.get("indicators", {}).items():
            if "withheld" in gi:
                counts["withheld_null_ratios"] += 1
                if any(gi.get(b, {}).get(f) is not None for b in ("tonnes", "kcal")
                       for f in ("ssr", "idr")):
                    record("withheld_null_ratios", {"file": "ssr.json", "country": iso, "group": g,
                                                    "field": "ratio present on withheld"}, True, False)

    # ---- trade.json ----
    counts["trade_mirror"] += 1
    if sorted(tr["meta"]["mirror"]) != sorted(mirror):
        record("trade_mirror", {"file": "trade.json", "field": "meta.mirror"},
               sorted(set(tr["meta"]["mirror"]) - mirror), sorted(mirror - set(tr["meta"]["mirror"])))
    def tvals(tobj, iso, g, flow):
        return tobj.get(iso, {}).get(g, {}).get(flow, {})

    def explain_trade(flow, check):
        """Names of alternative readings under which `check(values)` passes."""
        why = [n for n, t in trade_alts.items() if flow == "grown" and check(t)]
        return why

    # ---- withheld trade flows (methodology: "Trade records against the food balance") ----
    w_rec = trade_withheld(trade, res)
    hidden = {(i, g, f2) for i, g, f, *_ in w_rec for f2 in (["imports", "grown"] if f == "imports" else [f])}
    rec_by = {tuple(w[:3]): w for w in w_rec}
    exp_by = {tuple(w[:3]): w for w in tr["meta"].get("withheld", [])}
    for k in sorted(set(rec_by) | set(exp_by)):
        counts["trade_withheld"] += 1
        e, r_ = exp_by.get(k), rec_by.get(k)
        if e is None or r_ is None or abs(e[3] - r_[3]) > 1 or abs(e[4] - r_[4]) > 1:
            record("trade_withheld", {"file": "trade.json", "country": k[0], "group": k[1], "flow": k[2],
                                      "field": "meta.withheld"}, e, r_)

    # ---- concentration (methodology, "Trade partners": HHI over all partners) ----
    exp_h = tr.get("concentration", {})
    for iso, gs in trade.items():
        for g, fl in gs.items():
            for flow in ("imports", "exports"):
                parts = fl.get(flow)
                tot = sum(parts.values()) if parts else 0
                if not tot > 0 or (iso, g, flow) in hidden or iso not in tr["countries"]:
                    continue
                mine = round(sum((100 * v / tot) ** 2 for v in parts.values()))
                e = exp_h.get(iso, {}).get(g, {}).get(flow)
                counts["trade_hhi"] += 1
                if e is None or abs(e - mine) > 1:
                    record("trade_hhi", {"file": "trade.json", "country": iso, "group": g, "flow": flow,
                                         "field": "concentration"}, e, mine)

    # ---- scenario (methodology "Scenario") ----
    sc = json.load(open(OUT_DIR / "scenario.json"))["countries"]
    mine_sc = scenario_rows(res, D, trade, hidden)
    for iso in sorted(set(sc) | set(mine_sc)):
        for g in sorted(set(sc.get(iso, {})) | set(mine_sc.get(iso, {}))):
            e, m_ = sc.get(iso, {}).get(g), mine_sc.get(iso, {}).get(g)
            counts["scenario"] += 1
            if e is None or m_ is None or abs(e - m_) > 0.05 + 1e-9:
                record("scenario", {"file": "scenario.json", "country": iso, "group": g, "field": "lack"},
                       e, None if m_ is None else round(m_, 1))

    # ---- feed (methodology "Feed") ----
    mine_f = feed_rows(res, D)
    for iso in sorted(set(mine_f) | {i for i, c in ssr["countries"].items() if c.get("feed")}):
        e = ssr["countries"].get(iso, {}).get("feed")
        m_ = mine_f.get(iso)
        w = {"file": "ssr.json", "country": iso, "field": "feed"}
        counts["feed"] += 4
        if e is None or m_ is None:
            if iso in ssr["countries"]:
                record("feed", {**w, "field": "feed presence"}, e is not None, m_ is not None)
            continue
        def off(a, b):
            return (a is None) != (b is None or isnan(b)) or (a is not None and abs(a - b) > 0.05 + 1e-9)
        for k, mv in (("imported_pct", m_[0]), ("meat_ssr", m_[2]), ("eggs_ssr", m_[3]), ("items_pct", m_[4])):
            if off(e.get(k), mv):
                record("feed", {**w, "field": f"feed.{k}"}, e.get(k), None if isnan(mv) else round(mv, 1))
        counts["feed_top"] += 1
        if [x[0] for x in e["top"]] != [x[0] for x in m_[1]] or any(abs(a[1] - b[1]) > 1 for a, b in zip(e["top"], m_[1])):
            record("feed_top", {**w, "field": "feed.top"}, e["top"], m_[1])

    # ---- import months (methodology "When it comes from abroad") ----
    im = json.load(open(OUT_DIR / "import_months.json"))["countries"]
    mine_m = import_months(D.WIN)
    for iso in sorted(set(im) | set(mine_m)):
        for g in sorted(set(im.get(iso, {})) | set(mine_m.get(iso, {}))):
            e, m_ = im.get(iso, {}).get(g, []), mine_m.get(iso, {}).get(g, [])
            w = {"file": "import_months.json", "country": iso, "group": g}
            counts["import_months_rows"] += 1
            if [x["hs4"] for x in e] != [x[0] for x in m_]:
                record("import_months_rows", {**w, "field": "products"}, [x["hs4"] for x in e], [x[0] for x in m_])
                continue
            for a_, (h, share, top) in zip(e, m_):
                counts["import_months"] += 12
                if any(abs(x - y) > 0.05 + 1e-9 for x, y in zip(a_["share"], share)):
                    record("import_months", {**w, "field": f"{h}.share"}, a_["share"], [round(x, 1) for x in share])
                for k, (x, y) in enumerate(zip(a_["top"], top)):
                    counts["import_months_top"] += 1
                    if (x is None) != (y is None) or (x and (x[0] != y[0] or abs(x[1] - y[1]) > 0.5 + 1e-9)):
                        record("import_months_top", {**w, "field": f"{h}.top.{k + 1}"}, x, y and [y[0], round(y[1])])

    # ---- crop map images (methodology "Fields") ----
    cmj = json.load(open(OUT_DIR / "cropmap.json"))
    for g, (exact, worst) in cropmap_check(cmj).items():
        counts["cropmap_pixels"] += 4000
        if exact < 0.99:
            record("cropmap_pixels", {"file": "cropmap.json", "group": g, "field": "shade"},
                   ">=99% exact", f"{exact:.1%} exact, worst {worst}")

    # ---- regions (methodology "Where it is grown") ----
    reg = json.load(open(OUT_DIR / "regions.json"))
    mine_r, mine_b = region_rows(D.WIN)
    for g, b in sorted(mine_b.items()):
        counts["region_breaks"] += 1
        e = reg["meta"]["breaks"].get(g)
        if e is None or any(abs(a - b_) > 1e-9 * max(1, abs(b_)) for a, b_ in zip(e, b)):
            record("region_breaks", {"file": "regions.json", "group": g, "field": "breaks"}, e, b)
    for iso in sorted(set(reg["countries"]) | set(mine_r)):
        for g in sorted(set(reg["countries"].get(iso, {})) | set(mine_r.get(iso, {}))):
            e, m_ = reg["countries"].get(iso, {}).get(g), mine_r.get(iso, {}).get(g)
            w = {"file": "regions.json", "country": iso, "group": g}
            counts["region_sets"] += 1
            if e is None or m_ is None or {r[0] for r in e["regions"]} != set(m_["regions"]) \
                    or e["coverage"] != m_["coverage"]:
                record("region_sets", {**w, "field": "regions"}, e and sorted(r[0] for r in e["regions"]),
                       m_ and sorted(m_["regions"]))
                continue
            for code, kt, share, dens in e["regions"]:
                k2, s2, d2 = m_["regions"][code]
                counts["region_values"] += 3
                if abs(kt - k2) > 0.5 + 1e-6 or abs(share - s2) > 0.05 + 1e-6 or abs(dens - d2) > 0.5 + 1e-6:
                    record("region_values", {**w, "field": code}, [kt, share, dens], [round(k2), round(s2, 1), round(d2)])

    # ---- seasons (methodology "Seasons") ----
    sea = json.load(open(OUT_DIR / "seasons.json"))["countries"]
    mine_s = season_rows(res, D)
    for iso in sorted(set(sea) | set(mine_s)):
        for g in sorted(set(sea.get(iso, {})) | set(mine_s.get(iso, {}))):
            e, m_ = sea.get(iso, {}).get(g, []), mine_s.get(iso, {}).get(g, [])
            w = {"file": "seasons.json", "country": iso, "group": g}
            counts["season_rows"] += 1
            if [x["label"] for x in e] != [x["label"] for x in m_] or \
                    any(abs(a["share"] - b["share"]) > 1 for a, b in zip(e, m_)):
                record("season_rows", {**w, "field": "crops"}, [(x["label"], x["share"]) for x in e],
                       [(x["label"], x["share"]) for x in m_])
                continue
            for a, b in zip(e, m_):
                for f in ("sown", "growing", "harvest"):
                    counts["season_months"] += 12
                    if any(abs(x - y) > 1 for x, y in zip(a[f], b[f])):
                        record("season_months", {**w, "field": f"{a['label']}.{f}"}, a[f], b[f])

    # ---- value basis (methodology "Value basis"): totals, listed partners, HHI, in thousand EUR ----
    val = comext_value(D.WIN)
    exp_v = (tr.get("value") or {}).get("countries", {})
    exp_vh = (tr.get("value") or {}).get("concentration", {})
    keys = {(c, g, f) for c, gs in val.items() for g, fl in gs.items() for f, parts in fl.items()
            if sum(parts.values()) > 0} | {(c, g, f) for c, gs in exp_v.items() for g, fl in gs.items() for f in fl}
    for c, g, f in sorted(keys):
        w = {"file": "trade.json", "country": c, "group": g, "flow": f, "field": "value"}
        parts = val.get(c, {}).get(g, {}).get(f, {})
        tot = sum(parts.values()) / 1000
        e = exp_v.get(c, {}).get(g, {}).get(f)
        counts["value_total"] += 1
        if e is None or abs(e[0] - tot) > 1:
            record("value_total", w, e and e[0], round(tot))
            continue
        top = sorted(parts.items(), key=lambda kv: -kv[1])
        want = [[p, round(v / 1000)] for p, v in top if v / 1000 >= 0.005 * tot][:24]
        counts["value_partner"] += 1
        if [p for p, _ in e[1]] != [p for p, _ in want] or any(abs(a[1] - b[1]) > 1 for a, b in zip(e[1], want)):
            record("value_partner", w, e[1][:5], want[:5])
        counts["value_hhi"] += 1
        mine = round(sum((100 * v / (tot * 1000)) ** 2 for v in parts.values()))
        eh = exp_vh.get(c, {}).get(g, {}).get(f)
        if eh is None or abs(eh - mine) > 1:
            record("value_hhi", w, eh, mine)

    for iso, groups in tr["countries"].items():
        for g, flows in groups.items():
            for flow, (total, parts) in flows.items():
                w = {"file": "trade.json", "country": iso, "group": g, "flow": flow}
                if (iso, g, flow) in hidden:
                    counts["trade_withheld"] += 1
                    record("trade_withheld", {**w, "field": "withheld but published"}, total, None)
                mine = tvals(trade, iso, g, flow)
                mt = sum(mine.values())
                cat = "trade_grown" if flow == "grown" else "trade"
                counts[cat + "_total"] += 1
                if not same(total, mt, 0):
                    why = explain_trade(flow, lambda t: same(total, sum(tvals(t, iso, g, flow).values()), 0))
                    if not why and flow == "grown" and same(total, mt, 0, 1e-3):
                        why = ["numerical (< 0.1%)"]
                    record(cat + "_total", {**w, "field": "total"}, total, mt, why)
                for p, val in parts:
                    counts[cat + "_partner"] += 1
                    pv = mine.get(p, 0.0)
                    if not same(val, pv, 0):
                        why = explain_trade(flow, lambda t: same(val, tvals(t, iso, g, flow).get(p, 0.0), 0))
                        if not why and flow == "grown" and same(val, pv, 0, 1e-3):
                            why = ["numerical (< 0.1%)"]
                        record(cat + "_partner", {**w, "field": f"partner.{p}"}, val, pv, why)
                listed = {q for q, _ in parts}

                def missing_in(vals):
                    tot = sum(vals.values())
                    if tot <= 0:
                        return []
                    top = [q for q, v in sorted(vals.items(), key=lambda kv: -kv[1])
                           if v / tot >= 0.005][:24]
                    # tolerate partners sitting right at the 0.5% cut
                    return [q for q in top if q not in listed and vals[q] / tot >= 0.0051]

                counts[cat + "_partner_set"] += 1
                missing = missing_in(mine)
                if missing:
                    why = explain_trade(flow, lambda t: not missing_in(tvals(t, iso, g, flow)))
                    record(cat + "_partner_set", {**w, "field": "partners >= 0.5% not listed"},
                           [], missing, why)
                counts["trade_consistency"] += 1
                s_parts = sum(v for _, v in parts)
                shares_ok = all(v >= 0 for _, v in parts) and len(parts) <= 24
                if s_parts > total + 0.5 * len(parts) + 1 or not shares_ok or \
                        any((v + 0.5) / total < 0.005 for _, v in parts if total > 0):
                    record("trade_consistency", {**w, "field": "partners sum<=total, >=0.5%, <=24"},
                           total, s_parts)
        for g, flows in trade.get(iso, {}).items():
            for flow, mine in flows.items():
                if round(sum(mine.values())) >= 1 and flow not in groups.get(g, {}) \
                        and (iso, g, flow) not in hidden:
                    counts["trade_presence"] += 1
                    why = explain_trade(flow, lambda t: round(sum(tvals(t, iso, g, flow).values())) < 1)
                    record("trade_presence", {"file": "trade.json", "country": iso, "group": g,
                                              "flow": flow, "field": "flow missing in export"},
                           None, sum(mine.values()), why)
    for iso in trade:
        if iso not in tr["countries"] and any(round(sum(m_.values())) >= 1
                                              for fl in trade[iso].values() for m_ in fl.values()):
            counts["trade_presence"] += 1
            record("trade_presence", {"file": "trade.json", "country": iso,
                                      "field": "country missing in export"}, None, "has trade")

    # ---- unusual years in trends (methodology: "Trends") ----
    for iso in sorted(set(res) | {i for i, c in ssr["countries"].items() if "trend_unusual" in c}):
        mine = {g: ys for g, s in res.get(iso, {}).get("trend", {}).items()
                if (ys := unusual_years(s, D.TREND))}
        exp = ssr["countries"].get(iso, {}).get("trend_unusual", {})
        for g in sorted(set(mine) | set(exp)):
            counts["trend_unusual"] += 1
            if sorted(mine.get(g, [])) != sorted(exp.get(g, [])):
                record("trend_unusual", {"file": "ssr.json", "country": iso, "group": g,
                                         "field": "trend_unusual"}, exp.get(g), mine.get(g))

    not_recomputed = [
        {"field": "ssr.json groups[*] (label, plain, notes, items) and countries[*].name/notes",
         "why": "text copied from products.yaml / countries.yaml, not computed"},
        {"field": "ssr.json meta.sources, meta.generated, meta.formulas, meta.elements",
         "why": "provenance text"},
        {"field": "trade.json names", "why": "display names from trade_only.csv"},
        {"field": "ssr.json components_kt key presence",
         "why": "only values of the keys the export carries are compared; which use keys are "
                "omitted when FAO has no row is presentation"},
        {"field": "countries.geojson", "why": "geometry, out of scope"},
    ]
    total = sum(nmis.values())
    unexplained = sum(1 for x in mism if not x.get("explained_by_alternative_reading"))
    # list unexplained first, then ssr/items, then trade; summary by (category, explanation)
    mism.sort(key=lambda x: (bool(x.get("explained_by_alternative_reading")),
                             x["category"].startswith("trade")))
    summary = defaultdict(int)
    for x in mism:
        summary[f'{x["category"]} | {" OR ".join(x.get("explained_by_alternative_reading") or ["UNEXPLAINED"])}'] += 1
    report = {
        "ok": total == 0,
        "n_mismatches": total,
        "published_sha256": {k: SHAS["export:" + k] for k in ("ssr.json", "items.json", "trade.json", "seasons.json", "regions.json",
                                                              "import_months.json", "cropmap.json", "scenario.json")},
        "runtime_s": round(time.time() - T0, 1),
        "window": f"{D.WIN[0]}-{D.WIN[-1]}",
        "primary_reading": PRIMARY,
        "alternative_readings": ALTERNATIVES,
        "compared": dict(sorted(counts.items())),
        "compared_total": sum(counts.values()),
        "mismatches_by_category": dict(sorted(nmis.items())),
        "mismatches_total": total,
        "mismatches_not_explained_by_an_alternative_reading": unexplained,
        "mismatch_summary": dict(sorted(summary.items())),
        "mismatches_listed": min(len(mism), 500),
        "mismatches": mism[:500],
        "not_recomputed": not_recomputed,
        "usda_psd_names_with_window_data_not_compared": usda_unmapped,
        "inputs_sha256": SHAS,
    }
    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=float))
    FULL_MISMATCHES.write_text(json.dumps(mism, ensure_ascii=False, default=float))
    log(f"compared {report['compared_total']:,} values, {total:,} mismatches "
        f"({unexplained} not explained by an alternative reading) -> {REPORT}")
    for k, v in sorted(nmis.items()):
        log(f"  {k}: {v} / {counts[k]}")
    sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()
