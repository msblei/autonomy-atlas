"""Eurostat Comext: EU members' own trade, for what FAO's trade matrix lacks.

FAO's Detailed Trade Matrix stays the source of partner lists for every food it covers (one
method for every country). Comext adds, for the 27 EU members (methodology, "Comext"):

1. Fish: who EU members buy fish from and sell it to (the trade matrix has no fish), in live
   weight with EUMOFA's factor per CN8 code and year, and the members' extra-EU shares that the
   EU bloc's fish balance needs (compute.add_eu_bloc).
2. A comparison: the same members' trade in the other groups against the trade matrix
   (data/processed/comext_vs_fao.parquet, on the audit page).

Output data/interim/comext_yearly.parquet, one row per reporter × partner × group × flow × year:
    reporter (ISO3), partner (ISO3, or Comext's code when it is no country, e.g. QV), country
    (partner is a country), group, flow (imports | exports), year, tonnes (as traded), primary
    (in the FBS basis: live weight for fish, the crosswalk's factor otherwise), eur
"""

from __future__ import annotations

import csv
import gzip
import logging

import pandas as pd

from . import config, crosswalk

log = logging.getLogger(__name__)

RAW = config.RAW / "comext" / "DS-045409_food.csv.gz"
EUMOFA = config.RAW / "eumofa" / "conversion_factors_cn8.xlsx"
YEARLY = "comext_yearly.parquet"
COMPARE = "comext_vs_fao.parquet"
FLOWS = {"1": "imports", "2": "exports"}
# Comext's codes for partners that are not named but certainly inside the EU (confidential intra-EU
# trade, stores and provisions within the EU): they count as intra-EU for the extra-EU shares.
INTRA_UNNAMED = {"QR", "QV", "QY"}


def load_partners() -> dict[str, str]:
    with (config.MAPPINGS / "comext_partners.csv").open(encoding="utf-8") as f:
        return {r["comext"]: r["iso3"] for r in csv.DictReader(x for x in f if not x.startswith("#"))}


def load_cn8_items() -> dict[str, tuple[str, float]]:
    """CN8 code -> (group, factor) for the HS6 codes split at CN8 level (mappings/cn8_items.csv)."""
    with (config.MAPPINGS / "cn8_items.csv").open(encoding="utf-8") as f:
        rows = csv.DictReader(x for x in f if not x.startswith("#"))
        return {r["cn8"]: (r["group"], float(r["to_primary"] or 1)) for r in rows}


def load_eumofa() -> pd.DataFrame:
    """year, cn8, cf (kg live weight per kg product) for codes used as food (cf > 0)."""
    d = pd.read_excel(EUMOFA, sheet_name="List of CF", dtype=str)
    d = d[["Year", "CN-8", "CF"]].rename(columns={"Year": "year", "CN-8": "cn8", "CF": "cf"})
    d["cn8"] = d["cn8"].str.replace(" ", "", regex=False)
    d["year"] = d["year"].astype(int)
    d["cf"] = pd.to_numeric(d["cf"], errors="coerce")
    return d[d["cf"] > 0].drop_duplicates(["year", "cn8"])


# Fish as the FBS counts it: food fish, crustaceans, molluscs and other aquatic invertebrates,
# fresh to prepared. Not fish oil (1504), fishmeal (2301), seaweed (1212) or pasta and pet food
# that EUMOFA also lists; ornamental fish have no factor above 0.
FISH_PREFIXES = ("0301", "0302", "0303", "0304", "0305", "0306", "0307", "0308", "0309", "1604", "1605")


def is_fish(cn8: str) -> bool:
    return cn8.startswith(FISH_PREFIXES)


def fish_cn8_codes() -> list[str]:
    """EUMOFA's CN8 fish codes (factor > 0) of the years Comext is asked for."""
    e = load_eumofa()
    e = e[(e["year"] >= config.COMEXT_FISH_FIRST_YEAR - 1) & e["cn8"].map(is_fish)]
    return sorted(set(e["cn8"]))


def hs_version(year: int) -> int:
    """Comext reports in the HS version in force: HS 2017 up to 2021, HS 2022 from 2022 to 2027.
    HS 2028 applies from 1 January 2028; its codes are not in hs_items.csv, so stop rather than
    drop them silently (docs/updating.md, "Known dates")."""
    if year >= 2028:
        raise ValueError(f"Comext {year} is in HS 2028 codes, which the crosswalk does not convert yet: "
                         "add the UNSD HS 2028 -> HS 2022 conversion (docs/updating.md, 'Known dates')")
    return 2017 if year <= 2021 else 2022


