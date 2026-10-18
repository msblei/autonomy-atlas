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

### Withheld: balances that contradict themselves

`pipeline/checks.py` gives every balance (item, group, "all food"; window and single year) one
verdict, and every view obeys it. A withheld balance has no ratio, no per-person figures, no trend
point and no place in any ranking, map colour or comparison; the UI shows FAO's raw lines and
says why.

**Items and groups, on their own figures** (`checks.problems`, first match wins):

| Test | Reason | Why |
|---|---|---|
| D missing | `supply_missing` | nothing to divide by |
| D ≤ 0 | `supply_nonpositive` | negative use at home is impossible |
| X > (P + M − ΔS) × 1.02 + 1 kt | `exports_exceed_available` | more sold than there was |
| food > D × 1.25 + 1 kt | `food_exceeds_supply` | food is one of the uses of D; FAO closes the gap with a negative residual |

Not reasons: a very high SSR (Iceland catches about 20 times the fish it eats); a large residual
on its own (`uses_withheld`, below). Example: Jordan, eggs 2021–2023, P 81, M 3, X 114 kt, ΔS 0,
residuals −107 kt, D −30 kt. Before this rule the ratio was blank but the per-person ranking
still listed Jordan first with +10 kg "to spare". Ireland, beef 2016: P 588 kt, D 3 kt, ~50 kt
eaten (FAO's own food line): SSR 19 600%, which spiked Ireland's "all food" trend to 1474%.

**Withheld by review** (`reviewed`): a group listed in `pipeline/mappings/withheld_by_review.csv`
(iso3, group, date of the review, `note`) is withheld like a contradictory one, in the window and
in every single year, on both bases, although its balance adds up: only where a human review found
FAO's figure implausible for a reason a reader can check in FAO's own figures, written in `note`,
which the UI shows instead of the figure (and `ssr.json` carries as `withheld.note`). The group's
items keep their own figures (expert view), and "all food" is unchanged. Uruguay, pulses
2021–2023: 366 kt of "Pulses, Other" bought abroad a year, 361 kt of it fed to animals, against
about 10 kt eaten and 5 kt of pulses in the trade records: 2% self-sufficient on paper.

A withheld item has no SSR, so it drops out of the group kcal mean and "all food". JRC dairy is
judged as one balance: the `food` test is not applied to it (its P, M, X, D are the JRC's, the
food line FAO's), and its scaled items are not judged one by one.

**Groups that rest on contradictory items** (`checks.parts_sensitivity`, reason
`parts_contradict`). The tonnes group sums all its items, contradictory ones included (that is
FAO's total). It is also computed with each contradictory item's D raised to max(D, food, 0), the
least FAO's own figures say was used:

    ssr_pub = Σ P / Σ D                ssr_adj = Σ P / Σ D'     (D' = max(D, food, 0) for flagged items)

If |ssr_pub − ssr_adj| > max(10 points, 10% of ssr_adj), or one of them is undefined, the group's
ratios are withheld. `ssr_low` / `ssr_high` (min and max of the two) are exported as
`withheld.range` for every withheld group, whatever the reason; when one reading is undefined
(Σ D ≤ 0) the range is `[defined, null]`, and `null` when neither is; when both are ≥ 104.17 the UI says "on any reading of FAO's figures, X produces
more … than it uses", both < 99.5 "less". Ukraine, vegetable oils: sunflower oil's D is 125 kt
but 239 kt are eaten; the group is 1196% or 969% depending on the reading, so no number is shown,
but "more than it uses" is. Small contradictions do not withhold a group (Dutch offals in meat).

**"All food"** (`compute.overall`), per basis (protein, kcal) separately:

- `protein` g/day and `kcal` per day count every leaf item, withheld ones included (people eat
  them; only their ratio is unknown).
- `share` (capped) and `ssr` (uncapped) are weighted over the items with an SSR (reading A);
  `n_foods` counts the leaf items with an SSR **and** protein > 0 (those that carry weight in
  the protein figure the UI quotes), `n_withheld` the leaf items with protein > 0 but no SSR
  (absent from the export when 0).
- Reading B uses, for withheld items, SSR = P / max(D, food, 0). If A and B differ by more than
  max(10 points, 10% of B) in `share` or `ssr`, that basis is withheld (`parts_contradict`) with
  `withheld.range` (from `ssr`) and `withheld.share_range`. The protein verdict also withholds
  the "all" trend point of that year. 2021–2023: Uruguay, Paraguay and Ecuador protein (beef or
  oilseeds), six countries' kcal (e.g. Ukraine, through sunflower oil).

**Uses breakdown** (`uses_withheld`): |residuals| > 25% of D and > 1 kt. Only food, feed, seed,
losses, processing, other uses, tourist and residuals are left out of `components_kt`; the ratio
stands, because residuals sit on the utilisation side (D = food + … + residuals) and SSR uses only
the availability side.

2021–2023 counts: 95 group balances withheld (63 `supply_nonpositive`, 10 `food_exceeds_supply`,
22 `parts_contradict`), 20 uses breakdowns withheld, 3 protein and 6 kcal "all food" headlines.

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
the window, then compute ratios. The divisor is the number of window years the country reports
at all (its Population row; if D itself is never reported in the window, the balance is
missing, `supply_missing`, not zero), and inside a balance FAO publishes, a missing element counts as
zero in that year, for every component, not only P, M, X: a stock change reported in one year of
three is a third of it on average, not all of it (Afghanistan soybeans 2021–2023). Countries
that stopped reporting (Cuba after 2019, North Korea after 2018) have no window figures. Also keep the single latest year for users who want it; label it
as volatile.

## National vs EU-bloc view

- **national:** M includes imports from all partners, including other EU Member States. Needs only
  FBS.
- **eu_bloc:** treat EU27 as one reporter. For an EU member, M_extra = imports from non-EU partners
  only (from Comext/FAO trade matrix), and the denominator is EU-wide supply. For non-EU countries
  the two views are identical.

Always offer both. They answer different questions ("could France feed itself?" vs "could Europe?").

**Implemented:** `compute.add_eu_bloc` adds a pseudo-country `EU27` (years with all 27 members).
Production and stock variation are summed over members; the per-person elements (kcal, protein)
are population-weighted over **all** members (Σ value × population / EU population: a member
without an item eats none of it). Imports and
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

## EU countries: where the DG AGRI–JRC balance sheets replace FAO

`pipeline/jrc.py` reads the European Commission's DG AGRI–JRC "EU estimated agricultural balance
sheets" (Eurostat Comext trade with intra-EU imports taken as the mirror of partners' exports,
processed products converted back to the primary product with DG AGRI coefficients) and replaces
the FBS balance of selected items for EU members and the EU27. Members' trade = intra + extra EU;
EU27 = extra-EU only. The FBS items are scaled so they add up to the JRC production, imports,
exports and supply (uses scaled with supply; stock change = P + M − X − supply), which carries the
change into group totals and the protein and calorie headlines.

- **Edge rules.** A JRC year with production missing or apparent use ≤ 0 does not count as
  covered; a JRC year is not applied where FAO's supply for the food is missing or ≤ 0 (Estonia
  olive oil 2010, Malta 2020), since there are no items to scale. A negative JRC production
  (Luxembourg tomatoes 2019: −0.05 kt, rounding in the source) is clipped to 0.
