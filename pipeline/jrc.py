"""DG AGRI-JRC "EU estimated agricultural balance sheets": balances for EU Member States and the EU
that replace FAO's where FAO's trade figures do not hold up (docs/methodology.md).

The JRC dataset rebuilds trade from Eurostat Comext with intra-EU imports taken as the mirror of
partners' exports, and converts processed products back to the primary product with DG AGRI
coefficients. FAO's figures agree on production but fail on trade in processed goods:

- dairy: Germany sells cheese, milk powder and whey, FAO's milk-equivalent conversion makes it a
  net importer (SSR 89% instead of 116%; Ireland 105% instead of 195%);
- tomatoes: Italy exports tomato paste, FAO leaves 19 kg of tomatoes per Italian (SSR 556%
  instead of 200%);
- olive oil: the EU as a whole comes out at 101% instead of 129%;
- wine: FAO's German production is about half of the 8.2 million hl actually made.

Per food, country and year (1000 t; wine converted from hectolitres at 0.1 t/hl):
    production, imports, exports   members: intra + extra EU; the EU aggregate: extra-EU only
    supply                         JRC apparent use (wine and olive oil include stock changes;
                                   dairy and tomatoes: production + imports - exports)

Dairy is built from its products in milk equivalent (DG AGRI coefficients, milk-solids basis, so
products from the same milk add up): production = raw milk, trade = sum over drinking milk
(also bulk raw milk crossing borders), acidified milk, cream, buttermilk, total butter, total
cheese, skimmed and whole milk powder, whey powder. Aggregates that are parts of others (FRESH
DAIRY PRODUCTS, BUTTER 80-90%) are left out.

The file cannot be fetched by script (the JRC server rejects it); download it by hand, see
config.SOURCES["jrc_bal"], and unzip it into data/raw/jrc/bal/.
"""

from __future__ import annotations

import logging

import pandas as pd

from . import config
from .harmonise import load_countries, load_products

log = logging.getLogger(__name__)

ZIP = config.RAW / "jrc" / "Dataset_EU_estimated_agricultural_balance_sheets.zip"
CSV = config.RAW / "jrc" / "bal" / "Dataset_EU_estimated_agricultural_balance_sheets.csv"
EU_BLOC = "EU27"
DAIRY_PRODUCTS = [
    "DRINKING MILK", "ACIDIFIED MILK", "CREAM FOR DIRECT CONSUMPTION", "BUTTERMILK",
    "TOTAL BUTTER", "TOTAL CHEESE", "SKIMMED MILK POWDER", "WHOLE MILK POWDER", "WHEY POWDER",
]
_ME = "(THOUSAND TONNES (MILK EQ.))"

# food key -> JRC commodity, unit in the JRC column headers, factor to 1000 t, FBS items replaced.
# Dairy's items are the whole products.yaml group.
FOODS = {
    "tomatoes": ("TOMATOES", "THOUSAND TONNES", 1.0, ["Tomatoes and products"]),
    "olive_oil": ("TOTAL OLIVE OIL", "THOUSAND TONNES", 1.0, ["Olive Oil"]),
    "wine": ("WINE", "THOUSAND HECTOLITRES", 0.1, ["Wine"]),
}


def food_items() -> dict[str, list[str]]:
    """food key -> FBS items whose balance the JRC replaces."""
    return {"dairy": list(load_products()["groups"]["dairy"]["items"])} | {
        k: v[3] for k, v in FOODS.items()}


def _read(path) -> pd.DataFrame:
    d = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    geo = load_countries().set_index("eurostat")["iso3"].to_dict() | {"EU": EU_BLOC}
    d["iso3"] = d["Country (NUTS Code)"].map(geo)
    d = d[d["iso3"].notna()].rename(columns={"Year": "year"})
    meta = {"Country", "Country (NUTS Code)", "Country (Description)", "Commodity",
            "Commodity (Type)", "Commodity (Primary product)", "year", "iso3"}
    for c in d.columns.difference(list(meta)):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def _trade(d: pd.DataFrame, flow: str, unit: str) -> pd.Series:
    """Members: intra + extra EU; the EU aggregate trades with the rest of the world only."""
    extra = d[f"{flow} (Extra-EU) ({unit})"].fillna(0.0)
    intra = d[f"{flow} (Intra-EU) ({unit})"].fillna(0.0)
    return extra.where(d["iso3"] == EU_BLOC, extra + intra)


def _dairy(d: pd.DataFrame) -> pd.DataFrame:
    raw = d[d["Commodity (Type)"] == "RAW MILK"][["iso3", "year", "Production (THOUSAND TONNES)"]]
    raw = raw.rename(columns={"Production (THOUSAND TONNES)": "production"})
    p = d[d["Commodity"].isin(DAIRY_PRODUCTS)].copy()
    p["imports"] = _trade(p, "Imports", _ME[1:-1])
    p["exports"] = _trade(p, "Exports", _ME[1:-1])
    trade = p.groupby(["iso3", "year"], as_index=False)[["imports", "exports"]].sum()
    out = raw.merge(trade, on=["iso3", "year"], how="inner")
    out["supply"] = out["production"] + out["imports"] - out["exports"]
    return out.assign(food="dairy")