def read_raw() -> pd.DataFrame:
    with gzip.open(RAW, "rt", encoding="utf-8") as f:
        # keep_default_na=False: "NA" is Namibia, not a missing value
        d = pd.read_csv(f, dtype={"reporter": str, "partner": str, "product": str, "flow": str},
                        keep_default_na=False, na_values={"OBS_VALUE": [""]},
                        usecols=["reporter", "partner", "product", "flow", "indicators",
                                 "TIME_PERIOD", "OBS_VALUE"])
    d = d.rename(columns={"TIME_PERIOD": "year", "OBS_VALUE": "value"})
    # Partners are single countries or Comext's two-letter codes for unnamed partners; WORLD,
    # EXT_EU27_2020, INT_EU and the other aggregates would count trade twice. WORLD checks the sum.
    world = d[d["partner"] == "WORLD"]
    d = d[d["partner"].str.len() == 2]
    q = d["indicators"] == "QUANTITY_IN_100KG"
    gap = abs(d.loc[q, "value"].sum() - world.loc[world["indicators"] == "QUANTITY_IN_100KG", "value"].sum())
    log.info("comext: single partners add up to WORLD within %.3f%%",
             100 * gap / max(world.loc[world["indicators"] == "QUANTITY_IN_100KG", "value"].sum(), 1))
    w = d.pivot_table(index=["reporter", "partner", "product", "flow", "year"], columns="indicators",
                      values="value", aggfunc="sum").reset_index()
    w.columns.name = None
    w = w.rename(columns={"QUANTITY_IN_100KG": "q100", "VALUE_IN_EUROS": "eur"})
    for c in ("q100", "eur"):
        if c not in w:
            w[c] = float("nan")
    return w


def convert(w: pd.DataFrame, hs: pd.DataFrame, cf: pd.DataFrame, partners: dict[str, str]) -> pd.DataFrame:
    """Raw rows -> groups, tonnes and primary equivalents (see module doc)."""
    out = _rows(w, hs, cf, partners)
    keys = ["reporter", "partner", "country", "group", "flow", "year"]
    return out.groupby(keys, as_index=False)[["tonnes", "primary", "eur"]].sum(min_count=1)


MIX = "comext_hs6_factors.parquet"


def mix_factors(rows: pd.DataFrame, hs: pd.DataFrame) -> pd.DataFrame:
    """For HS6 codes decided at CN8 level (fish, whey): the factor of the EU's own mix under the
    code each year, Σ tonnes × factor / Σ tonnes over members' imports and exports, keyed by the
    HS 2017 code (methodology, "BACI"). Columns: hs2017, year, factor, tonnes."""
    r = rows[(rows["product"].str.len() == 8) & rows["tonnes"].notna() & (rows["tonnes"] > 0)]
    conv = hs[["version", "hs", "hs2017"]].drop_duplicates(["version", "hs"])
    r = r.assign(hs=r["product"].str[:6]).merge(conv, on=["version", "hs"], how="inner")
    r = r.assign(w=r["tonnes"] * r["factor"])
    g = r.groupby(["hs2017", "year"], as_index=False)[["w", "tonnes"]].sum()
    return g.assign(factor=g["w"] / g["tonnes"]).drop(columns="w")