- **The JRC's own ratio** (`jrc_published_ssr`, dairy only, shown next to ours): window mean of
  the RAW MILK row's production divided by the window mean of its apparent use (milk
  equivalent), × 100, when all window years have both. The dataset does not say how that
  apparent use is derived; it is not production + imports − exports of the dairy products.
- **One source per average.** The JRC replaces FAO in the 3-year window only for a country and
  food it covers in every year of it (`jrc.full_cover`); otherwise FAO stays the source for the
  whole window (Portugal's tomatoes 2021–2023: JRC has 2 of 3 years). Single-year trend points
  use the JRC wherever it has that year.
- **Dairy only as a whole.** The JRC dairy balance is one milk-equivalent total. FAO's dairy items
  (milk in milk equivalent, butter and cream in product weight) scaled to it are neither FAO's
  nor the JRC's figures (Ireland's scaled butter: 413 kt sold from 264 kt produced). So for JRC
  dairy: no per-product rows in the table (`jrc_group_only`), no kcal-basis ratio, and in "all
  food" the three items count as one food at the JRC group SSR, weighted by their summed protein
  and kcal (`compute.collapse_jrc_dairy`). This moved Ireland's calorie coverage from 154% to 99%
  and the Netherlands' from 130% to 118%; protein headlines moved by less than 3 points.
- **Cited where used.** Every row carries `source` (`fao_fbs`, `jrc_bal`, `fao_fbs+jrc_bal` for a
  group with one JRC item, `fao_fbs+fao_tm` for the EU27 bloc), computed from the rows the JRC
  actually replaced, and the UI cites from that.

