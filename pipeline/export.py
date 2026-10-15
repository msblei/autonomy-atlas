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


def export_ssr() -> None:
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    items = pd.read_parquet(config.PROCESSED / "ssr_items.parquet")
    countries = load_countries().set_index("iso3")
    products = load_products()["groups"]

    years = sorted(groups["years"].unique())
    out: dict = {
        "meta": {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "years": years[-1] if years else None,
            "source": "fao_fbs",
            "sources": sources(),
            "view": "national",
            "formulas": {
                "ssr": "production / domestic supply * 100",
                "idr": "imports / domestic supply * 100",
            },
        },
        "groups": [
            {"key": k, "label": g["label"], "notes": " ".join(g.get("notes", "").split()) or None}
            for k, g in products.items()
        ],
        "countries": {},
    }

    for iso3, c in countries.iterrows():
        entry = {
            "name": c["name"],
            "region": c["group"],
            "notes": c.get("notes") if isinstance(c.get("notes"), str) else None,
            "indicators": {},
            "items": {},
        }
        sub = groups[groups["iso3"] == iso3]
        for _, r in sub.iterrows():
            ind = entry["indicators"].setdefault(r["group"], {})
            ind[r["basis"]] = {
                "ssr": _round(r["ssr"]),
                "idr": _round(r["idr"]),
                "flag": r.get("flag") or None,
            }
            if r["basis"] == "tonnes":
                ind["components_kt"] = {
                    k: _round(r[k], 0)
                    for k in ("production", "imports", "exports", "supply", "food", "feed")
                }
                ind["per_capita_kg"] = {
                    k: _round(r[f"{k}_kg_pc"])
                    for k in ("production", "imports", "exports", "supply", "food", "feed")
                }
                entry["population_k"] = _round(r["population"], 0)
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
    log.info("wrote %s (%d countries)", dest, len(out["countries"]))


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