def _rows(w: pd.DataFrame, hs: pd.DataFrame, cf: pd.DataFrame, partners: dict[str, str]) -> pd.DataFrame:
    """Raw rows in groups with their factor, one row per product (before summing)."""
    w = w.assign(year=w["year"].astype(int), flow=w["flow"].map(FLOWS), tonnes=w["q100"] / 10)
    w = w[w["flow"].notna()]
    w["version"] = w["year"].map(hs_version)
    # HS6 codes: group and factor from the crosswalk of that year's HS version.
    six = w[w["product"].str.len() == 6].merge(
        hs[["version", "hs", "group", "to_primary"]].rename(columns={"hs": "product"}),
        on=["version", "product"], how="inner")
    six = six[(six["group"] != "fish") & (six["to_primary"] != "cn8")]
    six["factor"] = pd.to_numeric(six["to_primary"].replace("", "1"))
    # HS6 codes split at CN8 level (whey: powder or liquid)
    split = load_cn8_items()
    cn = w[w["product"].isin(split)].copy()
    cn["group"] = cn["product"].map(lambda c: split[c][0])
    cn["factor"] = cn["product"].map(lambda c: split[c][1])
    six = pd.concat([six, cn], ignore_index=True)
    # CN8 codes (fish): EUMOFA's factor for that code and year; a year EUMOFA does not list takes
    # the code's nearest listed year.
    eight = w[w["product"].str.len() == 8].rename(columns={"product": "cn8"})
    eight = eight[eight["cn8"].astype(str).str.startswith(FISH_PREFIXES)]
    eight = eight.merge(cf, on=["year", "cn8"], how="left")
    miss = eight["cf"].isna()
    if miss.any():
        near = cf.sort_values("year")
        for i in eight.index[miss]:
            c = near[near["cn8"] == eight.at[i, "cn8"]]
            if len(c):
                eight.at[i, "cf"] = c.iloc[(c["year"] - eight.at[i, "year"]).abs().argmin()]["cf"]
    gone = eight["cf"].isna()
    if gone.any():
        log.info("comext: %d fish rows (%.1f%% of fish tonnes) have no EUMOFA factor (not food): left out",
                 gone.sum(), 100 * eight.loc[gone, "tonnes"].sum() / max(eight["tonnes"].sum(), 1))
    eight = eight[~gone].assign(group="fish", factor=lambda x: x["cf"]).rename(columns={"cn8": "product"})
    out = pd.concat([six, eight], ignore_index=True)
    out["primary"] = out["tonnes"] * out["factor"]
    out["reporter"] = out["reporter"].map(partners)
    out["country"] = out["partner"].isin(partners)
    out["partner"] = out["partner"].map(partners).fillna(out["partner"])
    return out[out["partner"] != out["reporter"]]  # Spain with its Canary Islands, Ceuta, Melilla


def extract() -> None:
    """Raw extraction -> data/interim/comext_yearly.parquet. Runs before trade.extract."""
    dest = config.INTERIM / YEARLY
    if not RAW.exists():
        log.warning("no Comext extraction; run `atlas download --source comext`")
        dest.unlink(missing_ok=True)
        return
    partners = load_partners()
    hs = crosswalk.load()
    rows = _rows(read_raw(), hs, load_eumofa(), partners)
    mix_factors(rows, hs).to_parquet(config.INTERIM / MIX, index=False)
    keys = ["reporter", "partner", "country", "group", "flow", "year"]
    out = rows.groupby(keys, as_index=False)[["tonnes", "primary", "eur"]].sum(min_count=1)
    out.to_parquet(dest, index=False)
    log.info("wrote %s (%d rows; fish %.0f kt/year imported by members, live weight)", dest, len(out),
             out.query("group == 'fish' and flow == 'imports'").groupby("year")["primary"].sum().mean() / 1000)


