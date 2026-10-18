"""processed Parquet -> small JSON/GeoJSON files for the web frontend.

Outputs (web/public/data/):
    countries.geojson   country polygons in scope, properties {iso3, iso2, name}
    countries.topojson  the same as TopoJSON (web/scripts/build-topo.mjs), what the page loads
    ssr.json            {meta, groups[], countries{iso3: {name, region, notes, indicators, trend,
                        trend_unusual?}}}
    ssr_core.json       the subset the first paint needs (names, headline figures, withheld
                        reasons; core_of), 16 KB compressed against ~190 KB; loaded first
    items.json          {iso3: {group: [{item, ssr, supply_kt}]}}  (expert view, loaded lazily)
    trade.json          {meta{…, withheld}, names, countries{iso3: {group: {imports|exports|grown:
                        [total_t, [[partner, t], ...]]}}}}  (trade view, loaded lazily)
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pandas as pd

from . import checks, config, jrc, regions
from .compute import EU_BLOC, to_wide
from .harmonise import load_countries, load_products
from .trade import load_trade_only

log = logging.getLogger(__name__)


def _round(x, nd=1):
    if x is None or pd.isna(x):
        return None
    return round(float(x), nd)


def faostat_release(fname: str) -> str | None:
    """Release date (YYYY-MM-DD) of a FAOSTAT bulk file, from the catalogue saved at download."""
    cat = config.RAW / "faostat" / config.FAOSTAT_CATALOGUE
    if not cat.exists():
        log.warning("no %s; run `atlas download --source faostat` to record release dates", cat)
        return None
    for ds in ET.parse(cat).getroot().iter("Dataset"):
        if (ds.findtext("FileLocation") or "").endswith("/" + fname):
            return (ds.findtext("DateUpdate") or "")[:10] or None
    return None


def downloaded_on(path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()


def sources() -> dict:
    """config.SOURCES plus release / download dates of the files actually used."""
    out = {}
    for key, src in config.SOURCES.items():
        entry = {k: v for k, v in src.items() if k != "catalogue_file"}
        if "catalogue_file" in src:
            raw = config.RAW / "faostat" / src["catalogue_file"]
            entry["released"] = faostat_release(src["catalogue_file"])
            entry["downloaded"] = downloaded_on(raw)
            entry["size_mb"] = round(raw.stat().st_size / 1e6) if raw.exists() else None
        if key == "jrc_bal":
            entry["downloaded"] = downloaded_on(jrc.ZIP)
        out[key] = entry
    return out


def _range(lo, hi) -> list | None:
    """The two readings of a withheld ratio (compute.group_tonnes / overall), for "more than it
    uses" / "less than it uses" in words when both agree. None when there is no reading."""
    lo, hi = _round(lo), _round(hi)
    return None if lo is None else [lo, hi]


def _all_basis(r: pd.Series, w: str, extra: dict) -> dict:
    """ "All food" on one basis (protein or kcal): withheld like a food when it rests on
    contradictory balances (compute.overall `{w}_flag`)."""
    flag = r.get(f"{w}_flag") or ""
    if flag:
        return extra | {"withheld": {"reason": flag,
                                     "range": _range(r.get(f"{w}_ssr_low"), r.get(f"{w}_ssr_high")),
                                     "share_range": _range(r.get(f"{w}_share_low"),
                                                           r.get(f"{w}_share_high"))}}
    return {"share": _round(r[f"{w}_share"]), "ssr": _round(r[f"{w}_ssr"])} | extra


# A disagreement is shown for an item carrying at least this share of its group's domestic supply.
USDA_ITEM_SHARE = 0.10
USDA_GROUP_PP = 5.0  # ... or a disagreement that could move the group's figure by this many points


