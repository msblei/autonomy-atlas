"""processed Parquet -> small JSON/GeoJSON files for the web frontend.

Outputs (web/public/data/):
    countries.geojson   country polygons in scope, properties {iso3, iso2, name}
    ssr.json            {meta, groups[], countries{iso3: {name, region, notes, indicators, trend}}}
    items.json          {iso3: {group: [{item, ssr, supply_kt}]}}  (expert view, loaded lazily)
    trade.json          {meta, names, countries{iso3: {group: {imports|exports: [total_t,
                        [[partner, t], ...]]}}}}  (trade view, loaded lazily)
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pandas as pd

from . import checks, config, jrc
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


def _trend_series(trends: pd.DataFrame, years: list[int]) -> dict:
    """{iso3: {group: [ssr per year, aligned to `years`]}}."""
    out: dict = {}
    for (iso3, group), sub in trends.groupby(["iso3", "group"]):
        by_year = dict(zip(sub["year"], sub["ssr"], strict=False))
        out.setdefault(iso3, {})[group] = [_round(by_year.get(y)) for y in years]
    return out


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
    trend_years = sorted(int(y) for y in trends["year"].unique())
    series = _trend_series(trends, trend_years)
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
    for iso3, entry in entries:
        entry.update({"view": "eu_bloc" if iso3 == EU_BLOC else "national",
                      "europe": bool(iso3 == EU_BLOC or countries.loc[iso3, "europe"]),
                      "indicators": {}, "trend": series.get(iso3, {})})
        o = overall[overall["iso3"] == iso3]
        if len(o):
            r = o.iloc[0]
            entry["indicators"]["all"] = {
                "protein": {"share": _round(r["protein_share"]), "ssr": _round(r["protein_ssr"]),
                            "g_per_day": _round(r["protein"])},
                "kcal": {"share": _round(r["kcal_share"]), "ssr": _round(r["kcal_ssr"]),
                         "per_day": _round(r["kcal"], 0)},
                "n_foods": int(r["n_foods"]) if pd.notna(r.get("n_foods")) else None,
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
                    ind["withheld"] = {"reason": reason, "components_kt": comp}
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
    dest = config.WEB_DATA / "items.json"
    dest.write_text(json.dumps(_compact(item_tables), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)


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


def _trade_entry(sub: pd.DataFrame) -> list:
    """[total tonnes, [[partner, tonnes], ...]] largest first; the rest is total minus the list."""
    total = sub["tonnes"].sum()
    s = sub.groupby("partner")["tonnes"].sum().sort_values(ascending=False)
    s = s[s >= TRADE_MIN_SHARE * total].head(TRADE_MAX_PARTNERS)
    return [round(total), [[p, round(t)] for p, t in s.items()]]


def export_trade() -> None:
    src = config.PROCESSED / "trade_partners.parquet"
    if not src.exists():
        log.warning("no %s; run `atlas build` with the trade matrix downloaded", src)
        return
    config.require_fresh(src, [config.INTERIM / "trade_yearly.parquet",
                               config.PROCESSED / "ssr_groups.parquet"])
    t = pd.read_parquet(src)
    # "All food": every group added up, in tonnes as traded.
    t = pd.concat([t, t.assign(group="all")], ignore_index=True)
    countries: dict = {}
    for (iso3, group, flow), sub in t.groupby(["iso3", "group", "flow"]):
        countries.setdefault(iso3, {}).setdefault(group, {})[flow] = _trade_entry(sub)
    mirrored = sorted(t.loc[t["source"].isin(["mirror", "mixed"]), "iso3"].unique())
    out = {
        "meta": {
            "source": "fao_tm",
            "years": t["years"].iloc[0],
            "basis": {
                "imports": "tonnes as traded (product weight)",
                "exports": "tonnes as traded (product weight)",
                # trade.trace_origins scales the splits to FBS import totals.
                "grown": "tonnes in FBS primary equivalents (shares only)",
            },
            # Countries for which some flows come from partners' reports.
            "mirror": mirrored,
        },
        "names": dict(zip(*load_trade_only()[["iso3", "name"]].T.values, strict=True)),
        "countries": countries,
    }
    dest = config.WEB_DATA / "trade.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)


def run() -> None:
    config.ensure_dirs()
    export_countries_geojson()
    export_ssr()
    export_trade()