def fish_partners(yearly: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Members' fish partners averaged over `years`: iso3, group, flow, partner, tonnes (live
    weight), source "comext". Partners that are no country are left out of the lists."""
    f = yearly[(yearly["group"] == "fish") & yearly["year"].between(*years) & yearly["country"]]
    n = years[1] - years[0] + 1
    out = f.groupby(["reporter", "group", "flow", "partner"], as_index=False)["primary"].sum()
    out = out.assign(tonnes=out["primary"] / n, source="comext").drop(columns="primary")
    return out.rename(columns={"reporter": "iso3"})


def fish_extra_shares(yearly: pd.DataFrame) -> pd.DataFrame:
    """Per member, year and flow: the share of its fish trade (live weight) with partners outside
    the EU. Unnamed partners count as outside, except Comext's intra-EU codes (INTRA_UNNAMED).
    Columns as trade.extra_eu_shares: iso3, group, flow, year, share."""
    f = yearly[yearly["group"] == "fish"]
    inside = f["partner"].isin(config.EU27) | f["partner"].isin(INTRA_UNNAMED)
    f = f.assign(extra=f["primary"].where(~inside, 0.0))
    g = f.groupby(["reporter", "group", "flow", "year"], as_index=False)[["extra", "primary"]].sum()
    g = g[g["primary"] > 0]
    g["share"] = g["extra"] / g["primary"]
    return g.rename(columns={"reporter": "iso3"})[["iso3", "group", "flow", "year", "share"]]


VALUE = "trade_value.parquet"


def value_partners(yearly: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """What members pay and earn per partner (methodology, "Value basis"): iso3, group, flow,
    partner, eur (yearly mean over `years`, nominal), for members and the EU bloc (members' trade
    with non-members). Partners that are no country are left out."""
    v = yearly[yearly["year"].between(*years) & yearly["country"] & yearly["eur"].notna()]
    n = years[1] - years[0] + 1
    out = v.groupby(["reporter", "group", "flow", "partner"], as_index=False)["eur"].sum()
    out = out.assign(eur=out["eur"] / n).rename(columns={"reporter": "iso3"})
    bloc = out[out["iso3"].isin(config.EU27) & ~out["partner"].isin(config.EU27)]
    bloc = bloc.groupby(["group", "flow", "partner"], as_index=False)["eur"].sum().assign(iso3="EU27")
    return pd.concat([out, bloc[out.columns]], ignore_index=True)


def run_value(years: tuple[int, int]) -> None:
    src, dest = config.INTERIM / YEARLY, config.PROCESSED / VALUE
    if not src.exists():
        dest.unlink(missing_ok=True)
        return
    v = value_partners(pd.read_parquet(src), years).assign(years=f"{years[0]}-{years[1]}")
    v.to_parquet(dest, index=False)
    log.info("wrote %s (%d rows; EU bloc food imports %.1f bn EUR a year)", dest, len(v),
             v.query("iso3 == 'EU27' and flow == 'imports' and group != 'fish'")["eur"].sum() / 1e9)


def compare_with_fao(yearly: pd.DataFrame, fao: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Members' trade per group and flow over `years`, Comext against FAO's trade matrix as
    reported by the member (both in the FBS basis, partners that are countries, yearly kt):
    iso3, group, flow, comext_kt, fao_kt, ratio (Comext / FAO)."""
    n = years[1] - years[0] + 1
    c = yearly[(yearly["group"] != "fish") & yearly["year"].between(*years) & yearly["country"]]
    c = c.groupby(["reporter", "group", "flow"])["primary"].sum() / n / 1000
    f = fao[fao["reporter"].isin(config.EU27) & (fao["source"] == "reported") & fao["year"].between(*years)]
    f = f.groupby(["reporter", "group", "flow"])["primary"].sum() / n / 1000
    j = pd.concat([c.rename("comext_kt"), f.rename("fao_kt")], axis=1).fillna(0.0).reset_index()
    j = j.rename(columns={"reporter": "iso3"})
    j["ratio"] = j["comext_kt"] / j["fao_kt"].where(j["fao_kt"] > 0)
    return j


def run_compare(years: tuple[int, int]) -> None:
    src, fao = config.INTERIM / YEARLY, config.INTERIM / "trade_yearly.parquet"
    dest = config.PROCESSED / COMPARE
    if not (src.exists() and fao.exists()):
        dest.unlink(missing_ok=True)
        return
    j = compare_with_fao(pd.read_parquet(src), pd.read_parquet(fao), years)
    j.assign(years=f"{years[0]}-{years[1]}").to_parquet(dest, index=False)
    log.info("wrote %s (%d member-group-flows; median Comext/FAO %.2f)", dest, len(j), j["ratio"].median())


# --- When it comes from abroad (methodology, "When it comes from abroad") -------------------------
MONTHLY = config.RAW / "comext" / "DS-045409_monthly_imports.csv.gz"
MONTHS_OUT = "import_months.parquet"
MONTHLY_GROUPS = ("fruit", "vegetables", "potatoes_roots")


# Fresh products by HS heading (methodology, "When it comes from abroad"): their seasons do not
# even out the way a whole food group's do.
FRESH = {
    "0701": "Potatoes", "0702": "Tomatoes", "0703": "Onions, garlic", "0704": "Cabbages",
    "0705": "Lettuce", "0706": "Carrots, roots", "0707": "Cucumbers", "0708": "Peas and beans",
    "0709": "Peppers, courgettes, asparagus", "0803": "Bananas", "0804": "Pineapples, avocados, mangoes", "0805": "Citrus fruit",
    "0806": "Grapes", "0807": "Melons", "0808": "Apples, pears", "0809": "Stone fruit",
    "0810": "Berries, kiwis",
}
MONTHS_MIN_SHARE = 5.0
MONTHS_MAX_ROWS = 4


