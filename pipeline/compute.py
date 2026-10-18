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

from . import checks, config
from . import jrc as jrc_bal
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
    df = _drop_shadowing_aggregates(df)
    keys = ["iso3", "item", "year", "key"]
    dup = df.duplicated(keys, keep=False)
    if dup.any():
        raise ValueError(f"FBS has {dup.sum()} rows with the same iso3/item/year/element, "
                         f"e.g. {df.loc[dup, keys].head(3).to_dict('records')}")
    wide = (
        df.pivot_table(index=["iso3", "item", "year"], columns="key", values="value", aggfunc="first")
        .reset_index()
    )
    for k in config.FBS_ELEMENTS:
        if k not in wide:
            wide[k] = np.nan
    # FBS leaves out elements that are zero: Germany has no "Production" row for coffee. Inside a
    # balance that exists, a missing quantity means none, so SSR is 0%, not unknown.
    # The same holds for stock variation and the uses: averaged over a window, a use FAO reports in
    # one year only must count as zero in the others (Afghanistan soybeans: stock change 25 kt in
    # 2023 alone, averaged over one year it was 3x too large and made the balance contradict).
    has_balance = wide["supply"].notna()
    for k in COMPONENTS:
        if k != "supply":
            wide.loc[has_balance & wide[k].isna(), k] = 0.0
    return wide


def _drop_shadowing_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """Some FAO aggregates share a name with a leaf item: "Miscellaneous" is both the leaf 2899
    and the aggregate 2928 (= 2899 + Infant food); "Eggs" and "Milk - Excluding Butter" also have
    one-item aggregates. Rows are keyed by name downstream, so keep the leaf."""
    if "item_code" not in df:
        return df
    code = _item_code(df["item_code"])
    leaf_names = set(df.loc[code < FBS_AGGREGATE_CODE, "item"])
    return df[~((code >= FBS_AGGREGATE_CODE) & df["item"].isin(leaf_names))]


def _item_code(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.lstrip("'S"), errors="coerce")


