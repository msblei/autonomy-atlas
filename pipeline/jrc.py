"""DG AGRI-JRC "EU estimated agricultural balance sheets": dairy balances for EU Member States.

FAO's food balances get dairy trade badly wrong for processing countries (Germany sells cheese,
milk powder and whey but FAO's milk-equivalent conversion turns it into a net importer: SSR 89%
instead of about 116%; Ireland 105% instead of 195%). The JRC dataset rebuilds dairy trade from
Eurostat Comext with intra-EU imports taken as the mirror of partners' exports, and converts every
product to milk equivalent with DG AGRI coefficients (milk-solids basis: butter about 6.6, cheese
3.6, milk powders 7.6 kg milk per kg), so products made from the same milk add up without double
counting.

Per country and year (1000 t milk equivalent):
    production = raw milk produced (commodity type RAW MILK)
    imports    = sum of product imports, intra + extra EU (the EU aggregate: extra-EU only)
    exports    = sum of product exports, intra + extra EU (the EU aggregate: extra-EU only)
    supply     = production + imports - exports          (stock changes are not in the dataset)

Products (no overlaps; aggregates such as FRESH DAIRY PRODUCTS and BUTTER 80-90% are left out
because they are parts of others): drinking milk (also bulk raw milk crossing borders), acidified
milk, cream, buttermilk, total butter, total cheese, skimmed and whole milk powder, whey powder.

The file cannot be fetched by script (the JRC server rejects it); download it by hand, see
config.SOURCES["jrc_bal"], and unzip it into data/raw/jrc/bal/.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config
from .harmonise import load_countries, load_products

log = logging.getLogger(__name__)

ZIP = config.RAW / "jrc" / "Dataset_EU_estimated_agricultural_balance_sheets.zip"
CSV = config.RAW / "jrc" / "bal" / "Dataset_EU_estimated_agricultural_balance_sheets.csv"
PRODUCTS = [
    "DRINKING MILK", "ACIDIFIED MILK", "CREAM FOR DIRECT CONSUMPTION", "BUTTERMILK",
    "TOTAL BUTTER", "TOTAL CHEESE", "SKIMMED MILK POWDER", "WHOLE MILK POWDER", "WHEY POWDER",
]
_ME = "(THOUSAND TONNES (MILK EQ.))"
EU_BLOC = "EU27"


def load_dairy(path=CSV) -> pd.DataFrame | None:
    """Columns: iso3 (members + EU27), year, production, imports, exports, supply (1000 t milk
    equivalent). None when the file has not been downloaded."""
    if not path.exists():
        log.warning("no JRC balance sheets at %s: dairy for EU countries stays FAO's", path)
        return None
    d = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    geo = load_countries().set_index("eurostat")["iso3"].to_dict() | {"EU": EU_BLOC}
    d["iso3"] = d["Country (NUTS Code)"].map(geo)
    d = d[d["iso3"].notna()]

    raw = d[d["Commodity (Type)"] == "RAW MILK"][["iso3", "Year", "Production (THOUSAND TONNES)"]]
    raw = raw.rename(columns={"Year": "year", "Production (THOUSAND TONNES)": "production"})

    p = d[d["Commodity"].isin(PRODUCTS)].copy()
    for flow in ("Imports", "Exports"):
        cols = [f"{flow} (Extra-EU) {_ME}", f"{flow} (Intra-EU) {_ME}"]
        for c in cols:
            p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0.0)
        # The EU as a whole trades only with the rest of the world.
        p[flow.lower()] = np.where(p["iso3"] == EU_BLOC, p[cols[0]], p[cols[0]] + p[cols[1]])
    trade = p.groupby(["iso3", "Year"], as_index=False)[["imports", "exports"]].sum()
    trade = trade.rename(columns={"Year": "year"})

    out = raw.merge(trade, on=["iso3", "year"], how="inner")
    out["production"] = pd.to_numeric(out["production"], errors="coerce")
    out = out[out["production"] > 0]
    out["supply"] = out["production"] + out["imports"] - out["exports"]
    out = out[out["supply"] > 0]
    out["year"] = out["year"].astype(int)
    log.info("JRC dairy balances: %d countries, %d-%d", out["iso3"].nunique(),
             out["year"].min(), out["year"].max())
    return out.reset_index(drop=True)


def apply_dairy(wide: pd.DataFrame, jrc: pd.DataFrame | None,
                utilisation: list[str]) -> pd.DataFrame:
    """Replace the FBS dairy balance (items of the "dairy" group) with the JRC one for the countries
    and years it covers. Each dairy item is scaled so the group adds up to the JRC figures
    (production, imports, exports, supply; uses scaled with supply, stock change set to 0), which
    keeps item-level SSRs, and with them the protein and calorie totals, consistent. Rows changed
    get `dairy_source = "jrc"`."""
    if jrc is None or jrc.empty:
        return wide
    items = set(load_products()["groups"]["dairy"]["items"])
    wide = wide.copy()
    is_dairy = wide["item"].isin(items)
    keys = ["iso3", "year"]
    fao = wide[is_dairy].groupby(keys)[["production", "imports", "exports", "supply"]].sum(min_count=1)
    fac = jrc.set_index(keys).join(fao, rsuffix="_fao", how="inner")
    ratios = pd.DataFrame(index=fac.index)
    for c in ("production", "imports", "exports", "supply"):
        ratios[c] = (fac[c] / fac[f"{c}_fao"]).where(fac[f"{c}_fao"] > 0)

    sel = wide[is_dairy].join(ratios, on=keys, rsuffix="_r")
    hit = sel["supply_r"].notna()
    idx = sel.index[hit]
    for c in ("production", "imports", "exports", "supply"):
        r = sel.loc[hit, f"{c}_r"]
        wide.loc[idx, c] = (wide.loc[idx, c].fillna(0) * r).where(r.notna(), wide.loc[idx, c])
    for c in utilisation:
        if c in wide:
            wide.loc[idx, c] = wide.loc[idx, c] * sel.loc[hit, "supply_r"]
    if "stock_variation" in wide:
        wide.loc[idx, "stock_variation"] = 0.0
    wide["dairy_source"] = None
    wide.loc[idx, "dairy_source"] = "jrc"

    # Components FAO has as zero for every dairy item cannot be scaled: put them on the item with
    # the largest supply (milk).
    for c in ("production", "imports", "exports"):
        for key in fac.index[ratios[c].isna() & (fac[c] > 0)]:
            rows = wide.index[(wide["iso3"] == key[0]) & (wide["year"] == key[1])
                              & (wide["dairy_source"] == "jrc")]
            if len(rows):
                wide.loc[wide.loc[rows, "supply"].idxmax(), c] = fac.loc[key, c]
    log.info("dairy replaced by JRC balances for %d country-years",
             wide.loc[idx, keys].drop_duplicates().shape[0])
    return wide
