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
  Phase 1 ships tonnes and kcal (both from FBS). Value basis comes later from trade data.
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

1. **Phase 1 (current):** world choropleth of FBS-based SSR and IDR for ~14 product groups plus
   "all food" protein coverage, tonnes/kcal basis, EU bloc when zoomed out, 3-year average, trends.
2. **Phase 2:** partner-flow arcs from Eurostat Comext (intra + extra EU, CN8) and CEPII BACI
   (non-EU reporters), with import-concentration (HHI) and share-from-RU/UA indicators.
3. **Phase 3:** seasons (FAO Crop Calendar API, USDA IPAD, GGCMI) as a 12-month strip per
   country × crop; NUTS2 production from Eurostat `apro_cpshr` and JRC EUCROPMAP rasters as a
   "what is grown where" layer.
4. **Phase 4:** feed-adjusted SSR for livestock products (imported soy meal), calorie-weighted
   composite index, scenario toggles ("lose Ukraine/Russia supply").

## Data sources (phase 1 + 2)

| Need | Source | Access | Notes |
|---|---|---|---|
| Supply/utilisation, SSR/IDR | FAOSTAT FBS (2010–) | `https://bulks-faostat.fao.org/production/FoodBalanceSheets_E_All_Data_(Normalized).zip` | CC BY 4.0. Elements: Production, Import quantity, Export quantity, Domestic supply quantity, Stock Variation, Feed, Food supply (kcal/capita/day) |
| Production | FAOSTAT QCL | `.../Production_Crops_Livestock_E_All_Data_(Normalized).zip` | national, 1961– |
| Bilateral trade (FAO items) | FAOSTAT Detailed Trade Matrix | `.../Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip` | CC BY 4.0. 420 MB zip, 8.5 GB CSV: stream it, never unzip. Trade items (CPC), not FBS items: `mappings/trade_items.csv` maps them to groups. No fish |
| Bilateral trade (CN8, intra-EU) | Eurostat Comext | `https://ec.europa.eu/eurostat/api/comext/dissemination/` | EU reporters only |
| Bilateral trade (HS6, reconciled) | CEPII BACI | manual download from CEPII page | Etalab 2.0; ~2-year lag |
| EU balances (dairy, tomatoes, olive oil, wine) | DG AGRI–JRC "EU estimated agricultural balance sheets" | browser download only (`atlas download --source jrc` prints steps) → `data/raw/jrc/` | EC reuse notice (attribution). Intra-EU trade counted once, processed goods converted back; replaces FAO for EU dairy, tomatoes, olive oil, wine (`pipeline/jrc.py`, comparison in methodology) |
| Second opinion on FBS (cereals, oilseeds, oils, sugar, meat, butter, coffee) | USDA FAS PSD | `https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip` (`atlas download --source usda`) | US government work, public domain. EU only as a bloc. Compared, never substituted: `pipeline/usda.py`; large gaps shown next to FAO's figure |
| Regional crop production | Eurostat `apro_cpshr` | SDMX TSV: `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/apro_cpshr?format=TSV&compressed=true` | NUTS2, 2000–2024 |
| Trade → primary equivalent | FAO *Technical Conversion Factors for Agricultural Commodities* (TCF) | `https://www.fao.org/fileadmin/templates/ess/documents/methodology/tcf.pdf` | FAO publication (cite FAO). Extraction rates, medians across countries, become `to_primary` in `mappings/trade_items.csv` (roots, tomato products, coffee, cocoa); dairy uses the JRC's milk-equivalent factors |
| Seasons | FAO Crop Calendar API | `https://api-cropcalendar.apps.fao.org/` | inspect its OpenAPI docs before coding |
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