def _usda_disagreements(items: pd.DataFrame) -> dict:
    """(iso3, group) -> [{item, fao, usda}] where USDA's PSD puts an important item's SSR far from
    FAO's (pipeline/usda.py `large_gap`). Shown next to FAO's figure, never instead of it."""
    from . import usda

    if not usda.OUT.exists():
        return {}
    config.require_fresh(usda.OUT, [config.PROCESSED / "ssr_items.parquet", usda.ZIP])
    cmp = pd.read_parquet(usda.OUT)
    cmp = cmp[cmp["large_gap"] & cmp["ssr_fao"].notna() & cmp["ssr_usda"].notna()]
    groups = items[items["group"].notna()][["iso3", "item", "group", "supply"]]
    gsum = groups.groupby(["iso3", "group"])["supply"].sum()
    cmp = cmp.merge(groups[["iso3", "item", "group"]], on=["iso3", "item"], how="inner")
    out: dict = {}
    for _, r in cmp.sort_values("supply_fao", ascending=False).iterrows():
        tot = gsum.get((r["iso3"], r["group"]))
        if not tot or tot <= 0:
            continue
        share = r["supply_fao"] / tot
        # an important item, or one whose disagreement could move the group's figure by 5 points
        if share < USDA_ITEM_SHARE and share * abs(r["ssr_fao"] - r["ssr_usda"]) < USDA_GROUP_PP:
            continue
        out.setdefault((r["iso3"], r["group"]), []).append(
            {"item": r["item"], "fao": _round(r["ssr_fao"]), "usda": _round(r["ssr_usda"])})
    return out


def eu_intra_dairy(years: tuple[int, int]) -> dict | None:
    """Members' FBS dairy trade with each other, Mt/year over `years`: what they report buying from
    and selling to other members (FBS milk equivalent × intra-EU share from the trade matrix).
    The UI quotes it to explain why the EU bloc is rebuilt instead of summed."""
    fbs_path, shares_path = config.INTERIM / "fbs.parquet", config.INTERIM / "eu_extra_shares.parquet"
    if not (fbs_path.exists() and shares_path.exists()):
        return None
    dairy = list(load_products()["groups"]["dairy"]["items"])
    fbs = pd.read_parquet(fbs_path)
    fbs = fbs[fbs["iso3"].isin(config.EU27) & fbs["year"].between(*years)
              & fbs["item"].isin(dairy)]
    wide = to_wide(fbs)
    d = wide.groupby(["iso3", "year"], as_index=False)[["imports", "exports"]].sum()
    sh = pd.read_parquet(shares_path)
    sh = sh[(sh["group"] == "dairy") & sh["year"].between(*years)]
    out = {}
    for flow in ("imports", "exports"):
        x = d.merge(sh[sh["flow"] == flow][["iso3", "year", "share"]], on=["iso3", "year"])
        out[flow] = round(float((x[flow] * (1 - x["share"])).sum()) / (years[1] - years[0] + 1) / 1000)
    return out


USE_KEYS = ("food", "feed", "seed", "losses", "processing", "other_uses", "tourist", "residuals")
PER_CAPITA_KEYS = (
    "production", "imports", "exports", "supply",
    "food", "feed", "seed", "losses", "processing", "other_uses", "tourist", "residuals",
)
ALL_FOOD = {
    "key": "all",
    "label": "All food",
    "plain": "Counted by protein, the part of food that is hardest to replace. Meat, milk and "
    "eggs count as produced here even when the animals ate imported feed.",
    "notes": "Protein-weighted across every FBS commodity. Each food's self-sufficiency is capped "
    "at 100% so a surplus of one food cannot hide a shortage of another. Meat, milk and eggs count "
    "as home-grown even when the animals ate imported feed.",
}
EU_ENTRY = {
    "name": "European Union (27)",
    "region": "EU27",
    "notes": "All 27 member states as one. Production is summed; imports and exports are trade "
    "with non-members only, so trade between members does not count.",
}


# JRC foods that are one item inside a products.yaml group, and how the UI names them.
JRC_GROUP = {"tomatoes": "vegetables", "olive_oil": "vegetable_oils", "wine": "wine_beer"}
JRC_LABEL = {"tomatoes": "tomatoes", "olive_oil": "olive oil", "wine": "wine"}


