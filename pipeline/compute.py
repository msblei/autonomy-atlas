"""Indicators from the harmonised FBS table.

SSR = production / domestic supply * 100
IDR = imports    / domestic supply * 100

See docs/methodology.md for conventions (component averaging, bases, NaN handling).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config
from .harmonise import item_to_group

log = logging.getLogger(__name__)

COMPONENTS = ["production", "imports", "exports", "supply", "stock_variation", "feed", "food"]
# Components shown per person (kg/person/year) in the plain-language view.
PER_CAPITA = ["production", "imports", "exports", "supply", "feed", "food"]
POPULATION_ITEM = "Population"


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
    cols = [c for c in COMPONENTS + ["kcal", "population"] if c in sub]
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


# ------------------------------------------------------------------------------------------------


def latest_window(wide: pd.DataFrame, n: int = config.WINDOW_YEARS) -> tuple[int, int]:
    y1 = int(wide["year"].max())
    return (y1 - n + 1, y1)


def compute(fbs: pd.DataFrame, *, years: tuple[int, int] | None = None) -> dict[str, pd.DataFrame]:
    """Returns {'items': ..., 'groups': ...} tidy frames for the window (default: latest 3 years)."""
    wide = to_wide(fbs)
    years = years or latest_window(wide)
    log.info("window %s", years)

    items = window_mean(wide, years)
    if "population" not in items:
        items["population"] = np.nan
    is_pop = items["item"] == POPULATION_ITEM
    population = items.loc[is_pop, ["iso3", "population"]]
    items = add_ratios(items[~is_pop].drop(columns="population"))
    items["basis"] = "tonnes"
    items = items.merge(item_to_group(), on="item", how="left")

    groups = pd.concat([group_tonnes(items), group_kcal(items)], ignore_index=True)
    items = add_per_capita(items, population)
    groups = add_per_capita(groups, population)

    for df in (items, groups):
        df["source"] = "FAOSTAT FBS"
        df["view"] = "national"  # eu_bloc view needs trade partners: phase 2
    return {"items": items, "groups": groups}


def run(*, years: tuple[int, int] | None = None) -> None:
    config.ensure_dirs()
    fbs = pd.read_parquet(config.INTERIM / "fbs.parquet")
    res = compute(fbs, years=years)
    for name, df in res.items():
        out = config.PROCESSED / f"ssr_{name}.parquet"
        df.to_parquet(out, index=False)
        log.info("wrote %s (%d rows)", out, len(df))