def monthly_imports(years: tuple[int, int]) -> pd.DataFrame:
    """iso3 (members and EU27), group, hs4, month (1-12), share (% of the product's window
    imports), top (leading partner country that month), top_share (% of that month), rank."""
    with gzip.open(MONTHLY, "rt", encoding="utf-8") as f:
        d = pd.read_csv(f, dtype=str, keep_default_na=False,
                        usecols=["reporter", "partner", "product", "TIME_PERIOD", "OBS_VALUE"])
    d = d[(d["partner"].str.len() == 2) & (d["OBS_VALUE"] != "") & d["product"].str[:4].isin(FRESH)]
    d["year"] = d["TIME_PERIOD"].str[:4].astype(int)
    d["month"] = d["TIME_PERIOD"].str[5:7].astype(int)
    d = d[d["year"].between(*years)]
    d["version"] = d["year"].map(hs_version)
    hs = crosswalk.load()
    hs = hs[hs["group"].isin(MONTHLY_GROUPS)][["version", "hs", "group", "to_primary"]]
    d = d.merge(hs.rename(columns={"hs": "product"}), on=["version", "product"], how="inner")
    d["hs4"] = d["product"].str[:4]
    d["t"] = pd.to_numeric(d["OBS_VALUE"]) / 10 * pd.to_numeric(d["to_primary"].replace("", "1"))
    partners = load_partners()
    d["iso3"] = d["reporter"].map(partners)
    d["named"] = d["partner"].isin(partners)
    d["partner"] = d["partner"].map(partners).fillna(d["partner"])
    d = d[d["partner"] != d["iso3"]]
    keys = ["group", "hs4", "month", "partner", "named"]
    members = d.groupby(["iso3", *keys], as_index=False)["t"].sum()
    outside = ~(d["partner"].isin(config.EU27) | d["partner"].isin(INTRA_UNNAMED))
    bloc = d[outside].groupby(keys, as_index=False)["t"].sum().assign(iso3="EU27")
    m = pd.concat([members, bloc], ignore_index=True)
    rows = []
    for (iso3, group), gsub in m.groupby(["iso3", "group"]):
        gtot = gsub["t"].sum()
        tot = gsub.groupby("hs4")["t"].sum().sort_values(ascending=False)
        keep = [h for h, v in tot.items() if gtot > 0 and 100 * v / gtot >= MONTHS_MIN_SHARE][:MONTHS_MAX_ROWS]
        for rank, hs4 in enumerate(keep):
            sub = gsub[gsub["hs4"] == hs4]
            total = sub["t"].sum()
            for month in range(1, 13):
                mo = sub[sub["month"] == month]
                mt = mo["t"].sum()
                named = mo[mo["named"]].groupby("partner")["t"].sum()
                top, ts = (named.idxmax(), 100 * named.max() / mt) if mt > 0 and len(named) else (None, None)
                rows.append({"iso3": iso3, "group": group, "hs4": hs4, "rank": rank, "month": month,
                             "share": 100 * mt / total, "top": top, "top_share": ts})
    return pd.DataFrame(rows)


def run_months(years: tuple[int, int]) -> None:
    dest = config.PROCESSED / MONTHS_OUT
    if not MONTHLY.exists():
        log.warning("no monthly Comext imports; run `atlas download --source comext`")
        dest.unlink(missing_ok=True)
        return
    m = monthly_imports(years)
    m.assign(years=f"{years[0]}-{years[1]}").to_parquet(dest, index=False)
    log.info("wrote %s (%d countries)", dest, m["iso3"].nunique())


def export_months() -> None:
    import json

    src, dest = config.PROCESSED / MONTHS_OUT, config.WEB_DATA / "import_months.json"
    if not src.exists():
        dest.unlink(missing_ok=True)
        return
    m = pd.read_parquet(src).sort_values(["iso3", "group", "rank", "month"])
    countries: dict = {}
    for (iso3, group, _, hs4), sub in m.groupby(["iso3", "group", "rank", "hs4"], sort=True):
        countries.setdefault(iso3, {}).setdefault(group, []).append({
            "hs4": hs4,
            "share": [round(float(x), 1) for x in sub["share"]],
            "top": [[t, round(float(v))] if t else None for t, v in zip(sub["top"], sub["top_share"], strict=True)],
        })
    out = {"meta": {"source": "eurostat_comext", "years": m["years"].iloc[0],
                    "note": "imports by month, not harvests; EU27 = imports from outside the EU"},
           "names": FRESH, "countries": countries}
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)