def _compact(x):
    """Drop None values and empty containers from dicts (lists keep None to stay aligned)."""
    if isinstance(x, dict):
        out = {k: _compact(v) for k, v in x.items()}
        return {k: v for k, v in out.items() if v is not None and v != {} and v != []}
    if isinstance(x, list):
        return [_compact(v) for v in x]
    return x


def _trend_series(trends: pd.DataFrame, years: list[int]) -> tuple[dict, dict]:
    """{iso3: {group: [ssr per year, aligned to `years`]}}, and {iso3: {group: [unusual years]}}
    (checks.unusual_years: a year far from both neighbours, marked for the chart)."""
    out: dict = {}
    unusual: dict = {}
    for (iso3, group), sub in trends.groupby(["iso3", "group"]):
        by_year = dict(zip(sub["year"], sub["ssr"], strict=False))
        out.setdefault(iso3, {})[group] = [_round(by_year.get(y)) for y in years]
        odd = checks.unusual_years({int(y): by_year.get(y) for y in years})
        if odd:
            unusual.setdefault(iso3, {})[group] = odd
    return out, unusual


def _averages(groups: pd.DataFrame, overall: pd.DataFrame, national: list[str]) -> dict:
    """Population-weighted averages across `national` (EU27 bloc excluded)."""
    t = groups[(groups["basis"] == "tonnes") & groups["iso3"].isin(national)]
    avg = {}
    for group, sub in t.groupby("group"):
        sub = sub[sub["food"].notna() & sub["population"].notna()]
        if len(sub):
            avg[group] = {"food_kg_pc": _round(sub["food"].sum() * 1000 / sub["population"].sum())}
    o = overall[overall["iso3"].isin(national) & overall["protein"].notna()]
    if len(o):
        avg["all"] = {
            "protein_g": _round((o["protein"] * o["population"]).sum() / o["population"].sum())
        }
    return avg


def group_entries(products: dict) -> list[dict]:
    """Food groups for the UI. `items` are the FAO item names summed into each group, so readers
    can look the figures up in FAOSTAT themselves."""
    return [ALL_FOOD] + [
        {"key": k, "label": g["label"], "plain": g.get("plain"),
         "notes": " ".join(g.get("notes", "").split()) or None, "items": list(g["items"])}
        for k, g in products.items()
    ]


# The first paint (map colours, tooltips, the start page) needs only these; the panel waits for the
# full ssr.json, fetched in parallel. A strict subset: validate.check_core compares the two.
CORE_COUNTRY = ("name", "region", "europe", "view", "notes")


def core_of(full: dict) -> dict:
    """ssr.json -> ssr_core.json: meta, groups, and per country the names and each food's headline
    figure (tonnes SSR; all food: protein SSR) with its withheld reason."""
    countries = {}
    for iso3, c in full["countries"].items():
        e = {k: c[k] for k in CORE_COUNTRY if k in c}
        ind = {}
        for g, i in (c.get("indicators") or {}).items():
            where = i.get("protein", {}) if g == "all" else i
            figure = {"ssr": where["ssr"]} if where.get("ssr") is not None else {}
            w = {"reason": where["withheld"]["reason"]} if where.get("withheld") else None
            if g == "all":
                ind[g] = {"protein": {**figure, **({"withheld": w} if w else {})}}
            else:
                ind[g] = {**({"tonnes": {"ssr": i["tonnes"]["ssr"]}} if (i.get("tonnes") or {}).get("ssr") is not None else {}),
                          **({"withheld": w} if w else {})}
        if ind:
            e["indicators"] = ind
        countries[iso3] = e
    return {"meta": full["meta"], "groups": full["groups"], "countries": countries}


