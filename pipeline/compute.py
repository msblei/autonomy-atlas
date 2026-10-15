"""Indicators from the harmonised FBS table.

SSR = production / domestic supply * 100
IDR = imports    / domestic supply * 100

Also: kg/person/year figures, an "all food" protein/kcal coverage indicator, an EU27 bloc
pseudo-country ("EU27", members summed) and yearly SSR series for trend lines.

See docs/methodology.md for conventions (component averaging, bases, NaN handling).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config
from .harmonise import item_to_group

log = logging.getLogger(__name__)

COMPONENTS = [
    "production", "imports", "exports", "supply", "stock_variation",
    "feed", "food", "seed", "losses", "processing", "other_uses", "tourist", "residuals",
]
# Components shown per person (kg/person/year) in the plain-language view.
PER_CAPITA = [
    "production", "imports", "exports", "supply",
    "feed", "food", "seed", "losses", "processing", "other_uses", "tourist", "residuals",
]
# FBS elements that are already per person; summed across countries by population weight.
PER_CAPITA_ELEMENTS = ["kcal", "protein"]
POPULATION_ITEM = "Population"
EU_BLOC = "EU27"
# FAO aggregate items ("Grand Total", "Cereals - Excluding Beer", ...) have codes >= 2900.
FBS_AGGREGATE_CODE = 2900


# ------------------------------------------------------------------------------------------------
# pure helpers (unit-tested)


def ratio(numerator: pd.Series, supply: pd.Series) -> pd.Series:
    """numerator / supply * 100, NaN where supply is missing or <= 0."""
    sup = supply.where(supply > 0)
    return numerator / sup * 100.0


def to_wide(fbs: pd.DataFrame) -> pd.DataFrame:
    """Long FBS (iso3, item, element, year, value) -> one row per iso3 × item × year,
    with one column per element key in config.FBS_ELEMENTS."""
    name_to_key = {v: k for k, v in config.FBS_ELEMENTS.items()}
    df = fbs[fbs["element"].isin(name_to_key)].copy()
    df["key"] = df["element"].map(name_to_key)
    wide = (
        df.pivot_table(index=["iso3", "item", "year"], columns="key", values="value", aggfunc="first")
        .reset_index()
    )
    for k in config.FBS_ELEMENTS:
        if k not in wide:
            wide[k] = np.nan
    return wide


def window_mean(wide: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Average each component over [y0, y1] per iso3 × item. Ratios are computed afterwards."""
    y0, y1 = years
    sub = wide[(wide["year"] >= y0) & (wide["year"] <= y1)]
    cols = [c for c in COMPONENTS + PER_CAPITA_ELEMENTS + ["population"] if c in sub]
    out = sub.groupby(["iso3", "item"], as_index=False)[cols].mean()
    out["years"] = f"{y0}-{y1}"
    return out


