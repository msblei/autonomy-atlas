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
the EU as a bloc. The map opens on one plain question: if a country ate only what its own farms
produce, for how many months of the year would its food last? Readers then dig deeper
one level at a time: food by food, a single food (trend, per person, where the harvest goes),
"How do we know?" (the FAO figures, the sum worked out, how to check it on FAOSTAT) and finally
all the numbers (SSR/IDR, tonnes/kcal, FAO items). A "bought and sold" view shows who each
country buys each food from and sells it to, on the map, from the FAO trade matrix.

## Quick start

```bash
make setup      # Python venv, pip install -e ".[dev]", npm install in web/
make download   # FAOSTAT bulk files, Eurostat regional crops, boundaries (~1 GB)
make build      # harmonise + compute SSR/IDR -> data/processed/
make export     # write web/public/data/*.json
make serve      # http://localhost:5173
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
2. Trade-partner arcs from Eurostat Comext and CEPII BACI; import-concentration indices.
3. Crop calendars and NUTS2 regional production ("what is grown where, and when").
4. Feed-adjusted and calorie-weighted indices; scenario toggles.

## Data and licences

| Source | Used for | Licence |
|---|---|---|
| [FAOSTAT](https://www.fao.org/faostat/en/#data) Food Balance Sheets, Production, Trade Matrix | supply, SSR/IDR, bilateral trade | CC BY 4.0 |
| [Eurostat](https://ec.europa.eu/eurostat) Comext, `apro_cpshr` | intra/extra-EU trade, NUTS2 crops | free reuse with attribution |
| [CEPII BACI](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37) | reconciled bilateral trade | Etalab Open Licence 2.0 |
| [FAO Crop Calendar](https://cropcalendar.apps.fao.org) | seasons | free API |
| [Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco) NUTS | boundaries | non-commercial, © EuroGeographics |
| [Natural Earth](https://www.naturalearthdata.com) | country boundaries | public domain |

See `docs/research-report.md` for the full inventory, including crop-type maps, JRC MARS, USDA
crop calendars and the methodological caveats (re-exports, feed use, measurement basis, Ukraine data
gaps).

## Licence

MIT for the code. Data remain under their original licences listed above.