**Comparison that decided it** (2021–2023, EU members + EU27, SSR in percentage points). Production
agrees almost everywhere (median JRC/FAO ratio 1.00); the differences are in trade and use.

| Food | Median gap | > 15 pp | Decision |
|---|---|---|---|
| Dairy (milk equivalent) | large | most | **JRC**: FAO's milk-equivalent trade turns cheese and powder exporters into importers. Germany 89 → 116%, Ireland 105 → 195%, Denmark 83 → 140%, Netherlands 78 → 113%, EU 110 → 114% |
| Tomatoes | 4 | 5 | **JRC**: paste exports not converted back (Italy uses 1.1 Mt in FAO, 19 kg/person; JRC 3.3 Mt). Italy 556 → 200%, Netherlands 64 → 144% |
| Olive oil | 0 | 6 | **JRC**: EU27 101 → 129% (our group-level extra-EU share does not fit olive oil), Portugal 238 → 379% |
| Wine | 9 | 6 | **JRC**: FAO's German production is a little over half (57%) of the 8.2 Mhl made; Germany 31 → 44%. Hectolitres × 0.1 = tonnes |
| Oilseeds | 1.5 | 6 (small markets) | FAO |
| Meat | 5 | 6 | FAO. The JRC converts meat products back to carcass weight and gets lower SSRs for big exporters (Denmark 316 vs 223%, Ireland 251 vs 191%); not clearly better, so kept FAO and noted here |
| Cereals | 6 | 7 | FAO: FBS includes stock changes, the JRC apparent use for cereals does not (marketing years July–June) |
| Apples | 4 | 5 | FAO: large gaps (Hungary 80 vs 190%, Poland 420 vs 319%) without a clear reason |
| Oranges | – | – | not comparable (JRC oranges only, FAO oranges and mandarins) |

Dairy is built from products in milk equivalent (DG AGRI coefficients, milk-solids basis, so
products from the same milk add up: their production sums to the raw milk delivered):
production = raw milk; trade = Σ over drinking milk (also bulk raw milk), acidified milk, cream,
buttermilk, total butter, total cheese, skimmed and whole milk powder, whey powder; supply =
P + M − X (no stock data). Tomatoes: supply = P + M − X. Olive oil and wine: supply = JRC apparent
use, which includes stock changes (marketing years Oct–Sep and Aug–Jul, labelled by start year).

Coverage: dairy 26 members (not Luxembourg) + EU27; tomatoes and olive oil all members; wine the
19 producing members. Countries or years outside the dataset keep FAO's figures. The UI cites the
Commission on the affected pages ("How do we know?").

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
29xx; where an aggregate shares a leaf's name the leaf is used, so "Miscellaneous" is 2899, not
2928 = 2899 + Infant food, which counted infant food twice), with w = protein (g/cap/day) or kcal/cap/day. Capping stops a wheat surplus from offsetting
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

