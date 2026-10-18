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
    # Supply Utilization Accounts (SCL): every commodity incl. oilseed cakes, for pipeline/feed.py
    "sua": "SUA_Crops_Livestock_E_All_Data_(Normalized).zip",
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
    "seed": "Seed",
    "losses": "Losses",
    "processing": "Processing",  # turned into another FBS item (barley -> beer, seeds -> oil)
    "other_uses": "Other uses (non-food)",  # biofuel, industrial
    "tourist": "Tourist consumption",
    "residuals": "Residuals",  # statistical balancing term, can be negative
    "kcal": "Food supply (kcal/capita/day)",
    "protein": "Protein supply quantity (g/capita/day)",
    # Item "Population" (2501) carries this element, unit 1000 No. Used for per-person figures.
    "population": "Total Population - Both sexes",
}

# FAO's bulk catalogue: release date (DateUpdate) per file. Saved next to the raw ZIPs so export
# can cite the exact release without going back to the network.
FAOSTAT_CATALOGUE = "datasets_E.xml"

# Citable sources, keyed by the id that export.py attaches to every number.
SOURCES: dict[str, dict[str, str]] = {
    "fao_fbs": {
        "title": "Food Balances (2010-)",
        "publisher": "Food and Agriculture Organization of the United Nations (FAO), FAOSTAT",
        "url": "https://www.fao.org/faostat/en/#data/FBS",
        "file_url": FAOSTAT_BULK_BASE + "FoodBalanceSheets_E_All_Data_(Normalized).zip",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "catalogue_file": "FoodBalanceSheets_E_All_Data_(Normalized).zip",
    },
    "fao_tm": {
        "title": "Detailed trade matrix",
        "publisher": "Food and Agriculture Organization of the United Nations (FAO), FAOSTAT",
        "url": "https://www.fao.org/faostat/en/#data/TM",
        "file_url": FAOSTAT_BULK_BASE + "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "catalogue_file": "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip",
    },
    "jrc_bal": {
        "title": "EU estimated agricultural balance sheets",
        "publisher": "European Commission, DG AGRI and Joint Research Centre (JRC)",
        "url": "https://data.jrc.ec.europa.eu/dataset/33243e5e-44a1-4b43-9444-31d64dc7921f",
        "file_url": "https://datam.jrc.ec.europa.eu/datam/perm/dataset/33243e5e-44a1-4b43-9444-31d64dc7921f/download/Dataset_DG_AGRI-JRC_-_Production__trade_and_apparent_use__EU-27_.zip",
        "licence": "European Commission reuse notice (free reuse with attribution)",
        "licence_url": "https://commission.europa.eu/legal-notice_en",
        "doi": "https://doi.org/10.2905/JRC.EBBTB0G",
    },
    "usda_psd": {
        "title": "Production, Supply and Distribution (PSD)",
        "publisher": "U.S. Department of Agriculture, Foreign Agricultural Service",
        "url": "https://apps.fas.usda.gov/psdonline/app/index.html",
        "file_url": "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip",
        "licence": "US government work, public domain",
        "licence_url": "https://www.usa.gov/government-copyright",
    },
    "eurostat_comext": {
        "title": "EU trade since 1988 by HS2-4-6 and CN8 (DS-045409)",
        "publisher": "Eurostat, Comext",
        "url": "https://ec.europa.eu/eurostat/comext/newxtweb/",
        "file_url": "https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/DS-045409",
        "licence": "CC BY 4.0 (Eurostat copyright notice)",
        "licence_url": "https://ec.europa.eu/eurostat/about-us/policies/copyright",
    },
    "eumofa_cf": {
        "title": "Conversion factors by CN-8 code (Metadata 2, Annex 7)",
        "publisher": "European Commission, EUMOFA (European Market Observatory for Fisheries and "
                     "Aquaculture Products)",
        "url": "https://fishery-aquaculture-market-observatory.ec.europa.eu/en/data/metadata",
        "file_url": "https://fishery-aquaculture-market-observatory.ec.europa.eu/system/files/2026-05/"
                    "DM_Annex%207%20-%20CF%20by%20CN-8%20from%202011%20to%202026.xlsx",
        "licence": "European Commission reuse notice (free reuse with attribution)",
        "licence_url": "https://commission.europa.eu/legal-notice_en",
    },
    "unsd_cpc_hs": {
        "title": "CPC Ver. 2.1 to HS 2017 correspondence; HS 2022 to HS 2017 conversion",
        "publisher": "United Nations Statistics Division",
        "url": "https://unstats.un.org/unsd/classifications/Econ",
        "file_url": "https://unstats.un.org/unsd/classifications/Econ/tables/CPC/CPCv21_HS2017/CPC21-HS2017.csv",
        "file_url_hs2022": "https://unstats.un.org/unsd/classifications/Econ/tables/"
                           "HS2022toHS2017ConversionAndCorrelationTables.xlsx",
        "licence": "United Nations terms of use (free reuse with attribution)",
        "licence_url": "https://www.un.org/en/about-us/terms-of-use",
    },
    "ggcmi_calendar": {
        "title": "GGCMI Phase 3 crop calendar, v1.01",
        "publisher": "Jägermeyr et al. (2021), Nature Food 2: 873-885; AgMIP GGCMI",
        "url": "https://zenodo.org/records/5062513",
        "file_url": "https://zenodo.org/api/records/5062513/files/{name}/content",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "ggcmi_wheat_areas": {
        "title": "GGCMI Phase 2 winter and spring wheat areas (MIRCA2000-based)",
        "publisher": "AgMIP GGCMI (Franke et al. 2020)",
        "url": "https://zenodo.org/records/3773827",
        "file_url": "https://zenodo.org/api/records/3773827/files/winter_and_spring_wheat_areas_v1_180627.nc4/content",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "isimip_landuse": {
        "title": "ISIMIP3a land use, 15 crops, histsoc 1901-2021",
        "publisher": "Inter-Sectoral Impact Model Intercomparison Project (ISIMIP)",
        "url": "https://data.isimip.org/",
        "file_url": "https://files.isimip.org/ISIMIP3a/InputData/socioeconomic/landuse/histsoc/landuse-15crops_histsoc_annual_1901_2021.nc",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "isimip_countrymasks": {
        "title": "ISIMIP3a fractional country masks, 30 arcmin",
        "publisher": "Inter-Sectoral Impact Model Intercomparison Project (ISIMIP)",
        "url": "https://data.isimip.org/",
        "file_url": "https://files.isimip.org/ISIMIP3a/InputData/geo_conditions/countrymasks/countrymasks-fractional_30arcmin.nc",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "jrc_eucropmap": {
        "title": "Crop proportions on land at 2 km, from EUCROPMAP 2018 (EU crop type map, 10 m)",
        "publisher": "European Commission, Joint Research Centre (d'Andrimont et al. 2021)",
        "url": "https://data.jrc.ec.europa.eu/dataset/15f86c84-eae1-4723-8e00-c1b35c8f56b9",
        "file_url": "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/DRLL/CropDiversity/CropProportionLand/",
        "licence": "CC BY 4.0 (© European Union)",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    },
    "cepii_baci": {
        "title": "BACI, international trade database at the product level (HS 2017, release 202601)",
        "publisher": "CEPII; Gaulier and Zignago (2010), CEPII Working Paper 2010-23",
        "url": "https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37",
        "file_url": "https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS17_V202601.zip",
        "licence": "Etalab Open Licence 2.0",
        "licence_url": "https://www.etalab.gouv.fr/wp-content/uploads/2018/11/open-licence.pdf",
    },
    "gisco_countries": {
        "title": "Countries 2024, 1:20 million",
        "publisher": "Eurostat GISCO",
        "url": "https://ec.europa.eu/eurostat/web/gisco/geodata/administrative-units/countries",
        "licence": "© EuroGeographics for the administrative boundaries (non-commercial use)",
        "licence_url": "https://ec.europa.eu/eurostat/web/gisco/geodata/administrative-units/countries",
    },
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
# Comext (international trade in goods, HS6/CN8): EU members' own trade (pipeline/comext.py).
COMEXT_API = "https://ec.europa.eu/eurostat/api/comext/dissemination/"
COMEXT_DATA = COMEXT_API + "sdmx/2.1/data/DS-045409/"
# Larger extractions are queued: poll status, then fetch the data (both by the returned id).
COMEXT_ASYNC = COMEXT_API + "1.0/async/"
# Greece is GR in Comext (not Eurostat's usual EL).
COMEXT_FIRST_YEAR = 2021  # food other than fish: the FBS window and later (a comparison only)
COMEXT_FISH_FIRST_YEAR = 2010  # fish: every trend year, for the EU bloc's fish balance

# --- Trade (phase 2) -----------------------------------------------------------------------------
# BACI: SOURCES["cepii_baci"] (a direct zip per release; pipeline/baci.py names the release).
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


class StaleError(RuntimeError):
    """A derived file is older than an input it was built from."""


def require_fresh(output: Path, inputs: list[Path]) -> None:
    """Raise StaleError if `output` is older than any existing input. Stops a step from quietly
    reusing a file built from an older mapping or download (e.g. trade shares computed before a
    trade_items.csv fix)."""
    if not output.exists():
        return
    newer = [p for p in inputs if p.exists() and p.stat().st_mtime > output.stat().st_mtime]
    if newer:
        raise StaleError(f"{output.name} is older than {', '.join(p.name for p in newer)}; "
                         "rebuild it (`atlas build`)")
