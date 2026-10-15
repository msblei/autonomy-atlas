"""Paths, source URLs and defaults. Everything configurable lives here or in mappings/*.yaml."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
WEB_DATA = ROOT / "web" / "public" / "data"
MAPPINGS = Path(__file__).resolve().parent / "mappings"

# --- FAOSTAT -------------------------------------------------------------------------------------
# Bulk ZIPs. Verify filenames against https://bulks-faostat.fao.org/production/datasets_E.xml
# before relying on them; FAO renames files occasionally.
FAOSTAT_BULK_BASE = "https://bulks-faostat.fao.org/production/"
FAOSTAT_FILES: dict[str, str] = {
    "fbs": "FoodBalanceSheets_E_All_Data_(Normalized).zip",
    "production": "Production_Crops_Livestock_E_All_Data_(Normalized).zip",
    "trade_matrix": "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip",
}

# FBS element names used by compute.py (exact strings as they appear in the Normalized CSV).
FBS_ELEMENTS: dict[str, str] = {
    "production": "Production",
    "imports": "Import quantity",
    "exports": "Export quantity",
    "supply": "Domestic supply quantity",
    "stock_variation": "Stock Variation",
    "feed": "Feed",
    "food": "Food",
    "kcal": "Food supply (kcal/capita/day)",
}

# --- Eurostat ------------------------------------------------------------------------------------
# SDMX 2.1 TSV bulk endpoint; free, no key. Returns gzip when compressed=true.
EUROSTAT_SDMX_TSV = (
    "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/{code}"
    "?format=TSV&compressed=true"
)
EUROSTAT_DATASETS: dict[str, str] = {
    "crops_national": "apro_cpsh1",  # crop production in EU standard humidity, national
    "crops_regional": "apro_cpshr",  # same, NUTS2
    "meat": "apro_mt_pann",  # slaughtering in slaughterhouses, annual
    "milk": "apro_mk_pobta",  # milk collection and dairy products
}
# Comext (international trade in goods, CN8): phase 2.
COMEXT_API = "https://ec.europa.eu/eurostat/api/comext/dissemination/"

# --- Trade (phase 2) -----------------------------------------------------------------------------
# BACI has no stable download URL; fetch manually from the CEPII page and drop the CSVs in
# data/raw/baci/. Licence: Etalab 2.0, cite CEPII.
BACI_PAGE = "https://www.cepii.fr/DATA_DOWNLOAD/baci/doc/baci_webpage.html"

# --- Seasons (phase 3) ---------------------------------------------------------------------------
FAO_CROP_CALENDAR_API = "https://api-cropcalendar.apps.fao.org/"

# --- Boundaries ----------------------------------------------------------------------------------
# GISCO NUTS: non-commercial only, credit "© EuroGeographics for the administrative boundaries".
GISCO_NUTS_GEOJSON = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_{scale}_{year}_4326.geojson"
)
GISCO_NUTS_YEAR = 2024
GISCO_NUTS_SCALE = "20M"  # 1:20M is plenty for a continent-wide web map
# GISCO country polygons (same licence). Properties include ISO3_CODE, so no geopandas needed.
GISCO_COUNTRIES_GEOJSON = (
    "https://gisco-services.ec.europa.eu/distribution/v2/countries/geojson/"
    "CNTR_RG_{scale}_{year}_4326.geojson"
)
GISCO_COUNTRIES_YEAR = 2024

# Natural Earth: public domain. 50m admin-0 countries covers non-EU Europe (UA, RU, TR, ...).
NATURAL_EARTH_COUNTRIES = (
    "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"
)

# --- Defaults ------------------------------------------------------------------------------------
WINDOW_YEARS = 3  # 3-year average by default; see docs/methodology.md
EU27 = {
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN",
    "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP",
    "SWE",
}


def ensure_dirs() -> None:
    for d in (RAW, INTERIM, PROCESSED, WEB_DATA):
        d.mkdir(parents=True, exist_ok=True)
