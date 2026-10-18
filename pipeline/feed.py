"""Feed: how much of the meat and eggs rests on imported feed (methodology, "Feed").

FAOSTAT Supply Utilization Accounts give every commodity's production, imports and feed use,
oilseed cakes included. Per country over the FBS window: the imported share of feed protein, the
items behind it, and meat and egg self-sufficiency counting pigs and poultry only in the
home-grown share of their feed.

Output data/processed/feed.parquet: iso3, imported_pct, top (JSON list of [item, % of imported
protein]), meat_ssr, eggs_ssr, items_pct, and "all food" counting pigs and poultry the same way:
{protein,kcal}_feed_{ssr,share} and the calorie balance kcal_{produced,imports,exports,used}
(methodology, '"All food" coverage').
"""

from __future__ import annotations

import csv
import json
import logging
import zipfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from . import config

log = logging.getLogger(__name__)

SUA_ZIP = config.RAW / "faostat" / "SUA_Crops_Livestock_E_All_Data_(Normalized).zip"
SUA_CSV = "SUA_Crops_Livestock_E_All_Data_(Normalized).csv"
EU_EXTRA = "eu_feed_extra.parquet"
OUT = "feed.parquet"
EU_ITEMS = "feed_eu_items.parquet"  # the EU's items, for the comparison with DG AGRI (feedcheck.py)
ELEMENTS = {"Production": "P", "Import quantity": "M", "Feed": "F"}


def load_items() -> dict[int, dict]:
    with (config.MAPPINGS / "feed_items.csv").open(encoding="utf-8") as f:
        rows = csv.DictReader(x for x in f if not x.startswith("#"))
        return {int(r["item_code"]): {"item": r["item"], "protein": float(r["protein_pct"]) / 100,
                                      "parent": int(r["parent"]) if r["parent"] else None} for r in rows}


def eu_extra_shares(raw: pd.DataFrame) -> pd.DataFrame:
    """Per feed item and year: the share of EU members' reported imports (tonnes) that come from
    outside the EU (trade matrix rows as read by trade.read_matrix, ISO3 already)."""
    items = load_items()
    m = raw[raw["item_code"].isin(items) & (raw["flow"] == "imports") & raw["reporter"].isin(config.EU27)]
    m = m.assign(extra=m["value"].where(~m["partner"].isin(config.EU27), 0.0))
    g = m.groupby(["item_code", "year"], as_index=False)[["extra", "value"]].sum()
    g = g[g["value"] > 0]
    return g.assign(share=g["extra"] / g["value"])[["item_code", "year", "share"]]


def read_sua(years: tuple[int, int], codes: set[int]) -> pd.DataFrame:
    """iso3, item_code, element (P, M, F), year, t."""
    from .harmonise import load_countries

    with zipfile.ZipFile(SUA_ZIP) as z, z.open(SUA_CSV) as fh:
        t = pacsv.read_csv(fh, read_options=pacsv.ReadOptions(encoding="latin-1"),
                           convert_options=pacsv.ConvertOptions(
                               include_columns=["Area Code (M49)", "Item Code", "Element", "Year", "Unit", "Value"],
                               column_types={"Area Code (M49)": pa.string(), "Item Code": pa.int64(),
                                             "Year": pa.int64(), "Value": pa.float64()}))
    t = t.filter(pc.and_(pc.and_(pc.greater_equal(t["Year"], years[0]), pc.less_equal(t["Year"], years[1])),
                         pc.and_(pc.is_in(t["Item Code"], value_set=pa.array(sorted(codes))),
                                 pc.and_(pc.is_in(t["Element"], value_set=pa.array(list(ELEMENTS))),
                                         pc.equal(t["Unit"], "t")))))
    d = t.to_pandas().rename(columns={"Area Code (M49)": "m49", "Item Code": "item_code", "Year": "year",
                                      "Value": "t"})
    d["m49"] = d["m49"].str.lstrip("'").str.zfill(3)
    iso = load_countries().set_index("m49")["iso3"]
    d["iso3"] = d["m49"].map(iso)
    d["element"] = d["Element"].map(ELEMENTS)
    return d.dropna(subset=["iso3"])[["iso3", "item_code", "element", "year", "t"]]


# Leaf items whose production counts only in the home-grown share of the feed (pigs and poultry),
# and the ruminants', counted for the traded share of their diet (GLEAM, `traded_share`).
ADJUSTED_ITEMS = ("Pigmeat", "Poultry Meat", "Eggs")
CATTLE_ITEMS = ("Bovine Meat",)
SMALL_ITEMS = ("Mutton & Goat Meat",)
GLEAM_INTAKE = "gleam_feed_intake.csv"
GLEAM_PROTEIN = "gleam_feed_protein.csv"


