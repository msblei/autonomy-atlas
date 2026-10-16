# Methodology

## Indicators

All quantities below come from FAO Food Balance Sheets (FBS) unless stated otherwise, in
1000 tonnes per year, per country × item.

| Symbol | FBS element | Notes |
|---|---|---|
| P | Production | |
| M | Import quantity | |
| X | Export quantity | |
| ΔS | Stock Variation | positive = stock build |
| D | Domestic supply quantity | FBS computes D = P + M − X − ΔS (sign convention varies; use the FBS value, don't recompute) |
| F | Feed | |
| kcal | Food supply (kcal/capita/day) | per item |

**Self-sufficiency ratio** (FAO convention):

    SSR = P / D × 100

**Import dependency ratio**:

    IDR = M / D × 100

Both are per country, per item (or product group), per year. Note SSR + IDR ≠ 100 in general
because of exports and stock changes.

**Simple variants** that ignore stocks, used when D is unavailable or ≤ 0:

    SSR_simple = P / (P + M − X) × 100

Values of D ≤ 0 happen (a country exports a product it barely consumes). Return NaN and flag
`supply_nonpositive`; never clip to 0 or 100 silently.

## Aggregation to product groups

Group definitions: `pipeline/mappings/products.yaml`.

- **Tonnes basis:** sum P, M, X, D across items in the group, then compute SSR/IDR from the sums.
- **kcal basis:** compute SSR per item, then weight by each item's kcal/capita/day within the
  group: SSR_kcal = Σ(SSR_i × kcal_i) / Σ kcal_i.
- **Value basis** (phase 2+): weight by import or supply value from trade data at current prices.

Report the basis in every output row. Do not show a tonnes figure next to a kcal figure in one
chart without saying so.

## Time averaging

Default window = latest three available FBS years. Average the components (P, M, X, D, kcal) over
the window, then compute ratios. Also keep the single latest year for users who want it; label it
as volatile.

## National vs EU-bloc view

- **national:** M includes imports from all partners, including other EU Member States. Needs only
  FBS.
- **eu_bloc:** treat EU27 as one reporter. For an EU member, M_extra = imports from non-EU partners
  only (from Comext/FAO trade matrix), and the denominator is EU-wide supply. For non-EU countries
  the two views are identical.

Always offer both. They answer different questions ("could France feed itself?" vs "could Europe?").

**Implemented now (FBS only):** `compute.add_eu_bloc` adds a pseudo-country `EU27` by summing all
27 members per item and year (years with a missing member are skipped). Intra-EU trade appears in
both members' imports and exports, so it cancels out of D = P + M − X − ΔS: EU-wide SSR, per-person
figures and net trade are valid. Gross M and X are blanked, so EU-bloc IDR stays NaN until
partner-level trade (phase 2) gives M_extra. FAO's own "European Union (27)" area (M49 097) is the
same plain sum of members (checked 2022: wheat imports 71 Mt, overwhelmingly intra-EU), so it has
the same limitation.

## Per-person figures

kg/person/year = component (1000 t) × 1000 / population (1000 persons). Population is FBS item
2501 "Population", element "Total Population - Both sexes", from the same file and window. "Food"
in FBS is food available for consumption (incl. household waste), not intake.

Utilisation of domestic supply: food, feed, seed, losses, processing (turned into another FBS
item, e.g. barley → beer, soybeans → oil + cake), other uses (non-food: biofuel, industry),
tourist consumption, residuals (balancing term, can be negative).

## "All food" coverage

    coverage_w = Σ_i w_i · min(SSR_i, 100) / Σ_i w_i

over FBS leaf items (item code < 2900, Population excluded; FAO aggregates like "Grand Total" are
29xx), with w = protein (g/cap/day) or kcal/cap/day. Capping stops a wheat surplus from offsetting
a soy deficit; read it as "share of what people eat that own production could cover". The uncapped
version is reported as `*_ssr`. Livestock products count as domestic regardless of feed origin
(feed adjustment is phase 4).

## Running-out day (what the UI shows first)

The first figure readers see is a date, not a ratio:

    days = min(p, 100) / 100 × 365,   last day with food = 1 January + days − 1

with p = protein coverage for "all food" and tonnes SSR for a single food. Above 100% the UI says
"the whole year, with N months to spare", N = round((p − 100) / 100 × 12); from 200% it says
"p/100 years". Map colours use the same date bands (before July, July–September,
October–November, December, whole year, more than enough), so map and text always agree
(`web/src/calendar.js`).

It is a thought experiment and the "How do we know?" page says so: stores spread evenly over the
year, seasons and perishability ignored, the diet stays the same. It adds no information beyond
SSR, so the methodology above still applies unchanged.

## Trends

`ssr_trends.parquet` holds single-year values (tonnes SSR per group, protein coverage for "all")
for 2010 onwards. Single years are volatile (droughts: DE cereals 2018 = 91%); the headline
figures stay 3-year averages.

## Scenario "without trade" (considered, not built)

With all trade stopped a country keeps its production, so "available without trade" per person is
just production per person — the SSR view already shows it. A useful scenario needs feed origin
(phase 4) or partner-level trade to remove specific suppliers such as RU/UA (phase 2).

## Pitfalls checklist

Tick these off before publishing any indicator.

- [ ] **Re-exports (Rotterdam/Antwerp effect).** Raw trade data assigns transit goods to NL/BE.
      FBS already nets exports out of supply, which helps. For partner shares, prefer BACI or FAO
      trade matrix over raw Comext imports, and consider the Trase-style re-export adjustment for
      cocoa, coffee, soy, fruit.
- [ ] **Intra-EU vs extra-EU.** See above. Never report a single "dependence" number without the
      view label.
- [ ] **Mirror discrepancies.** Importer CIF ≠ exporter FOB; RU/BY reporting degraded since 2022.
      Use BACI (reconciled) or FAO TM; record which was used in `source`.
- [ ] **Aggregation hides structure.** "Fruit" mixes apples (high SSR in the north) with bananas and
      citrus (zero). Always allow drill-down to items.
- [ ] **Feed vs food.** Meat/dairy SSR > 100% can coexist with ~15% soy self-sufficiency. Phase 4
      adds a feed-adjusted SSR: subtract the imported-feed share of livestock output.
- [ ] **Basis.** Tonnes overweight cereals and milk; value overweights wine, cheese, coffee; kcal
      overweights cereals, oils, sugar.
- [ ] **Processed vs primary.** FBS is already in primary equivalents. HS trade is not — flour, oil
      cake, meat preparations need conversion factors (FAO technical conversion factors) before
      being compared with FBS.
- [ ] **Volatility.** Droughts swing SSR by tens of points (2022, 2025 summer crops). Default to
      3-year averages.
- [ ] **Series breaks.** FBS old vs new methodology (2010/2014); Eurostat SAIO regulation from
      reference year 2025; NUTS 2021 → 2024; HS 2017 → 2022; FAOSTAT area renames (join on M49).
- [ ] **Ukraine 2022–2025.** Ukrstat suspended most releases from April 2023, resumed mandatory
      reporting July 2025 and has been backfilling since December 2025. Figures exclude occupied
      territories. Mark as provisional and cross-check with FAO, USDA PSD and JRC MARS.
- [ ] **Kosovo** is absent or merged into Serbia in FAO data. Note it on the map rather than leaving
      a silent hole.
- [ ] **Licensing.** GISCO boundaries are non-commercial; Comtrade extracts may not be
      redistributed; BACI requires citing CEPII.
