"""Fetch raw source files into data/raw/<source>/.

Raw files are never modified. Re-running skips files that already exist unless force=True.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from tqdm import tqdm

from . import config

log = logging.getLogger(__name__)

CHUNK = 1 << 20  # 1 MiB


def fetch(url: str, dest: Path, *, force: bool = False, timeout: int = 60) -> Path:
    """Stream `url` to `dest` with a progress bar. Returns dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        log.info("exists, skipping: %s", dest.name)
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or None
        with tmp.open("wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=dest.name, leave=False
        ) as bar:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
                bar.update(len(chunk))
    tmp.replace(dest)
    log.info("downloaded %s", dest)
    return dest


# --- sources -------------------------------------------------------------------------------------


def faostat(keys: list[str] | None = None, *, force: bool = False) -> list[Path]:
    """FAOSTAT bulk ZIPs (Normalized layout). Default: fbs + production (trade_matrix is ~2 GB)."""
    keys = keys or ["fbs", "production"]
    # Always refresh the catalogue: it is small and records which release we downloaded.
    out = [fetch(config.FAOSTAT_BULK_BASE + config.FAOSTAT_CATALOGUE,
                 config.RAW / "faostat" / config.FAOSTAT_CATALOGUE, force=True)]
    for key in keys:
        fname = config.FAOSTAT_FILES[key]
        out.append(fetch(config.FAOSTAT_BULK_BASE + fname, config.RAW / "faostat" / fname, force=force))
    return out


def eurostat(keys: list[str] | None = None, *, force: bool = False) -> list[Path]:
    """Eurostat datasets as gzipped TSV via the SDMX 2.1 dissemination API."""
    keys = keys or ["crops_regional"]
    out = []
    for key in keys:
        code = config.EUROSTAT_DATASETS[key]
        url = config.EUROSTAT_SDMX_TSV.format(code=code)
        out.append(fetch(url, config.RAW / "eurostat" / f"{code}.tsv.gz", force=force))
    return out


def boundaries(*, force: bool = False) -> list[Path]:
    """GISCO NUTS (non-commercial) + Natural Earth countries (public domain)."""
    nuts_url = config.GISCO_NUTS_GEOJSON.format(
        scale=config.GISCO_NUTS_SCALE, year=config.GISCO_NUTS_YEAR
    )
    nuts = fetch(
        nuts_url,
        config.RAW / "gisco" / f"NUTS_RG_{config.GISCO_NUTS_SCALE}_{config.GISCO_NUTS_YEAR}_4326.geojson",
        force=force,
    )
    cntr_url = config.GISCO_COUNTRIES_GEOJSON.format(
        scale=config.GISCO_NUTS_SCALE, year=config.GISCO_COUNTRIES_YEAR
    )
    cntr = fetch(
        cntr_url,
        config.RAW / "gisco" / f"CNTR_RG_{config.GISCO_NUTS_SCALE}_{config.GISCO_COUNTRIES_YEAR}_4326.geojson",
        force=force,
    )
    # Natural Earth is the public-domain fallback if the project ever needs a commercial licence.
    # It is a shapefile ZIP; converting it needs the optional `geo` extra (geopandas).
    ne = fetch(
        config.NATURAL_EARTH_COUNTRIES,
        config.RAW / "natural_earth" / "ne_50m_admin_0_countries.zip",
        force=force,
    )
    return [nuts, cntr, ne]


def baci() -> None:
    """BACI has no stable direct URL. Print instructions instead of guessing."""
    target = config.RAW / "baci"
    target.mkdir(parents=True, exist_ok=True)
    print(
        "BACI must be downloaded manually (free, Etalab 2.0 licence):\n"
        f"  1. Open {config.BACI_PAGE}\n"
        "  2. Download the latest HS22 (or HS17) release ZIP.\n"
        f"  3. Extract the BACI_HSxx_Yyyyy_Vyyyymm.csv files into {target}\n"
        "Cite: Gaulier & Zignago (2010), BACI, CEPII Working Paper 2010-23."
    )


def jrc() -> None:
    """The DG AGRI-JRC balance sheets server rejects scripted downloads. Print instructions."""
    target = config.RAW / "jrc"
    target.mkdir(parents=True, exist_ok=True)
    src = config.SOURCES["jrc_bal"]
    print(
        "DG AGRI-JRC EU estimated agricultural balance sheets must be downloaded in a browser\n"
        "(free reuse with attribution, European Commission reuse notice):\n"
        f"  1. Open {src['url']}\n"
        "  2. Under 'Data access', download the ZIP 'EU estimated agricultural balance sheets (EU-27)'.\n"
        f"  3. Save it as {target / 'Dataset_EU_estimated_agricultural_balance_sheets.zip'} and unzip\n"
        f"     it into {target / 'bal'}\n"
        "Without it, dairy for EU countries uses FAO's figures (see pipeline/jrc.py)."
    )


def crop_calendar() -> None:
    """FAO Crop Calendar API (phase 3). Endpoints are not documented here on purpose —
    inspect the API's OpenAPI/Swagger page first, then implement."""
    print(
        f"FAO Crop Calendar API: {config.FAO_CROP_CALENDAR_API}\n"
        "Open it in a browser, find the OpenAPI spec, then implement the fetch here.\n"
        "Alternative static source: GGCMI phase 3 crop calendar, https://zenodo.org/records/5062513"
    )


ALL = {
    "faostat": faostat,
    "eurostat": eurostat,
    "boundaries": boundaries,
    "baci": baci,
    "jrc": jrc,
    "crop_calendar": crop_calendar,
}


def run(sources: list[str] | None = None, *, force: bool = False) -> None:
    config.ensure_dirs()
    sources = sources or ["faostat", "eurostat", "boundaries"]
    for name in sources:
        fn = ALL[name]
        log.info("== %s", name)
        if name in ("baci", "jrc", "crop_calendar"):
            fn()
        else:
            fn(force=force)
