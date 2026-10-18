# Mapping Europe's Food Autonomy: Existing Tools, Data Inventory and Build Guide

*Research report compiled 15 October 2026 during project scoping. Prices, quotas, dataset versions
and URLs reflect pages accessed in 2026 and may change.*

No existing tool combines crop calendars, regional production, bilateral trade and self-sufficiency in one interactive map of Europe. The pieces all exist, most of the underlying data is free, and building it is feasible: a solo developer or small team could get a credible national-level MVP within weeks. The real gap is integrating and explaining these sources, not finding new data.

## TL;DR
- **No single tool does all of this.** The closest are the European Commission's DG AGRI "Food Supply" dashboard (self-sufficiency and import dependency for the EU and each Member State, but only as charts, EU-only, with no API), Our World in Data (a global choropleth of net food trade as a share of domestic supply), resourcetrade.earth and Trase (trade flows and sustainability, but no self-sufficiency or seasonality), and FAO/USDA crop calendars (seasons only). None of them puts all four layers on one pan-European map.
- **The data is available and mostly free.** Production comes from FAOSTAT and Eurostat (NUTS2 crop production for 2000–2024). Trade comes from Eurostat Comext (CN8, from 1988, free bulk/API), FAOSTAT's detailed trade matrix (1961–2024) and CEPII BACI (open licence). Self-sufficiency comes from FAO Food Balance Sheets (2010–2023). Seasons come from the FAO Crop Calendar API, USDA IPAD, JRC and GGCMI. Boundaries come from Eurostat GISCO. The main constraints are UN Comtrade's re-dissemination terms, GISCO's non-commercial clause, and Ukraine's 2022–2025 statistics gap, which is now being backfilled.
- **The opportunity is a "Europe-wide, product-by-product autonomy atlas".** Use FAO Food Balance Sheets as the backbone for comparable self-sufficiency ratios (SSR) across EU27, UK, EFTA, Western Balkans, Ukraine, Moldova, Turkey, Russia and Belarus. Layer Comext/BACI partner flows, Eurostat NUTS2 production and crop calendars on top. Be explicit about re-exports, feed use and the basis of measurement (calories, tonnes or value).

## Part 1 — Existing projects

### Key findings
The closest thing to this project is the **DG AGRI Food Supply dashboard**: https://agridata.ec.europa.eu/extensions/FoodSupply/FoodSupply.html. Its menu offers "Self-sufficiency rates", "Import dependency", "Shares of imports per origin" and "Diversification of supplies", each split into commodities, inputs and resources, plus a "Data Explorer – imports and CN codes". The Commission launched it on 8 December 2022 at the EU Agricultural Outlook Conference. At launch it promised a section showing self-sufficiency rates of the most significant agricultural commodities, as well as shares of EU and EU countries' imports for these commodities and fertilisers. Later updates added self-sufficiency and import dependency for energy inputs at both the EU and Member State levels. The experts of the European Food Security Crisis preparedness and response Mechanism (EFSCM) chose the datasets.

The dashboard has four limits:
- It covers the EU and its Member States only, with no UK, Norway, Switzerland, Balkans or Ukraine.
- It shows charts and tables, not a map.
- It has no crop calendar or regional production layer.
- The Agri-food portal's machine-to-machine API does not include it. The API covers sector data such as beef, cereals, oilseeds, sugar and fertiliser, but not Food Supply/EFSCM.

DG AGRI's outlook work defines self-sufficiency simply as production divided by consumption. Analysts working from Commission data use the same convention: Agriculture Stratégies (Alessandra Kirsch, 21 October 2024, using 2019–2022 averages) defines the self-sufficiency rate as production/consumption, where apparent consumption is production + imports – exports. The dashboard's own "Info" tab could not be read to confirm its exact formula or the years it covers.

The other tools each cover one or two of the layers:

