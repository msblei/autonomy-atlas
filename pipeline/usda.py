"""FAO against an independent source: USDA's Production, Supply and Distribution (PSD) database.

PSD is built by USDA's attachés and analysts from national statistics, customs data and their own
estimates, independently of FAO. It covers the commodities that matter most for self-sufficiency
(cereals, oilseeds, vegetable oils, sugar, meat, butter, coffee) for about 190 countries, with
EU members only as "European Union" (extra-EU trade, like our EU27 bloc).

For each country and commodity we compare the 3-year averages of production, imports, exports,
domestic use and the SSR. It does not change any published figure: large gaps become warnings in
`atlas validate` and the audit page, and the summary measures how far FAO and USDA agree
(docs/methodology.md, "FAO against USDA").

Differences that are expected, not errors:
- PSD uses marketing years (wheat in the EU: July-June), labelled by their start year; FBS uses
  calendar years. Market year y is compared with calendar year y.
- PSD's domestic consumption excludes stock changes, like FBS domestic supply (D = P + M - X - dS).
- Poultry: PSD has chicken only, FBS all poultry. Sugar: PSD centrifugal sugar, raw value; FBS
  "Sugar (Raw Equivalent)" is the same concept. Coffee: PSD 60 kg bags, converted.

Licence: US government work, public domain (cite USDA FAS PSD Online).
"""

from __future__ import annotations

import logging
import zipfile

import numpy as np
import pandas as pd

from . import config

log = logging.getLogger(__name__)

ZIP = config.RAW / "usda" / "psd_alldata_csv.zip"
OUT = config.PROCESSED / "usda_comparison.parquet"

# PSD commodity -> (FBS item, factor to 1000 t, PSD attribute for domestic use)
COMMODITIES = {
    "Wheat": ("Wheat and products", 1.0, "Domestic Consumption"),
    "Corn": ("Maize and products", 1.0, "Domestic Consumption"),
    "Rice, Milled": ("Rice and products", 1.0, "Domestic Consumption"),
    "Barley": ("Barley and products", 1.0, "Domestic Consumption"),
    "Rye": ("Rye and products", 1.0, "Domestic Consumption"),
    "Oats": ("Oats", 1.0, "Domestic Consumption"),
    "Sorghum": ("Sorghum and products", 1.0, "Domestic Consumption"),
    "Millet": ("Millet and products", 1.0, "Domestic Consumption"),
    "Oilseed, Soybean": ("Soyabeans", 1.0, "Domestic Consumption"),
    "Oilseed, Rapeseed": ("Rape and Mustardseed", 1.0, "Domestic Consumption"),
    "Oilseed, Sunflowerseed": ("Sunflower seed", 1.0, "Domestic Consumption"),
    "Oilseed, Peanut": ("Groundnuts", 1.0, "Domestic Consumption"),
    "Oil, Soybean": ("Soyabean Oil", 1.0, "Domestic Consumption"),
    "Oil, Sunflowerseed": ("Sunflowerseed Oil", 1.0, "Domestic Consumption"),
    "Oil, Rapeseed": ("Rape and Mustard Oil", 1.0, "Domestic Consumption"),
    "Oil, Palm": ("Palm Oil", 1.0, "Domestic Consumption"),
    "Oil, Olive": ("Olive Oil", 1.0, "Domestic Consumption"),
    "Sugar, Centrifugal": ("Sugar (Raw Equivalent)", 1.0, "Total Disappearance"),
    "Meat, Beef and Veal": ("Bovine Meat", 1.0, "Domestic Consumption"),
    "Meat, Swine": ("Pigmeat", 1.0, "Domestic Consumption"),
    "Meat, Chicken": ("Poultry Meat", 1.0, "Domestic Consumption"),
    "Dairy, Butter": ("Butter, Ghee", 1.0, "Domestic Consumption"),
    "Coffee, Green": ("Coffee and products", 0.06, "Domestic Consumption"),  # 1000 x 60 kg bags
}

ATTRS = {"Production": "production", "Imports": "imports", "Exports": "exports"}
SSR_GAP_PP, SSR_GAP_REL, MIN_KT = 20.0, 0.20, 50.0  # warn above these (both SSRs, use >= 50 kt)


def load_names() -> pd.Series:
    """PSD Country_Name -> ISO3 ("" = not compared), from mappings/usda_countries.csv."""
    m = pd.read_csv(config.MAPPINGS / "usda_countries.csv", comment="#", dtype=str,
                    keep_default_na=False)
    return m.set_index("psd_name")["iso3"]


