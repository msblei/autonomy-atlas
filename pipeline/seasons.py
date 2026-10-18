"""When crops are sown and harvested: a typical year per country and crop (methodology, "Seasons").

GGCMI Phase 3 crop calendar (planting and maturity day per 0.5 degree cell) weighted by where each
crop grows (ISIMIP3a 15-crop land use, mean 2019-2021; wheat: GGCMI Phase 2 winter and spring
wheat areas) and summed per country with ISIMIP's fractional country masks.

Output data/processed/seasons.parquet: iso3, crop, month (1-12), sown, growing, harvest (% of the
crop's weighted area in the country), plus weight (the crop's weighted area, arbitrary units).
"""

from __future__ import annotations

import logging

import h5py
import numpy as np
import pandas as pd

from . import config

log = logging.getLogger(__name__)

GGCMI = config.RAW / "ggcmi"
ISIMIP = config.RAW / "isimip"
CALENDAR = "{crop}_{ws}_ggcmi_crop_calendar_phase3_v1.01.nc4"
WHEAT_AREAS = GGCMI / "winter_and_spring_wheat_areas_v1_180627.nc4"
LANDUSE = ISIMIP / "landuse-15crops_histsoc_annual_1901_2021.nc"
MASKS = ISIMIP / "countrymasks-fractional_30arcmin.nc"
OUT = "seasons.parquet"
LANDUSE_YEARS = 3  # the last three years of the land-use file (2019-2021)
WS = {"rf": "rainfed", "ir": "irrigated"}