- **Product weight, except where processing changes it a lot.** Partner shares count each
  shipment in the FBS basis of its group (`to_primary` in `trade_items.csv`; other items as
  traded: a tonne of flour or juice counts as a tonne).
  *Potatoes and roots, tomato products, coffee and cocoa products* in fresh, green or bean
  equivalent, with FAO's *Technical Conversion Factors for Agricultural Commodities*: the median
  extraction rate over the countries that list the product, factor = 100 / rate (dried cassava 4.0,
  cassava starch and tapioca 5.0, frozen potatoes 1.43, potato flour 5.0, tomato paste 3.85, tomato
  juice 1.33, roasted coffee 1.25, coffee extracts 3.03, cocoa paste 1.25). Cocoa butter and powder
  are joint products of the paste (each 1.25); chocolate is 470% of the cocoa paste it contains
  (0.27). Tea extracts and frozen or dried vegetables have no factor there and stay as traded.
  *Dairy* is counted in milk equivalent, the basis of its food balance, with the
  EU's own factors, derived from the DG AGRI–JRC balance sheets 2021–2023 as milk equivalent per
  tonne traded (cheese 3.58, butter 6.57, milk powders 7.57, cream 3.21, drinking milk 0.85,
  acidified milk 0.98); products the EU does not list take the factor of the closest product or an
  estimate, marked in the file. By weight, a country shipping liquid milk across a border looked
  like a large supplier and one selling cheese or powder like a small one: half the absolute
  change in partner shares was 14 points for the median country, and the largest supplier changed
  for 15 of 73 buyers (Germany's: the Netherlands 17% by weight, 28% in milk equivalent).
  The EU-bloc shares behind the balance figures (section "National vs EU-bloc view") stay in
  product weight, so no balance figure changes.
  *Checked, not converted:* fruit, meat and sugar move under 3 points (median) with typical
  factors (juice, boneless meat, refined sugar); cereals, oilseeds, pulses, oils, eggs, wine and
  beer are nearly all traded raw.
- **Reporter first, mirror second.** A country's own import/export reports are used; for a
  country, flow and year with no report at all, partners' reports of the opposite flow are used
  instead (`source = mirror`; Russia, Belarus and small states). A partner whose window mixes
  reported and mirror years is `mixed`; every country with any mirror or mixed flow is listed in
  `trade.json` `meta.mirror` and the UI says so. Gaps are filled per country, flow and year, not
  per food group: FAO publishes no zero rows, so a country that reports some food trade but none
  of one group may mean "none", and partners' figures are not put in its place.
- **Under-reported food groups.** Some countries keep single products out of their own reports
  (Australia 2021–2023: 110 kt of sugar exports in its own figures, 3,315 kt in its buyers'). For
  the partner lists only, per country, flow and food group over the window (in the partner
  lists' basis: product weight, dairy in milk equivalent): when partners report
  more than 3 times the figures above would use, and at least 20 kt a year, and their total is no
  more than 1.5 times the country's FBS flow for that group (`components_kt` as published, or
  `withheld.components_kt`; no limit for a country without a food balance), the partners' reports
  of the opposite flow replace them for that group (`source = mirror`, and the country is listed
  in `meta.mirror`). The last condition keeps trading hubs out: partners book cargo as coming from
  the United Arab Emirates or Switzerland that the balance shows never was theirs, and such a
  swap would only make the flow implausible (section "Trade records against the food balance"). The figures above compare that window total including the per-year mirror
  gaps already filled. The EU bloc is built from its members after this step. The extra-EU
  shares that the EU-bloc balance uses (section "National vs EU-bloc view") keep the per-year
  rule only, so no balance figure changes.
- **Derived totals are not mapped.** Item 30 "Rice; paddy (rice milled equivalent)" is FAO's sum
  of the other rice items converted to milled weight (checked row by row in the 2022 data);
  mapping it counted rice twice (EU27 cereal imports 1.9 Mt/year too high). `tests/test_trade.py`
  keeps any "…equivalent" item out.
- **"Grown in" shares** (re-export tracing): totals in FBS primary equivalents, splits by country
  in the trade records' basis (product weight; dairy in milk equivalent); `trade.json`
  `meta.basis` gives the basis per flow.
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

### Trade records against the food balance

Trade records (product weight; dairy in milk equivalent) and the FBS import or export total
(primary equivalent) are not the same number, but for one food group they stand in a typical
ratio: dried cassava and starch weigh far less than the fresh roots the balance counts, so trade
records for potatoes and roots are typically about 0.6 of the balance; for pulses or wine they
are about equal. A country far from its group's typical ratio has trade
records that do not describe its balance (transit cargo, misreported or mirrored flows).

For each flow (imports, exports), each food group except fish, and each country with a food
balance (not the EU27 bloc):

- `T` = the trade-records total in kt (window mean, the total published in `trade.json`);
  `B` = the FBS flow in kt as published (`components_kt`, with the JRC's figures where they replace
  FAO's; for a withheld balance, FAO's figure as listed in `withheld.components_kt`).
  A pair is compared when `B > 0` and `B > 20` or `T > 20`.
- `r = T / B`; the group's typical ratio `m` is the median of `r` over all compared countries of
  that group and flow.
- **Warning** (`trade_vs_fbs`) when `r > 3m` or `r < m / 3`.
- **Withheld** (`trade_withheld`) when `r > 3m` **and** `r > 1.5`: the trade records are far above
  what is usual for the food **and** larger than the balance itself by more than half, which
  processing cannot explain (processed food weighs less than what it is made from). Saint Lucia
  2021–2023: 449 kt of sugar in the trade records for a balance of 14 kt.
- **All food** uses the same rule with `T` = the all-food trade total and `B` = the sum of the
  groups' FBS flows (fish excluded, as trade has none), with its own median.

A withheld flow is not published: `imports` withholds that country's `imports` and `grown` entries
for the group, `exports` its `exports` entry. `trade.json` `meta.withheld` lists each as
`[iso3, group, flow, T, B]` (kt, rounded to whole kt), and the UI says so where the partners would
be. The balance figures themselves (bought and sold in the FBS) are unaffected; for all food,
whose bought and sold totals come from the trade records, those totals are withheld with it.
Other countries' flows with the withheld country as partner are their own records and stay.

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

**Unusual years.** A year whose value is more than 3 times, or less than a third of, both the year
before and the year after (all three values present and at least 5%) is far more likely an error
in FAO's figures than a real harvest: Türkiye's coffee, cocoa and tea 2017 is 292% between 63%
and 58%. Such years stay in the series but are listed per country and group in `ssr.json`
`countries[iso3].trend_unusual` (`{group: [year, …]}`); the chart draws them apart (hollow, not on
the line, not used for its scale or labels) and names them. The same rule raises the
`trend_spike` warning.

## Scenario "without trade" (considered, not built)

With all trade stopped a country keeps its production, so "available without trade" per person is
just production per person — the SSR view already shows it. A useful scenario needs feed origin
(phase 4) or partner-level trade to remove specific suppliers such as RU/UA (phase 2).

## FAO against USDA

`pipeline/usda.py` compares FBS items with USDA's Production, Supply and Distribution database,
compiled independently of FAO (attachés, national statistics, customs data). For 23 commodities
(cereals, oilseeds, vegetable oils, centrifugal sugar, beef, pork, chicken, butter, green coffee
at 0.06 t per 60 kg bag) and every country in both, over the same window: PSD market year y is
set against calendar year y; PSD domestic consumption (sugar: total disappearance) against FBS
domestic supply; SSR = production / domestic use × 100 on both sides. EU members appear in PSD
only as "European Union" (extra-EU trade), compared with our EU27 bloc. PSD country names map to
ISO3 through `pipeline/mappings/usda_countries.csv` (empty = not compared).

**Result, 2021–2023** (pairs where both SSRs exist and USDA's domestic use ≥ 50 kt): 977 pairs; median gap
2.8 points; 60% within 5, 75% within 10, 87% within 20 points (weighted by consumption: 82% within
10, 92% within 20). Production agrees (median ratio FAO/USDA 1.00): the gaps are in domestic use
(in 80% of gaps > 20 points the use differs more than production), so they are largest for
exporters that use little of what they produce. Commodities agreeing best: wheat, rice, palm
oil, coffee, beef (median gap ≤ 2 points); least: barley, oats, rye, olive oil, rapeseed and
soybean oil (5–7 points). Examples of large gaps:

- Turkey, wheat: FAO 61%, USDA 92%. FAO counts 14–16 Mt a year fed to animals and 32 Mt of use;
  USDA 20 Mt of use in total. Turkey, sugar: FAO 118%, USDA 91%, so the sources disagree on
  whether Turkey has a surplus.
- Norway, wheat: FAO 8%, USDA 48%. FAO's 2.6 Mt of "other uses" is most likely wheat gluten
  for fish feed converted back to grain; USDA counts grain only. Both right by their definitions.
- Ukraine maize 447% vs 553%, Russia sunflower oil 178% vs 263%: small differences in domestic use
  of a large export.

**Exact rules.** PSD commodities and the FBS item each is compared with: Wheat, Corn (Maize),
Rice Milled, Barley, Rye, Oats, Sorghum, Millet (each "… and products"); Oilseed Soybean
(Soyabeans), Oilseed Rapeseed (Rape and Mustardseed), Oilseed Sunflowerseed (Sunflower seed),
Oilseed Peanut (Groundnuts); Oil Soybean, Oil Sunflowerseed, Oil Rapeseed (Rape and Mustard
Oil), Oil Palm, Oil Olive; Sugar Centrifugal (Sugar (Raw Equivalent)); Meat Beef and Veal (Bovine
Meat), Meat Swine (Pigmeat), Meat Chicken (Poultry Meat; not "Poultry, Meat, Broiler"); Dairy
Butter (Butter, Ghee); Coffee Green (Coffee and products). PSD values are summed over market
years 2021–2023 and divided by 3 (a missing year counts as 0), then the ratio is taken. The FAO
side is the published window item balance (after JRC replacement); an item whose FAO SSR is
withheld gets no note. EU members are not compared (PSD has none for these commodities);
"European Union" is compared with our EU27. The use threshold (≥ 50 kt) applies to **either**
source's domestic use: a pair where one source sees 86 kt used and the other 14 kt (Papua New
Guinea palm oil) is exactly a disagreement worth showing. The 10% test divides the item's FAO
domestic supply by the sum over the group's items (the published group supply).

**Use.** Nothing is replaced. Pairs with |gap| > max(20 points, 20% of the smaller SSR) and use
≥ 50 kt (either source) are `usda_gap` findings in `atlas validate`. When such an item carries
≥ 10% of its group's domestic supply, **or** could move the group's figure by 5 points or more
(its share of the group's domestic supply × |gap| ≥ 5; Uruguay's rice is 4% of its cereals but
FAO and USDA are 1,015 points apart), the export adds `usda: [{item, fao, usda}]` to the group
and the food page and "How do we know?" say that another source disagrees, with both figures,
and note when the two fall on different sides of 100%. A pair below both thresholds cannot move
the group's figure by 5 points and is listed on the audit page as handled.

## Checks: how a published number is known to be right

`make verify` runs every layer; any failure stops a release, and `npm run build`
(`web/scripts/check-data.mjs`) refuses to build data that did not pass. What each layer catches:

| Layer | Where | Catches |
|---|---|---|
| Raw files pinned | `pipeline/manifest.py`, `data/raw/manifest.json` | a raw file replaced by hand; build refuses until re-recorded (`atlas download` / `atlas manifest`) |
| Raw shape | `manifest.check_fbs_shape`, `harmonise._check_areas` | renamed elements, unexpected units (all quantities `1000 t`), unknown flags, duplicate rows, an FAO area neither mapped nor a known aggregate |
| Stale outputs | `config.require_fresh` | an interim or processed file older than a mapping or input it was built from |
| Consistency verdicts | `pipeline/checks.py` (section "Withheld") | balances that contradict themselves; withheld everywhere, explained in the UI |
| Invariants | `pipeline/validate.py` → `validation.json` | identity P + M − X − ΔS = D on rows we build (exactly) and on FAO's (warning only beyond its rounding: each figure of each item is rounded to 1 kt, so a group of n items may miss by n × 2.5 kt); group = sum of items; EU27 production = members' sum and = FAO's own EU27 row item by item (within FAO's rounding); extra-EU trade ≤ members' total; our JRC-based ratio = the JRC's own for tomatoes, olive oil, wine; exported ratio = exported components; withheld figures carry nothing usable; trade partners ≤ total; no self-trade. Warnings for review: very high SSRs, unusual years in trends, trade records more than 3× from their food group's typical ratio to the balance (section "Trade records against the food balance"; far above it and above the balance: withheld), JRC dairy vs the JRC's own ratio, negative-supply items in groups |
| FAOSTAT live sample | `tests/golden/`, `tests/test_golden.py` | 1,695 three-year totals (20 countries × 23 items × P/M/X/D, population, kcal, protein) read from FAOSTAT's website in a browser; harmonised data and window averages must equal them. A wrong M49 → ISO3 line fails it (tested: Brazil/USA swapped, 187 values off) |
| Known facts | `tests/test_real_data.py` | France poultry < 100% and EU > 100%, EU soybeans 10–30%, NL a cereal hub, JRC replacements in place, Jordan eggs and Ukraine oils withheld, Iceland fish not |
| Independent recomputation | `verify/recompute.py` | written from this document alone, without reading `pipeline/`; recomputes every published number (≈250,000) from the raw files and must agree on all of them. Its first run found three pipeline bugs (EU27 per-person population, window averaging, EU27 fish kcal IDR) |
| What the page shows | `web/tests/*.spec.js` (Playwright, installed Chrome) | headline and food-page wording = `calendar.js` of the exported figure; receipt sum = exported ratio; rankings never include a withheld figure and equal the data's top five; no factual figure typed into `main.js` |
| Second source | `pipeline/usda.py` (section "FAO against USDA") | FAO figures far from USDA's for the same country and commodity: warnings, and a note on the page |
| Human review | `atlas report` → `data/processed/audit.html` | every withheld figure and warning, and the 50 largest changes since the last release (`atlas release-snapshot` after publishing). A warning ends one of three ways: **handled** when the site deals with it by itself (`validate.resolve`: unusual years drawn apart; the JRC's own dairy ratio shown next to ours; negative-supply items kept within the withholding threshold by the parts test; a USDA disagreement shown on the page or too small to move the group's figure by 5 points; trade records under half of the balance, which the trade page then says); **confirmed** when a review found it right, with the reason and date in `pipeline/mappings/confirmed_findings.csv`; or fixed or withheld (by a rule or by review). A release should have no open warnings |

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
