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
    """FAOSTAT bulk ZIPs (Normalized layout). Default: fbs, production and trade_matrix (420 MB;
    the EU bloc and the trade views need it)."""
    keys = keys or ["fbs", "production", "trade_matrix"]
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
    # NUTS 2021 too: regional series keep 2021 codes where NUTS 2024 changed (pipeline/regions.py)
    nuts21 = fetch(config.GISCO_NUTS_GEOJSON.format(scale=config.GISCO_NUTS_SCALE, year=2021),
                   config.RAW / "gisco" / f"NUTS_RG_{config.GISCO_NUTS_SCALE}_2021_4326.geojson", force=force)
    return [nuts, nuts21, cntr, ne]


def baci(*, force: bool = False) -> list[Path]:
    """CEPII BACI, HS 2017 edition (795 MB, kept zipped; pipeline/baci.py). Etalab 2.0; cite
    Gaulier & Zignago (2010), CEPII Working Paper 2010-23. A new release changes the file name:
    update SOURCES["cepii_baci"] and baci.RELEASE together."""
    url = config.SOURCES["cepii_baci"]["file_url"]
    return [fetch(url, config.RAW / "baci" / url.rsplit("/", 1)[1], force=force, timeout=600)]


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


def usda(*, force: bool = False) -> list[Path]:
    """USDA PSD, all commodities (~10 MB): a second source to compare FAO with (pipeline/usda.py)."""
    url = config.SOURCES["usda_psd"]["file_url"]
    return [fetch(url, config.RAW / "usda" / url.rsplit("/", 1)[1], force=force)]


def unsd(*, force: bool = False) -> list[Path]:
    """UN Statistics Division: CPC 2.1 <-> HS 2017 correspondence and the HS 2022 -> HS 2017
    conversion, the base of mappings/hs_items.csv (`atlas crosswalk`)."""
    src = config.SOURCES["unsd_cpc_hs"]
    d = config.RAW / "unsd"
    return [fetch(u, d / u.rsplit("/", 1)[1], force=force)
            for u in (src["file_url"], src["file_url_hs2022"])]


def eumofa(*, force: bool = False) -> list[Path]:
    """EUMOFA live-weight conversion factors per CN8 code and year (fish, pipeline/comext.py)."""
    url = config.SOURCES["eumofa_cf"]["file_url"]
    return [fetch(url, config.RAW / "eumofa" / "conversion_factors_cn8.xlsx", force=force)]


COMEXT_FILE = "DS-045409_food.csv.gz"
COMEXT_QUERY = "query.json"
COMEXT_CHUNK = 150  # product codes per request: keeps the URL short and each extraction small


def comext_codes() -> tuple[list[str], list[str]]:
    """Product codes to request: HS6 codes in a group (both HS versions), except fish, which is
    requested as EUMOFA's CN8 codes (every year EUMOFA lists) so its factor per code applies."""
    from . import comext, crosswalk

    hs = crosswalk.load()
    hs6 = sorted(set(hs.loc[(hs["group"] != "fish") & (hs["to_primary"] != "cn8"), "hs"]))
    return hs6 + sorted(comext.load_cn8_items()), comext.fish_cn8_codes()


def _comext_get(url: str, timeout: int = 600) -> bytes:
    """One extraction: answered at once (gzip CSV) or queued (XML with an id to poll)."""
    import gzip
    import re
    import time

    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    body = r.content
    if body[:2] == b"\x1f\x8b":
        return gzip.decompress(body)
    m = re.search(rb"<(?:\w+:)?id>([0-9a-f-]{36})<", body)
    if not m:
        raise RuntimeError(f"Comext: unexpected answer {body[:300]!r}")
    key = m.group(1).decode()
    for _ in range(360):  # up to an hour
        st = requests.get(config.COMEXT_ASYNC + f"status/{key}", timeout=60).content
        if b"AVAILABLE" in st:
            data = requests.get(config.COMEXT_ASYNC + f"data/{key}", timeout=timeout).content
            return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        if b"EXPIRED" in st or b"FAILED" in st or b"<faultcode>" in st:
            raise RuntimeError(f"Comext extraction {key}: {st[:300]!r}")
        time.sleep(10)
    raise TimeoutError(f"Comext extraction {key} not ready after an hour")


