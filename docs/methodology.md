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

**Implemented:** `compute.add_eu_bloc` adds a pseudo-country `EU27` (years with all 27 members).
Production, stock variation and the per-person elements are summed over members. Imports and
exports are the trade with non-members only, in FBS primary equivalents:

    M_EU = Σ_j M_j · s_imp,j      s_imp,j = share of member j's imports from outside the EU
    X_EU = Σ_j X_j · s_exp,j      s_exp,j = share of member j's exports to outside the EU
    D_EU = P_EU + M_EU − X_EU − ΔS_EU

The shares are per member, food group and year from the FAOSTAT trade matrix
(`trade.extra_eu_shares`, reported flows with mirror fallback; items outside the groups use the
member's all-food share). Uses (food, feed, …) are the members' sums scaled to D_EU. Fish, which
the trade matrix does not cover, keeps the members' sum with gross trade blanked.

Why not simply add up the members (as FAO's own "European Union (27)" area does): members report
buying far more from each other than they report selling to each other, so intra-EU trade does
not cancel. Dairy 2021–2023: members' imports 104.5 Mt, exports 77.8 Mt (milk equivalent), so the
sum makes the EU look like a net importer that uses 190.9 Mt from 165.9 Mt produced (SSR 87%).
With extra-EU trade it buys 5.3 Mt, sells 18.8 Mt and uses 150.6 Mt (SSR 110%). Cereals move from
101% to 105%, vegetables from 86% to 104%; meat and oilseeds barely change. With M_EU known, EU
import dependency (IDR) is now defined.

## Dairy for EU countries: DG AGRI–JRC balance sheets

FAO's milk-equivalent trade for dairy is unreliable for processing countries: Germany sells
cheese, milk powder and whey (net exporter by product weight) but FBS has it importing 4.3 Mt
milk equivalent net (SSR 89%); Ireland, which exports most of its milk, comes out at 105%. FAO's
own conversion factors (Technical Conversion Factors, 1990s) differ widely between countries
(whole milk powder 3.8 kg milk/kg in Germany, 8.3 in the Netherlands) and miss whey and skimmed
milk powder.

For EU members and the EU27, `pipeline/jrc.py` replaces the FBS dairy group with the DG AGRI–JRC
"EU estimated agricultural balance sheets" (Eurostat Comext trade, intra-EU imports taken as the
mirror of partners' exports, DG AGRI milk-equivalent coefficients on a milk-solids basis, so
products from the same milk add up: their production sums to the raw milk delivered):

    production = raw milk produced
    M, X       = Σ product imports / exports in milk equivalent (members: intra + extra EU;
                 EU27: extra-EU only) over drinking milk, acidified milk, cream, buttermilk,
                 total butter, total cheese, skimmed and whole milk powder, whey powder
    supply     = production + M − X          (no stock data)

The FBS dairy items are scaled so the group equals these totals (uses scaled with supply), which
carries the change into the protein and calorie totals. Luxembourg is not in the dataset and keeps
FAO's figures. 2021–2023 SSR, FAO → JRC: Germany 89 → 116%, Ireland 105 → 195%, Denmark 83 →
140%, Netherlands 78 → 113%, Italy 76 → 89%, EU27 110 → 114%. Germany's protein headline moves
from 92% to 100%.

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
version is reported as `*_ssr`:

    ssr_w = Σ_i w_i · SSR_i / Σ_i w_i

Livestock products count as domestic regardless of feed origin (feed adjustment is phase 4).

**Which one is the headline.** The UI leads with the uncapped protein figure (`protein_ssr`):
"does the country produce as much protein as its people eat?", letting a wheat or meat surplus
stand in for imported soy or fish. That is the closer answer to "could it feed itself", and coffee,
cocoa or bananas barely count because they carry almost no protein. The capped version is the
stricter "could it keep today's menu, food by food?" and is shown second (and on the "How do we
know?" page). With the cap only India reaches 100% (2021–2023); without it, 41 countries do.
Trend lines for "all food" use the uncapped figure too.

## "How long would it last?" (what the UI shows first)

The first figure readers see is a duration, not a ratio:

    months = min(p, 100) / 100 × 12

with p = uncapped protein SSR for "all food" and tonnes SSR for a single food. Text rounds to half
months ("about 10 months of the year"), switches to weeks below about 2 months and to "a few
days" below one week. Above 100% it says "the whole year, with N months to spare",
N = round((p − 100) / 100 × 12); from 200% "p/100 years". Map colours use the same bands (under
6 months, 6–9, 9–11, 11–12, the whole year, more than enough), so map and text always agree
(`web/src/calendar.js`).

A duration was chosen over a date ("runs out on 5 November", counting from 1 January) and over
"from today": both suggest a real starting point and invite questions about harvest timing that
the data cannot answer, and "from today" would change the wording daily on fixed averages. The
date is still shown on the "How do we know?" page as an alternative reading of the same share.

It is a thought experiment and the "How do we know?" page says so: a year's production treated
as one store, seasons and perishability ignored, the diet unchanged. It adds no information
beyond SSR, so the methodology above still applies unchanged.

## Trade partners (who buys from and sells to whom)

Source: FAOSTAT Detailed Trade Matrix (`pipeline/trade.py`), same 3-year window as the FBS
figures, yearly mean. Items are mapped to the food groups by CPC code in
`pipeline/mappings/trade_items.csv` (feed such as oilcakes, live animals, fibres, tobacco and nuts
other than groundnuts are left out). FAO's trade data has no fish.

- **Product weight, not primary equivalent.** A tonne of flour, juice or cheese counts as a tonne.
  Use it for partner shares within one group, never to compare with FBS totals.
- **Reporter first, mirror second.** A country's own import/export reports are used; for a
  country, flow and year with no report at all, partners' reports of the opposite flow are used
  instead (`source = mirror`; Russia, Belarus and small states). The UI says so.
- **Partners without a food balance** (Japan, Singapore, Benin…) are kept via
  `pipeline/mappings/trade_only.csv` (without them 4.7% of tonnes would be lost). Regions, income
  groups and historical areas would be dropped, but none appear in the 2021–2023 rows.
- **EU bloc:** members' trade with non-members only. This is the M_extra the eu_bloc view needs;
  EU-bloc IDR still waits for a primary-equivalent conversion.
- **Re-export hubs:** the Netherlands and Belgium show up as large suppliers of food they only
  transship (Rotterdam, Antwerp). The UI notes this when they are among the top five; no
  adjustment is applied.
- **Export file:** `trade.json` keeps, per country × group × flow, the total and every partner with
  at least 0.5% (at most 24), plus "all food" = all groups added up by weight.

## Where imports were grown (re-export tracing)

The trade view's "Grown in" switch follows imports back through transit and processing hubs
(`pipeline/trade.trace_origins`), with the proportional allocation of Kastner et al. (2011): every
country sells on an even mix of what it has, its own production plus its imports.

For one food group, with Z[i, j] the flow from i to j, P the production and x = max(P + imports,
exports) what each country has:

    A = Z / x          (row i divided by x_i)
    C = diag(P) · (I − A)⁻¹      C[k, i] = country k's production that ends up in i
    origin[k, j] = Σ_i C[k, i] / x_i · Z[i, j]

- Bilateral splits come from the trade matrix and are scaled to each importer's FBS import total,
  so production and trade are both in FBS primary equivalents. Trade-only countries (Japan,
  Singapore) keep trade-matrix totals and count as producing nothing.
- The importer itself is dropped from its own origins (re-imports).
- EU27: members' imports from non-members, traced back, non-EU origins only.
- It is an estimate: a hub does not really ship an even mix, and processing (cocoa to chocolate)
  is treated like repacking. The page says so.

Example, 2021–2023: Germany's coffee, cocoa and tea are bought 17% from the Netherlands and 11%
from Belgium, but traced back they were grown 23% in Brazil, 19% in Côte d'Ivoire and 13% in
Vietnam. Countries that grow most of what they sell (the US, Brazil) look the same either way.

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