# GGCMI crop -> (land-use weight, FBS item, group, label). Weight "wheat" = GGCMI Phase 2 areas.
# Cassava and sugar cane are left out: harvested over many months or after more than a year, they
# do not fit one season per cell (GGCMI's single date is a convention there).
CROPS = {
    "wwh": ("wheat", "Wheat and products", "cereals", "Winter wheat"),
    "swh": ("wheat", "Wheat and products", "cereals", "Spring wheat"),
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
# Shown on a food page (methodology, "Seasons"): crops with at least MIN_SHARE of the group's
# production, at most MAX_ROWS; month states from these shares.
MIN_SHARE = 5.0
MAX_ROWS = 4
HARVEST_MIN, SOWN_MIN, GROWING_MIN = 20.0, 20.0, 50.0
# First day of each month in a 365-day year.
MONTH_START = np.array([1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335])


def inputs() -> list:
    cal = [GGCMI / CALENDAR.format(crop=c, ws=w) for c in CROPS for w in WS]
    return cal + [WHEAT_AREAS, LANDUSE, MASKS]


def month_of(doy: np.ndarray) -> np.ndarray:
    """Day of year (1-365, NaN) -> month index 0-11 (-1 for NaN)."""
    m = np.searchsorted(MONTH_START, np.clip(np.nan_to_num(doy, nan=1), 1, 365), side="right") - 1
    return np.where(np.isnan(doy), -1, m)


def _read(path, var) -> np.ndarray:
    with h5py.File(path) as f:
        a = f[var][...].astype("float64")
    a[a > 1e19] = np.nan
    return a


def weights(crop: str, ws: str, cell_area: np.ndarray) -> np.ndarray:
    """Weighted area of a crop in every cell (rainfed or irrigated), flat."""
    kind = CROPS[crop][0]
    if kind == "wheat":
        w = _read(WHEAT_AREAS, f"{crop}_{ws}_area")  # hectares already
        return np.nan_to_num(w).ravel()
    with h5py.File(LANDUSE) as f:
        frac = f[f"{kind}_{WS[ws]}"][-LANDUSE_YEARS:, :, :].astype("float64")
    frac[frac > 1e19] = np.nan
    return (np.nan_to_num(frac).mean(axis=0) * cell_area).ravel()


def masks() -> tuple[list[str], np.ndarray]:
    with h5py.File(MASKS) as f:
        names = [k for k in f if k.startswith("m_") and k != "m_world"]
        m = np.stack([np.nan_to_num(f[k][...].astype("float64")).ravel() for k in names])
    m[m > 1e19] = 0
    return [n[2:] for n in names], m


def compute() -> pd.DataFrame:
    with h5py.File(MASKS) as f:
        lat = f["lat"][...]
    cell_area = np.repeat(np.cos(np.deg2rad(lat))[:, None], 720, axis=1)
    iso, m = masks()
    eu = [i for i, c in enumerate(iso) if c in config.EU27]
    m = np.vstack([m, m[eu].sum(axis=0)])
    iso = iso + ["EU27"]
    keep = m.sum(axis=0) > 0
    m = m[:, keep]
    rows = []
    for crop in CROPS:
        sown = np.zeros((len(iso), 12))
        grow = np.zeros((len(iso), 12))
        harv = np.zeros((len(iso), 12))
        total = np.zeros(len(iso))
        for ws in WS:
            path = GGCMI / CALENDAR.format(crop=crop, ws=ws)
            p = month_of(_read(path, "planting_day").ravel()[keep])
            h = month_of(_read(path, "maturity_day").ravel()[keep])
            w = weights(crop, ws, cell_area)[keep]
            w = np.where((p >= 0) & (h >= 0), w, 0.0)
            one = np.arange(12)
            ps = (p[:, None] == one) * w[:, None]
            hs = (h[:, None] == one) * w[:, None]
            inside = np.where(h[:, None] >= p[:, None], (one >= p[:, None]) & (one <= h[:, None]),
                              (one >= p[:, None]) | (one <= h[:, None]))
            gs = inside * w[:, None]
            sown += m @ ps
            harv += m @ hs
            grow += m @ gs
            total += m @ w
        ok = total > 0
        for i in np.nonzero(ok)[0]:
            for k in range(12):
                rows.append((iso[i], crop, k + 1, 100 * sown[i, k] / total[i], 100 * grow[i, k] / total[i],
                             100 * harv[i, k] / total[i], total[i]))
    return pd.DataFrame(rows, columns=["iso3", "crop", "month", "sown", "growing", "harvest", "weight"])


def run() -> None:
    if not all(p.exists() for p in inputs()):
        log.warning("no crop calendars; run `atlas download --source seasons`")
        (config.PROCESSED / OUT).unlink(missing_ok=True)
        return
    s = compute()
    dest = config.PROCESSED / OUT
    s.to_parquet(dest, index=False)
    log.info("wrote %s (%d countries, %d crops)", dest, s["iso3"].nunique(), s["crop"].nunique())


# Shown rows: winter and spring wheat become one wheat row (their kind is botany, not season:
# India's "spring" wheat is sown in November).
SHOWN = {"wheat": ("wheat", "Wheat and products", "cereals", "Wheat"),
         **{k: v for k, v in CROPS.items() if k not in ("wwh", "swh")}}


def combine_wheat(s: pd.DataFrame) -> pd.DataFrame:
    """Winter + spring wheat -> crop "wheat": monthly shares weighted by the two crops' areas."""
    w = s[s["crop"].isin(["wwh", "swh"])]
    if w.empty:
        return s
    cols = ["sown", "growing", "harvest"]
    x = w.assign(**{c: w[c] * w["weight"] for c in cols})
    g = x.groupby(["iso3", "month"], as_index=False)[cols + ["weight"]].sum()
    g = g[g["weight"] > 0]
    g[cols] = g[cols].div(g["weight"], axis=0)
    return pd.concat([s[~s["crop"].isin(["wwh", "swh"])], g.assign(crop="wheat")], ignore_index=True)


def state(sown: float, growing: float, harvest: float) -> str:
    """The month's state on a food page."""
    if harvest >= HARVEST_MIN:
        return "harvest"
    if sown >= SOWN_MIN:
        return "sowing"
    if growing >= GROWING_MIN:
        return "growing"
    return ""


# Checked against the wheat harvest (docs/methodology.md, "Seasons"): GGCMI's calendars for Europe
# are often month-level placeholders (peas "sown 1 May, ripe 31 October" from Spain to Ukraine;
# wheat "ripe 23 June" in Ireland, Sweden and Austria). Wheat must have at least CHECK_SHARE % of
# its harvest in the International Wheat Council's harvest months for the country; barley, rye,
# rapeseed and peas, which are harvested with or just before wheat, too, where those months lie in
# May-September (northern summer harvests). A row that fails is not shown.
WHEAT_REF = config.MAPPINGS / "wheat_harvest_iwc.csv"
CHECK_SHARE = 50.0
WITH_WHEAT = ("bar", "rye", "rap", "pea")
SUMMER = set(range(4, 9))  # May-September, month index 0-11


def wheat_reference() -> dict[str, set[int]]:
    """iso3 -> harvest month indexes (0-11) from mappings/wheat_harvest_iwc.csv."""
    import csv

    out = {}
    with WHEAT_REF.open(encoding="utf-8") as f:
        for r in csv.DictReader(line for line in f if not line.startswith("#")):
            months = set()
            for span in r["months"].split():
                a, b = (int(x) - 1 for x in span.split("-"))
                months |= {(a + k) % 12 for k in range((b - a) % 12 + 1)}
            out[r["iso3"]] = months
    return out


def fails_reference(row: dict, window: set[int] | None) -> bool:
    """True when the row must be checked and has under CHECK_SHARE % of its harvest in `window`."""
    if window is None:
        return False
    if row["crop"] != "wheat" and not (row["crop"] in WITH_WHEAT and window <= SUMMER):
        return False
    total = sum(row["harvest"])
    return total > 0 and 100 * sum(row["harvest"][k] for k in window) / total < CHECK_SHARE


def rows_for(s: pd.DataFrame, items: pd.DataFrame, groups: dict[str, list[str]],
             dropped: dict | None = None) -> dict:
    """{iso3: {group: [{crop, label, item, share, sown, growing, harvest}]}} for the export.

    `items`: ssr_items rows on the tonnes basis (iso3, item, production); `groups`: products.yaml
    group -> FBS items (sugar uses the sugar crops instead, methodology "Seasons"). Rows that fail
    the wheat-harvest check go to `dropped` ({iso3: {group: [label]}}) instead."""
    ref = wheat_reference()
    prod = items.set_index(["iso3", "item"])["production"]
    s = combine_wheat(s)
    by = {k: g for k, g in s.groupby(["iso3", "crop"])}
    out: dict = {}
    for iso3 in sorted(s["iso3"].unique()):
        for group in sorted({v[2] for v in CROPS.values()}):
            members = ["Sugar beet", "Sugar cane"] if group == "sugar" else groups.get(group, [])
            gp = sum(float(prod.get((iso3, i), 0) or 0) for i in members)
            if not gp > 0:
                continue
            cand = []
            for crop, (_, item, g, label) in SHOWN.items():
                if g != group or (iso3, crop) not in by:
                    continue
                share = 100 * float(prod.get((iso3, item), 0) or 0) / gp
                if share >= MIN_SHARE:
                    c = by[(iso3, crop)].sort_values("month")
                    row = {"crop": crop, "label": label, "item": item, "share": round(share),
                           "sown": [round(x) for x in c["sown"]],
                           "growing": [round(x) for x in c["growing"]],
                           "harvest": [round(x) for x in c["harvest"]]}
                    if fails_reference(row, ref.get(iso3)):
                        if dropped is not None:
                            dropped.setdefault(iso3, {}).setdefault(group, []).append(label)
                        continue
                    cand.append(row)
            if cand:
                cand.sort(key=lambda r: -r["share"])
                out.setdefault(iso3, {})[group] = cand[:MAX_ROWS]
    return out