def traded_share() -> pd.DataFrame:
    """iso3 (and EU27) -> c_cattle, c_small: the share of the protein cattle and buffaloes, and
    sheep and goats, eat as traded feed (grains, by-products, oilseed cakes), from GLEAM 3's dry
    matter intake weighted by crude protein (methodology, "Feed", "Cattle, sheep and goats")."""
    def rows(name):
        with (config.MAPPINGS / name).open(encoding="utf-8") as f:
            return list(csv.DictReader(x for x in f if not x.startswith("#")))
    cp = {r["category"]: (float(r["protein_pct_dm"]) / 100, r["traded"] == "yes") for r in rows(GLEAM_PROTEIN)}
    d = pd.DataFrame(rows(GLEAM_INTAKE))
    if d.empty:
        return pd.DataFrame(columns=["c_cattle", "c_small"])
    d["kind"] = d["kind"].map({"cattle": "cattle", "sheep_goats": "small"})
    for c in cp:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    d = pd.concat([d, d[d["iso3"].isin(config.EU27)].assign(iso3="EU27")], ignore_index=True)
    g = d.groupby(["iso3", "kind"])[list(cp)].sum()
    prot = sum(g[c] * cp[c][0] for c in cp)
    traded = sum(g[c] * cp[c][0] for c in cp if cp[c][1])
    share = (traded / prot.where(prot > 0)).unstack("kind")
    return share.rename(columns={"cattle": "c_cattle", "small": "c_small"}).reindex(columns=["c_cattle", "c_small"])


def all_food(f: float, items: pd.DataFrame, total: pd.Series, cc: float = 0.0, cs: float = 0.0) -> dict:
    """"All food" with SSR_i' = factor_i * SSR_i: 1 - f for ADJUSTED_ITEMS, 1 - f*c_cattle for beef and
    dairy (as one food, compute.overall's dairy_*), 1 - f*c_small for mutton and goat meat; against
    the same items and weights as compute.overall (its `{w}_den`, reading A)."""
    out = {}
    for w in ("protein", "kcal"):
        keys = [f"{w}_feed_ssr", f"{w}_feed_share"]
        den, ssr, share = total.get(f"{w}_den"), total.get(f"{w}_ssr"), total.get(f"{w}_share")
        if str(total.get(f"{w}_flag") or "") != "" or pd.isna(den) or not den > 0 or pd.isna(ssr):
            out.update(dict.fromkeys(keys, np.nan))
            continue
        a = items[items["ssr"].notna() & (items[w] > 0)]
        parts = [(a[a["item"].isin(ADJUSTED_ITEMS)], 1 - f), (a[a["item"].isin(CATTLE_ITEMS)], 1 - f * cc),
                 (a[a["item"].isin(SMALL_ITEMS)], 1 - f * cs)]
        terms = [(r[w], r["ssr"], k) for sub, k in parts for _, r in sub.iterrows()]
        dw, ds = total.get(f"dairy_{w}"), total.get("dairy_ssr")
        if pd.notna(dw) and dw > 0 and pd.notna(ds):
            terms.append((dw, ds, 1 - f * cc))
        d_ssr = sum(wi * (1 - k) * si for wi, si, k in terms) / den
        d_share = sum(wi * (min(si, 100) - min(k * si, 100)) for wi, si, k in terms) / den
        out.update({keys[0]: ssr - d_ssr, keys[1]: share - d_share})
        if w == "kcal":
            # Calorie balance per person a day: produced = the headline's share of the use; what
            # rests on imported feed counts as bought abroad.
            out.update({"kcal_produced": (ssr - d_ssr) * den / 100,
                        "kcal_imports": total.get("kcal_imports") + d_ssr * den / 100,
                        "kcal_exports": total.get("kcal_exports"), "kcal_used": den})
    return out


