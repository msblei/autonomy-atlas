# Food Autonomy Atlas

Interactive map of European agriculture: what's grown where and when, who imports and exports
what, and how self-sufficient each country really is.

## Why

Europe's food dependence is discussed constantly but mapped almost nowhere. The European Commission
publishes self-sufficiency rates, but only for EU members, only as charts, and with no API. Global
trade explorers show flows but not whether a country could feed itself; crop calendars show seasons
but not trade. Food Autonomy Atlas puts those layers on one map, for the whole continent, product by
product, with every number traceable to its source.

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

## Data and licences

| Source | Used for | Licence |
|---|---|---|
| [FAOSTAT](https://www.fao.org/faostat/en/#data) Food Balance Sheets, Supply Utilization Accounts, Production, Trade Matrix | supply, SSR/IDR, animal feed, bilateral trade | CC BY 4.0 |
| [Feedipedia](https://www.feedipedia.org) (INRAE, CIRAD, AFZ, FAO) | protein content of feed | cited values |
| [FAO GLEAM 3](https://foodandagricultureorganization.shinyapps.io/GLEAMV3_Public/) dashboard, dry matter intake | share of cattle, sheep and goat feed that is traded | CC BY 4.0, © FAO 2022 |
| [MAFF Japan](https://www.maff.go.jp/j/zyukyu/zikyu_ritu/012.html) food self-sufficiency ratio | Japan's "all food" figure (FAO publishes no balance) | Government of Japan Standard Terms of Use 2.0 (CC BY 4.0 compatible) |
| [DG AGRI EU feed protein balance sheet](https://agriculture.ec.europa.eu) | check on imported feed protein | EC reuse notice (attribution) |
| [Eurostat](https://ec.europa.eu/eurostat) Comext, `apro_cpshr` | EU members' fish trade and the EU's fish balance; a check on FAO's trade figures; where crops grow, by region | CC BY 4.0 |
| [EUMOFA](https://fishery-aquaculture-market-observatory.ec.europa.eu) conversion factors | fish trade in live weight | EC reuse notice (attribution) |
| [UN Statistics Division](https://unstats.un.org/unsd/classifications/Econ) CPC–HS correspondence | trade codes to food groups | UN terms of use (attribution) |
| [CEPII BACI](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37) | fish trade outside the EU; a check on FAO's trade figures | Etalab Open Licence 2.0 (cite Gaulier & Zignago 2010) |
| [DG AGRI–JRC EU agricultural balance sheets](https://agridata.ec.europa.eu) | EU dairy, tomatoes, olive oil, wine; dairy milk-equivalent factors | EC reuse notice (attribution) |
| [USDA FAS PSD](https://apps.fas.usda.gov/psdonline) | second opinion on FAO's figures | US government work, public domain |
| [FAO Technical Conversion Factors](https://www.fao.org/fileadmin/templates/ess/documents/methodology/tcf.pdf) | processed trade back to raw product | FAO publication (cite FAO) |
| [GGCMI Phase 3 crop calendar](https://zenodo.org/records/5062513) (Jägermeyr et al. 2021), [ISIMIP3a](https://data.isimip.org) land use and country masks | when crops are sown and harvested | CC BY 4.0 (GGCMI), CC0 1.0 (ISIMIP) |
| [FAO Crop Calendar](https://cropcalendar.apps.fao.org) | seasons of fruit and vegetables (planned) | free API |
| [JRC EUCROPMAP](https://data.jrc.ec.europa.eu/dataset/15f86c84-eae1-4723-8e00-c1b35c8f56b9) crop shares at 2 km (2018) | where the fields are | CC BY 4.0, © European Union |
| [Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco) countries and NUTS | all boundaries on the map | non-commercial only, "© EuroGeographics for the administrative boundaries" |
| [Natural Earth](https://www.naturalearthdata.com) | country boundaries (downloaded as the public-domain fallback, not on the map) | public domain |
| [Atkinson Hyperlegible Next](https://www.brailleinstitute.org/freefont/) (Braille Institute) | typeface, also on the map | SIL Open Font License |

To update the data: `docs/updating.md`.

See `docs/research-report.md` for the full inventory, including crop-type maps, JRC MARS, USDA
crop calendars and the methodological caveats (re-exports, feed use, measurement basis, Ukraine data
gaps).

## Licence

MIT for the code. Data remain under their original licences listed above.
