"""processed Parquet -> small JSON/GeoJSON files for the web frontend.

Outputs (web/public/data/):
    countries.geojson   country polygons in scope, properties {iso3, name}
    ssr.json            {meta, groups[], countries{iso3: {name, region, notes, indicators{...}}}}
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pandas as pd

from . import config
from .compute import EU_BLOC
from .harmonise import load_countries, load_products

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
            entry["released"] = faostat_release(src["catalogue_file"])
            entry["downloaded"] = downloaded_on(config.RAW / "faostat" / src["catalogue_file"])
        out[key] = entry
    return out


PER_CAPITA_KEYS = (
    "production", "imports", "exports", "supply",
    "food", "feed", "seed", "losses", "processing", "other_uses", "tourist", "residuals",
)
ALL_FOOD = {
    "key": "all",
    "label": "All food",
    "notes": "Protein-weighted across every FBS commodity. Each food's self-sufficiency is capped "
    "at 100% so a surplus of one food cannot hide a shortage of another. Meat, milk and eggs count "
    "as home-grown even when the animals ate imported feed.",
}
EU_ENTRY = {
    "name": "European Union (27)",
    "region": "EU27",
    "notes": "All 27 member states added together. Trade between members cancels out, so "
    "self-sufficiency is valid; import dependency needs partner-level trade data (phase 2).",
}


def _trend_series(trends: pd.DataFrame, years: list[int]) -> dict:
    """{iso3: {group: [ssr per year, aligned to `years`]}}."""
    out: dict = {}
    for (iso3, group), sub in trends.groupby(["iso3", "group"]):
        by_year = dict(zip(sub["year"], sub["ssr"], strict=False))
        out.setdefault(iso3, {})[group] = [_round(by_year.get(y)) for y in years]
    return out


def _europe_averages(groups: pd.DataFrame, overall: pd.DataFrame, national: list[str]) -> dict:
    """Population-weighted averages across the in-scope countries (EU27 bloc excluded)."""
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


def export_ssr() -> None:
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
            "sources": sources(),
            "view": "national",
            "eu_members": sorted(config.EU27),
            "europe_avg": _europe_averages(groups, overall, list(countries.index)),
            "formulas": {
                "ssr": "production / domestic supply * 100",
                "idr": "imports / domestic supply * 100",
                "protein_share": "sum(protein_i * min(ssr_i, 100)) / sum(protein_i), FBS leaf items",
            },
        },
        "groups": [ALL_FOOD] + [
            {"key": k, "label": g["label"], "notes": " ".join(g.get("notes", "").split()) or None}
            for k, g in products.items()
        ],
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

    for iso3, entry in entries:
        entry.update({"view": "eu_bloc" if iso3 == EU_BLOC else "national",
                      "indicators": {}, "items": {}, "trend": series.get(iso3, {})})
        o = overall[overall["iso3"] == iso3]
        if len(o):
            r = o.iloc[0]
            entry["indicators"]["all"] = {
                "protein": {"share": _round(r["protein_share"]), "ssr": _round(r["protein_ssr"]),
                            "g_per_day": _round(r["protein"])},
                "kcal": {"share": _round(r["kcal_share"]), "ssr": _round(r["kcal_ssr"]),
                         "per_day": _round(r["kcal"], 0)},
            }
            entry["population_k"] = _round(r["population"], 0)
        for _, r in groups[groups["iso3"] == iso3].iterrows():
            ind = entry["indicators"].setdefault(r["group"], {})
            ind[r["basis"]] = {
                "ssr": _round(r["ssr"]),
                "idr": _round(r["idr"]),
                "flag": r.get("flag") or None,
            }
            if r["basis"] == "tonnes":
                ind["components_kt"] = {k: _round(r[k], 0) for k in PER_CAPITA_KEYS}
                ind["per_capita_kg"] = {k: _round(r[f"{k}_kg_pc"]) for k in PER_CAPITA_KEYS}
        isub = items[(items["iso3"] == iso3) & items["group"].notna()]
        for _, r in isub.iterrows():
            entry["items"].setdefault(r["group"], []).append(
                {
                    "item": r["item"],
                    "ssr": _round(r["ssr"]),
                    "idr": _round(r["idr"]),
                    "supply_kt": _round(r["supply"], 0),
                    "production_kg_pc": _round(r["production_kg_pc"]),
                    "supply_kg_pc": _round(r["supply_kg_pc"]),
                    "flag": r.get("flag") or None,
                }
            )
        out["countries"][iso3] = entry

    dest = config.WEB_DATA / "ssr.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%d countries, %.0f KB)", dest, len(out["countries"]),
             dest.stat().st_size / 1024)


def export_countries_geojson() -> None:
    src = (
        config.RAW
        / "gisco"
        / f"CNTR_RG_{config.GISCO_NUTS_SCALE}_{config.GISCO_COUNTRIES_YEAR}_4326.geojson"
    )
    if not src.exists():
        log.warning("no GISCO countries file at %s; run `atlas download --source boundaries`", src)
        return
    scope = load_countries().set_index("iso3")["name"].to_dict()
    gj = json.loads(src.read_text(encoding="utf-8"))
    feats = []
    for f in gj["features"]:
        p = f.get("properties", {})
        iso3 = p.get("ISO3_CODE")
        if iso3 in scope:
            feats.append({"type": "Feature", "geometry": f["geometry"],
                          "properties": {"iso3": iso3, "name": scope[iso3]}})
    missing = sorted(set(scope) - {f["properties"]["iso3"] for f in feats})
    if missing:
        log.warning("no polygon for: %s", missing)
    dest = config.WEB_DATA / "countries.geojson"
    dest.write_text(
        json.dumps({"type": "FeatureCollection",
                    "attribution": "© EuroGeographics for the administrative boundaries",
                    "source": "gisco_countries",
                    "features": feats}, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info("wrote %s (%d features)", dest, len(feats))


def run() -> None:
    config.ensure_dirs()
    export_countries_geojson()
    export_ssr()
