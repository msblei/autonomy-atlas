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

### Withheld as implausible: balances that add up but cannot be right

A balance can add up and still describe more food than a country could use. Two cases found in a
pre-release review (2026-10-18): New Zealand "using" 1.9 t of milk a person a year (fixed at the
source: section "Dairy in milk equivalent"), and the United States buying 51 Mt of fruit a year
where the trade records hold 19 Mt: FAO books 2.05 Mt of "apple juice, concentrated" (2022) and
converts it into about 14 Mt of apples, 54 kg a person against the 18–20 kg the USDA counts. The
consistency tests above cannot see this, so `pipeline/plausible.py` (`checks.plausibility`)
reads every shown group figure (tonnes, 2021–2023, countries of 500,000 people or more) a second
way:

| Test | Second reading | Why |
|---|---|---|
| `use_per_person`: D per person above a ceiling (kg/year: dairy 550 in milk equivalent, meat 150, eggs 30, fish 120, fruit 250, vegetables 300, pulses 60, wine and beer 200) | D = ceiling × population | no national average is known above these; cereals, oilseeds, oils, sugar, roots and stimulants have none (feed, crushing, biofuel, distilling) |
| `imports_vs_trade`: imports more than 1.5× the group's typical ratio to the trade records (median over countries; both ≥ 50 kt) | M = trade records × typical ratio, D lowered by the difference | the balance counts primary equivalents, the records product weight, so each group has its own usual ratio; far above it, the balance describes conversions or flows the records do not hold |

The trade records are the yearly partner flows of section "Trade partners" (FAO trade matrix,
fish from Comext and BACI) for the same window. A figure is withheld (`implausible`) when a second
reading moves its SSR by more than max(10 points, 10% of the second reading), the threshold of the
parts test, or leaves no use at home: in the window and in every single year, on both bases, like
a figure withheld by review. `withheld.range` is the published and the second readings (lowest,
highest; no upper end when a reading leaves no use at home), so the UI can still say "more" or
"less than it uses" when all agree, and `withheld.plausibility` lists each reading with the
figures the text quotes (kg a person and the ceiling; the records' kt, the ratio and the typical
ratio). As for a figure withheld by review, the group's items keep their own figures and "all
food" uses the published reading (dairy, which counts there as one food, too).

`atlas build` runs the test after the trade partners exist, writes
`data/processed/plausibility.parquet`, then computes the balances again with its verdicts; the
test reads a figure it withheld before like any other, so a second run gives the same verdicts.

Examples, 2021–2023 (published → second reading): Germany vegetables 24% → 35% (the Federal
Office for Agriculture, BLE, has about 36%); United Kingdom vegetables 20% → 32%, dairy 75% →
90% (Defra about 90%); Turkey cereals 67% → 86% (USDA 92% for wheat); United States fruit 31% →
55%; Ireland dairy 195% → 319%, the Netherlands 113% → 147% and Denmark 140% → 175% (the
Commission's dairy balance leaves out infant formula, casein and milk protein concentrates, which
these countries export, so too little leaves the country and their use at home reaches 700–900 kg
a person); Norway fish 248% → 574% (FAO counts 1.2 Mt of fish fed to farmed salmon as used).

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

2021–2023 counts: 183 group balances withheld (63 `supply_nonpositive`, 11 `food_exceeds_supply`,
22 `parts_contradict`, 82 `implausible`, 5 `reviewed`), 20 uses breakdowns withheld, 3 protein and 6 kcal "all food" headlines.

## Aggregation to product groups

Group definitions: `pipeline/mappings/products.yaml`.

- **Tonnes basis:** sum P, M, X, D across items in the group, then compute SSR/IDR from the sums.
  Dairy is in milk equivalent (below).
- **kcal basis:** compute SSR per item, then weight by each item's kcal/capita/day within the
  group: SSR_kcal = Σ(SSR_i × kcal_i) / Σ kcal_i.
- **Value basis** (phase 2+): weight by import or supply value from trade data at current prices.

Report the basis in every output row. Do not show a tonnes figure next to a kcal figure in one
chart without saying so.

### Dairy in milk equivalent

FAO's "Milk - Excluding Butter" is in milk equivalent and its "Processing" line is the milk
churned into butter and cream, which are separate items in product weight. Summed as they are,
a butter exporter keeps the milk of the butter it sells abroad in its own use: New Zealand's
"use at home" was 9.8 Mt, 9.0 Mt of it that milk, 1.9 t a person (SSR 224%). So the dairy group
(`compute.dairy_milk_equivalent`, FAO dairy only; the JRC's is milk equivalent already) counts
butter and cream as the milk they are made from:

    f = milk Processing / (butter + cream Production)      per country and window
    butter, cream:  production 0; imports, exports, stock change, supply and uses × f
    milk:           supply and processing − f × (butter + cream Production)

f is the country's own ratio (median 17.5 t of milk per t of butter and cream, 2021–2023; New
Zealand 14.6, Ireland 20.6, United States 22.1), clipped to 5–30, and 17.5 where no butter or
cream is made. P + M − X − ΔS = D holds exactly for any f, since the milk's production is the
group's. New Zealand: 1,669% (250 kg used a person); Belarus 142 → 179%, Uruguay 153 → 184%.
Only the tonnes basis is converted: the parts test judges each item on FAO's own rows (a butter
row with its production moved to the milk would otherwise "sell more than it has") and then
raises a flagged item's converted D to max(D, food, 0); the kcal basis weights FAO's own item
ratios, and the table of items keeps FAO's product rows. In "all food" a country's dairy counts
as one food at the tonnes ratio (`compute.collapse_dairy`, as for the JRC's dairy below).

Tried and not used for EU members: the same conversion on FAO's figures puts Germany's use at
438 kg of milk a person and the Netherlands' at 906 kg (FAO's milk-equivalent trade in cheese and
powders, section "EU countries"), against 337 and 716 kg with the JRC; the JRC stays.

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
member's all-food share). Fruit and meat have shares per FBS item (`fbs_item` in
`mappings/trade_items.csv`, from the members' own reports; key `item:<FBS item>`), because one
share does not fit them all: almost every banana comes from outside the EU, most apples from
inside. With the fruit group's share the EU used 3.7 Mt of bananas a year, against 5.8 Mt in FAO's
own sum of the members. Uses (food, feed, …) are the members' sums scaled to D_EU. Fish, which
the trade matrix does not cover, takes its shares from Eurostat Comext (section "Comext": live
weight, per member, flow and year).

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
- **The JRC's raw-milk ratio** (not shown since 2026-10-18). The RAW MILK row has a
  "Self sufficiency" ratio, production over its "apparent use", but no trade columns, and that
  use is raw milk not delivered to dairies, not dairy use: Latvia 107 kt, 57 kg a person
  (2021–2023), against 975 kt produced, so "8 times self-sufficient". It used to be shown next to
  ours as "the Commission's own dairy ratio" (Latvia 914%, Slovenia 344%); it measures something
  else and is no longer exported or compared.
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
  group with one JRC item, `fao_fbs+fao_tm` for the EU27 bloc, `fao_fbs+eurostat_comext` for its fish,
  `fao_fbs+fao_tm+eurostat_comext` for its all food), computed from the rows the JRC
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