def compute(years: tuple[int, int], groups: pd.DataFrame, items_fbs: pd.DataFrame,
            detail: list | None = None, overall: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per country. `detail`, when given, receives the EU's items: item_code, item, protein_t
    (crude protein fed, t a year) and imported_t (its share from outside the EU)."""
    items = load_items()
    n = years[1] - years[0] + 1
    sua = read_sua(years, set(items) | {i["parent"] for i in items.values() if i["parent"]})
    # members' imports from outside the EU (per item and year), for the EU as one
    ex = pd.read_parquet(config.INTERIM / EU_EXTRA) if (config.INTERIM / EU_EXTRA).exists() else None
    eu = sua[sua["iso3"].isin(config.EU27)].copy()
    if ex is not None:
        imp = eu["element"] == "M"
        sh = eu.loc[imp, ["item_code", "year"]].merge(ex, on=["item_code", "year"], how="left")["share"]
        eu.loc[imp, "t"] = eu.loc[imp, "t"].to_numpy() * sh.fillna(1.0).to_numpy()
    eu = eu.groupby(["item_code", "element", "year"], as_index=False)["t"].sum().assign(iso3="EU27")
    all_ = pd.concat([sua, eu], ignore_index=True)
    w = all_.groupby(["iso3", "item_code", "element"])["t"].sum().div(n).unstack("element").reindex(
        columns=["P", "M", "F"]).fillna(0.0)
    have = w["P"] + w["M"]
    own = (w["P"] / have.where(have > 0)).fillna(1.0).clip(0, 1)

    prod = items_fbs.set_index(["iso3", "item"])["production"]
    ts = traded_share()
    g = groups[groups["basis"] == "tonnes"].set_index(["iso3", "group"])
    rows = []
    for iso3, sub in w.groupby(level="iso3"):
        sub = sub.droplevel("iso3")
        fed = sub[(sub["F"] > 0) & sub.index.isin(list(items))]
        tot_t = sub.loc[sub["F"] > 0, "F"].sum()
        if fed.empty:
            continue
        s = {}
        for code in fed.index:
            parent = items[code]["parent"]
            s[code] = own.get((iso3, code), 1.0) * (own.get((iso3, parent), 1.0) if parent else 1.0)
        prot = pd.Series({c: fed.at[c, "F"] * items[c]["protein"] for c in fed.index})
        imported = pd.Series({c: prot[c] * (1 - s[c]) for c in fed.index})
        if not prot.sum() > 0:
            continue
        if detail is not None and iso3 == "EU27":
            detail += [{"item_code": int(c), "item": items[c]["item"], "protein_t": prot[c],
                        "imported_t": imported[c]} for c in fed.index]
        f = imported.sum() / prot.sum()
        top = imported.sort_values(ascending=False)
        top = [[items[c]["item"], round(100 * v / imported.sum())] for c, v in top.head(3).items()
               if imported.sum() > 0 and v / imported.sum() >= 0.05]

        def p(item, iso3=iso3):
            v = prod.get((iso3, item), 0.0)
            return 0.0 if pd.isna(v) else float(v)

        def ssr(group, num, iso3=iso3):
            if (iso3, group) not in g.index:
                return np.nan
            r = g.loc[(iso3, group)]
            if str(r.get("flag") or "") != "" or not r["supply"] > 0:
                return np.nan
            return 100 * num / r["supply"]

        cc = float(ts.at[iso3, "c_cattle"]) if iso3 in ts.index and pd.notna(ts.at[iso3, "c_cattle"]) else 0.0
        cs = float(ts.at[iso3, "c_small"]) if iso3 in ts.index and pd.notna(ts.at[iso3, "c_small"]) else 0.0
        meat = ssr("meat", g.loc[(iso3, "meat"), "production"] - f * (p("Pigmeat") + p("Poultry Meat"))
                   - f * cc * p("Bovine Meat") - f * cs * p("Mutton & Goat Meat")
                   if (iso3, "meat") in g.index else np.nan)
        dairy = ssr("dairy", (1 - f * cc) * g.loc[(iso3, "dairy"), "production"]) if (iso3, "dairy") in g.index else np.nan
        eggs = ssr("eggs", (1 - f) * g.loc[(iso3, "eggs"), "production"] if (iso3, "eggs") in g.index else np.nan)
        row = {"iso3": iso3, "imported_pct": 100 * f, "top": json.dumps(top), "meat_ssr": meat, "eggs_ssr": eggs,
               "dairy_ssr": dairy,
               "c_cattle": 100 * ts.at[iso3, "c_cattle"] if iso3 in ts.index else np.nan,
               "c_small": 100 * ts.at[iso3, "c_small"] if iso3 in ts.index else np.nan,
               "items_pct": 100 * fed["F"].sum() / tot_t if tot_t > 0 else np.nan}
        if overall is not None and iso3 in overall.index:
            row.update(all_food(f, items_fbs[items_fbs["iso3"] == iso3], overall.loc[iso3], cc, cs))
        rows.append(row)
    return pd.DataFrame(rows)


def run() -> None:
    from .trade import fbs_window

    dest = config.PROCESSED / OUT
    if not SUA_ZIP.exists():
        log.warning("no Supply Utilization Accounts; run `atlas download --source faostat`")
        dest.unlink(missing_ok=True)
        return
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    items = pd.read_parquet(config.PROCESSED / "ssr_items.parquet")
    if "basis" in items:
        items = items[items["basis"] == "tonnes"]
    overall = pd.read_parquet(config.PROCESSED / "ssr_overall.parquet").set_index("iso3")
    detail = []
    out = compute(fbs_window(), groups, items, detail, overall)
    out.to_parquet(dest, index=False)
    pd.DataFrame(detail).to_parquet(config.PROCESSED / EU_ITEMS, index=False)
    log.info("wrote %s (%d countries; median imported feed protein %.0f%%)", dest, len(out),
             out["imported_pct"].median())
