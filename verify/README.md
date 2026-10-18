# verify/: independent recomputation of the published numbers

`recompute.py` re-derives every number in `web/public/data/ssr.json`, `items.json` and
`trade.json` from the raw downloads, without importing or reading anything under `pipeline/`
(apart from `pipeline/mappings/`, which is input data) or `tests/`. It was written from
`docs/methodology.md` and `CLAUDE.md` only, so a disagreement points either at a pipeline bug or
at a place where the spec can be read two ways.

## Run

```
.venv/bin/python -I verify/recompute.py      # ~25 s; exit 1 if any value differs
```

Inputs, read directly:

- `data/raw/faostat/FoodBalanceSheets_E_All_Data_(Normalized).zip` (CSV read out of the zip)
- `data/raw/faostat/Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip`. `tm_cache.py` streams
  the 8.5 GB CSV out of the zip (never unzipped) and keeps the tonnes rows from 2010 on in
  `verify/.cache/tm_qty_<sha>.parquet` (about 15 s, once per zip hash).
- `data/raw/jrc/bal/Dataset_EU_estimated_agricultural_balance_sheets.csv`
- `data/raw/usda/psd_alldata_csv.zip` (USDA PSD, read out of the zip)
- `data/raw/comext/DS-045409_food.csv.gz` (Eurostat Comext; only its fish CN8 rows are used) and
  `data/raw/eumofa/conversion_factors_cn8.xlsx` (EUMOFA live-weight factors)
- `data/raw/baci/BACI_HS17_V202601.zip` (CEPII BACI; fish HS6 codes of the window years only)
- `data/raw/ggcmi/*.nc4` and `data/raw/isimip/*.nc` (crop calendars, wheat areas, crop land use,
  country masks; read with h5py) for `seasons.json`
- `data/raw/comext/DS-045409_monthly_imports.csv.gz` for `import_months.json`
- `data/raw/eucropmap/crop_percent_on_land_*_2km.tif` (read with rasterio) for the crop map
  images, checked at 4,000 sampled pixels per food
- `data/raw/faostat/SUA_Crops_Livestock_E_All_Data_(Normalized).zip` (feed, read out of the zip)
- `data/raw/eurostat/apro_cpshr.tsv.gz` and `data/raw/gisco/NUTS_RG_20M_{2024,2021}_4326.geojson`
  for `regions.json`
- `pipeline/mappings/{world.csv,trade_only.csv,countries.yaml,products.yaml,trade_items.csv,usda_countries.csv,comext_partners.csv}`

Outputs:

- `verify/recompute_report.json` contains `ok`, `n_mismatches`, `published_sha256` (the three
  exported files compared), the number of values compared per category, the
  mismatches by category, a `mismatch_summary` by (category, explanation), and up to 500
  mismatches (unexplained ones first). It also lists fields not recomputed and the sha256 of
  every input and of the three exported files.
- `verify/.cache/mismatches_full.json` is the uncapped mismatch list.

## What is compared

| Category | What |
|---|---|
| group_ratio, components, withheld | per country × group, tonnes: SSR, IDR, every `components_kt` value the export carries (also inside `withheld`), withheld reason, `uses_withheld` |
| group_ratio_kcal | kcal-basis SSR and IDR per group (`jrc_group_only` for JRC dairy) |
| all_food, per_person, population | protein and kcal share (capped) and ssr (uncapped), `g_per_day`, `per_day`, `n_foods`, `population_k` |
| trend | every point of every trend series, 2010–2023, including EU27 and "all" |
| item_ssr, item_supply, item_flag, item_set | every row of `items.json` |
| labels | `source`, `jrc_items`, region / europe / view |
| averages, claims, meta | `europe_avg`, `world_avg`, `claims.eu_intra_dairy_mt`, window, trend years, EU member list |
| withheld_null_ratios | every withheld balance has no tonnes or kcal ratio |
| withheld | group verdict (own figures + `parts_contradict`), `withheld.range`, kcal flag, `uses_withheld`, and that a `uses_withheld` group carries no uses |
| all_food_withheld | per basis: verdict, `range`, `share_range` (readings A and B); also `n_withheld` |
| usda_items, usda_values | per country × group, the `usda: [{item, fao, usda}]` array: which items, and both SSRs (methodology "FAO against USDA") |
| jrc_published_ssr | the JRC's own dairy ratio (methodology "The JRC's own ratio") |
| trade_total, trade_partner, trade_partner_set, trade_mirror | `trade.json` imports/exports: totals, every listed partner, "every partner ≥ 0.5% is listed", `meta.mirror` |
| trade_grown_* | "Grown in" (Kastner re-export tracing) totals and partners, recomputed in full |
| trade_consistency | partners sum to no more than the total; every listed partner ≥ 0.5%; at most 24 |

Tolerance: a value rounded to d decimals matches if |exported − recomputed| ≤ 0.6·10^-d +
1e-6·|recomputed|. A null on one side and a number on the other is a mismatch, so a ratio the
export leaves out but the recompute has (or the reverse) counts too.