def _simple(d: pd.DataFrame, food: str) -> pd.DataFrame:
    commodity, unit, factor, _ = FOODS[food]
    s = d[d["Commodity"] == commodity].copy()
    out = pd.DataFrame({
        "iso3": s["iso3"], "year": s["year"],
        "production": s[f"Production ({unit})"] * factor,
        "imports": _trade(s, "Imports", unit) * factor,
        "exports": _trade(s, "Exports", unit) * factor,
        "supply": s[f"Apparent use ({unit})"] * factor,
    })
    return out.assign(food=food)


def load_balances(path=CSV) -> pd.DataFrame | None:
    """Columns: food, iso3 (members + EU27), year, production, imports, exports, supply (1000 t).
    None when the file has not been downloaded."""
    if not path.exists():
        log.warning("no JRC balance sheets at %s: EU dairy, tomatoes, olive oil and wine stay "
                    "FAO's", path)
        return None
    d = _read(path)
    out = pd.concat([_dairy(d)] + [_simple(d, f) for f in FOODS], ignore_index=True)
    out = out[(out["production"].notna()) & (out["supply"] > 0)]
    out["year"] = out["year"].astype(int)
    for food, g in out.groupby("food"):
        log.info("JRC %s: %d countries, %d-%d", food, g["iso3"].nunique(), g["year"].min(),
                 g["year"].max())
    return out.reset_index(drop=True)


def coverage(bal: pd.DataFrame | None, years: tuple[int, int]) -> dict[str, set[str]]:
    """iso3 -> foods whose JRC balance covers every year of `years` (what the UI may cite)."""
    if bal is None:
        return {}
    need = set(range(years[0], years[1] + 1))
    out: dict[str, set[str]] = {}
    for (iso3, food), ys in bal.groupby(["iso3", "food"])["year"]:
        if need <= set(ys):
            out.setdefault(iso3, set()).add(food)
    return out


def apply(wide: pd.DataFrame, bal: pd.DataFrame | None, utilisation: list[str]) -> pd.DataFrame:
    """Replace the FBS balance of each food's items with the JRC one where it is available.

    The items of a food are scaled so they add up to the JRC production, imports, exports and
    supply (uses scaled with supply; stock change set so production + imports - exports - stock
    change = supply), which keeps item-level SSRs, and with them the protein and calorie totals,
    consistent. A component FAO has as zero for all of a food's items goes on its largest item.
    Rows changed get `jrc_food` = the food key."""
    if bal is None or bal.empty:
        return wide
    wide = wide.copy()
    wide["jrc_food"] = None
    keys = ["iso3", "year"]
    comps = ["production", "imports", "exports", "supply"]
    for food, items in food_items().items():
        jb = bal[bal["food"] == food].set_index(keys)[comps]
        is_food = wide["item"].isin(items)
        fao = wide[is_food].groupby(keys)[comps].sum(min_count=1)
        fac = jb.join(fao, rsuffix="_fao", how="inner")
        ratios = pd.DataFrame({c: (fac[c] / fac[f"{c}_fao"]).where(fac[f"{c}_fao"] > 0)
                               for c in comps}, index=fac.index)
        sel = wide[is_food].join(ratios, on=keys, rsuffix="_r")
        hit = sel["supply_r"].notna()
        idx = sel.index[hit]
        for c in comps:
            r = sel.loc[hit, f"{c}_r"]
            wide.loc[idx, c] = (wide.loc[idx, c].fillna(0) * r).where(r.notna(), wide.loc[idx, c])
        for c in utilisation:
            if c in wide:
                wide.loc[idx, c] = wide.loc[idx, c] * sel.loc[hit, "supply_r"]
        wide.loc[idx, "jrc_food"] = food
        for c in ("production", "imports", "exports"):
            for key in fac.index[ratios[c].isna() & (fac[c] > 0)]:
                rows = wide.index[(wide["iso3"] == key[0]) & (wide["year"] == key[1])
                                  & (wide["jrc_food"] == food)]
                if len(rows):
                    wide.loc[wide.loc[rows, "supply"].idxmax(), c] = fac.loc[key, c]
        if "stock_variation" in wide:
            done = wide.loc[idx]
            wide.loc[idx, "stock_variation"] = (done["production"].fillna(0)
                                                + done["imports"].fillna(0)
                                                - done["exports"].fillna(0) - done["supply"])
        log.info("%s replaced by JRC balances for %d country-years", food,
                 wide.loc[idx, keys].drop_duplicates().shape[0])
    return wide
