# Autonomy Atlas — project brief for Claude Code

Interactive map of European agriculture: what is grown where and when, who imports and exports
what, and how self-sufficient each country really is. The goal is a pan-European, product-by-product
"autonomy atlas" that no existing tool provides (the official EU Food Supply dashboard is EU-only,
chart-based and has no API; global tools lack European depth and seasonality).

Full background: `docs/research-report.md` (existing tools, data inventory, pitfalls).
Formulas and methodological rules: `docs/methodology.md`.

## Decisions already made (don't relitigate without asking)

- **Scope:** global for everything FBS-based (~178 countries, `pipeline/mappings/world.csv`,
  M49 → ISO3). The European core — EU27 + UK + EFTA (NO, CH, IS) + Western Balkans (AL, BA, ME,
  MK, RS) + UA, MD + BY, RU, TR, ~41 countries in `pipeline/mappings/countries.yaml` (groups,
  Eurostat codes, notes) — stays the focus for the Europe-only phases (Comext, NUTS, seasons).
  Map: zoomed out, the EU27 is drawn as one country (bloc figures); zoomed in, its members.
  (Changed from Europe-only on 2026-10-15 at the user's request.)
- **Backbone dataset:** FAO Food Balance Sheets (FBS, 2010–) for self-sufficiency and import
  dependency. It is the only source that covers every country above with one methodology and already
  converts processed goods to primary equivalents.
- **Product key:** FAO FBS item names/codes are the master key. Everything else (HS6/CN8 trade,
  Eurostat crop codes) is crosswalked *to* FAO items. User-facing groups (~14) are defined in
  `pipeline/mappings/products.yaml`.
- **Country key:** ISO3. M49 → ISO3 for the world lives in `world.csv`; Europe-specific mappings
  (Eurostat geo codes, groups, notes) in `countries.yaml`.
- **Default time window:** 3-year average (latest three FBS years). Average the *components*
  (production, imports, exports, supply) over the window, then compute the ratio — never average
  ratios.
- **Two autonomy views, always both:** `national` (all imports count, including from other EU
  states) and `eu_bloc` (only extra-EU imports count, EU treated as one unit). They can tell
  opposite stories; the UI must let the user toggle.
- **Measurement basis is explicit:** every indicator is labelled `tonnes`, `kcal` or `value`.
  Phase 1 ships tonnes and kcal (both from FBS). Value (EUR) exists for trade only, EU members
  and the EU bloc, from Comext ("Money paid / earned" on the trade page; no value SSR: that
  would need production values).
- **Stack:** Python 3.11+ pipeline (pandas, pyarrow, DuckDB) producing Parquet in `data/processed/`
  and small JSON/GeoJSON for the web in `web/public/data/`. Frontend is Vite + vanilla JS +
  MapLibre GL JS. deck.gl ArcLayer for trade flows (phase 2). No framework until it earns its place.
- **Licensing:** default stack is open-licensed (FAOSTAT CC BY 4.0, Eurostat/Comext, BACI Etalab
  2.0, Natural Earth public domain; typeface Atkinson Hyperlegible Next, SIL OFL, self-hosted, map
  label glyphs in `web/public/fonts` built by `npm run glyphs`). GISCO NUTS boundaries are non-commercial only — fine for now,
  swap for Natural Earth / geoBoundaries if the project ever goes commercial. Never redistribute raw
  UN Comtrade extracts.

## Repository layout

```
CLAUDE.md               this file
README.md               public-facing overview
docs/                   research report, methodology
pipeline/               Python package
  config.py             paths, URLs, dataset codes, default years
  mappings/             countries.yaml (Europe), world.csv (M49 -> ISO3), products.yaml
  download.py           fetch raw files into data/raw/<source>/
  harmonise.py          raw -> tidy Parquet in data/interim/ (ISO3, FAO item, year, element, value)
  compute.py            SSR / IDR / concentration indices -> data/processed/
  export.py             processed -> web/public/data/*.json + countries.geojson
  cli.py                `atlas download|build|export|all`
tests/                  pytest; formula tests use tiny synthetic frames
web/                    Vite + MapLibre frontend
data/                   raw/ interim/ processed/ (all gitignored except .gitkeep)
```

## Commands

```
make setup       # python venv + pip install -e ".[dev]" + npm install in web/
make download    # atlas download (FAOSTAT bulk, Eurostat, boundaries)
make build       # atlas build   (harmonise + compute)
make export      # atlas export  (write web/public/data)
make test        # pytest
make verify      # every data check: tests, atlas validate, verify/recompute.py, browser tests, audit page
make release     # all + verify + gated web build (web/scripts/check-data.mjs)
make serve       # cd web && npm run dev
```

## Roadmap

1. **Phase 1 (done, 2026-10):** world choropleth of FBS-based SSR and IDR for ~14 product groups
   plus "all food" protein coverage, tonnes/kcal basis, EU bloc when zoomed out, 3-year average,
   trends; JRC balances for EU dairy/tomatoes/olive oil/wine; USDA second opinion; every published
   number verified (`make verify`, independent recompute), every audit warning resolved.
2. **Phase 2 (done, 2026-10):** partner flows and arcs come from the FAOSTAT Detailed Trade Matrix for
   now (partners' reports where a country under-reports; processed goods converted to the FBS
   basis; implausible flows withheld), with the share from Russia and Ukraine on the trade page
   and import/export concentration (HHI) on "All the numbers". Eurostat Comext adds EU members'
   fish partners and the EU bloc's fish balance, and a comparison with the FAO matrix on the audit
   page, and a value basis in euros for EU trade (what members pay and earn, per partner).
   CEPII BACI gives fish partners for every other country and a check of the FAO matrix for
   all countries (mirror-flow countries such as Russia marked) on the audit page. Phase 2 is
   done but for the arcs' deck.gl ArcLayer (MapLibre lines do the job so far).
3. **Phase 3 (in part):** seasons as a 12-month strip per country × crop: done for cereals,
   potatoes, sugar beet, pulses and oilseeds (GGCMI calendar weighted by ISIMIP crop areas, "When
   it is grown" on the food page). Fruit and vegetables: no open European harvest calendar exists
   (FAO's Crop Calendar API has 58 countries, none in Europe), so EU countries show when fresh
   produce comes from abroad instead: monthly Comext imports per fresh product with the leading
   supplier ("When it comes from abroad").
   "What is grown where": regional production from Eurostat `apro_cpshr` (NUTS2, Germany NUTS1)
   for cereals, potatoes, sugar beet, pulses and oilseeds, as a list and a map of t per km²
   ("Where in … do they grow?", `#ISO/group/where`, `pipeline/regions.py`). Still to do: JRC
   EUCROPMAP rasters (10 m crop types) for detail within regions.
4. **Phase 4:** feed-adjusted SSR for livestock products (imported soy meal), calorie-weighted
   composite index, scenario toggles ("lose Ukraine/Russia supply").

## Data sources (phase 1 + 2)

| Need | Source | Access | Notes |
|---|---|---|---|
| Supply/utilisation, SSR/IDR | FAOSTAT FBS (2010–) | `https://bulks-faostat.fao.org/production/FoodBalanceSheets_E_All_Data_(Normalized).zip` | CC BY 4.0. Elements: Production, Import quantity, Export quantity, Domestic supply quantity, Stock Variation, Feed, Food supply (kcal/capita/day) |
| Production | FAOSTAT QCL | `.../Production_Crops_Livestock_E_All_Data_(Normalized).zip` | national, 1961– |
| Bilateral trade (FAO items) | FAOSTAT Detailed Trade Matrix | `.../Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip` | CC BY 4.0. 420 MB zip, 8.5 GB CSV: stream it, never unzip. Trade items (CPC), not FBS items: `mappings/trade_items.csv` maps them to groups. No fish |
| Bilateral trade (HS6/CN8, EU members) | Eurostat Comext DS-045409 | SDMX API `https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1/data/DS-045409/` (`atlas download --source comext`, ~270 queued requests merged into one file) | CC BY 4.0 (Eurostat). EU reporters only. Fish partners and the EU bloc's fish shares (FAO has no fish trade); other foods only compared with the FAO matrix (`pipeline/comext.py`). HS6 → groups via `mappings/hs_items.csv` (`atlas crosswalk`) |
| HS ↔ CPC correspondence | UN Statistics Division: CPC 2.1–HS 2017 correspondence, HS 2022→2017 conversion | `https://unstats.un.org/unsd/classifications/Econ` | UN terms of use (attribution). Base of the HS6 crosswalk; hand decisions in `mappings/hs_overrides.csv` |
| Fish live-weight factors | EUMOFA, Metadata 2 Annex 7 "Conversion factors by CN-8 code" | `https://fishery-aquaculture-market-observatory.ec.europa.eu/en/data/metadata` | EC reuse notice (attribution). Per CN8 code and year, 2011– |
| Bilateral trade (HS6, reconciled) | CEPII BACI, HS 2017 edition, release 202601 | `https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS17_V202601.zip` (`atlas download --source baci`, 795 MB, kept zipped) | Etalab 2.0, cite Gaulier & Zignago (2010). ~1-year lag. Fish partners outside the EU (live weight with the EU's EUMOFA mix per HS6); other foods only compared with the FAO matrix (`pipeline/baci.py`). A new release renames the file: update `config.SOURCES` and `baci.RELEASE` |
| EU balances (dairy, tomatoes, olive oil, wine) | DG AGRI–JRC "EU estimated agricultural balance sheets" | browser download only (`atlas download --source jrc` prints steps) → `data/raw/jrc/` | EC reuse notice (attribution). Intra-EU trade counted once, processed goods converted back; replaces FAO for EU dairy, tomatoes, olive oil, wine (`pipeline/jrc.py`, comparison in methodology) |
| Second opinion on FBS (cereals, oilseeds, oils, sugar, meat, butter, coffee) | USDA FAS PSD | `https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip` (`atlas download --source usda`) | US government work, public domain. EU only as a bloc. Compared, never substituted: `pipeline/usda.py`; large gaps shown next to FAO's figure |
| Regional crop production | Eurostat `apro_cpshr` | SDMX TSV: `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/apro_cpshr?format=TSV&compressed=true` | CC BY 4.0. NUTS2 (Germany NUTS1), 2000–2024; codes from several NUTS versions: matched to GISCO NUTS 2024, else 2021 (both downloaded with `boundaries`) |
| Trade → primary equivalent | FAO *Technical Conversion Factors for Agricultural Commodities* (TCF) | `https://www.fao.org/fileadmin/templates/ess/documents/methodology/tcf.pdf` | FAO publication (cite FAO). Extraction rates, medians across countries, become `to_primary` in `mappings/trade_items.csv` (roots, tomato products, coffee, cocoa); dairy uses the JRC's milk-equivalent factors |
| Seasons (calendar) | GGCMI Phase 3 crop calendar v1.01 (Jägermeyr et al. 2021) | Zenodo record 5062513 (`atlas download --source seasons`) | CC BY 4.0. Planting/maturity day per 0.5° cell, crop, rainfed/irrigated; static. Used for cereals, potatoes, sugar beet, pulses, oilseeds (`pipeline/seasons.py`); cassava and sugar cane left out (no single season) |
| Seasons (where crops grow) | ISIMIP3a 15-crop land use (histsoc 1901–2021) and fractional country masks; GGCMI Phase 2 winter/spring wheat areas (Zenodo 3773827) | `files.isimip.org` (379 MB + 1 MB), Zenodo | CC BY 4.0. Weights for the calendar grid. MapSPAM 2020 would be finer but needs a guestbook form (name, e-mail) and IFPRI's terms: not scripted |
| Fruit and vegetables by month (EU) | Eurostat Comext DS-045409, monthly imports | as Comext; `DS-045409_monthly_imports.csv.gz` (54 requests, with `--source comext`) | CC BY 4.0. Imports, not harvests; per fresh product (HS heading) |
| Seasons of fruit and vegetables (checked, not used) | FAO Crop Calendar API | `https://api-cropcalendar.apps.fao.org/` (spec: `/swagger.json`) | 58 countries, none in Europe; advice per agro-ecological zone without area weights; no licence stated |
| Boundaries | Eurostat GISCO NUTS 2024; Natural Earth 50m countries | see `config.py` | GISCO non-commercial |

Verify every bulk filename against `https://bulks-faostat.fao.org/production/datasets_E.xml`
before assuming it — FAO renames files occasionally.

## Conventions

- Tidy long format in `data/interim/`: columns `iso3, item_code, item, element, year, unit, value, flag`.
- Keep raw downloads untouched; everything derived is reproducible from `make all`.
- Treat FAOSTAT "Area Code (M49)" values as strings; they sometimes carry a leading apostrophe
  (`'040`). Strip and zero-pad to 3 digits.
- FAOSTAT area names change ("Netherlands (Kingdom of the)" from the 2023 release). Join on M49
  codes, never on names.
- Guard every ratio against zero/negative domestic supply (net exporters of a product they don't
  consume can produce supply ≤ 0 in FBS). Return NaN and flag it.
- Any number shown in the UI must be traceable: carry `source`, `years` and `basis` columns through
  to the exported JSON.
- Nothing is published that `make verify` has not passed (docs/methodology.md, "Checks"). A figure
  whose FAO balance contradicts itself is withheld everywhere (`pipeline/checks.py`), never shown
  in one view and hidden in another. No factual number is typed into UI text; compute it in the
  pipeline (`meta.claims`). `verify/recompute.py` must stay independent: change it only from the
  methodology, never by reading `pipeline/`.
- When adding a new source, add it to the table above, to `docs/research-report.md` Part 2 if it is
  not already there, and note its licence.

## Known pitfalls (short list — full version in docs/methodology.md)

- Rotterdam/Antwerp re-export effect inflates NL/BE import dependence in raw trade data.
- Intra-EU vs extra-EU: France is below 100% in poultry since 2014, EU as a bloc is above 100%.
- Meat/dairy SSR > 100% can hide dependence on imported soy feed (EU soy SSR ≈ 15%).
- Tonnes vs kcal vs value give different rankings; never mix bases in one view.
- FBS methodology break at 2010/2014; Eurostat SAIO transition from reference year 2025;
  NUTS 2021 → 2024; HS 2017 → 2022.
- Ukraine 2022–2025 statistics were suspended and are being backfilled; exclude occupied
  territories; mark provisional. Russia/Belarus trade reporting is patchy since 2022 — use mirror
  flows (BACI, partner-reported Comext) and flag them.