Livestock products count as domestic regardless of feed origin; section "Feed" shows meat and
eggs counting pigs and poultry only for home-grown feed, next to the figures here.

**Feed-adjusted, the headline.** Livestock products above count as home-grown whatever the
animals ate. The headline takes section "Feed"'s imported share of feed protein `f` (per country;
the EU as one) off pigs and poultry, as section "Feed" does for the meat and egg groups: for the
leaf items Pigmeat, Poultry Meat and Eggs, `SSR_i' = (1 − f) · SSR_i`, every other item
unchanged, then the same two weighted means over the same items:

    feed_ssr_w   = Σ_i w_i · SSR_i' / Σ_i w_i
    feed_share_w = Σ_i w_i · min(SSR_i', 100) / Σ_i w_i

Cattle, sheep, goats and milk are not adjusted (section "Feed": grass and hay are not traded, so
a concentrate-only share would overstate their dependence; dairy cows' concentrate feed is a
known gap this leaves). A withheld "all food" figure (`*_flag`) has no feed-adjusted figure. A
country without feed records in FAO's accounts has none either. Exported as `feed_ssr` and
`feed_share` next to `ssr` and `share` for both bases.

**The calorie balance** (the four rows of the "All food" card), per person a day, over the same
items: each food's calories split by the shares of its use that are produced, bought and sold.

    used     = Σ_i k_i                          (k = kcal/cap/day; = kcal_den)
    produced = feed_ssr_kcal × used / 100        (Σ_i k_i · SSR_i' / 100)
    imports  = Σ_i k_i · M_i / D_i  +  Σ_{pigs, poultry, eggs} k_i · f · SSR_i / 100
    exports  = Σ_i k_i · X_i / D_i

Dairy as one food uses its group's milk-equivalent M, X and D. The calories of pork, chicken and
eggs raised on imported feed count as bought abroad, so produced + imports − exports = used up to
stock changes. A hub that moves much more than it uses (Netherlands) buys and sells several times
the calories it uses: that is its balance, not an error. Exported as `kcal.balance`
`{produced, imports, exports, used}`, whole kcal; absent where the headline is withheld.

Without the adjustment, imported soybean meal hardly counts: it enters the weights only through
the soy that people eat, while the meat made from it counts in full. The Netherlands came out at
122% of its protein, Denmark at 182%, Germany at 100%.

**Which one is the headline.** The UI leads with the feed-adjusted, uncapped **calorie** figure
(`kcal.feed_ssr`): "does the country produce as many calories as its people use, counting meat
and eggs only for home-grown feed?", letting a wheat surplus stand in for imported fruit. Calories,
because that is how FAO, national statistics (Switzerland, Japan) and the JRC measure food
self-sufficiency, and because energy, not protein, is what a diet runs short of first in Europe,
where people get about twice the protein they need. A protein weighting also hid vegetable oil
almost entirely (India: 99.5% of its protein, while it imports over half its edible oil). The
protein figures stay on "All the numbers". The capped version (`kcal.feed_share`, "could it keep
today's menu, food by food?") is on "All the numbers" only: two figures for nearly the same
question confused readers (2026-10-18), and the capped one answers a different question (it marks a
country down for coffee it cannot grow, and it cannot exceed 100%). Trend
lines for "all food" (not shown in the UI) stay the unadjusted protein figure: feed shares exist
for the window only.

## "How long would it last?" (what the UI shows first)

The first figure readers see is a duration, not a ratio:

    months = min(p, 100) / 100 × 12

with p = feed-adjusted uncapped kcal SSR (`kcal.feed_ssr`) for "all food" and tonnes SSR for a single food. Text rounds to half
months ("about 10 months of the year"), switches to weeks below about 2 months and to "a few
days" below one week. Above 100% it says "the whole year, with N months to spare",
N = round((p − 100) / 100 × 12); from 200% "p/100 years". Map colours use the same bands (under
6 months, 6–9, 9–11, 11–12, the whole year, more than enough), so map and text always agree
(`web/src/calendar.js`).

**Comparisons between countries** ("How does … compare?", "Runs out soonest", "Lasts longest")
use the headline (`kcal.feed_ssr`), so the map, the tooltip and the lists show one figure. Sugar
exporters lead the list (Eswatini, Belize): in calories that is what their land produces. (With
the earlier protein headline a fish surplus put Iceland first, which is why the lists then used the
capped figure.)

A duration was chosen over a date ("runs out on 5 November", counting from 1 January) and over
"from today": both suggest a real starting point and invite questions about harvest timing that
the data cannot answer, and "from today" would change the wording daily on fixed averages. The
date is still shown on the "How do we know?" page as an alternative reading of the same share.

It is a thought experiment and the "How do we know?" page says so: a year's production treated
as one store, seasons and perishability ignored, the diet unchanged. It adds no information
beyond SSR, so the methodology above still applies unchanged.

## National statistics where FAO has no balance

FAO publishes no food balance for some countries, Japan among them. Instead of a blank, the map and
the country page show the country's own figure for "all food" where it is on the headline's basis
(calories) and counts livestock only for home-grown feed, as the headline does:
`mappings/national_stats.csv`, one row per country with the official yearly figures for the
window's years and their mean. Japan: MAFF's calorie-based food self-sufficiency ratio, fiscal
2021–2023, 38% in each (MAFF counts cattle and milk for home-grown feed too, which the headline
here does not, so it is somewhat stricter). It is never ranked against FAO-based countries and
carries no food-by-food figures. Exported as `ssr.json` `meta.national`.

## Withheld foods on the map

A withheld food (sections "Withheld") has no figure, but its two readings (`withheld.range`) can
agree on the map's band: both at or above 104.17% (more than a year) or both under 50% (under
six months). The map and the country's food list then show that band, in words ("more than a
year on any reading of FAO's figures"), never a number; rankings still leave the food out.
Single foods only: the "all food" range is not feed-adjusted.

## Trade partners (who buys from and sells to whom)

Source: FAOSTAT Detailed Trade Matrix (`pipeline/trade.py`), same 3-year window as the FBS
figures, yearly mean. Items are mapped to the food groups by CPC code in
`pipeline/mappings/trade_items.csv` (feed such as oilcakes, live animals, fibres, tobacco and nuts
other than groundnuts are left out). FAO's trade data has no fish: fish partners come from
Eurostat Comext for EU members and the EU bloc (section "Comext"), and from CEPII BACI for every
other country (section "BACI").

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
- **Shares shown with the list:** for EU members, the share from (or to, or grown in) other EU
  countries; for imports, the share from (or grown in) Russia and Ukraine, the supply most at risk
  since 2022. Both add up the listed partners (at least 0.5% each), so they are slightly low
  bounds, and are shown from 1%.
- **Concentration (HHI):** per country × group × flow (imports, exports; "all food" too), the
  Herfindahl–Hirschman index of the partner shares in percent, over **all** partners (not only the
  listed ones), in the partner lists' basis: HHI = Σ (100 × tᵢ / Σt)², rounded to a whole number;
  10,000 = one partner, under about 1,500 = spread out. `trade.json` `concentration`
  `{iso3: {group: {imports, exports}}}`; withheld flows have none. Shown on "All the numbers".
- **Re-export hubs:** the Netherlands and Belgium show up as large suppliers of food they only
  transship (Rotterdam, Antwerp). The UI notes this when they are among the top five; no
  adjustment is applied.
- **Export file:** `trade.json` keeps, per country × group × flow, the total and every partner with
  at least 0.5% (at most 24), plus "all food" = all groups added up by weight as shipped, fish
  excluded (fish is counted in live weight, from other sources). `meta.group_source` names the
  source per group where it is not the trade matrix (fish: Comext for the EU, BACI elsewhere),
  `meta.basis` the fish basis.

### Trade records against the food balance

Trade records (product weight; dairy in milk equivalent) and the FBS import or export total
(primary equivalent) are not the same number, but for one food group they stand in a typical
ratio: dried cassava and starch weigh far less than the fresh roots the balance counts, so trade
records for potatoes and roots are typically about 0.6 of the balance; for pulses or wine they
are about equal. A country far from its group's typical ratio has trade
records that do not describe its balance (transit cargo, misreported or mirrored flows).

For each flow (imports, exports), each food group (fish: EU members, from Comext), and each
country with a food balance (not the EU27 bloc):

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
  groups' FBS flows, both without fish (the all-food trade total has none), with its own median.

A withheld flow is not published: `imports` withholds that country's `imports` and `grown` entries
for the group, `exports` its `exports` entry. `trade.json` `meta.withheld` lists each as
`[iso3, group, flow, T, B]` (kt, rounded to whole kt), and the UI says so where the partners would
be. The balance figures themselves (bought and sold in the FBS) are unaffected; for all food,
whose bought and sold totals come from the trade records, those totals are withheld with it.
Other countries' flows with the withheld country as partner are their own records and stay.

**Withheld by review.** A flow the test lets through can still be false: a country that reports
nothing gets its partners' reports, and a seller may book cargo to a ship's flag. Flows a review
finds false are listed in `mappings/trade_withheld_by_review.csv` (iso3, group, flow, date, a
reason in words) and withheld like the others; `meta.withheld` carries the note as a sixth
element and the page shows it instead of the records-against-balance wording. 2026-10-18: the
Marshall Islands' cereal imports, which rest on Ukraine's reported sales to them (19.7 kt in
2022, single years only), most likely cargo for ships flagged there; found because the scenario
section put the islands' cereals at 53% from Russia and Ukraine.

## Comext: EU members' fish trade, and a second look at the trade matrix

Source: Eurostat Comext, dataset DS-045409 "EU trade since 1988 by HS2-4-6 and CN8"
(`pipeline/comext.py`; download `atlas download --source comext`, about 270 requests through the
SDMX API, merged into one raw file with `query.json` recording the query). Reporters: the 27
members (Greece is GR in Comext). Partners: every partner; years 2021 to the latest complete year
for food other than fish, 2010 on for fish (every trend year of the EU bloc's fish balance);
flows 1 (imports) and 2 (exports); quantity (100 kg) and value (EUR). The value is kept for a
later value basis and not shown yet. Partner codes become ISO3 with
`mappings/comext_partners.csv` (Comext's own codes: XS Serbia, XM Montenegro, XI/XU the United
Kingdom, XB/XC/XL Spain's Canary Islands, Ceuta, Melilla, XP Palestine). Codes that name no
country (Q*: confidential partners, stores and provisions, high seas) stay out of the partner
lists but count in the totals behind the extra-EU shares, as outside the EU except QR, QV and QY,
which Comext defines as intra-EU. Aggregate partners in the extraction (WORLD, EXT_EU27_2020,
INT_EU, …) are dropped, so nothing counts twice; the single partners add up to WORLD. Self-trade
(Spain with the Canary Islands) is dropped.

**Products.** Food other than fish is requested as HS6 codes, fish as CN8 codes.

- *HS6 → food group* (`mappings/hs_items.csv`, generated by `atlas crosswalk`,
  `pipeline/crosswalk.py`): the UN Statistics Division's CPC 2.1 ↔ HS 2017 correspondence gives
  each HS6 code its CPC classes; FAO's trade items carry CPC codes (`trade_items.csv`), so the
  code takes the group and `to_primary` factor of its FAO items when they agree. Where the CPC
  class has no FAO item (frozen meat, fish, chocolate, bread), the items disagree (milk and
  cream), or the factors differ (milk powders, tomato products), a hand decision in
  `mappings/hs_overrides.csv` settles it, with its reason; the generator stops on any undecided
  code. HS 2022 codes take the decision of the HS 2017 code they convert to (UNSD conversion
  table); Comext reports 2021 in HS 2017 and later years in HS 2022.
  One HS6 code is split at CN8 level because its products differ too much: whey (0404 10) in
  powder counts as dry whey (7.48), liquid or concentrated whey as fresh whey (0.45)
  (`mappings/cn8_items.csv`). Potato starch is left out, as are wheat and maize starch: FAO's
  trade items count only cassava starch in the group.
- *Fish* (the CN8 codes EUMOFA lists under HS 0301–0309, 1604 and 1605; not fish oil, fishmeal,
  seaweed or the pasta and pet food EUMOFA also lists, which are no FBS fish item) is counted in
  live weight, the basis of the FBS fish balance, with the EU fish
  market observatory's (EUMOFA) conversion factor for each CN8 code and year (Metadata 2,
  Annex 7, 2011 on: fresh whole fish 1, fillets about 2–3, salted, dried or canned fish more). A
  code and year EUMOFA does not list (all of 2010) takes the code's nearest listed year (on a tie, the earlier one); a code
  EUMOFA gives no factor above 0 (ornamental fish) is left out. Fish does not go through the HS6
  crosswalk, whose overrides only mark it so it is not requested twice.

**What it is used for.**

1. *Fish partner lists* for EU members (yearly mean over the FBS window, partners that are
   countries) and the EU bloc (members' trade with non-members, as for every group). `source`
   `comext`; the "grown in" tracing needs the whole world's trade and is not done for fish.
   Fishmeal is no fish in these records, but the FBS counts fish used as feed: a member that
   imports fishmeal for its fish farms has records far below its balance (Greece 2021–2023: 189 kt
   against 668 kt, of which 490 kt feed). The check of section "Trade records against the food
   balance" flags it and the trade page says the records hold only part of the balance. Not every
   gap is fishmeal: Rwanda's balance has 32 kt of fish exports and no feed or non-food use, and
   the records none (most likely fish sold across land borders unrecorded), so the page names
   both causes. Fish codes with large live-weight factors are right by definition (shark fins,
   0305 71: 20 kg of shark per kg) but magnify a mis-coded record: Botswana's 1.7 kt of "shark
   fins" to South Africa become 31 kt of fish, which the check withholds.
2. *The EU bloc's fish balance*: the extra-EU shares `s_imp`, `s_exp` of section "National vs
   EU-bloc view" for fish, per member, flow and year, live weight over all partners.
3. *A comparison with the trade matrix* (not a source): for each member, group (fish excluded)
   and flow over the window, Comext against the trade matrix's figures as the member reported
   them, both in the FBS basis of the partner lists, partners that are countries
   (`data/processed/comext_vs_fao.parquet`, shown on the audit page). FAO builds the EU members'
   rows of its trade matrix from Comext, so large gaps point at a mapping difference, not at two
   views of the world.

### Value basis: what EU countries pay and earn (EUR)

From the same Comext extraction (`VALUE_IN_EUROS`), for EU members and the EU bloc only:

- **What it is.** Per member, food group and flow (imports, exports), the value of its trade with
  each partner that is a country, yearly mean over the FBS window, in nominal euros (not
  adjusted for prices; food prices peaked in 2022). Imports are valued at the EU border including
  freight and insurance (CIF), exports free on board (FOB), as Comext records them. Products and
  groups as in the tonnes basis (`hs_items.csv`, `cn8_items.csv`; fish = the CN8 codes with an
  EUMOFA factor above 0); no conversion factors, a euro is a euro. Self-trade and partners that
  are no country are left out, as for the partner lists by weight.
- **EU bloc:** members' trade with non-members, summed.
- **All food** = all groups but fish, as for weight (the two bases describe the same goods).
- **Never mixed with weight.** It is a basis of its own: the trade page switches between "by
  weight" (FAO trade matrix, FBS basis, as above; fish from Comext in live weight) and "by
  value" (Comext, EUR) for the whole view: list, totals, map. The balance card stays in tonnes.
  No self-sufficiency ratio is computed in value: that would need the value of production,
  which trade data does not have.
- **Export:** `trade.json` `value`: `meta` (`source: eurostat_comext`, `years`, `unit:
  "thousand EUR"`, `basis`), `countries` `{iso3: {group: {imports|exports: [total, [[partner,
  value], …]]}}}` with the same list rule as by weight (every partner with at least 0.5%, at most
  24; values in thousand euros, rounded), and `concentration` (HHI over all partners, as by
  weight, of the value shares).

## BACI: fish partners for the rest of the world, and a check on the trade matrix

Source: CEPII BACI, release 202601, HS 2017 edition (`BACI_HS17_V202601.zip`, 2017–2024, one
CSV per year; `atlas download --source baci`, 795 MB, kept zipped and streamed;
`pipeline/baci.py`). Licence Etalab Open Licence 2.0; cite Gaulier & Zignago (2010), CEPII
Working Paper 2010-23. BACI reconciles what exporters and importers report into one flow per
year, exporter, importer and HS6 product: value (thousand USD, FOB) and quantity (tonnes).

- **Countries:** BACI's numeric codes become ISO3 with its own `country_codes` file; "Other Asia,
  nes" (S19) is Taiwan, as in the UN's practice and FAO's area list. Partners outside our
  country lists and self-trade are dropped.
- **Products:** HS 2017 codes of `hs_items.csv` (version 2017), groups and factors as for Comext.
  Two kinds of HS6 codes are decided at CN8 level for Comext, fish (EUMOFA factor per CN8 code)
  and whey (`cn8_items.csv`); at HS6 they take the **factor of the EU's own mix** under that
  code in that year: Σ (tonnes × CN8 factor) / Σ tonnes over all members' Comext imports and
  exports (CN8 codes of HS 2022 years counted under the HS 2017 code they convert to). A fish
  HS6 code and year without Comext tonnes takes the median EUMOFA factor of its CN8 codes that
  year; a code with neither keeps the nearest year's factor, or 1.
- **Quantities:** rows without a quantity (under 1% of the value of every group but potatoes and
  roots, 4%) are left out.
- **Window:** the FBS window, yearly mean.

**What it is used for.**

1. *Fish partner lists for every country outside the EU* (members and the EU bloc keep Comext,
   which has CN8 detail): imports = flows with the country as importer, exports = as exporter,
   live weight, partners that are countries, yearly mean. `source` `baci`. `trade.json`
   `meta.group_source` gives fish's source by area: `{"fish": {"eu": "eurostat_comext",
   "other": "cepii_baci"}}`. No "grown" tracing for fish (two sources in one matrix).
2. *A check on the trade matrix* (not a source; `data/processed/baci_vs_fao.parquet`, on the
   audit page): for every country, group but fish and flow over the window, BACI against the
   flows the partner lists use (own reports, mirror flows where a country reported nothing, the
   under-reported groups filled), both in the FBS basis of the partner lists, partners that are
   countries. Countries whose FAO flows rest on partners' reports (`meta.mirror`: Russia,
   Belarus, …) are marked: there BACI is the independent view CLAUDE.md asks for.

**What the comparisons showed (2021–2023).** Fish: BACI's totals in live weight against FAO's
fish balances, countries with over 50 kt, median 0.94 for imports and 0.97 for exports; the
large gaps are fish made into fishmeal and fish oil (Peru's exports, Norway's, Turkey's and
China's imports for fish farms), which the FBS counts as fish and the trade records as feed.
Other foods: median BACI/FAO 1.00–1.06 per group; for countries on mirror flows (Russia, Iran,
Argentina, Australia, …) the large flows agree within a few percent. Remaining gaps are real
differences between the compilations, not mappings: fresh cassava roots crossing from Cambodia
and Laos to Vietnam and Thailand, which HS6 cannot tell from dried chips (counted ×4 like FAO's
"cassava dry", the code's whole FAO trade); Romania's cereal imports, which in BACI include
Ukrainian grain passing through Constanța since 2022; re-exports from the United Arab Emirates.
The mapping review that the comparisons led to: potato starch left out, crisps moved to
vegetables, whey split by CN8, HS 0714 10 counted as dried cassava.

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

## Seasons: when crops are sown and harvested

A typical year per country and crop (`pipeline/seasons.py`, `web/public/data/seasons.json`).

**Sources** (all CC BY 4.0, `atlas download --source seasons`):

- *Calendar:* GGCMI Phase 3 crop calendar v1.01 (Jägermeyr et al. 2021, Nature Food 2: 873–885;
  Zenodo record 5062513): planting day and maturity day (day of year) per 0.5° cell, crop, rainfed
  and irrigated; static multi-year averages from observations (MIRCA2000, SAGE, national
  calendars), gap-filled outside cropland. One season per crop and cell; winter and spring wheat
  and two rice seasons apart.
- *Where each crop grows (weights):* ISIMIP3a "histsoc" 15-crop land use
  (`landuse-15crops_histsoc_annual_1901_2021.nc`), the fraction of each cell under the crop,
  rainfed and irrigated, mean of 2019–2021. Wheat uses GGCMI Phase 2's winter and spring wheat
  areas (Zenodo record 3773827, `winter_and_spring_wheat_areas_v1_180627.nc4`, hectares from
  MIRCA2000), because the land-use file has only "temperate cereals".
- *Countries:* ISIMIP3a fractional country masks at 30 arcmin (share of each cell in each
  country).

**Crops** (GGCMI code → weight in the land-use file → FBS item → group): winter and spring wheat
(`wwh`, `swh` → their GGCMI Phase 2 areas → Wheat and products → cereals); maize (`mai` → maize);
rice, main season only (`ri1` → rice); barley and rye (`bar`, `rye` → temperate cereals); millet
and sorghum (`mil`, `sor` → tropical cereals); potatoes (`pot` → temperate roots → Potatoes and
products); sugar beet (`sgb` → temperate roots → Sugar beet) for the sugar group; peas and beans
(`pea`, `bea` → pulses); soybeans, sunflower, rapeseed, groundnuts (`soy`, `sun`, `rap`, `nut` →
their oil-crop types → oilseeds). Left out: cotton (no food group), and cassava and sugar cane,
which are harvested over many months or after more than a year, so one planting and one maturity
date per cell (GGCMI's convention for them) would draw a season that does not exist (Nigeria's
cassava "sown in May, harvested in December"). Fruit, vegetables and animal products have no
calendar here.

**Per country and crop.** Weight of a cell = crop fraction (rainfed and irrigated separately,
each with its own calendar) × cell area (proportional to cos latitude) × the cell's share in the
country; the EU27 adds up its members. A cell's season runs from its planting month to its
maturity month, both included, wrapping over the new year; the month of a day of year is taken
from a 365-day year. Per month, the share of the crop's weighted area (in %, rounded) that is
sown in it, harvested in it (maturity), and growing in it (inside the season). A crop with no
weight in the country has no calendar.

**What a food page shows.** The crops of the food group whose FBS production (window mean, as
published; for sugar, the sugar beet and sugar cane items) is at least 5% of the group's (of the
two sugar crops, for sugar: a cane country shows no strip), at most four, largest first. Winter
and spring wheat are one row, "Wheat": their monthly shares weighted by their areas in the
country (the kind is botany, not season: India's "spring" wheat is sown in November). A month is
"harvest" when at least 20% of the area is harvested in it, otherwise "sowing" when at least 20%
is sown in it, otherwise "growing" when at least 50% is growing, otherwise empty. The page says it
is a typical year, not the years of the other figures.

**Checked against the wheat harvest.** A pre-release review (2026-10-18) found GGCMI's calendars
for Europe to be month-level placeholders in many places, mostly where it falls back to MIRCA2000
(its `data_source_used` = 1): peas "sown 1 May, ripe 31 October" in every cell from Spain to
Ukraine (field peas there are harvested in July; Spain's in May–June), barley "ripe 24 May" in
Ukraine and Romania, winter wheat "ripe 23 June" in Ireland, Sweden and Austria. So every crop
row is checked against the wheat harvest months of the International Wheat Council (World Wheat
Statistics, "Wheat harvesting calendar", `mappings/wheat_harvest_iwc.csv`; its Belgium-Luxembourg,
Czechoslovakia, Yugoslavia and Former U.S.S.R. rows apply to today's countries; Ireland, missing
there, from Teagasc's harvest reports: August–September):

- **Wheat** must have at least 50% of its harvest (sum of the monthly harvest shares) in those
  months.
- **Barley, rye, rapeseed and peas** too, where those months lie within May–September: in a
  northern summer they are harvested with wheat or just before it.
- A row that fails is not shown (`left_out` in the export, and a line on the food page naming the
  crops). Countries the table does not list are not checked; maize, rice, millet, sorghum,
  potatoes, sugar beet, beans, soybeans, sunflower and groundnuts are not checked (their seasons
  are not tied to wheat's; spot checks for the European core found them right within a month).

2021–2023: 43 countries lose at least one row; in the EU, peas in 19 members (still shown in
Finland, which the table does not list, and Greece, whose wheat harvest runs May–August), rapeseed
in 15 (Germany among them: "ripe 24 June", where the harvest is in July), barley in 8, wheat in 7
(Austria, Belgium, Czechia, Ireland, Luxembourg, Slovakia, Sweden), rye in Poland.

**Export:** `seasons.json` `meta` (sources, thresholds, `check`), `countries` `{iso3: {group:
[{crop, item, share, sown: [12], growing: [12], harvest: [12]}]}}`, `share` = the crop's % of the
group's production, and `left_out` `{iso3: {group: [label]}}`.

## When it comes from abroad: fruit and vegetables month by month (EU countries)

No open, machine-readable harvest calendar exists for European fruit and vegetables: FAO's Crop
Calendar API covers 58 countries, none in Europe (checked 2026-10-18), and the gridded calendars
of section "Seasons" cover field crops only. What is measured month by month is trade: Eurostat
Comext has monthly imports for every EU member. The page shows those, and says so; it does not
infer harvests from them.

- **Source:** Comext DS-045409, monthly (`freq M`), imports (flow 1), quantity, every partner,
  EU members as reporters, from January 2021 (`atlas download --source comext`, file
  `DS-045409_monthly_imports.csv.gz`, 54 requests). Products: the HS6 codes of
  `hs_items.csv` in fruit, vegetables and potatoes and roots (`pipeline/comext.py`,
  `monthly_imports`), with their factors, as by weight; the HS version of each year.
- **Per fresh product, not per food group.** Summed over a whole group the months even out
  (Germany's vegetables: 7–10% in every month), because frozen, preserved and fresh goods and
  products with opposite seasons cancel. The seasons are in single fresh products, by HS
  heading: potatoes (0701); tomatoes (0702), onions and garlic (0703), cabbages and cauliflower
  (0704), lettuce (0705), carrots and other roots (0706), cucumbers (0707), fresh peas and beans
  (0708), peppers, courgettes and other fresh vegetables (0709); bananas (0803), dates, figs,
  avocados and mangoes (0804), citrus (0805), grapes (0806), melons (0807), apples and pears
  (0808), apricots, cherries, peaches and plums (0809), berries, kiwis and other fresh fruit
  (0810). Only the HS6 codes of each heading that belong to the food group count (olives in 0709
  are oilseeds).
- **Per member, product and calendar month:** imports in the FBS basis (factors of
  `hs_items.csv`), summed over the FBS window years (January = the window's three Januaries), as a
  share of the product's window total (%, one decimal). All partners count in the shares, named or
  not; self-trade is dropped. The EU bloc: members' imports from non-members (unnamed partners
  outside the EU except QR, QV, QY, as in section "Comext").
- **Which products:** per country and food group, the fresh products with the most imports over
  the window, each at least 5% of the group's fresh-product imports, at most four, largest first.
- **Leading supplier per month:** the partner country with the largest share of that month's
  imports of the product, with that share (%, whole).
- **Shown** on the food page of EU members and the EU for fruit, vegetables and potatoes and
  roots: per product twelve cells shaded by the month's share, the leading supplier on hover,
  and in words the suppliers that lead the year (each leading supplier with its months).
- **Export:** `import_months.json` `{meta, names: {heading: name}, countries: {iso3: {group:
  [{hs4, share: [12], top: [[iso3, %] | null × 12]}]}}}`.

## Where it is grown: regions in Europe

Regional crop production from Eurostat `apro_cpshr` ("Crop production in EU standard humidity by
NUTS 2 regions"; `pipeline/regions.py`, `web/public/data/regions.json` and `regions.geojson`).
Licence: Eurostat (CC BY 4.0); boundaries GISCO NUTS 2024 and 2021, 1:20 million (non-commercial,
© EuroGeographics).

- **What:** harvested production (`HPRD_HUMD_EU_THS_T`, 1000 t at EU standard humidity) per
  region, yearly mean over the FBS window years the region reports. Food groups: cereals
  (`C0000`, cereals for grain incl. seed), potatoes and roots (`R1000` potatoes), sugar (`R2000`
  sugar beet), pulses (`P0000`), oilseeds (`I1110` rape and turnip rape + `I1120` sunflower +
  `I1130` soya, the sum of those a region reports). Fruit, vegetables and wine are too sparse.
- **Which regions:** per country and crop, the finest NUTS level with data in the window (NUTS 2,
  else NUTS 1: Germany reports by Land). Codes are matched to the NUTS 2024 boundaries, else to
  NUTS 2021; codes in neither (older classifications kept in the series, extra-regio `ZZ`) are
  dropped. A country is shown when its kept regions add up to at least 90% of its national total
  in the same table (`coverage`) and it has more than one region. The EU27 shows all its members'
  shown regions (shares of their sum).
- **Shown:** each region's share of the regions' sum (%), its production (kt a year), and its
  production per km² of the region (t per km²; area from the boundaries, spherical, at 1:20
  million). The map shades regions by t per km² in five classes per food, the same for every
  country: the 20th, 40th, 60th and 80th percentiles of all shown regions' densities above 0,
  rounded to two significant digits; regions that grow none of it are drawn as none.
- **Not the FBS:** Eurostat's crop statistics (EU standard humidity, harvested production) are not
  FAO's balance; the page shows shares and regional tonnes only, never next to the balance figures.

### Fields: the crop map at 2 km

Inside the regions, where the fields are: JRC's crop proportions derived from EUCROPMAP 2018
(the 10 m crop-type map of the EU and the UK from Sentinel-1, d'Andrimont et al. 2021), as the
share of the land under each crop class in 2 km cells (`DRLL/CropDiversity/CropProportionLand`,
EPSG:3035; CC BY 4.0, © European Union; `atlas download --source cropmap`, 14 files, 363 MB;
`pipeline/cropmap.py`). The 10 m map itself (2018 and 2022, 7.3 GB per year, no overviews) is not
read: aggregating it here would mean decoding about 150 billion pixels for the same picture.

- **Classes per food:** cereals 211–219 (common and durum wheat, barley, rye, oats, maize,
  rice, triticale, other cereals); potatoes 221; sugar beet 222; oilseeds 232 (rapeseed) and 233
  (soya), sunflower being no class of the 2018 product; pulses 240 (dry pulses). A food's share
  of a cell = the sum of its classes (at most 1).
- **Image:** reprojected to Web Mercator (EPSG:3857) at 2 km per pixel at the equator scale
  (nearest cell: every pixel shows a real cell's value; bilinear smoothing invented in-between
  values at field edges and failed the check below), cropped to the cells with data, and drawn in five shades by share of the land:
  2–10%, 10–20%, 20–35%, 35–50%, 50% and more; under 2% is transparent. One PNG per food
  (`cropmap_<group>.png`) with its corners in `cropmap.json`.
- **Shown** as the "Fields" reading of "Where … do they grow?", with the regions' outlines over
  it and its own legend; the page says it is the 2018 map. The regions' tonnes are not shown at
  the same time (one measure per view).
- **Checked:** `atlas validate` checks that the image's corners match `cropmap.json` and its
  colours are the five shades; `verify/recompute.py` re-reads the class rasters, sums the classes
  at 4,000 sampled image pixels per food (nearest cell; transparent in a country left out by the
  check below, which it repeats) and requires the same shade for at least 99% of them (2026-10-18: 99.45–99.95%). The rest are pixels whose centre falls on a cell
  border, where the reprojection and the check can pick neighbouring cells with very different
  shares.

- **Checked against the statistics** (`cropmap.area_check`): per country the map covers (EU27 and
  the United Kingdom) and food, the map's area, Σ share × cell area over the cells inside the
  country (GISCO countries, the file of the site's borders), against Eurostat's crop area for 2018
  (`apro_cpshr`, `AR_THS_HA`; cereals C0000 + G3000, because the map's maize includes maize cut
  green; potatoes R1000; sugar beet R2000; oilseeds I1110 + I1130; pulses P0000). Under half or
  over twice it, the country is left out of that food's image (transparent) and named in the
  page's notes with both areas (`cropmap.json` `groups.<food>.left_out: {iso3: {map_kha,
  eurostat_kha, ratio}}`). The satellite map misses small plots and confuses some crops: it finds
  7% of Romania's potato area and 8% of Spain's, 6% of Spain's sugar beet, six times the
  Netherlands' pulses; cereals agree within a factor 1.7 everywhere but Cyprus. 2018: left out
  for potatoes in 15 countries, pulses 13, oilseeds 7, sugar beet 5, cereals 1.

## Feed: how much of the meat and eggs rests on imported feed

Meat and egg self-sufficiency counts every animal raised at home as home-grown, also when it ate
imported soy. This section (`pipeline/feed.py`) says how much of the feed is imported and what
self-sufficiency is left for the animals that live on it.

- **Source:** FAOSTAT Supply Utilization Accounts (SCL, "Food Balances: Supply Utilization
  Accounts (2010-)", `SUA_Crops_Livestock_E_All_Data_(Normalized).zip`, CC BY 4.0): production,
  imports, exports and **feed** for every commodity, oilseed cakes and brans included (the food
  balances leave them out). FBS window years, yearly means.
- **Feed basket:** the items fed in the country (element Feed), weighted by **crude protein**
  (`mappings/feed_items.csv`: % as fed, typical values from Feedipedia, the feed tables of INRAE,
  CIRAD, AFZ and FAO; the items that make 98.7% of the world's feed by weight). Protein, not
  energy: the known blind spot is imported soy protein, which an energy weighting hides again
  behind grain. Items not in the table are left out (their share of the feed tonnage is logged).
- **Home-grown share of a feed item** `s = P / (P + M)`: what the country has, as in section
  "Where imports were grown", an even mix of its own production and its imports (exports leave
  in the same mix). A by-product (cakes, brans, germ, gluten feed; the `parent` column) is only
  home-grown if its crop was: `s = P / (P + M) × s_parent` (Germany crushes imported soybeans: its
  soy cake is not home-grown even when crushed at home). `P + M = 0`: `s = 1` (nothing fed).
- **The EU as one:** members' sums of P, M and feed, with M = members' imports from outside the
  EU: per item and year the share of members' reported imports from non-members in FAO's trade
  matrix (`trade.extract`), applied to the members' summed imports; an item without trade-matrix
  rows keeps all imports.
- **Imported share of feed protein** `f = Σ feed_i · protein_i · (1 − s_i) / Σ feed_i · protein_i`,
  with the largest imported items (share of the imported protein) for the page.
- **Feed-adjusted self-sufficiency** (tonnes basis): pigs and poultry live on concentrate feed,
  so their meat counts as home-grown only in the home-grown share of the feed:
  `meat: (P_meat − f · (P_pigmeat + P_poultry)) / D_meat`, `eggs: (1 − f) · P_eggs / D_eggs`, with
  the group figures as published. Cattle, sheep, goats and milk are not adjusted: they live
  largely on grass and hay, which no statistic counts as traded, so a concentrate-only share would
  overstate their dependence. Withheld groups get no adjusted figure.
- **Export:** `ssr.json` country `feed`: `{imported_pct, top: [[item, % of imported protein] × ≤3],
  meat_ssr, eggs_ssr, items_pct}` (`items_pct` = share of the feed tonnage the table covers).
- **Second opinion (EU):** DG AGRI's *EU feed protein balance sheet* (`pipeline/feedcheck.py`)
  gives per marketing year and protein source the EU's feed use in crude protein (column H) and
  the part of EU origin (I), counting meal from imported beans as not of EU origin, as here.
  Compared: the marketing years starting in the window's years (2021 → 2021/22), averaged;
  DG AGRI's roughage (grass, silage maize, fodder legumes) left out, since FAO's accounts have
  none; imported = H − I. Per source: whole cereals, soya bean, rapeseed and sunflower meal
  (our items in `feedcheck.SOURCES`), and all concentrate feed. A gap over 10 points in the
  imported share of all concentrate feed is a warning (`feed_dgagri_gap`). On the audit page,
  never on the site. With the 2021–2023 window: 41.9% imported against DG AGRI's 40.7%; soya
  bean meal 93% against 97%, rapeseed meal 28% against 30%, sunflower meal 43% against 48%,
  cereals 10% against 15%. The cereals gap is an assumption, not a difference in the data: both
  count about the same cereal protein fed (14.4 Mt against 15.2 Mt; wheat 4.3 against 4.7, maize
  4.8 against 4.8). DG AGRI's methodology sheet sends imported cereals to feed first: all imported
  common wheat, 90% of imported maize (in each of 2021/22–2023/24: wheat not of EU origin equals
  the imports exactly; maize 90%; barley none). Here imports and production mix evenly (wheat
  5% imported, maize 24%; DG AGRI 17% and 30%). We keep the even mix: it is one rule for every
  country and item, applied per member before the EU is summed, while DG AGRI's is an expert
  judgement for the EU alone. With DG AGRI's rule for cereals the EU's imported share would be
  about 44% instead of 41.9% (0.8 Mt more imported cereal protein). Total concentrate protein 38.1 Mt against 42.2 Mt
  (4.2 Mt, traced by category, DG AGRI minus ours):
  - **Sources FAO's accounts have no item for: 3.8 Mt.** Distillers' dried grains 1.20, wet
    distillers' grains 0.33, beet pulp 0.54, citrus pulp 0.01 (other co-products); processed
    animal protein 0.92, former foodstuff 0.51, fish meal 0.30 (non-plant). FAO's SUA lists none
    of these with a feed use. They are mostly of EU origin (0.41 Mt imported): counted in, our
    imported share would be 39.1% instead of 41.9%.
  - **Different estimates of the same feed: +0.4 Mt net.** Cereal grain +0.8 (FAO records 38 Mt of
    wheat fed, DG AGRI 43), starch-industry protein +0.9 (DG AGRI 1.18, our gluten feed and maize
    gluten 0.33), oilseed meals +0.4 (sunflower meal 2.5 against 1.8, soy protein concentrate
    0.2), pulses +0.2; against brans and germs −1.0 (FAO's brans, germs and maize cake 2.1,
    DG AGRI's wheat bran 1.1),
    milk and whey −0.7 (FAO counts liquid milk and whey fed to calves, 0.8 against 0.13),
    whole oilseeds −0.1, roots −0.1.
  - **Items FAO does list as feed but `feed_items.csv` leaves out** (outside the 98.7% of the
    world's feed tonnage the table covers): in the EU among them rye bran 0.31 Mt, wheat gluten
    0.13 Mt, casein 0.11 Mt and flours, a few tenths of a Mt of protein at typical contents. Left
    out, as everywhere, so that one table serves every country.

## Scenarios: what if some countries stopped selling

What a country would lack if a group of countries stopped selling food, and nothing took their
place (`pipeline/scenario.py`, `web/public/data/scenario.json`). The groups are in
`mappings/scenarios.yaml`: Russia and Ukraine, India, Indonesia and Malaysia, Côte d'Ivoire and
Ghana, South America, the United States and Canada, China, the EU (rule `eu27`: the 27 members,
and the EU as one counts as a seller too) and the rest of the world selling to Europe (rule
`outside_europe`: every trade partner not in `countries.yaml`). Besides these, **every country is
a scenario of its own** ("What if Brazil stopped selling?", from its sales page). Below, "Russia
and Ukraine" stands for any group; a country in the group gets no figure.

- **Per country and food:** `lack = 100 × M × s / (P + M)` (% of what it uses), with P and M the
  food balance's production and imports as published (`components_kt`), and `s` the share of its
  imports **grown** in Russia or Ukraine. What a country has, P + M, is an even mix (as in section
  "Where imports were grown"): exports and stocks take the same mix, so its own use has the same
  share from Russia and Ukraine. Dividing by D instead counted transit as use (Slovenia, through
  Koper, came out at 213% of its oilseeds) (section "Where imports were grown": what comes through
  Turkey as flour or through the Netherlands counts where it was grown). Fish has no tracing: its
  `s` is the share bought from them (Comext or BACI). The EU as one: its own figures (imports from
  outside the EU, traced).
- **All food:** the foods' figures weighted by their calories per person (FBS items, as the
  headline): `Σ_g kcal_g × lack_g / Σ_g kcal_g` over the foods with a figure, shown only
  when those foods carry at least 90% of the calories of all groups (summed over items with
  kcal > 0): with its cereals withheld (section "Withheld as implausible") Turkey's fell from
  17% to 3% (protein-weighted then), the food it buys most from Russia left out.
- **No figure:** for Russia and Ukraine themselves; for a withheld food (its balance contradicts
  itself) or a withheld import flow (section "Trade records against the food balance"); where
  D ≤ 0 (nothing used).
- **What it does not say:** that the food would be missing for long (other sellers step in, at a
  price), or what animals would lack in feed (sunflower meal from Ukraine is feed, not a food
  group here). The page says so.
- **Small figures:** files keep figures from 0.05% on. `meta.cover` `{iso3: [group]}` lists where
  a figure exists at all (the figures with no seller): a covered food missing from a file is 0, one
  outside the cover has none.
- **Export:** `scenario.json` `{meta: {years, basis, eu_bloc, eu27, min_lack, scenarios: [{key,
  label, note, sellers}], sellers: [iso3 with a file], cover}, scenarios: {key: {iso3: {group:
  lack %}}}}`, and per seller `whatif/<ISO3>.json` `{iso3: {group: lack %}}`; chosen with the "What if?" button on
  the map, shown as that map for the chosen food (a badge on the map says which scenario is on) and
  a line on the country's and food's page while it is on.

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
| Invariants | `pipeline/validate.py` → `validation.json` | identity P + M − X − ΔS = D on rows we build (exactly) and on FAO's (warning only beyond its rounding: each figure of each item is rounded to 1 kt, so a group of n items may miss by n × 2.5 kt); group = sum of items; EU27 production = members' sum and = FAO's own EU27 row item by item (within FAO's rounding); extra-EU trade ≤ members' total; our JRC-based ratio = the JRC's own for tomatoes, olive oil, wine; exported ratio = exported components; withheld figures carry nothing usable; trade partners ≤ total; no self-trade. Warnings for review: very high SSRs, unusual years in trends, trade records more than 3× from their food group's typical ratio to the balance (section "Trade records against the food balance"; far above it and above the balance: withheld), negative-supply items in groups |
| FAOSTAT live sample | `tests/golden/`, `tests/test_golden.py` | 1,695 three-year totals (20 countries × 23 items × P/M/X/D, population, kcal, protein) read from FAOSTAT's website in a browser; harmonised data and window averages must equal them. A wrong M49 → ISO3 line fails it (tested: Brazil/USA swapped, 187 values off) |
| Known facts | `tests/test_real_data.py` | France poultry < 100% and EU > 100%, EU soybeans 10–30%, NL a cereal hub, JRC replacements in place, Jordan eggs and Ukraine oils withheld, Iceland fish not |
| Independent recomputation | `verify/recompute.py` | written from this document alone, without reading `pipeline/`; recomputes every published number (≈250,000) from the raw files and must agree on all of them. Its first run found three pipeline bugs (EU27 per-person population, window averaging, EU27 fish kcal IDR) |
| What the page shows | `web/tests/*.spec.js` (Playwright, installed Chrome) | headline and food-page wording = `calendar.js` of the exported figure; receipt sum = exported ratio; rankings never include a withheld figure and equal the data's top five; no factual figure typed into `main.js` |
| Plausibility | `pipeline/plausible.py`, `checks.plausibility` (section "Withheld as implausible") | balances that add up but put use at home per person beyond any known national average, or imports far beyond the trade records: withheld with both readings |
| Second source | `pipeline/usda.py` (section "FAO against USDA") | FAO figures far from USDA's for the same country and commodity: warnings, and a note on the page |
| Human review | `atlas report` → `data/processed/audit.html` | every withheld figure (with why: the review note, the plausibility readings, the items a group rests on, or FAO's lines), every warning, the season rows and crop-map countries left out, and the 50 largest changes since the last release (`atlas release-snapshot` after publishing). A warning ends one of three ways: **handled** when the site deals with it by itself (`validate.resolve`: unusual years drawn apart; negative-supply items kept within the withholding threshold by the parts test; a USDA disagreement shown on the page or too small to move the group's figure by 5 points; trade records under half of the balance, which the trade page then says); **confirmed** when a review found it right, with the reason and date in `pipeline/mappings/confirmed_findings.csv`; or fixed or withheld (by a rule or by review). A release should have no open warnings |

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
- [x] **Feed vs food.** Meat/dairy SSR > 100% can coexist with ~15% soy self-sufficiency. Done:
      section "Feed" (pigs, poultry and eggs; cattle, sheep and milk explained, not adjusted).
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
