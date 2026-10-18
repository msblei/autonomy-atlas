# Autonomy Atlas

Interactive map of European agriculture: what's grown where and when, who imports and exports
what, and how self-sufficient each country really is.

## Why

Europe's food dependence is discussed constantly but mapped almost nowhere. The European Commission
publishes self-sufficiency rates, but only for EU members, only as charts, and with no API. Global
trade explorers show flows but not whether a country could feed itself; crop calendars show seasons
but not trade. Autonomy Atlas puts those layers on one map, for the whole continent, product by
product, with every number traceable to its source.

## Status

**Phase 1 working locally.** The pipeline builds FAO Food Balance figures for ~178 countries plus
the EU as a bloc, with the European Commission's balance sheets for EU dairy, tomatoes, olive oil
and wine. The map opens on one plain question: if a country ate only what its own farms produce,
for how many months of the year would its food last? Choose a country and a food, and a card shows
the year's balance (produces + buys − sells = uses), which is also the way in: how long the food
lasts and how that changed, who the country buys from and sells to (on the map), and what the food
is used for. "How do we know?" works every figure out from FAO's lines; "All the numbers" shows
SSR/IDR, tonnes/kcal and FAO items.

Every published number is checked before release (`make verify`): tests, invariant checks, an
independent recomputation written from `docs/methodology.md` alone, and browser tests of what the
page shows. Figures whose FAO balance contradicts itself, or that a review found implausible, are
withheld everywhere and the page says why.

## Quick start

```bash
make setup      # Python venv, pip install -e ".[dev]", npm install in web/
make download   # FAOSTAT bulk files, Eurostat regional crops, boundaries (~1 GB)
make build      # harmonise + compute SSR/IDR -> data/processed/
make export     # write web/public/data/*.json
make verify     # every check; required before anything is published
make serve      # http://localhost:5173 (or the next free port)
```

Or step by step with the CLI: `atlas download --source faostat`, `atlas build`, `atlas export`.

## Layout

```
pipeline/   Python: download -> harmonise -> compute -> export
web/        Vite + MapLibre GL frontend
docs/       research report (existing tools, data inventory, pitfalls) and methodology
data/       raw / interim / processed (gitignored)
```

## Roadmap

1. Country-level SSR/IDR choropleth from FAO Food Balance Sheets.
2. Trade partners and arcs (FAO trade matrix; fish from Eurostat Comext), import concentration;
   for EU countries also in euros (Comext); fish from Comext and CEPII BACI.
3. Crop calendars and NUTS2 regional production ("what is grown where, and when").
4. Feed-adjusted and calorie-weighted indices; scenario toggles.

## Data and licences

| Source | Used for | Licence |
|---|---|---|
| [FAOSTAT](https://www.fao.org/faostat/en/#data) Food Balance Sheets, Production, Trade Matrix | supply, SSR/IDR, bilateral trade | CC BY 4.0 |
| [Eurostat](https://ec.europa.eu/eurostat) Comext, `apro_cpshr` | EU members' fish trade and the EU's fish balance; a check on FAO's trade figures; NUTS2 crops (planned) | CC BY 4.0 |
| [EUMOFA](https://fishery-aquaculture-market-observatory.ec.europa.eu) conversion factors | fish trade in live weight | EC reuse notice (attribution) |
| [UN Statistics Division](https://unstats.un.org/unsd/classifications/Econ) CPC–HS correspondence | trade codes to food groups | UN terms of use (attribution) |
| [CEPII BACI](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37) | fish trade outside the EU; a check on FAO's trade figures | Etalab Open Licence 2.0 (cite Gaulier & Zignago 2010) |
| [DG AGRI–JRC EU agricultural balance sheets](https://agridata.ec.europa.eu) | EU dairy, tomatoes, olive oil, wine; dairy milk-equivalent factors | EC reuse notice (attribution) |
| [USDA FAS PSD](https://apps.fas.usda.gov/psdonline) | second opinion on FAO's figures | US government work, public domain |
| [FAO Technical Conversion Factors](https://www.fao.org/fileadmin/templates/ess/documents/methodology/tcf.pdf) | processed trade back to raw product | FAO publication (cite FAO) |
| [GGCMI Phase 3 crop calendar](https://zenodo.org/records/5062513) (Jägermeyr et al. 2021), [ISIMIP3a](https://data.isimip.org) land use and country masks | when crops are sown and harvested | CC BY 4.0 |
| [FAO Crop Calendar](https://cropcalendar.apps.fao.org) | seasons of fruit and vegetables (planned) | free API |
| [Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco) NUTS | boundaries | non-commercial, © EuroGeographics |
| [Natural Earth](https://www.naturalearthdata.com) | country boundaries | public domain |
| [Atkinson Hyperlegible Next](https://www.brailleinstitute.org/freefont/) (Braille Institute) | typeface, also on the map | SIL Open Font License |

See `docs/research-report.md` for the full inventory, including crop-type maps, JRC MARS, USDA
crop calendars and the methodological caveats (re-exports, feed use, measurement basis, Ukraine data
gaps).

## Licence

MIT for the code. Data remain under their original licences listed above.