- **JRC EU Food System Monitoring Dashboard (DataM)**: https://datam.jrc.ec.europa.eu/datam/mashup/EU_FOOD_SYSTEM_MONITORING/. It tracks the sustainability of the EU food system across environmental, economic and social indicators, including self-sufficiency rates. It now offers "flat data" downloads; its last update was 18/06/2026. It is broad and policy-focused, with a single SSR indicator rather than product-level trade maps.
- **DG AGRI Agri-food data portal, trade apps and sector dashboards**: https://agridata.ec.europa.eu/extensions/DataPortal/trade.html. The "Overview of EU agri-food trade" app gives monthly figures (value, volume, unit value) by product, extra-EU partner and Member State, built from Comext. It has a typical delay of 2 months, and intra-EU trade is not taken into account. There are separate monthly trade views for sugar, rice, wine, olive oil and other sectors.
- **Our World in Data (OWID)**. One chart, "Net trade of food products as a share of domestic supply", is a global choropleth calculated as 100 × (exports − imports) / domestic supply from FAO data: https://ourworldindata.org/grapher/net-food-trade-as-a-share-of-domestic-supply. Its CSV and metadata can be fetched directly. OWID also built a Sankey tool from FAO country-to-country data showing where each food is exported and imported: https://ourworldindata.org/how-does-food-get-traded-around-the-world. It is open (CC BY) and polished, but global, national-only and without seasonality.
- **resourcetrade.earth (Chatham House)**: https://resourcetrade.earth. It maps bilateral trade in over 1,350 resource products between 200+ countries, including agriculture. It reconciles importer and exporter reports from UN Comtrade under licence, and shows embodied land and water for some (non-livestock) agricultural flows. It is good for exploring flows, but it has no self-sufficiency measure, no crop calendar, and the bulk data cannot be freely reused because of Comtrade licensing.
- **Trase**: https://trase.earth. It maps supply chains for commodities that carry deforestation risk (soy, beef, cocoa, palm oil, coffee) down to the sub-national sourcing region, and links them to EU import markets. Its recent EU assessment covers over 150 commodities for 2021–2023 and finds the EU most exposed via cocoa from Côte d'Ivoire (38,800 ha per year, 40.1% of the EU total). It also adjusts for re-exports: the EU's deforestation exposure from cocoa falls from 45,600 ha to 41,700 ha once re-exports are accounted for. It is an excellent model for handling re-exports, but its scope is sustainability, not food autonomy.
- **Observatory of Economic Complexity (OEC)**: https://oec.world. It has rich treemap, network and map visualisations of bilateral trade, mainly built on BACI. Historical data is free. Pro costs USD 299/month and adds the latest data, the Data Explorer and an API key. Premium costs USD 1,999/month and adds bulk downloads. Researchers and students get 50% off. It covers trade only.
- **FAOSTAT** (https://www.fao.org/faostat/en/#data) and the **FAO Hand-in-Hand geospatial platform / FAO data catalog** (https://data.apps.fao.org). These offer official data with basic charts and maps, but they are a data platform rather than a European storytelling map.
- **Crop-season tools.**
  - The FAO Crop Calendar (https://cropcalendar.apps.fao.org) is a free web app covering more than 100 crops by country and agro-ecological zone, with a public REST API (https://api-cropcalendar.apps.fao.org).
  - USDA FAS IPAD publishes crop calendars and production maps for Europe and for Ukraine, Moldova and Belarus: https://ipad.fas.usda.gov/rssiws/al/crop_calendar/europe.aspx and https://ipad.fas.usda.gov/rssiws/al/crop_calendar/umb.aspx.
  - The JRC MARS Bulletin gives monthly crop monitoring and yield forecasts for the EU and its neighbours. The September 2026 issue (Vol. 34 No 8, 28 September 2026) reported EU summer crop yield forecasts well below the five-year average, further reduced that month by 7% for sugar beet, 2% each for grain maize and soybean and 1% for potatoes, with rice 3% below average.
- **Academic SSR work.**
  - A 2025 Nature Food paper by Stehl, Vonderschmidt, Vollmer, Alexander and Jaacks (Nature Food 6:571–576, published 16 May 2025) compared domestic production with dietary guidelines across seven food groups (https://www.nature.com/articles/s43016-025-01173-4). It found that over a third of all countries cannot meet self-sufficiency for more than two of the seven essential food groups, that 7 European countries are self-sufficient in two or fewer groups, and that all European countries can reach their dairy requirements independently. Its replication code is open: https://github.com/JonasStl/SelfSufficiency.
  - The SSFSSR web calculator (https://ssfssr-app.github.io/ssfssr-app/) publishes a supply-side food self-sufficiency ratio for 188 countries from 2010 to 2023, based on FAO Food Balances.
  - A NUTS2 study of 226 EU regions (https://www.sciencedirect.com/science/article/pii/S2352550922002214) found that 14% of regions were self-sufficient and 26% import-dependent across all three of its SSR dimensions.
  - A 2024 study in Scientific Reports modelled regional food self-sufficiency potential in the Alpine space (https://www.nature.com/articles/s41598-024-60010-z).
- **Think tanks and media.**
  - Agriculture Stratégies (https://www.agriculture-strategies.eu/en/2024/10/european-food-sovereignty-what-do-the-numbers-say/) estimates EU self-sufficiency in soybeans at only 15% (2.5 Mt produced against 16.2 Mt consumed in 2022). It puts sunflower at 93% and rapeseed at 74%.
  - The Savills Global Food Self-Sufficiency Tracker, which compares 20 nations using FAO data, puts the UK among the poorest performers at 62%. This matches Defra's 2023 figure of 62%, though Savills' 2026 "Food Beyond Today" report gives 65%.
  - After the 2022 invasion, outlets produced static or lightly interactive dependency graphics. Examples are Al Jazeera's wheat infographic (February 2022), BNP Paribas Economic Research's heatmap of European exposure to Russian and Ukrainian imports (March 2022), iMEdD Lab's dependency maps, and FAO's information note on Ukraine and Russia (updated July 2023).
  - No persistent, updated interactive European food-dependency map from Reuters, the FT, the Guardian or Le Monde was found. If one exists, it was not surfaced in this research.
- **GitHub.** There are many FAOSTAT explorers (Streamlit and Power BI dashboards), FAO's own `gisfao` boundary tools, and the FABIO input-output tables (martinbruckner/fabio_v1). No open-source project was found that maps Europe-wide product-level SSR together with trade partners and seasons.

### Comparison table

| Project | Layers covered | Geography | Interactivity | Open data / code | Main gap vs. this project |
|---|---|---|---|---|---|
| DG AGRI Food Supply (EFSCM) | SSR, import dependency, import origin, diversification | EU + Member States | Charts and filters | Viewable, no API | No map, EU-only, no seasons or regions |
| JRC Food System Monitoring | Sustainability indicators incl. SSR | EU | Dashboard | Flat data download | Not product-level, no trade partners |
| Agri-food portal trade apps | Monthly extra-EU trade | EU + Member States | Dashboards | Downloads | No intra-EU trade, no SSR |
| Our World in Data | Net trade/supply share, Sankey flows | Global | Choropleth, Sankey | CC BY CSV | National only, no seasons |
| resourcetrade.earth | Bilateral resource trade, embodied land and water | Global | High (map/flows) | Comtrade-licensed | No SSR or seasons |
| Trase | Deforestation-risk supply chains | Producer subnational → EU | High | Open data | Narrow commodities |
| OEC | Bilateral trade (BACI) | Global, some subnational | High | Free historical; paid API | Trade only |
| FAO Crop Calendar / USDA IPAD / GIEWS | Planting and harvest seasons | Global/Europe | Lookup tools | Free (FAO API) | No trade or SSR |
| Nature Food 2025 / SSFSSR app | SSR by food group | Global | Static maps / web app | Code on GitHub | No trade partners, no seasons |

## Part 2 — Data inventory

### A. Production

| Dataset | URL / access | Coverage | Granularity | Licence and caveats |
|---|---|---|---|---|
| FAOSTAT Crops and livestock products (QCL) | https://www.fao.org/faostat/en/#data/QCL; bulk ZIP via bulks-faostat.fao.org; R `FAOSTAT` package | ~200 countries incl. all of Europe, Ukraine, Russia, Belarus, Turkey; 1961–latest | National | CC BY 4.0; some values are FAO estimates or imputations |
| Eurostat crop production `apro_cpsh1` / `apro_cpnh1` | https://ec.europa.eu/eurostat/databrowser (SDMX/JSON API, free) | EU, EFTA, candidates; 100+ crops; standardised to EU standard humidity (14% for cereals) | National | Free reuse with attribution; from reference year 2025 collected under the SAIO Regulation (EU) 2022/2379, so watch for series breaks |
| Eurostat `apro_cpshr` (regional) | https://ec.europa.eu/eurostat/databrowser/view/apro_cpshr/default/table | 2000–2024; last update 08/09/2026; includes e.g. Albania | NUTS2 (Germany only NUTS1) | Gaps for minor crops; a harmonised 2017–2021 NUTS2 gap-filled set is in Scientific Data (https://www.nature.com/articles/s41597-025-05436-4) |
| Eurostat animal production (`apro_mt_*` meat, `apro_mk_*` milk) and regional `agr_r_*` | Eurostat databrowser / API | EU + EFTA + candidates | National; some regional | Livestock regional coverage thinner than crops |
| Eurostat Farm Structure Survey / Integrated Farm Statistics (`ef_*`) | Eurostat databrowser | Census-type rounds (2010, 2016, 2020, 2023) | NUTS2 | Structural (area, livestock units), not annual output |
| LUCAS land-use/cover survey | Eurostat LUCAS pages | EU, 3-yearly point survey (2018, 2022) | Point/field | Training/validation data for crop maps |
| JRC EUCROPMAP 2018 / 2022 | https://data.jrc.ec.europa.eu/dataset/555e5d1d-1aae-4320-a716-2e6d18aa1e7c ; FTP and WMS; Google Earth Engine `JRC/D5/EUCROPMAP/V1` | 2022: EU27 + Ukraine, 19 crop types; 2018: EU28 | 10 m raster | Open; Ukraine accuracy lower (79.3% overall for 7 main classes) |
| Corine Land Cover / Copernicus HRL | land.copernicus.eu | EEA39 | 100 m / HR | Land cover, not crop-specific |
| JRC MARS Bulletin and Agri4Cast | https://joint-research-centre.ec.europa.eu/monitoring-agricultural-resources-mars/jrc-mars-bulletin_en ; Agri4Cast data portal | EU + neighbours (Ukraine, Türkiye, Maghreb); monthly | National/regional forecasts; 25 km gridded weather | Forecasts, not final statistics |
| National statistics offices (e.g. Defra UK, SSB Norway, FSO Switzerland, Ukrstat) | Various | Country-specific | Often regional | Mixed licences; Ukrstat CC BY 4.0 |

### B. Crop calendars and seasons

| Dataset | URL / access | Coverage | Resolution | Notes |
|---|---|---|---|---|
| FAO Crop Calendar | https://cropcalendar.apps.fao.org ; REST API https://api-cropcalendar.apps.fao.org | 100+ crops, many countries, by agro-ecological zone | Country/AEZ | Free; best machine-readable source for fruit and vegetables |
| FAO GIEWS Crop Calendar | https://data.apps.fao.org/catalog/dataset/giews-crop-calendar (CSV via BigQuery API) | Main staples, global | National | Free |
| USDA FAS IPAD crop calendars | https://ipad.fas.usda.gov/rssiws/al/crop_calendar/europe.aspx | EU, UK, Balkans, Ukraine, Moldova, Belarus | National/regional graphics | Images, not data; need manual digitisation |
| JRC-MARS European Crop Calendar | Agri4Cast data portal (listed by the EEA) | EU28; winter wheat, grain maize, rice; 3 phenological phases | National | Old (2016); limited crops |
| JRC ASAP crop calendars | https://data.jrc.ec.europa.eu/dataset/jrc-10112-10003 | Global; sowing/growth/harvest by dekad | GAUL0/GAUL1 | Matched to satellite phenology |
| GGCMI Phase 3 crop calendar | https://zenodo.org/records/5062513 | Global, 18 crops, rainfed vs irrigated | 0.5° grid | CC BY 4.0; static multi-year averages, one season per crop. **Used** (`pipeline/seasons.py`) for cereals, potatoes, sugar beet, pulses, oilseeds; its single date is a convention for cassava and sugar cane, which are left out |
| ISIMIP3a land use, 15 crops (histsoc) and fractional country masks | https://data.isimip.org | Global, 1901–2021, rainfed and irrigated | 0.5° grid | CC BY 4.0, open download; **used** to weight the calendar by where each crop grows (mean 2019–2021) |
| GGCMI Phase 2 winter and spring wheat areas | https://zenodo.org/records/3773827 | Global (MIRCA2000-based) | 0.5° grid | CC BY 4.0; **used** for wheat, which the land-use file pools with barley and rye |
| MapSPAM 2020 (IFPRI) | https://doi.org/10.7910/DVN/SWPENT | Global harvested area, 46 crops | 5 arc-min | CC BY 4.0, but download behind a guestbook (name, e-mail) and IFPRI terms of use; not scripted here |
| Sacks et al. 2010 (SAGE) | Univ. Wisconsin SAGE | Global, 19 crops | 5 arc-min | Older observations |
| MIRCA2000 / MIRCA-OS | Nature Scientific Data (https://www.nature.com/articles/s41597-024-04313-w) | Monthly irrigated/rainfed areas | Gridded | Useful for "what is in the ground this month" |
| GEOGLAM Crop Monitor | cropmonitor.org | Major producers | National/subnational | Monthly crop conditions for AMIS crops |

### C. Trade

| Dataset | URL / access | Coverage | Granularity | Cost / licence and caveats |
|---|---|---|---|---|
| Eurostat Comext | https://ec.europa.eu/eurostat/web/international-trade-in-goods/database ; bulk via https://ec.europa.eu/eurostat/api/dissemination/files?file=comext/... ; API https://ec.europa.eu/eurostat/api/comext/dissemination/ | EU27 Member States as reporters (intra- and extra-EU), all partners; monthly and annual from January 1988 | CN8 (8-digit) | Free (CC BY 4.0, Eurostat); the best source for intra-EU flows; the old Bulk Download Listing was phased out from October 2023. Used here through dataset DS-045409 of the SDMX API: an extraction over 5 million rows is refused, larger ones are queued (poll `1.0/async/status/{id}`, fetch `1.0/async/data/{id}`); Greece is GR, the UK XI/XU since 2021 |
| UN Comtrade (Comtrade Plus) | https://comtradeplus.un.org ; API https://comtradeapi.un.org | 200+ reporters (UK, NO, CH, Balkans, UA, MD, TR, RU*) ; HS chapters 01–24 | HS6 | Free registered: 500 calls/day, 100,000 records/call, no bulk files. Premium Individual: USD 2,000/year, 5,000 calls/day plus bulk. Re-dissemination is restricted, though public free-of-charge data visualisation with small extracts (≤100k records) is exempt |
| CEPII BACI | https://www.cepii.fr/DATA_DOWNLOAD/baci/doc/baci_webpage.html | ~200 countries, ~5,000 HS6 products; HS92 from 1995; HS22 2022–2024; version 202601 | HS6 | Free, Etalab Open Licence 2.0 (cite CEPII); reconciles mirror flows, CIF/FOB adjusted; ~2-year lag |
| FAOSTAT Detailed Trade Matrix (TM) | https://www.fao.org/faostat/en/#data/TM ; bulk ZIP | All countries, FAO item codes (food and agriculture), 1961–2024 (December 2025 release; next due December 2026) | Bilateral, FAO items | CC BY 4.0; already in FAO commodity codes, so easy to join to FBS and production |
| FAO Technical Conversion Factors for Agricultural Commodities (TCF) | https://www.fao.org/fileadmin/templates/ess/documents/methodology/tcf.pdf | Extraction rates per country (data for 1992–1996) for primary crops and livestock up to the first processing stage | Country × product | Free FAO publication; used for the conversion factors in `trade_items.csv` (cite FAO); old, so medians across countries rather than one country's rate |
| UNSD CPC 2.1–HS 2017 correspondence; HS 2022→2017 conversion | https://unstats.un.org/unsd/classifications/Econ | All HS6 codes | HS6 ↔ CPC 2.1 class | Free (UN terms of use, attribution); links HS6 trade codes to FAO's CPC-coded trade items, the base of `mappings/hs_items.csv` |
| EUMOFA conversion factors by CN8 | https://fishery-aquaculture-market-observatory.ec.europa.eu/en/data/metadata (Metadata 2, Annex 7) | Fish and seafood CN8 codes, 2011–2026 | CN8 × year | Free (European Commission reuse notice, attribution); product weight → live weight, the basis of the FBS fish balance |
| WITS (World Bank) | wits.worldbank.org | Comtrade/tariff front-end | HS6 | Free interface, same Comtrade data |
| DG AGRI monthly agri-food trade reports and app | https://agridata.ec.europa.eu/extensions/DataPortal/trade.html | Extra-EU only | Product categories | Free; around 2-month lag |
| Global Trade Atlas (S&P Global) | Commercial | Monthly, many countries | HS/national lines | Paid; unnecessary for this project |
| OEC | https://oec.world | BACI-based plus national sources | HS6 (some subnational) | Free viewing; API only from Pro (USD 299/month) |

### D. Self-sufficiency and dependency

| Dataset | URL | Coverage | Notes |
|---|---|---|---|
| FAO Food Balance Sheets (FBS, 2010–) | https://www.fao.org/faostat/en/#data/FBS | 2010–2023 (released 28 October 2025); supply-utilization accounts for 178 countries and 449 products | Gives production, imports, exports, stock change, feed, seed, food, losses and kcal. This is the best backbone for comparable SSR and import dependency ratios (IDR) across all of Europe |
| FAO FBS historic (–2013) | https://www.fao.org/faostat/en/#data/FBSH | 1961–2013, old methodology | Series break at 2010/2014 |
| DG AGRI Food Supply / EFSCM | https://agridata.ec.europa.eu/extensions/FoodSupply/FoodSupply.html | EU + Member States | Official EU SSR; no API |
| DG AGRI–JRC EU estimated agricultural balance sheets | https://data.jrc.ec.europa.eu/dataset/33243e5e-44a1-4b43-9444-31d64dc7921f (doi 10.2905/JRC.EBBTB0G) | EU27 Member States + EU, 2002–2025, updated twice a year | Production, intra/extra-EU trade, apparent use, SSR for dairy (milk equivalent), cereals, oilseeds, meat, wine, olive oil, apples, oranges, tomatoes. Intra-EU imports mirrored from exports. EC reuse notice. The server rejects scripted downloads: fetch the ZIP in a browser. Used for EU dairy, tomatoes, olive oil and wine; compared with FAO for all its foods (see methodology) |
| USDA FAS Production, Supply and Distribution (PSD) | https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip | ~190 countries (EU as one unit), market years to the current outlook; cereals, oilseeds, oils, sugar, meat, dairy products, coffee | Compiled by USDA independently of FAO from national statistics, attaché reports and customs data. Production, imports, exports, domestic consumption, stocks in 1000 t. Public domain. Used as a second opinion on FAO's SSR, not as a replacement (see methodology, "FAO against USDA") |
| DG AGRI EU Agricultural Outlook | agriculture.ec.europa.eu | EU-level SSR projections to 2035 | Self-sufficiency defined as production/consumption |
| OWID net trade share | https://ourworldindata.org/grapher/net-food-trade-as-a-share-of-domestic-supply | Global | Ready-made CSV |
| SSFSSR app / Nature Food 2025 code | see Part 1 | 186–188 countries | Alternative, nutrition-based SSR |

**Formulas (FAO convention):**
- SSR = production / (production + imports − exports) × 100.
- IDR = imports / (production + imports − exports) × 100.
- In FBS terms the denominator is the domestic supply quantity, which also includes stock changes.

### E. Geospatial base layers

| Layer | URL | Formats | Licence |
|---|---|---|---|
| Eurostat GISCO NUTS (2024, 2021, 2016 and earlier) | https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics ; API https://gisco-services.ec.europa.eu/distribution/v2/nuts/download | GeoPackage, SHP, GeoJSON, TopoJSON, PBF, SVG; scales 1:1M–1:60M; EPSG 3035/4326/3857 | Free for **non-commercial** use with the credit "© EuroGeographics for the administrative boundaries"; commercial use requires a EuroGeographics licence |
| Natural Earth | naturalearthdata.com | SHP/GeoJSON | Public domain; good for non-EU countries |
| GADM | gadm.org | Admin levels 0–5 | Free for non-commercial use only |
| geoBoundaries | geoboundaries.org | Admin boundaries | Open (CC BY) alternative for Ukraine, Moldova and Balkans |

### Country coverage beyond the EU27
- **Fully covered by FAO (FBS, trade matrix, production):** UK, Norway, Switzerland, Iceland, Serbia, Bosnia and Herzegovina, North Macedonia, Montenegro, Albania, Ukraine, Moldova, Turkey, Russia, Belarus. Kosovo is typically missing or merged with Serbia in FAO data.
- **Eurostat:** covers EFTA and candidate countries for many production tables (e.g. Albania in `apro_cpshr`). Comext reporters are EU Member States only, so non-EU flows have to come from mirror data or from Comtrade/BACI.
- **Belarus and Russia:** UN Comtrade reporting has been patchy since 2022. Rely on mirror (partner-reported) flows in BACI/Comext and flag them as such.
- **Ukraine:** On 10 April 2023 Ukrstat suspended most statistical publication under martial law, except the CPI, export-import of goods, the preliminary GDP estimate and some other series. Crop production releases were marked "publication postponed" in 2024. Mandatory reporting resumed on 5 July 2025. Since December 2025 Derzhstat has published monthly backfills of 2022–2025 data, including crop areas, harvests, yields and livestock. Its rural household survey restarted on 18 May 2026 after a four-year break. Derzhstat puts the 2025 harvest at 30.9 Mt of maize and 23.3 Mt of wheat. All figures exclude occupied territories. EUCROPMAP 2022 and the MARS bulletins give independent satellite-based views.

## Part 3 — Build guidance and pitfalls

### Recommended pipeline
1. **Ingest.** Pull these sources into a DuckDB or Parquet store, scheduled annually and monthly with GitHub Actions:
   - FAOSTAT bulk files: FBS, TM, QCL.
   - Eurostat via SDMX or the `eurostat` Python/R packages: `apro_cpsh1`, `apro_cpshr`, animal tables.
   - Comext annual CN8 bulk files.
   - BACI HS17/HS22.
   - FAO Crop Calendar via its API.
   - GISCO NUTS 2024 GeoJSON/TopoJSON.
2. **Harmonise products.** Use FAO item codes or FBS groups as the master key. Map HS6/CN8 to FAO items with FAO's published HS–FAOSTAT correspondence. Map Eurostat crop codes (e.g. C1500 grain maize) to FAO items by hand; there are only around 100 of them. Aggregate everything into about 12–15 user-facing groups: cereals, oilseeds and vegetable oils, protein crops/soy, sugar, fruit, vegetables, potatoes, meat by species, dairy, eggs, fish, and coffee/cocoa/tea.
3. **Compute indicators per country × product × year:**
   - SSR and IDR, as both a 3-year average and the latest year.
   - Import concentration as a Herfindahl–Hirschman index (HHI) across partners.
   - Share of imports from outside the EU and from Russia/Ukraine.
   - A calorie-weighted aggregate SSR using FBS kcal.
   - Optionally, a "feed-adjusted" SSR for livestock products that counts imported soy meal.
4. **Season layer.** Turn FAO, USDA and GGCMI calendars into a 12-month matrix per country and crop. Overlay it with monthly Comext imports to show "import windows", for example tomatoes from Morocco in winter.
5. **Regional layer.** Join Eurostat NUTS2 production and EUCROPMAP rasters to NUTS polygons. Present this as "what is grown where". Do not present regional SSR without a consumption model; the NUTS2 literature shows it needs one.
6. **Frontend.**
   - Use MapLibre GL JS with vector tiles (PMTiles) for the base map and choropleths.
   - Use deck.gl's ArcLayer for trade flows.
   - Use D3 or Observable Plot for side panels (seasonal heat strips, partner bars).
   - Use Svelte or React for state.
   - Kepler.gl suits prototyping. Datawrapper or Flourish can produce quick static or semi-interactive country choropleths, but they won't do linked multi-layer exploration.
   - Leaflet works but handles many polygons plus arcs less well.

### Methodological pitfalls
- **Re-exports and the Rotterdam/Antwerp effect.** Comext records the Netherlands and Belgium as the importer of soy, cocoa, fruit and other goods that are then shipped on. Raw imports overstate their dependence and hide the real dependence of Germany and others. Use FBS supply (which nets out exports) and, where possible, Trase-style re-export adjustment. The EU's own trade apps avoid the problem only by excluding intra-EU trade.
- **Intra-EU vs extra-EU trade.** Make the user choose explicitly between "national autonomy" (all imports, including from other EU states) and "EU bloc autonomy" (extra-EU only). These can tell opposite stories. Agriculture Stratégies found that the EU as a whole is above 100% self-sufficient in chicken meat, while France has fallen short of its own demand since 2014.
- **Mirror discrepancies.** Importer CIF values and exporter FOB values never match. Intra-EU arrivals and dispatches diverge, and Russia and Belarus reporting is degraded. Use BACI's reconciled flows or the FAO TM, and document which you used.
- **Aggregation.** "Fruit" SSR mixes apples (high SSR) with bananas and citrus (near zero in the north). Show product drill-down and avoid single headline numbers.
- **Feed vs food.** An SSR above 100% for meat or dairy can coexist with heavy dependence on imported protein feed. The EU produces only about 15% of the soybeans it consumes (Agriculture Stratégies). The NUTS2 literature makes the same point. Offer a feed-adjusted view.
- **Measurement basis: calories, tonnes or value.** Tonnage SSR is dominated by heavy, low-value goods such as cereals and milk, value SSR by coffee, wine and cheese, and calorie SSR by cereals, oils and sugar. Choose one per view and label it.
- **Processed vs raw.** Trade in flour, oils, cakes and meat preparations needs conversion to primary equivalents. FBS already does this; raw HS trade does not.
- **Year-to-year volatility.** Droughts swing SSR sharply. JRC's 2025–2026 bulletins report south-eastern Europe's maize and sunflower losses, and the August 2026 MARS Bulletin (Vol. 34 No 7) put EU yield forecasts for all summer crops below the five-year average by up to 14%. Default to 3-year averages.
- **Statistical breaks.** Watch for FBS methodology changes (2010/2014), Eurostat's SAIO transition from 2025, NUTS revisions (2021 → 2024), and HS revisions (2017 → 2022) that change product codes.
- **Ukraine since 2022.** National data has gaps and is being backfilled; it excludes occupied areas, and trade has shifted to the Danube and EU "solidarity lanes". Mark 2022–2024 values as provisional and cross-check them with FAO, USDA PSD and JRC.
- **Licensing.** If you publish the app commercially, swap GISCO boundaries for Natural Earth or geoBoundaries, or obtain a EuroGeographics licence. Avoid redistributing raw Comtrade extracts; use BACI (open) or Comext (free) instead.

## Recommendations
- **Build it, and position it as the pan-European, product-level "autonomy atlas".** That gap is real: the official EU tool is EU-only, chart-based and has no API, and global tools lack European depth and seasonality.
- **Phased MVP:**
  1. Phase 1: a country choropleth of FBS-based SSR and IDR for about 12 product groups across about 45 European countries.
  2. Phase 2: partner-flow arcs from Comext and BACI, with an intra-EU vs extra-EU toggle.
  3. Phase 3: crop calendars plus NUTS2 production and EUCROPMAP layers.
  4. Phase 4: feed-adjusted and calorie-weighted indices, and scenario toggles such as "lose Ukraine/Russia supply".
- **Use open-licensed sources as the default stack:** FAOSTAT (CC BY 4.0), Eurostat/Comext, BACI (Etalab 2.0), and Natural Earth or GISCO. Treat Comtrade, OEC and Global Trade Atlas as optional.
- **Publish the harmonised dataset and code.** A reusable SSR/IDR panel with an HS↔FAO crosswalk is itself a contribution nobody currently provides openly for Europe.

## Caveats
- The DG AGRI Food Supply dashboard's full commodity list, exact formula and year coverage could not be read, because the app's Info tab is dynamic. The production/consumption definition comes from DG AGRI's outlook publications.
- Specific interactive pieces from Reuters, the FT, the Guardian or Le Monde were not verified. The media examples cited are Al Jazeera, BNP Paribas and iMEdD.
- Prices and quotas (OEC, Comtrade) and dataset versions reflect pages accessed in 2026 and may change.
- Several self-sufficiency rankings in circulation (e.g. Visual Capitalist, Savills) are secondary repackagings with differing methods. They are not comparable with each other or with FAO SSR.

## Sources

- https://agridata.ec.europa.eu/extensions/FoodSupply/FoodSupply.html
- https://agriculture.ec.europa.eu/media/news/european-commission-launches-dashboard-food-security-eu-2022-12-08_en
- https://agridata.ec.europa.eu/extensions/DataPortal/API_Documentation.html
- https://datam.jrc.ec.europa.eu/datam/mashup/EU_FOOD_SYSTEM_MONITORING/
- https://agridata.ec.europa.eu/extensions/DataPortal/trade.html
- https://ourworldindata.org/grapher/net-food-trade-as-a-share-of-domestic-supply
- https://ourworldindata.org/how-does-food-get-traded-around-the-world
- https://resourcetrade.earth/about
- https://trase.earth/insights/eu-s-deforestation-footprint-highlights-need-for-eudr
- https://oec.world/en/plans
- https://api-cropcalendar.apps.fao.org/
- https://ipad.fas.usda.gov/rssiws/al/crop_calendar/europe.aspx
- https://ipad.fas.usda.gov/rssiws/al/crop_calendar/umb.aspx
- https://ssfssr-app.github.io/ssfssr-app/
- https://www.sciencedirect.com/science/article/pii/S2352550922002214
- https://www.nature.com/articles/s41598-024-60010-z
- https://www.nature.com/articles/s43016-025-01173-4
- https://github.com/JonasStl/SelfSufficiency
- https://www.agriculture-strategies.eu/en/2024/10/european-food-sovereignty-what-do-the-numbers-say/
- https://ec.europa.eu/eurostat/cache/metadata/en/apro_cp_esms.htm
- https://ec.europa.eu/eurostat/databrowser/view/apro_cpshr/default/table
- https://www.nature.com/articles/s41597-025-05436-4
- https://developers.google.com/earth-engine/datasets/catalog/JRC_D5_EUCROPMAP_V1
- https://joint-research-centre.ec.europa.eu/monitoring-agricultural-resources-mars/jrc-mars-bulletin_en
- https://data.apps.fao.org/catalog/dataset/giews-crop-calendar
- https://data.jrc.ec.europa.eu/dataset/jrc-10112-10003
- https://zenodo.org/records/5062513
- https://www.nature.com/articles/s41597-024-04313-w
- https://ec.europa.eu/eurostat/en/web/international-trade-in-goods/database
- https://uncomtrade.org/docs/subscriptions/
- https://www.cepii.fr/DATA_DOWNLOAD/baci/doc/baci_webpage.html
- https://www.fao.org/statistics/highlights-archive/highlights-detail/food-balance-sheets-2010-2023/en
- https://bulks-faostat.fao.org/production/datasets_E.xml
- https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics
- https://stat.gov.ua/en/news/suspend-publication-statistical-information
- https://stat.gov.ua/uk/news/vidnovlennya-danykh-za-2022-2025-shcho-vzhe-oprylyudnyv-derzhstat-u-hrudni-2025-roku
- https://www.savills.com/impacts/environment/self-sufficiency-in-food-production-an-international-comparison.html