def load(years: tuple[int, int], path=ZIP) -> pd.DataFrame | None:
    """PSD 3-year means per iso3 x FBS item: production, imports, exports, supply (1000 t)."""
    if not path.exists():
        log.warning("no %s; run `atlas download --source usda`", path)
        return None
    with zipfile.ZipFile(path) as z:
        d = pd.read_csv(z.open("psd_alldata.csv"), low_memory=False,
                        usecols=["Commodity_Description", "Country_Name", "Market_Year",
                                 "Attribute_Description", "Unit_Description", "Value"])
    d = d[d["Commodity_Description"].isin(COMMODITIES) & d["Market_Year"].between(*years)
          & d["Unit_Description"].str.contains("1000", na=False)
          & ~d["Unit_Description"].str.contains("HA|HEAD", na=False)]
    use_attr = {k: v[2] for k, v in COMMODITIES.items()}
    d = d[d["Attribute_Description"].isin(ATTRS)
          | (d["Attribute_Description"] == d["Commodity_Description"].map(use_attr))]
    d["key"] = d["Attribute_Description"].map(ATTRS).fillna("supply")

    names = load_names()
    iso3 = d["Country_Name"].map(names)
    unknown = sorted(set(d.loc[~d["Country_Name"].isin(names.index), "Country_Name"]))
    if unknown:
        log.warning("PSD countries not in mappings/usda_countries.csv (left out): %s", unknown)
    d = d.assign(iso3=iso3)[iso3.notna() & (iso3 != "")]
    d["item"] = d["Commodity_Description"].map(lambda c: COMMODITIES[c][0])
    d["value"] = d["Value"] * d["Commodity_Description"].map(lambda c: COMMODITIES[c][1])
    n_years = years[1] - years[0] + 1
    w = (d.pivot_table(index=["iso3", "item", "Commodity_Description"], columns="key",
                       values="value", aggfunc="sum") / n_years).reset_index()
    return w.rename(columns={"Commodity_Description": "psd_commodity"})


def compare(fao_items: pd.DataFrame, psd: pd.DataFrame) -> pd.DataFrame:
    """One row per iso3 x item present in both, with each side's components and SSR."""
    cols = ["production", "imports", "exports", "supply"]
    f = fao_items[["iso3", "item", *cols, "ssr", "flag"]]
    j = psd.merge(f, on=["iso3", "item"], suffixes=("_usda", "_fao"), how="inner")
    j["ssr_usda"] = 100 * j["production_usda"] / j["supply_usda"].where(j["supply_usda"] > 0)
    j = j.rename(columns={"ssr": "ssr_fao", "flag": "fao_flag"})
    j["gap_pp"] = j["ssr_fao"] - j["ssr_usda"]
    big = j["supply_usda"].fillna(0).clip(lower=j["supply_fao"].fillna(0)) >= MIN_KT
    j["large_gap"] = big & (j["gap_pp"].abs() > np.maximum(
        SSR_GAP_PP, SSR_GAP_REL * j[["ssr_fao", "ssr_usda"]].min(axis=1)))
    return j


def summary(cmp: pd.DataFrame) -> dict:
    """How far FAO and USDA agree on SSR, over pairs where both are defined and use >= 50 kt."""
    c = cmp[cmp["ssr_fao"].notna() & cmp["ssr_usda"].notna()
            & (cmp["supply_usda"].fillna(0) >= MIN_KT)]
    gap = c["gap_pp"].abs()
    by_item = (c.assign(gap=gap).groupby("psd_commodity")["gap"]
               .agg(pairs="size", median="median", within_10=lambda s: float((s <= 10).mean()))
               .round(2).reset_index().to_dict("records"))
    prod = (c["production_fao"] / c["production_usda"]).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "pairs": len(c),
        "median_gap_pp": round(float(gap.median()), 1) if len(c) else None,
        "share_within_5pp": round(float((gap <= 5).mean()), 3) if len(c) else None,
        "share_within_10pp": round(float((gap <= 10).mean()), 3) if len(c) else None,
        "share_within_20pp": round(float((gap <= 20).mean()), 3) if len(c) else None,
        "production_ratio_median": round(float(prod.median()), 3) if len(prod) else None,
        "by_commodity": by_item,
    }


def run() -> pd.DataFrame | None:
    items = pd.read_parquet(config.PROCESSED / "ssr_items.parquet")
    years = tuple(int(y) for y in items["years"].iloc[0].split("-"))
    psd = load(years)
    if psd is None:
        return None
    cmp = compare(items, psd)
    cmp.to_parquet(OUT, index=False)
    s = summary(cmp)
    log.info("FAO vs USDA PSD: %d pairs, median SSR gap %s pp, %.0f%% within 10 pp",
             s["pairs"], s["median_gap_pp"], 100 * (s["share_within_10pp"] or 0))
    return cmp