def comext(*, force: bool = False) -> list[Path]:
    """Eurostat Comext DS-045409: every EU member's food trade with every partner, yearly from
    COMEXT_FIRST_YEAR, quantity (100 kg) and value (EUR), imports (flow 1) and exports (2). HS6 for
    food in the groups, CN8 for fish. Merged into one gzip CSV; query.json records what was asked
    (about 300 requests, a few minutes)."""
    import gzip
    import json
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime

    out = unsd(force=force) + eumofa(force=force)
    dest = config.RAW / "comext" / COMEXT_FILE
    if dest.exists() and not force:
        log.info("exists, skipping: %s", dest.name)
        return out + [dest]
    hs6, cn8 = comext_codes()
    reporters = sorted(comext_reporters())
    jobs = [(rep, codes[i:i + COMEXT_CHUNK], first) for rep in reporters
            for codes, first in ((hs6, config.COMEXT_FIRST_YEAR), (cn8, config.COMEXT_FISH_FIRST_YEAR))
            for i in range(0, len(codes), COMEXT_CHUNK)]

    def one(job):
        rep, codes, first = job
        url = (config.COMEXT_DATA + f"A.{rep}..{'+'.join(codes)}.1+2.QUANTITY_IN_100KG+VALUE_IN_EUROS"
               f"?startPeriod={first}&format=SDMX-CSV&compressed=true")
        return _comext_get(url).decode("utf-8").splitlines()

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    header, n = None, 0
    with gzip.open(tmp, "wt", encoding="utf-8") as f, ThreadPoolExecutor(4) as pool:
        for lines in tqdm(pool.map(one, jobs), total=len(jobs), desc="comext", leave=False):
            if not lines:
                continue
            if header is None:
                header = lines[0]
                f.write(header + "\n")
            elif lines[0] != header:
                raise RuntimeError(f"Comext: header changed: {lines[0]}")
            f.write("\n".join(lines[1:]) + ("\n" if len(lines) > 1 else ""))
            n += len(lines) - 1
    tmp.replace(dest)
    (dest.parent / COMEXT_QUERY).write_text(json.dumps({
        "dataset": "DS-045409", "fetched": datetime.now(UTC).isoformat(timespec="seconds"),
        "first_year": config.COMEXT_FIRST_YEAR, "fish_first_year": config.COMEXT_FISH_FIRST_YEAR,
        "reporters": reporters,
        "hs6": hs6, "cn8": cn8, "rows": n}, indent=1) + "\n", encoding="utf-8")
    log.info("downloaded %s (%d rows, %d requests)", dest, n, len(jobs))
    return out + [dest]


def comext_reporters() -> set[str]:
    """Comext reporter codes of the EU members (Greece is GR there, EL elsewhere at Eurostat)."""
    from .harmonise import load_countries

    c = load_countries()
    codes = set(c.loc[c["iso3"].isin(config.EU27), "eurostat"])
    return {"GR" if c == "EL" else c for c in codes}


def seasons(*, force: bool = False) -> list[Path]:
    """Crop calendars (GGCMI Phase 3, 32 small files), the winter/spring wheat areas, ISIMIP3a
    15-crop land use (379 MB) and country masks: pipeline/seasons.py. All CC BY 4.0."""
    from . import seasons as s

    src = config.SOURCES
    out = []
    for crop in s.CROPS:
        for ws in s.WS:
            name = s.CALENDAR.format(crop=crop, ws=ws)
            out.append(fetch(src["ggcmi_calendar"]["file_url"].format(name=name), s.GGCMI / name, force=force))
    out.append(fetch(src["ggcmi_wheat_areas"]["file_url"], s.WHEAT_AREAS, force=force))
    out.append(fetch(src["isimip_countrymasks"]["file_url"], s.MASKS, force=force))
    out.append(fetch(src["isimip_landuse"]["file_url"], s.LANDUSE, force=force, timeout=600))
    return out


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
    "usda": usda,
    "unsd": unsd,
    "eumofa": eumofa,
    "comext": comext,
    "seasons": seasons,
    "crop_calendar": crop_calendar,
}


def run(sources: list[str] | None = None, *, force: bool = False) -> None:
    config.ensure_dirs()
    sources = sources or ["faostat", "eurostat", "boundaries", "usda", "comext", "baci", "seasons"]
    for name in sources:
        fn = ALL[name]
        log.info("== %s", name)
        if name in ("jrc", "crop_calendar"):
            fn()
        else:
            fn(force=force)