**Alternative readings.** Where the spec is ambiguous, the script computes the primary reading
(below) and also the other plausible readings. A mismatch is never suppressed, but it gets an
`explained_by_alternative_reading` tag when another reading reproduces the exported value. Read
the tag as "the pipeline does X here"; whether X is acceptable is a separate judgement.

## Readings chosen where `docs/methodology.md` is ambiguous or silent

Settled by the spec and implemented as written: window averaging (divisor = window years with a
Population row; every missing component inside a published balance = 0; D never reported in the
window = missing, `supply_missing`), EU27 per-person weighting over the whole EU population, the
JRC edge rules (year not covered if production is missing or apparent use ≤ 0; not applied where
FAO's supply is missing or ≤ 0; negative JRC production clipped to 0), `jrc_published_ssr`
(window-mean RAW MILK production / window-mean apparent use × 100, when every window year has
both), "grown" keeping every origin, `food_exceeds_supply`, `parts_contradict` with "10% of
ssr_adj" for groups and "10% of B" for all food, `withheld.range` on every withheld group
(`[defined, null]` when one reading is undefined, null when neither is), `n_foods` = leaf items
with an SSR and protein > 0, `n_withheld` = items with protein > 0 and no SSR (absent when 0),
per-day totals over all leaf items, and `uses_withheld` (> 25% of D and > 1 kt).

Still open. *Alternative* marks a reading that is also computed and used to tag mismatches (the
alternatives now are the pipeline's earlier behaviours, kept to explain any regression):

1. **`withheld.range` "null".** The spec says `null` when neither reading is defined; the export
   leaves the key out (55 groups). Both read as null, so they count as equal.
2. **An explicit `n_withheld: 0`** would count as a mismatch, since the spec says the key is
   absent when 0.
3. **Flagged items in the parts test** are items with any problem, including `supply_missing`
   (D' = max(food, 0)). In reading B, an item whose max(D, food, 0) is 0 has no SSR and drops
   out.
4. **JRC dairy in all-food.** It counts as one food. If the JRC dairy balance itself fails a
   test, it counts once in `n_withheld` (when it carries protein) and is left out of reading B.
   Not reached by the current data.
5. **kcal flag on withheld groups.** Where the export has no `kcal` key at all, the withheld
   reason is not compared there; null ratios are still checked.
6. **USDA** follows the methodology's "Exact rules" as written: the 23 PSD↔FBS pairs, window
   sum / 3, the FAO side is the published window item balance, withheld FAO SSR gets no note, EU
   members not compared, use ≥ 50 kt on *either* source, 10% of the published group supply.
   (*Alternative* kept for regressions: use ≥ 50 kt on both.) The "Result" summary statistics
   are text in the doc, not exported, so they are not recomputed.
7. **JRC year coverage.** A year counts only if production is present and apparent use > 0
    (the edge rules).
8. **JRC series.** Tomatoes: the `TOMATOES` row, supply = P + M − X. Olive oil: `TOTAL OLIVE
    OIL`, supply = apparent use. Wine: `WINE`, hectolitres × 0.1. Dairy: production =
    `RAW MILK`; trade = milk-equivalent sum of DRINKING MILK, ACIDIFIED MILK, CREAM FOR DIRECT
    CONSUMPTION, BUTTERMILK, TOTAL BUTTER, TOTAL CHEESE, SKIMMED and WHOLE MILK POWDER, WHEY
    POWDER. The file has no separate bulk raw milk trade line, so it is taken to be inside
    drinking milk. Only uses are scaled with supply; FAO's per-person kcal and protein are kept.
    Dairy uses are scaled year by year, then averaged.
9. **EU27 extra-EU shares.** By product weight, over partners mapped to ISO3; fish from Comext in
    live weight over all partners (unnamed Q codes outside the EU except QR, QV, QY). Fallback
    order: member's all-food share, then 1.0. EU27 uses = members' sums × D_EU / ΣD_members per item
    and year.
10. **kcal-basis IDR** is not defined in the spec. It is computed like kcal SSR; unknown imports
    give null.
11. **Averages and claims** are not in the spec. `europe_avg` / `world_avg`: food kg per person
    = Σ food / Σ population; protein = population-weighted `g_per_day`.
    `claims.eu_intra_dairy_mt` = FAO members' dairy trade × (1 − extra-EU share), Mt. Both were
    fitted to the export, so they are weak checks.
12. **Trade.** "No report at all" = no tonnes row of any item for that country, flow and year.
    Yearly mean = window sum / 3. "Grown" tracing runs on window-mean matrices, using the
    published (JRC-adjusted) national P and M. Trade-only countries, and countries without a
    window balance, keep trade-matrix imports and P = 0. Fish partners: EU members' Comext rows
    (CN8 under 0301–0309, 1604, 1605, EUMOFA factor of that year or the nearest listed year; the
    earlier year on a tie), named partners only; no "grown"; "all" leaves fish out. Other
    countries' fish from BACI: live weight with the EU's Comext mix per HS 2017 code and year
    (all partners), else the median EUMOFA factor of CN8 codes starting with that code that
    year, else the nearest year (earlier on a tie), else 1; rows without quantity dropped.

## Not recomputed

Text fields (labels, notes, names, provenance in `meta.sources`), which `components_kt` keys are
present (only values are compared), and `countries.geojson`.