def export_ssr() -> None:
    m = config.MAPPINGS
    for name in ("groups", "items", "overall", "trends"):
        config.require_fresh(config.PROCESSED / f"ssr_{name}.parquet",
                             [config.INTERIM / "fbs.parquet", config.INTERIM / "eu_extra_shares.parquet",
                              jrc.CSV, m / "products.yaml", m / "countries.yaml", m / "world.csv"])
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    items = pd.read_parquet(config.PROCESSED / "ssr_items.parquet")
    overall = pd.read_parquet(config.PROCESSED / "ssr_overall.parquet")
    trends = pd.read_parquet(config.PROCESSED / "ssr_trends.parquet")
    countries = load_countries().set_index("iso3")
    products = load_products()["groups"]

    years = sorted(groups["years"].unique())
    disagree = _usda_disagreements(items)
    review = checks.reviewed_withholds()
    plaus = _plausibility()
    window = tuple(int(y) for y in years[-1].split("-")) if years else None
    trend_years = sorted(int(y) for y in trends["year"].unique())
    series, unusual = _trend_series(trends, trend_years)
    out: dict = {
        "meta": {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "years": years[-1] if years else None,
            "trend_years": trend_years,
            "source": "fao_fbs",
            "elements": {k: config.FBS_ELEMENTS[k]
                         for k in ("production", "imports", "exports", "supply", "population",
                                   "stock_variation", "residuals")},
            "sources": sources(),
            "view": "national",
            "eu_members": sorted(config.EU27),
            # Figures quoted in the UI's text, computed here so no number there is typed by hand.
            "claims": {"eu_intra_dairy_mt": eu_intra_dairy(
                tuple(int(y) for y in years[-1].split("-"))) if years else None},
            "europe_avg": _averages(groups, overall, list(countries.index[countries["europe"]])),
            "world_avg": _averages(groups, overall, list(countries.index)),
            "formulas": {
                "ssr": "production / domestic supply * 100",
                "idr": "imports / domestic supply * 100",
                "protein_share": "sum(protein_i * min(ssr_i, 100)) / sum(protein_i), FBS leaf items",
            },
        },
        "groups": group_entries(products),
        "countries": {},
    }

    entries = [
        (iso3, {
            "name": c["name"],
            "region": c["group"],
            "notes": c.get("notes") if isinstance(c.get("notes"), str) else None,
        })
        for iso3, c in countries.iterrows()
    ]
    if (groups["iso3"] == EU_BLOC).any():
        entries.append((EU_BLOC, dict(EU_ENTRY)))

    item_tables: dict = {}  # expert-only detail, written to items.json and loaded on demand
    # Feed: imported share of feed protein, feed-adjusted meat and eggs (methodology, "Feed").
    fp = config.PROCESSED / "feed.parquet"
    feed = pd.read_parquet(fp).set_index("iso3") if fp.exists() else pd.DataFrame()
    for iso3, entry in entries:
        if iso3 in feed.index:
            r = feed.loc[iso3]
            entry["feed"] = {"imported_pct": _round(r["imported_pct"]), "top": json.loads(r["top"]),
                             "meat_ssr": _round(r["meat_ssr"]), "eggs_ssr": _round(r["eggs_ssr"]),
                             "items_pct": _round(r["items_pct"])}
        entry.update({"view": "eu_bloc" if iso3 == EU_BLOC else "national",
                      "europe": bool(iso3 == EU_BLOC or countries.loc[iso3, "europe"]),
                      "indicators": {}, "trend": series.get(iso3, {})})
        if iso3 in unusual:
            entry["trend_unusual"] = unusual[iso3]
        o = overall[overall["iso3"] == iso3]
        if len(o):
            r = o.iloc[0]
            entry["indicators"]["all"] = {
                w: _all_basis(r, w, extra) for w, extra in
                (("protein", {"g_per_day": _round(r["protein"])}),
                 ("kcal", {"per_day": _round(r["kcal"], 0)}))
            } | {
                "n_foods": int(r["n_foods"]) if pd.notna(r.get("n_foods")) else None,
                # foods left out because FAO's balance for them contradicts itself
                "n_withheld": int(r["n_withheld"]) if r.get("n_withheld") else None,
            }
            entry["indicators"]["all"]["source"] = r["source"]
            entry["population_k"] = _round(r["population"], 0)
        g_rows = groups[groups["iso3"] == iso3]
        g_rows = g_rows.assign(uses_bad=checks.uses_problem(g_rows))
        # One verdict per balance (pipeline/checks.py), set by the tonnes row and applied to both
        # bases: a withheld food has no ratio and no per-person figures anywhere in the UI, only
        # FAO's raw lines under "withheld" so the receipt can show why.
        withheld = {r["group"]: r["flag"] for _, r in g_rows.iterrows()
                    if r["basis"] == "tonnes" and r.get("flag")}
        for _, r in g_rows.iterrows():
            ind = entry["indicators"].setdefault(r["group"], {})
            reason = withheld.get(r["group"])
            ind[r["basis"]] = {
                "ssr": None if reason else _round(r["ssr"]),
                "idr": None if reason else _round(r["idr"]),
                "flag": reason or None,
            }
            if r["basis"] == "tonnes":
                # kt with one decimal so small countries keep usable kg/person precision.
                comp = {k: _round(r[k], 1) for k in (*PER_CAPITA_KEYS, "stock_variation")}
                if reason:
                    ind["withheld"] = {"reason": reason, "components_kt": comp,
                                       "range": _range(r.get("ssr_low"), r.get("ssr_high"))}
                    if reason == checks.REVIEWED:
                        ind["withheld"]["note"] = review.get((iso3, r["group"]))
                    if reason == checks.IMPLAUSIBLE:
                        # the second readings that moved the figure (plausible.py), for the text
                        ind["withheld"]["plausibility"] = plaus.get((iso3, r["group"]), [])
                    if reason == checks.PARTS_CONTRADICT:
                        # which foods' own figures contradict themselves, for the explanation
                        bad = items[(items["iso3"] == iso3) & (items["group"] == r["group"])
                                    & (items["flag"].fillna("") != "")
                                    & (items["production"].fillna(0).abs()
                                       + items["imports"].fillna(0).abs() > 0)]
                        ind["withheld"]["items"] = sorted(bad["item"])
                else:
                    ind["components_kt"] = {k: comp[k] for k in PER_CAPITA_KEYS}
                    # FAO's uses (food, feed, ...) do not add up to domestic supply: keep the
                    # ratio, drop the breakdown (pipeline/checks.py).
                    if r["uses_bad"]:
                        ind["uses_withheld"] = checks.RESIDUALS_LARGE
                        for k in USE_KEYS:
                            ind["components_kt"].pop(k, None)
                # Source as computed (compute._source): the JRC is cited exactly where it
                # replaced FAO in this window, dairy as a whole, the others as one item.
                ind["source"] = r["source"]
                foods = set(filter(None, str(r.get("jrc_foods") or "").split(",")))
                parts = [JRC_LABEL[f] for f, g in JRC_GROUP.items() if g == r["group"] and f in foods]
                if parts:
                    ind["jrc_items"] = parts
                if (iso3, r["group"]) in disagree:
                    ind["usda"] = disagree[(iso3, r["group"])]
                if r["source"] == "jrc_bal" and "kcal" not in ind:
                    # One milk-equivalent balance: no per-product ratio to weight by calories.
                    ind["kcal"] = {"flag": "jrc_group_only"}
        isub = items[(items["iso3"] == iso3) & items["group"].notna()]
        for _, r in isub.iterrows():
            item_tables.setdefault(iso3, {}).setdefault(r["group"], []).append(
                # JRC dairy: FAO's product-weight items scaled to a milk-equivalent total are
                # neither FAO's figures nor the JRC's, so no per-product ratio is shown.
                {
                    "item": r["item"],
                    "ssr": None if r.get("jrc_food") == "dairy" else _round(r["ssr"]),
                    "supply_kt": None if r.get("jrc_food") == "dairy" else _round(r["supply"], 0),
                    "flag": "jrc_group_only" if r.get("jrc_food") == "dairy" else (r.get("flag") or None),
                }
            )
        out["countries"][iso3] = entry

    dest = config.WEB_DATA / "ssr.json"
    dest.write_text(json.dumps(_compact(out), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    log.info("wrote %s (%d countries, %.0f KB)", dest, len(out["countries"]),
             dest.stat().st_size / 1024)
    dest = config.WEB_DATA / "ssr_core.json"
    dest.write_text(json.dumps(core_of(_compact(out)), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)
    dest = config.WEB_DATA / "items.json"
    dest.write_text(json.dumps(_compact(item_tables), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)


def _plausibility() -> dict[tuple[str, str], list[dict]]:
    """(iso3, group) -> the plausibility test's second readings (data/processed/plausibility.parquet):
    test, ssr_alt (null: no use at home left), and per test the figures the UI quotes: kg a
    person and the ceiling (use_per_person); the records' imports in kt and the balance's ratio to
    them against the group's typical one (imports_vs_trade)."""
    from . import plausible

    path = config.PROCESSED / plausible.OUT
    if not path.exists():
        return {}
    out: dict = {}
    for r in pd.read_parquet(path).itertuples():
        d = {"test": r.test, "ssr_alt": _round(r.ssr_alt)}
        if r.test == "use_per_person":
            d |= {"kg": _round(r.value, 0), "ceiling_kg": _round(r.limit, 0)}
        else:
            d |= {"trade_kt": _round(r.trade_kt, 0), "ratio": _round(r.value), "typical": _round(r.limit)}
        out.setdefault((r.iso3, r.group), []).append(d)
    return out


def _round_coords(c, nd: int = 3):
    """Round nested coordinate arrays (3 decimals ~ 100 m; plenty at 1:20M)."""
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [_round_coords(x, nd) for x in c]


# GISCO country ids are ISO 3166-1 alpha-2 except for Greece and the UK.
GISCO_ISO2 = {"EL": "GR", "UK": "GB"}


def export_countries_geojson() -> None:
    src = (
        config.RAW
        / "gisco"
        / f"CNTR_RG_{config.GISCO_NUTS_SCALE}_{config.GISCO_COUNTRIES_YEAR}_4326.geojson"
    )
    if not src.exists():
        log.warning("no GISCO countries file at %s; run `atlas download --source boundaries`", src)
        return
    known = load_countries().set_index("iso3")["name"].to_dict()
    gj = json.loads(src.read_text(encoding="utf-8"))
    feats = []
    for f in gj["features"]:
        p = f.get("properties", {})
        iso3 = p.get("ISO3_CODE")
        if not iso3 or iso3 == "ATA":
            continue
        geom = {"type": f["geometry"]["type"],
                "coordinates": _round_coords(f["geometry"]["coordinates"])}
        feats.append({"type": "Feature", "geometry": geom,
                      "properties": {"iso3": iso3, "iso2": GISCO_ISO2.get(p["CNTR_ID"], p["CNTR_ID"]),
                                     "name": known.get(iso3, p.get("NAME_ENGL"))}})
    missing = sorted(set(known) - {f["properties"]["iso3"] for f in feats})
    if missing:
        log.warning("FBS countries with no polygon: %s", missing)
    dest = config.WEB_DATA / "countries.geojson"
    dest.write_text(
        json.dumps({"type": "FeatureCollection",
                    "attribution": "© EuroGeographics for the administrative boundaries",
                    "source": "gisco_countries",
                    "features": feats}, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info("wrote %s (%d features, %.0f KB)", dest, len(feats), dest.stat().st_size / 1024)


# Partners kept per country × food × flow: everyone with at least this share, at most this many.
TRADE_MIN_SHARE = 0.005
TRADE_MAX_PARTNERS = 24


def _trade_entry(sub: pd.DataFrame, col: str = "tonnes", scale: float = 1.0) -> list:
    """[total, [[partner, amount], ...]] largest first; the rest is total minus the list.
    `col` / `scale`: tonnes as they are, or euros in thousands (scale 1/1000)."""
    total = sub[col].sum() * scale
    s = sub.groupby("partner")[col].sum().sort_values(ascending=False) * scale
    s = s[s >= TRADE_MIN_SHARE * total].head(TRADE_MAX_PARTNERS)
    return [round(total), [[p, round(t)] for p, t in s.items()]]


def _hhi(sub: pd.DataFrame, col: str = "tonnes") -> int | None:
    """Sum of squared partner shares in percent, over all partners: 10,000 = one partner."""
    by = sub.groupby("partner")[col].sum()
    total = by.sum()
    if not total > 0:
        return None
    return round(float(((by / total * 100) ** 2).sum()))


def _value_block() -> dict | None:
    from . import comext

    src = config.PROCESSED / comext.VALUE
    if not src.exists():
        return None
    v = pd.read_parquet(src)
    v = pd.concat([v, v[v["group"] != "fish"].assign(group="all")], ignore_index=True)
    countries: dict = {}
    concentration: dict = {}
    for (iso3, group, flow), sub in v.groupby(["iso3", "group", "flow"]):
        if not sub["eur"].sum() > 0:
            continue
        countries.setdefault(iso3, {}).setdefault(group, {})[flow] = _trade_entry(sub, "eur", 1 / 1000)
        h = _hhi(sub, "eur")
        if h is not None:
            concentration.setdefault(iso3, {}).setdefault(group, {})[flow] = h
    return {
        "meta": {"source": "eurostat_comext", "years": v["years"].iloc[0], "unit": "thousand EUR",
                 "basis": "nominal euros a year; imports CIF, exports FOB; all food without fish"},
        "countries": countries,
        "concentration": concentration,
    }


def export_trade() -> None:
    src = config.PROCESSED / "trade_partners.parquet"
    if not src.exists():
        log.warning("no %s; run `atlas build` with the trade matrix downloaded", src)
        return
    config.require_fresh(src, [config.INTERIM / "trade_yearly.parquet",
                               config.PROCESSED / "ssr_groups.parquet"])
    t = pd.read_parquet(src)
    # Trade records far above the food balance describe transit or misreporting, not the country's
    # own trade: those flows are withheld (checks.trade_verdicts; methodology, "Trade records
    # against the food balance"). Withheld imports take the "grown" tracing with them.
    v = checks.trade_verdicts(t, pd.read_parquet(config.PROCESSED / "ssr_groups.parquet"))
    v = v[v["verdict"] == "withhold"].sort_values(["iso3", "group", "flow"])
    hidden = {(r.iso3, r.group, f) for r in v.itertuples()
              for f in (["imports", "grown"] if r.flow == "imports" else ["exports"])}
    # "All food": every group added up, in tonnes as traded; fish left out, since only EU members
    # have fish partners (methodology, "Trade partners", export file).
    t = pd.concat([t, t[t["group"] != "fish"].assign(group="all")], ignore_index=True)
    countries: dict = {}
    concentration: dict = {}
    for (iso3, group, flow), sub in t.groupby(["iso3", "group", "flow"]):
        if (iso3, group, flow) in hidden:
            continue
        countries.setdefault(iso3, {}).setdefault(group, {})[flow] = _trade_entry(sub)
        if flow in ("imports", "exports"):
            h = _hhi(sub)
            if h is not None:
                concentration.setdefault(iso3, {}).setdefault(group, {})[flow] = h
    mirrored = sorted(t.loc[t["source"].isin(["mirror", "mixed"]), "iso3"].unique())
    out = {
        "meta": {
            "source": "fao_tm",
            # Groups whose partners come from another source (methodology, "Comext").
            "group_source": {"fish": {"eu": "eurostat_comext", "other": "cepii_baci"}},
            "years": t["years"].iloc[0],
            "basis": {
                "imports": "tonnes as traded (product weight); dairy in milk equivalent",
                "exports": "tonnes as traded (product weight); dairy in milk equivalent",
                # trade.trace_origins scales the splits to FBS import totals.
                "grown": "tonnes in FBS primary equivalents (shares only)",
                "fish": "tonnes live weight: EU members and bloc from Comext (EUMOFA factor per CN8 "
                        "code and year), other countries from BACI (the EU's mix of those factors per HS6)",
            },
            # Countries for which some flows come from partners' reports.
            "mirror": mirrored,
            # Flows not published: [iso3, group, flow, trade records kt, food balance kt].
            "withheld": [[r.iso3, r.group, r.flow, round(r.trade_kt), round(r.balance_kt)]
                         + ([r.note] if isinstance(r.note, str) and r.note else []) for r in v.itertuples()],
        },
        "names": dict(zip(*load_trade_only()[["iso3", "name"]].T.values, strict=True)),
        "countries": countries,
        # Herfindahl-Hirschman index of partner shares (methodology, "Trade partners").
        "concentration": concentration,
        # What EU members and the EU bloc pay and earn (methodology, "Value basis").
        "value": _value_block(),
    }
    dest = config.WEB_DATA / "trade.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)


def export_seasons() -> None:
    """seasons.json (methodology, "Seasons"): the crop strips each food page shows."""
    from . import seasons
    from .harmonise import load_products

    src = config.PROCESSED / seasons.OUT
    dest = config.WEB_DATA / "seasons.json"
    if not src.exists():
        dest.unlink(missing_ok=True)
        return
    items = pd.read_parquet(config.PROCESSED / "ssr_items.parquet")
    if "basis" in items:
        items = items[items["basis"] == "tonnes"]
    g = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    g = g[g["basis"] == "tonnes"]
    withheld = set(zip(g.loc[g["flag"].fillna("") != "", "iso3"], g.loc[g["flag"].fillna("") != "", "group"]))
    groups = {k: v["items"] for k, v in load_products()["groups"].items()}
    dropped: dict = {}
    rows = seasons.rows_for(pd.read_parquet(src), items, groups, dropped)
    rows = {iso: {gr: r for gr, r in gs.items() if (iso, gr) not in withheld} for iso, gs in rows.items()}
    rows = {iso: gs for iso, gs in rows.items() if gs}
    dropped = {iso: {gr: sorted(v) for gr, v in gs.items() if (iso, gr) not in withheld}
               for iso, gs in dropped.items()}
    dropped = {iso: gs for iso, gs in dropped.items() if gs}
    out = {
        "meta": {
            "sources": ["ggcmi_calendar", "isimip_landuse", "ggcmi_wheat_areas", "isimip_countrymasks",
                        "wheat_harvest_iwc"],
            "note": "a typical year (multi-year average calendars), not the years of the other figures",
            "thresholds": {"harvest": seasons.HARVEST_MIN, "sowing": seasons.SOWN_MIN,
                           "growing": seasons.GROWING_MIN, "min_share": seasons.MIN_SHARE,
                           "max_rows": seasons.MAX_ROWS, "check_share": seasons.CHECK_SHARE},
            "check": "wheat_harvest_iwc",
        },
        "countries": rows,
        # crops left out because their calendar fails the wheat-harvest check (seasons.fails_reference)
        "left_out": dropped,
    }
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%.0f KB, %d countries)", dest, dest.stat().st_size / 1024, len(rows))


def export_topojson() -> None:
    """countries.topojson from countries.geojson (web/scripts/build-topo.mjs, Node): shared borders
    stored once, about 40% smaller compressed. Without Node the page falls back to the GeoJSON."""
    import shutil
    import subprocess

    dest = config.WEB_DATA / "countries.topojson"
    node = shutil.which("node")
    script = config.ROOT / "web" / "scripts" / "build-topo.mjs"
    if node is None or not (config.ROOT / "web" / "node_modules" / "topojson-server").exists():
        log.warning("no Node or topojson-server (cd web && npm install): the page loads countries.geojson")
        dest.unlink(missing_ok=True)
        return
    out = subprocess.run([node, str(script)], cwd=config.ROOT / "web", capture_output=True, text=True, check=True)
    log.info("%s (%.0f KB)", out.stdout.strip(), dest.stat().st_size / 1024)


def run() -> None:
    config.ensure_dirs()
    export_countries_geojson()
    export_topojson()
    export_ssr()
    export_trade()
    export_seasons()
    regions.export()
    from . import comext

    comext.export_months()
    from . import cropmap

    cropmap.run()
    from . import scenario

    scenario.export()