def add_ratios(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ssr"] = ratio(df["production"], df["supply"])
    df["idr"] = ratio(df["imports"], df["supply"])
    df["flag"] = np.where(df["supply"].isna(), "supply_missing",
                 np.where(df["supply"] <= 0, "supply_nonpositive", ""))
    return df


def _with_groups(items: pd.DataFrame) -> pd.DataFrame:
    """Attach group / group_label (if not already present) and drop unmapped items."""
    if "group" not in items:
        items = items.merge(item_to_group(), on="item", how="left")
    return items[items["group"].notna()]


def group_tonnes(items: pd.DataFrame) -> pd.DataFrame:
    """Sum components across items of a group, then compute ratios. Basis: tonnes."""
    g = _with_groups(items)
    agg = g.groupby(["iso3", "group", "group_label", "years"], as_index=False)[COMPONENTS].sum(
        min_count=1
    )
    agg = add_ratios(agg)
    agg["basis"] = "tonnes"
    return agg


def group_kcal(items: pd.DataFrame) -> pd.DataFrame:
    """kcal-weighted mean of item SSR/IDR within a group. Basis: kcal."""
    g = add_ratios(_with_groups(items))
    g = g[g["kcal"].notna() & (g["kcal"] > 0) & g["ssr"].notna()]

    def weighted(sub: pd.DataFrame) -> pd.Series:
        w = sub["kcal"]
        return pd.Series(
            {
                "ssr": np.average(sub["ssr"], weights=w),
                "idr": np.average(sub["idr"].fillna(0), weights=w),
                "kcal": w.sum(),
                "n_items": len(sub),
            }
        )

    out = (
        g.groupby(["iso3", "group", "group_label", "years"])
        .apply(weighted, include_groups=False)
        .reset_index()
    )
    out["basis"] = "kcal"
    out["flag"] = ""
    return out


def add_per_capita(df: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    """Attach population (1000 persons, window mean) and kg/person/year for PER_CAPITA columns.

    FBS quantities are in 1000 t, so kg/person = 1000 t * 1e6 / (1000 persons * 1e3) =
    value * 1000 / population.
    """
    df = df.drop(columns="population", errors="ignore").merge(population, on="iso3", how="left")
    pop = df["population"].where(df["population"] > 0)
    for c in PER_CAPITA:
        df[f"{c}_kg_pc"] = df[c] * 1000.0 / pop
    return df


def leaf_items(fbs: pd.DataFrame) -> set[str]:
    """FBS item names that are single commodities, not FAO aggregates or Population.

    Some names exist both as a leaf and as an identical one-item aggregate ("Eggs" 2744 / 2949);
    those count as leaves. Without item codes (synthetic test frames), use the mapped items.
    """
    if "item_code" not in fbs:
        return set(item_to_group()["item"])
    code = pd.to_numeric(fbs["item_code"].astype(str).str.lstrip("'S"), errors="coerce")
    leaves = set(fbs.loc[code < FBS_AGGREGATE_CODE, "item"])
    return leaves - {POPULATION_ITEM}


def add_eu_bloc(wide: pd.DataFrame) -> pd.DataFrame:
    """Append iso3 == "EU27": members summed per item and year (years with all 27 members only).

    Trade between members cancels out of domestic supply, so EU-wide SSR and net trade are valid.
    Gross imports/exports still contain intra-EU trade (FAO's own EU27 aggregate does the same),
    so they are blanked; IDR for the bloc needs partner data (phase 2).
    """
    members = wide[wide["iso3"].isin(config.EU27)]
    if members.empty:
        return wide
    n = members.groupby("year")["iso3"].nunique()
    full = n[n == len(config.EU27)].index
    if len(full) < len(n):
        log.warning("EU27 bloc skipped for years with missing members: %s",
                    sorted(set(n.index) - set(full)))
    members = members[members["year"].isin(full)]
    if members.empty:
        return wide

    pop = members.loc[members["item"] == POPULATION_ITEM, ["iso3", "year", "population"]]
    m = members.drop(columns="population").merge(pop, on=["iso3", "year"], how="left")
    for c in PER_CAPITA_ELEMENTS:
        m[c] = m[c] * m["population"]  # -> population-weighted sum, divided below
        m[f"{c}_w"] = m["population"].where(m[c].notna())

    cols = [c for c in COMPONENTS if c in m]
    sums = m.groupby(["item", "year"], as_index=False)[
        cols + PER_CAPITA_ELEMENTS + [f"{c}_w" for c in PER_CAPITA_ELEMENTS]
    ].sum(min_count=1)
    for c in PER_CAPITA_ELEMENTS:
        sums[c] = sums[c] / sums.pop(f"{c}_w")
    sums[["imports", "exports"]] = np.nan
    eu_pop = pop.groupby("year", as_index=False)["population"].sum()
    eu_pop["item"] = POPULATION_ITEM
    sums = pd.concat([sums[sums["item"] != POPULATION_ITEM], eu_pop], ignore_index=True)
    sums["iso3"] = EU_BLOC
    return pd.concat([wide, sums], ignore_index=True)


def overall(items: pd.DataFrame, leaves: set[str]) -> pd.DataFrame:
    """"All food": how much of the protein / kcal people eat could own production cover?

    share = sum_i w_i * min(SSR_i, 100) / sum_i w_i, w = protein (g/cap/day) or kcal/cap/day of
    leaf item i. Capping stops a wheat surplus from hiding a soy deficit. `*_ssr` is the uncapped
    weighted mean (can exceed 100) for experts. Livestock products count as home-grown even when
    fed on imported feed (phase 4 adjusts for that).
    """
    g = items[items["item"].isin(leaves) & items["ssr"].notna()]
    rows = []
    for (iso3, years), sub in g.groupby(["iso3", "years"]):
        row = {"iso3": iso3, "years": years}
        for w in PER_CAPITA_ELEMENTS:
            s = sub[sub[w].notna() & (sub[w] > 0)]
            tot = s[w].sum()
            row[w] = tot if tot > 0 else np.nan
            row[f"{w}_share"] = (s[w] * s["ssr"].clip(upper=100)).sum() / tot if tot > 0 else np.nan
            row[f"{w}_ssr"] = (s[w] * s["ssr"]).sum() / tot if tot > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows, columns=["iso3", "years"] + [
        f"{w}{suffix}" for w in PER_CAPITA_ELEMENTS for suffix in ("", "_share", "_ssr")
    ])


# ------------------------------------------------------------------------------------------------


def latest_window(wide: pd.DataFrame, n: int = config.WINDOW_YEARS) -> tuple[int, int]:
    y1 = int(wide["year"].max())
    return (y1 - n + 1, y1)


def _compute_window(wide: pd.DataFrame, years: tuple[int, int], leaves: set[str]) -> dict:
    items = window_mean(wide, years)
    if "population" not in items:
        items["population"] = np.nan
    is_pop = items["item"] == POPULATION_ITEM
    population = items.loc[is_pop, ["iso3", "population"]]
    items = add_ratios(items[~is_pop].drop(columns="population"))
    items["basis"] = "tonnes"
    items = items.merge(item_to_group(), on="item", how="left")

    groups = pd.concat([group_tonnes(items), group_kcal(items)], ignore_index=True)
    totals = overall(items, leaves)
    items = add_per_capita(items, population)
    groups = add_per_capita(groups, population)
    totals = totals.merge(population, on="iso3", how="left")
    return {"items": items, "groups": groups, "overall": totals}


def compute(fbs: pd.DataFrame, *, years: tuple[int, int] | None = None) -> dict[str, pd.DataFrame]:
    """Returns {'items', 'groups', 'overall', 'trends'} tidy frames.

    items/groups/overall cover the window (default: latest 3 years); trends has one SSR value per
    iso3 × group × year (group "all" = protein share) for sparklines.
    """
    wide = add_eu_bloc(to_wide(fbs))
    leaves = leaf_items(fbs)
    years = years or latest_window(wide)
    log.info("window %s", years)
    res = _compute_window(wide, years, leaves)

    trend_rows = []
    for y in sorted(wide["year"].dropna().unique()):
        r = _compute_window(wide, (int(y), int(y)), leaves)
        t = r["groups"][r["groups"]["basis"] == "tonnes"][["iso3", "group", "ssr"]]
        o = r["overall"][["iso3", "protein_share"]].rename(columns={"protein_share": "ssr"})
        o["group"] = "all"
        trend_rows.append(pd.concat([t, o], ignore_index=True).assign(year=int(y)))
    res["trends"] = pd.concat(trend_rows, ignore_index=True) if trend_rows else pd.DataFrame(
        columns=["iso3", "group", "ssr", "year"]
    )

    for df in res.values():
        df["source"] = "FAOSTAT FBS"
        df["view"] = np.where(df["iso3"] == EU_BLOC, "eu_bloc", "national")
    return res


def run(*, years: tuple[int, int] | None = None) -> None:
    config.ensure_dirs()
    fbs = pd.read_parquet(config.INTERIM / "fbs.parquet")
    res = compute(fbs, years=years)
    for name, df in res.items():
        out = config.PROCESSED / f"ssr_{name}.parquet"
        df.to_parquet(out, index=False)
        log.info("wrote %s (%d rows)", out, len(df))