def window_mean(wide: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Average each component over [y0, y1] per iso3 × item. Ratios are computed afterwards."""
    y0, y1 = years
    sub = wide[(wide["year"] >= y0) & (wide["year"] <= y1)]
    # Divide by the years the country reports at all (Population present), not by the years an
    # item or element happens to appear: an item FAO leaves out in one year had none that year.
    # Countries that stopped reporting (Cuba after 2019) keep the years they have.
    reported = sub[sub["item"] == POPULATION_ITEM].groupby("iso3")["year"].nunique()
    if reported.empty:  # synthetic frames without a Population item
        reported = sub.groupby("iso3")["year"].nunique()
    sums = [c for c in COMPONENTS + PER_CAPITA_ELEMENTS if c in sub]
    out = sub.groupby(["iso3", "item"], as_index=False)[sums].sum(min_count=1)
    n = out["iso3"].map(reported)
    out[sums] = out[sums].div(n, axis=0)
    if "population" in sub:
        pop = sub.groupby(["iso3", "item"], as_index=False)["population"].mean()
        out = out.merge(pop, on=["iso3", "item"], how="left")
    if "jrc_food" in sub:
        # Which JRC food replaced the item; compute() only lets the JRC cover a whole window.
        jf = sub.dropna(subset=["jrc_food"]).groupby(["iso3", "item"])["jrc_food"].first()
        out = out.merge(jf.rename("jrc_food"), on=["iso3", "item"], how="left")
    out["years"] = f"{y0}-{y1}"
    return out


def add_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """SSR and IDR, withheld (NaN, with the reason in `flag`) where the balance contradicts
    itself (pipeline/checks.py). Withheld items drop out of group kcal means, "all food" and
    trends, so no view can show a figure built on them."""
    df = df.copy()
    df["ssr"] = ratio(df["production"], df["supply"])
    df["idr"] = ratio(df["imports"], df["supply"])
    df["flag"] = checks.problems(df)
    bad = df["flag"] != ""
    df.loc[bad, ["ssr", "idr"]] = np.nan
    return df


def _with_groups(items: pd.DataFrame) -> pd.DataFrame:
    """Attach group / group_label (if not already present) and drop unmapped items."""
    if "group" not in items:
        items = items.merge(item_to_group(), on="item", how="left")
    return items[items["group"].notna()]


# FAO's dairy items (docs/methodology.md, "Dairy in milk equivalent"): "Milk - Excluding Butter"
# is in milk equivalent and its "Processing" line is the milk churned into butter and cream, which
# are separate items in product weight. Summed as they are, a butter exporter keeps the milk of its
# exported butter in its own supply (New Zealand: 9.0 Mt of 9.8 Mt "used at home").
DAIRY_GROUP = "dairy"
MILK_ITEM = "Milk - Excluding Butter"
FAT_ITEMS = ("Butter, Ghee", "Cream")
MILK_PER_FAT = (5.0, 30.0)  # t of milk per t of butter and cream: the country's own ratio, clipped
MILK_PER_FAT_DEFAULT = 17.5  # median of the countries that make butter or cream (2021-2023)


def milk_per_fat(items: pd.DataFrame) -> pd.Series:
    """f per (iso3, years): milk processed / (butter + cream produced), clipped to MILK_PER_FAT,
    MILK_PER_FAT_DEFAULT where none is made. `items`: FAO dairy rows (milk, butter, cream)."""
    keys = ["iso3", "years"]
    proc = items[items["item"] == MILK_ITEM].groupby(keys)["processing"].sum(min_count=1)
    made = items[items["item"].isin(FAT_ITEMS)].groupby(keys)["production"].sum(min_count=1).clip(lower=0)
    f = (proc / made.where(made > 0)).reindex(proc.index.union(made.index))
    return f.clip(*MILK_PER_FAT).fillna(MILK_PER_FAT_DEFAULT)


def dairy_milk_equivalent(items: pd.DataFrame) -> pd.DataFrame:
    """FAO dairy items -> rows that sum to a milk-equivalent balance (JRC dairy left alone).

    Per country and window, f = milk processed / (butter + cream produced), clipped to
    MILK_PER_FAT (MILK_PER_FAT_DEFAULT where none is produced). Butter and cream: production 0,
    every other quantity x f (their milk is the milk's own production); milk: supply and
    processing less f x (butter + cream produced). P + M - X - dS = D holds exactly for any f."""
    g = items
    is_jrc = g["jrc_food"].eq(JRC_WHOLE_GROUP) if "jrc_food" in g else pd.Series(False, index=g.index)
    milk = (g["item"] == MILK_ITEM) & ~is_jrc
    fat = g["item"].isin(FAT_ITEMS) & ~is_jrc
    if not (milk.any() and fat.any()):
        return g
    g = g.copy()
    keys = ["iso3", "years"]
    made = g[fat].groupby(keys)["production"].sum(min_count=1).clip(lower=0)
    f = milk_per_fat(g[milk | fat])
    idx = pd.MultiIndex.from_frame(g[keys])
    fk = pd.Series(f.reindex(idx).fillna(MILK_PER_FAT_DEFAULT).to_numpy(), index=g.index)
    qty = [c for c in COMPONENTS if c in g and c != "production"]
    g.loc[fat, qty] = g.loc[fat, qty].mul(fk[fat], axis=0)
    g.loc[fat, "production"] = 0.0
    churned = pd.Series((made.reindex(idx).fillna(0) * fk.to_numpy()).to_numpy(), index=g.index)
    for c in ("supply", "processing"):
        g.loc[milk, c] = g.loc[milk, c] - churned[milk]
    return g


def group_tonnes(items: pd.DataFrame) -> pd.DataFrame:
    """Sum components across items of a group, then compute ratios. Basis: tonnes (dairy in milk
    equivalent, dairy_milk_equivalent)."""
    g = dairy_milk_equivalent(_with_groups(items))
    agg = g.groupby(["iso3", "group", "group_label", "years"], as_index=False)[COMPONENTS].sum(
        min_count=1
    )
    agg = add_ratios(agg)
    if "jrc_food" in g:
        # A JRC dairy balance is checked on its own terms: its P, M, X and D come from the JRC,
        # the food line is FAO's (scaled), so "more eaten than used" compares two sources.
        jd = g[g["jrc_food"] == JRC_WHOLE_GROUP][["iso3", "group", "years"]].drop_duplicates()
        is_jd = agg.merge(jd.assign(_jd=True), on=["iso3", "group", "years"], how="left")["_jd"]
        is_jd = is_jd.fillna(False).astype(bool).to_numpy()
        if is_jd.any():
            redo = add_ratios(agg.loc[is_jd].drop(columns=["food", "ssr", "idr", "flag"]))
            agg.loc[is_jd, ["ssr", "idr", "flag"]] = redo[["ssr", "idr", "flag"]].to_numpy()
    # A group whose ratio rests on items that contradict themselves is withheld like they are;
    # ssr_low / ssr_high keep the two readings so the UI can still say "more" or "less" when both
    # agree (pipeline/checks.py, parts_sensitivity).
    if "flag" in g:
        keys = ["iso3", "group", "group_label", "years"]
        g = g.copy()
        if "jrc_food" in g:  # JRC dairy is judged as one balance, not by its scaled items
            g.loc[g["jrc_food"] == JRC_WHOLE_GROUP, "flag"] = ""
        sens = checks.parts_sensitivity(g, keys).reset_index()
        agg = agg.merge(sens, on=keys, how="left")
        hit = agg["depends"].fillna(False).astype(bool) & (agg["flag"] == "")
        agg.loc[hit, "flag"] = checks.PARTS_CONTRADICT
        agg.loc[hit, ["ssr", "idr"]] = np.nan
        lo = agg[["ssr_pub", "ssr_adj"]].min(axis=1)
        hi = agg[["ssr_pub", "ssr_adj"]].max(axis=1)
        withheld = agg["flag"] != ""
        agg["ssr_low"] = lo.where(withheld)
        agg["ssr_high"] = hi.where(withheld & agg["ssr_pub"].notna())
        agg = agg.drop(columns=["ssr_pub", "ssr_adj", "depends"])
    agg["basis"] = "tonnes"
    return agg


def group_kcal(items: pd.DataFrame) -> pd.DataFrame:
    """kcal-weighted mean of item SSR/IDR within a group. Basis: kcal."""
    g = add_ratios(_with_groups(items))
    g = g[g["kcal"].notna() & (g["kcal"] > 0) & g["ssr"].notna()]
    # JRC dairy is one milk-equivalent balance: there is no JRC ratio per product to weight.
    if "jrc_food" in g:
        g = g[g["jrc_food"] != JRC_WHOLE_GROUP]

    def weighted(sub: pd.DataFrame) -> pd.Series:
        w = sub["kcal"]
        return pd.Series(
            {
                "ssr": np.average(sub["ssr"], weights=w),
                # unknown imports (an EU27 year without trade shares) stay unknown, not 0%
                "idr": np.average(sub["idr"], weights=w) if sub["idr"].notna().all() else np.nan,
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
    code = _item_code(fbs["item_code"])
    leaves = set(fbs.loc[code < FBS_AGGREGATE_CODE, "item"])
    return leaves - {POPULATION_ITEM}


# The JRC food whose balance covers a whole group (in milk equivalent) rather than one item.
JRC_WHOLE_GROUP = "dairy"
JRC_DAIRY_ITEM = "Dairy (milk equivalent, European Commission)"


FAO_DAIRY_ITEM = "Dairy (milk equivalent)"


def collapse_dairy(items: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    """For "all food": a country's dairy items become one row with the dairy group's SSR (milk
    equivalent: the JRC's where it replaced dairy, else FAO's via dairy_milk_equivalent) and the
    items' summed protein and kcal. Item-level dairy SSRs are product-weight figures: FAO's milk
    line keeps the milk of exported butter in its supply, and the JRC-scaled items are neither
    FAO's nor the JRC's figures."""
    if "group" not in items:
        return items
    is_d = items["group"] == DAIRY_GROUP
    if not is_d.any():
        return items
    t = groups[(groups["basis"] == "tonnes") & (groups["group"] == DAIRY_GROUP)]
    sub = items[is_d].assign(_jrc=items.loc[is_d, "jrc_food"].eq(JRC_WHOLE_GROUP) if "jrc_food" in items else False)
    d = sub.groupby(["iso3", "years"], as_index=False).agg(
        **{c: (c, lambda x: x.sum(min_count=1)) for c in PER_CAPITA_ELEMENTS}, _jrc=("_jrc", "any"))
    d = d.merge(t[["iso3", "years", "ssr", "flag", "production", "supply"]], on=["iso3", "years"], how="left")
    # Withheld by review or by the plausibility test, the balance still adds up: "all food" keeps
    # the published reading, as it keeps the items of any such group (methodology, "Withheld").
    kept = d["flag"].isin([checks.REVIEWED, checks.IMPLAUSIBLE])
    d.loc[kept, "ssr"] = ratio(d.loc[kept, "production"], d.loc[kept, "supply"])
    d.loc[kept, "flag"] = ""
    d = d.drop(columns=["production", "supply"])
    d["item"] = np.where(d["_jrc"], JRC_DAIRY_ITEM, FAO_DAIRY_ITEM)
    d["jrc_food"] = np.where(d["_jrc"], JRC_WHOLE_GROUP, None)
    d["group"] = DAIRY_GROUP
    d = d.drop(columns="_jrc")
    if "jrc_food" not in items:
        d = d.drop(columns="jrc_food")
    return pd.concat([items[~is_d], d], ignore_index=True)


UTILISATION = ["feed", "food", "seed", "losses", "processing", "other_uses", "tourist", "residuals"]


def add_eu_bloc(wide: pd.DataFrame, extra: pd.DataFrame | None = None) -> pd.DataFrame:
    """Append iso3 == "EU27": members summed per item and year (years with all 27 members only).

    Summing members' balances does not cancel trade between them: members report buying much more
    from each other than they report selling to each other (dairy: export.eu_intra_dairy, quoted
    in the UI), and FAO's own EU27 aggregate has the same gap. So, given `extra` (members'
    extra-EU trade shares per group, flow and year, from trade.extract):

        imports = sum_j imports_j * share of j's imports from outside the EU
        exports = sum_j exports_j * share of j's exports to outside the EU
        supply  = production + imports - exports - stock variation

    and the uses (food, feed, ...) are scaled to that supply. Without `extra`, gross trade is
    blanked and supply stays the members' sum (the old, inflated behaviour).
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

    cols = [c for c in COMPONENTS if c in m]
    sums = m.groupby(["item", "year"], as_index=False)[cols + PER_CAPITA_ELEMENTS].sum(min_count=1)
    # Per person for the whole EU: divided by all members' population, not only by the members
    # that report the item (a member without the item eats none of it).
    eu_pop_y = pop.groupby("year")["population"].sum()
    for c in PER_CAPITA_ELEMENTS:
        sums[c] = sums[c] / sums["year"].map(eu_pop_y)
    sums[["imports", "exports"]] = np.nan
    if extra is not None and len(extra):
        sums = _extra_eu_trade(sums, members, extra)
    eu_pop = pop.groupby("year", as_index=False)["population"].sum()
    eu_pop["item"] = POPULATION_ITEM
    sums = pd.concat([sums[sums["item"] != POPULATION_ITEM], eu_pop], ignore_index=True)
    sums["iso3"] = EU_BLOC
    return pd.concat([wide, sums], ignore_index=True)


def _extra_eu_trade(sums: pd.DataFrame, members: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """EU27 rows: imports/exports with the rest of the world in FBS units, supply rebuilt from them,
    uses scaled to match (see add_eu_bloc)."""
    groups = item_to_group()[["item", "group"]]
    m = members[["iso3", "item", "year", "imports", "exports"]].merge(groups, on="item", how="left")
    # Items outside the groups use the members' share for all foods; a group with no shares at
    # all keeps the old members' sum (fish without a Comext download).
    traded = set(extra["group"])
    m = m[m["group"].isna() | m["group"].isin(traded)].reset_index(drop=True)
    m["group"] = m["group"].fillna("all")
    for flow in ("imports", "exports"):
        sh = extra[extra["flow"] == flow][["iso3", "group", "year", "share"]]
        own = m.merge(sh, on=["iso3", "group", "year"], how="left")["share"]
        # The item's own share where the trade records have one (fruit and meat: trade.ITEM_KEY).
        item = m[["iso3", "item", "year"]].assign(group="item:" + m["item"]).merge(
            sh, on=["iso3", "group", "year"], how="left")["share"]
        own = item.fillna(own)
        # A member without trade records for that food: its share across all foods that year.
        alls = m[["iso3", "year"]].merge(sh[sh["group"] == "all"].drop(columns="group"),
                                        on=["iso3", "year"], how="left")["share"]
        m[f"{flow}_share"] = own.fillna(alls).to_numpy()
    covered = m.groupby("year")["imports_share"].apply(lambda s: s.notna().any())
    m["imports"] = m["imports"].fillna(0) * m["imports_share"]
    m["exports"] = m["exports"].fillna(0) * m["exports_share"]
    ext = m.groupby(["item", "year"], as_index=False)[["imports", "exports"]].sum(min_count=1)
    ext = ext[ext["year"].isin(covered[covered].index)]

    sums = sums.drop(columns=["imports", "exports"]).merge(ext, on=["item", "year"], how="left")
    has = sums["imports"].notna() | sums["exports"].notna()
    new = (sums["production"].fillna(0) + sums["imports"].fillna(0) - sums["exports"].fillna(0)
           - sums["stock_variation"].fillna(0))
    old = sums["supply"]
    scale = (new / old).where(has & (old > 0))
    for c in UTILISATION:
        if c in sums:
            sums[c] = np.where(scale.notna(), sums[c] * scale, sums[c])
    sums["supply"] = np.where(has, new, old)
    return sums


def overall(items: pd.DataFrame, leaves: set[str]) -> pd.DataFrame:
    """"All food": how much of the protein / kcal people eat could own production cover?

    share = sum_i w_i * min(SSR_i, 100) / sum_i w_i, w = protein (g/cap/day) or kcal/cap/day of
    leaf item i. Capping stops a wheat surplus from hiding a soy deficit. `*_ssr` is the uncapped
    weighted mean (can exceed 100) for experts. Livestock products count as home-grown even when
    fed on imported feed (phase 4 adjusts for that).

    Items whose balance contradicts itself (`flag`, pipeline/checks.py) have no SSR and are left
    out of the shares; `protein` / `kcal` (per person per day) still count every leaf item. The
    shares are also computed with those items read generously (supply at least their food line);
    `protein_flag` / `kcal_flag` = parts_contradict when the two differ by more than checks.PARTS_PP / PARTS_REL, and
    `*_low` / `*_high` keep both readings.
    """
    g = items[items["item"].isin(leaves)].copy()
    bad = g["flag"].fillna("") != "" if "flag" in g else pd.Series(False, index=g.index)
    floor = pd.concat([g["supply"].fillna(0), g["food"].fillna(0) if "food" in g else g["supply"] * 0,
                       pd.Series(0.0, index=g.index)], axis=1).max(axis=1)
    g["ssr_b"] = g["ssr"].where(~bad, 100 * g["production"] / floor.where(floor > 0))
    rows = []
    for (iso3, years), sub in g.groupby(["iso3", "years"]):
        ok = sub[sub["ssr"].notna()]
        row = {"iso3": iso3, "years": years,
               "n_foods": int((ok["protein"].fillna(0) > 0).sum()),
               "n_withheld": int(((sub["protein"].fillna(0) > 0) & sub["ssr"].isna()).sum())}
        for w in PER_CAPITA_ELEMENTS:
            depends = False
            allw = sub[w].where(sub[w] > 0).sum()
            row[w] = allw if allw > 0 else np.nan
            for suffix, cap in (("_share", 100), ("_ssr", None)):
                vals = {}
                for name, col, frame in (("a", "ssr", ok), ("b", "ssr_b", sub)):
                    s = frame[frame[w].notna() & (frame[w] > 0) & frame[col].notna()]
                    tot = s[w].sum()
                    v = s[col].clip(upper=cap) if cap else s[col]
                    vals[name] = (s[w] * v).sum() / tot if tot > 0 else np.nan
                row[f"{w}{suffix}"] = vals["a"]
                both = pd.Series([vals["a"], vals["b"]], dtype=float)
                lo, hi = both.min(), both.max()
                row[f"{w}{suffix}_low"], row[f"{w}{suffix}_high"] = lo, hi
                # same rule as for groups: 10% of the generous reading (B)
                if pd.notna(vals["a"]) and pd.notna(vals["b"]) and abs(vals["a"] - vals["b"]) > max(
                        checks.PARTS_PP, checks.PARTS_REL * vals["b"]):
                    depends = True
            row[f"{w}_flag"] = checks.PARTS_CONTRADICT if depends else ""
        rows.append(row)
    cols = ["iso3", "years", "n_foods", "n_withheld", "protein_flag", "kcal_flag"] + [
        f"{w}{suffix}{b}" for w in PER_CAPITA_ELEMENTS for suffix in ("", "_share", "_ssr")
        for b in (("",) if suffix == "" else ("", "_low", "_high"))]
    return pd.DataFrame(rows, columns=cols)


# ------------------------------------------------------------------------------------------------


def _jrc_foods(items: pd.DataFrame) -> pd.DataFrame:
    """iso3 × group -> comma-separated JRC foods that replaced some of the group's items."""
    if "jrc_food" not in items:
        return pd.DataFrame(columns=["iso3", "group", "jrc_foods"])
    j = items.dropna(subset=["jrc_food", "group"])
    return (j.groupby(["iso3", "group"])["jrc_food"]
            .agg(lambda s: ",".join(sorted(set(s)))).rename("jrc_foods").reset_index())


def _source(df: pd.DataFrame) -> pd.Series:
    """Where a row's figures come from (config.SOURCES keys, '+'-joined):
    fao_fbs; jrc_bal where the DG AGRI-JRC balance replaced FAO; the EU27 bloc's trade is
    rebuilt from the FAO trade matrix (fao_tm), its fish trade from Eurostat Comext
    (eurostat_comext), all food from both."""
    jrc = pd.Series(False, index=df.index)
    for c in ("jrc_food", "jrc_foods"):
        if c in df:
            jrc |= df[c].fillna("").astype(str) != ""
    whole = pd.Series(False, index=df.index)
    if "jrc_food" in df:
        whole |= df["jrc_food"].notna()
    if "group" in df and "jrc_foods" in df:
        whole |= (df["group"] == JRC_WHOLE_GROUP) & (df["jrc_foods"] == JRC_WHOLE_GROUP)
    eu = df["iso3"] == EU_BLOC
    group = df["group"] if "group" in df else pd.Series("all", index=df.index)  # overall = all food
    base = np.where(~eu, "fao_fbs", np.where(group == "fish", "fao_fbs+eurostat_comext",
                                             np.where(group == "all", "fao_fbs+fao_tm+eurostat_comext",
                                                      "fao_fbs+fao_tm")))
    return pd.Series(np.where(whole, "jrc_bal", np.where(jrc, base + "+jrc_bal", base)),
                     index=df.index)


def latest_window(wide: pd.DataFrame, n: int = config.WINDOW_YEARS) -> tuple[int, int]:
    y1 = int(wide["year"].max())
    return (y1 - n + 1, y1)


def _compute_window(wide: pd.DataFrame, years: tuple[int, int], leaves: set[str],
                    plausible: dict | None = None) -> dict:
    items = window_mean(wide, years)
    if "population" not in items:
        items["population"] = np.nan
    is_pop = items["item"] == POPULATION_ITEM
    population = items.loc[is_pop, ["iso3", "population"]]
    items = add_ratios(items[~is_pop].drop(columns="population"))
    items["basis"] = "tonnes"
    items = items.merge(item_to_group(), on="item", how="left")

    groups = pd.concat([group_tonnes(items), group_kcal(items)], ignore_index=True)
    # Withheld by review (checks.reviewed_withholds) and by the plausibility test (plausible.py):
    # window and single years, both bases. A plausibility verdict keeps both readings as the range.
    for reason, keys in ((checks.REVIEWED, checks.reviewed_withholds()), (checks.IMPLAUSIBLE, plausible)):
        if not keys:
            continue
        hit = pd.Series([(i, g) in keys for i, g in zip(groups["iso3"], groups["group"], strict=True)],
                        index=groups.index)
        free = (groups["flag"].fillna("") == "") & (groups["basis"] == "tonnes")
        groups.loc[hit & free, "flag"] = reason
        if reason == checks.IMPLAUSIBLE:
            rng = [keys.get((i, g), (np.nan, np.nan)) for i, g in zip(groups["iso3"], groups["group"], strict=True)]
            groups.loc[hit & free, "ssr_low"] = [r[0] for r, h in zip(rng, hit & free, strict=True) if h]
            groups.loc[hit & free, "ssr_high"] = [r[1] for r, h in zip(rng, hit & free, strict=True) if h]
        groups.loc[hit, ["ssr", "idr"]] = np.nan
    totals = overall(collapse_dairy(items, groups), leaves | {JRC_DAIRY_ITEM, FAO_DAIRY_ITEM})
    groups = groups.merge(_jrc_foods(items), on=["iso3", "group"], how="left")
    groups["jrc_foods"] = groups["jrc_foods"].fillna("")
    jf = _jrc_foods(items.assign(group="all")).drop(columns="group")
    totals = totals.merge(jf, on="iso3", how="left").assign(
        jrc_foods=lambda d: d["jrc_foods"].fillna(""))
    items = add_per_capita(items, population)
    groups = add_per_capita(groups, population)
    totals = totals.merge(population, on="iso3", how="left")
    return {"items": items, "groups": groups, "overall": totals}


def compute(fbs: pd.DataFrame, *, years: tuple[int, int] | None = None,
            extra: pd.DataFrame | None = None,
            jrc: pd.DataFrame | None = None,
            plausible: dict | None = None) -> dict[str, pd.DataFrame]:
    """Returns {'items', 'groups', 'overall', 'trends'} tidy frames.

    items/groups/overall cover the window (default: latest 3 years); trends has one SSR value per
    iso3 × group × year (group "all" = uncapped protein SSR) for sparklines.
    """
    base = add_eu_bloc(to_wide(fbs), extra)
    # EU countries' dairy, tomatoes, olive oil and wine from the DG AGRI-JRC balance sheets:
    # single years wherever the JRC has them (trends); the averaged window only where the JRC
    # covers all of it, so one average never mixes two sources.
    wide = jrc_bal.apply(base, jrc, UTILISATION)
    leaves = leaf_items(fbs)
    years = years or latest_window(wide)
    log.info("window %s", years)
    res = _compute_window(jrc_bal.apply(base, jrc_bal.full_cover(jrc, years), UTILISATION),
                          years, leaves, plausible)

    trend_rows = []
    for y in sorted(wide["year"].dropna().unique()):
        r = _compute_window(wide, (int(y), int(y)), leaves, plausible)
        t = r["groups"][r["groups"]["basis"] == "tonnes"][["iso3", "group", "ssr", "jrc_foods"]]
        # "All food" headline: total protein produced vs used (uncapped), see docs/methodology.md.
        o = r["overall"][["iso3", "protein_ssr", "jrc_foods", "protein_flag"]].rename(
            columns={"protein_ssr": "ssr"})
        o.loc[o["protein_flag"] != "", "ssr"] = np.nan  # a headline that rests on contradictions
        o = o.drop(columns="protein_flag")
        o["group"] = "all"
        trend_rows.append(pd.concat([t, o], ignore_index=True).assign(year=int(y)))
    res["trends"] = pd.concat(trend_rows, ignore_index=True) if trend_rows else pd.DataFrame(
        columns=["iso3", "group", "ssr", "year", "jrc_foods"]
    )

    for df in res.values():
        df["source"] = _source(df)
        df["view"] = np.where(df["iso3"] == EU_BLOC, "eu_bloc", "national")
    return res


def run(*, years: tuple[int, int] | None = None) -> None:
    config.ensure_dirs()
    fbs = pd.read_parquet(config.INTERIM / "fbs.parquet")
    shares = config.INTERIM / "eu_extra_shares.parquet"  # trade.extract(); see add_eu_bloc
    from .trade import trade_inputs  # trade imports compute
    config.require_fresh(shares, trade_inputs())
    extra = pd.read_parquet(shares) if shares.exists() else None
    if extra is None:
        log.warning("no %s: EU27 supply is the members' sum, which double counts intra-EU trade",
                    shares)
    from . import plausible

    res = compute(fbs, years=years, extra=extra, jrc=jrc_bal.load_balances(), plausible=plausible.load())
    for name, df in res.items():
        out = config.PROCESSED / f"ssr_{name}.parquet"
        df.to_parquet(out, index=False)
        log.info("wrote %s (%d rows)", out, len(df))
