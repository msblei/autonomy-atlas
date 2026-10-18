# Updating the data

How to bring the atlas up to date when a source publishes new figures: what changes when, the one
manual step, where versions are set, what to review, and what will break on a known date.
Formulas and checks: `methodology.md`. Sources and licences: the table in `CLAUDE.md`.

## The short version

```
# by hand first, if the JRC balances changed: see "The one manual step" below
make refresh                            # atlas download --force, build, export
                                        # (plain `make download` keeps the files it already has!)
make verify                             # tests, validate, independent recompute, browser tests, audit page
# read data/processed/audit.html: every warning must end handled, confirmed, fixed or withheld
make release                            # = all + verify + the gated web build into web/dist
# after publishing web/dist:
.venv/bin/atlas release-snapshot        # baseline for the next audit's "largest changes"
```

`atlas download` without `--force` **skips files that already exist**, so a refresh without it
silently keeps the old data. `atlas download` re-records `data/raw/manifest.json`; `atlas build`
refuses to run on raw files that differ from it (replaced by hand without `atlas manifest`).

The years follow the data: the window is the latest three FBS years (`compute.latest_window`), and
trade, Comext, BACI, regions, feed and scenario take the same window. No year is typed anywhere.

## What changes when

| Source | Publishes | What to do |
|---|---|---|
| FAOSTAT FBS, SUA (SCL), trade matrix, QCL | once a year (the latest in December; the next is due December 2026) | `--force` download. Bulk file names are in `config.FAOSTAT_FILES`; FAO renames files now and then: check them against `datasets_E.xml` (downloaded every time). Area names change too: joins use M49 codes, `harmonise` stops on an unknown area |
| DG AGRI–JRC EU balance sheets | a few times a year | **manual** (below) |
| USDA PSD | monthly | `--force` download; only a comparison |
| Eurostat Comext (annual and monthly) | monthly | `--force` download (about 300 queued requests, 20 minutes); years run from `config.COMEXT_FIRST_YEAR` (2021) and `COMEXT_FISH_FIRST_YEAR` (2010) to the latest; the FBS window picks its years |
| CEPII BACI | once a year (January) | the file name carries the release (`V202601`): change `config.SOURCES["cepii_baci"]["file_url"]` **and** `baci.RELEASE` together, then download |
| Eurostat `apro_cpshr` | a few times a year | `--force` download |
| EUMOFA conversion factors | when CN codes change (yearly) | the URL holds a dated folder (`system/files/2026-05/`): if the download fails, take the new link from the EUMOFA metadata page and update `config.SOURCES["eumofa_cf"]` |
| UNSD CPC–HS correspondences | with a new HS version | see "Known dates" |
| GGCMI calendars, ISIMIP land use and country masks, JRC crop shares, GISCO boundaries | rarely (static releases) | nothing; a new release is a new URL in `config.SOURCES` |

## The one manual step: JRC balance sheets

The JRC server refuses scripted downloads. `atlas download --source jrc` prints the steps: open
the dataset page in `config.SOURCES["jrc_bal"]["url"]`, download the ZIP "EU estimated
agricultural balance sheets (EU-27)", save it as
`data/raw/jrc/Dataset_EU_estimated_agricultural_balance_sheets.zip` and unzip it into
`data/raw/jrc/bal/`. Then `atlas manifest` to record it. Without it, EU dairy, tomatoes, olive oil
and wine fall back to FAO's figures (`pipeline/jrc.py`).

## What to review after a refresh

1. **The audit page** (`data/processed/audit.html`): blocking findings (none allowed), the
   comparisons (FAO against USDA, Comext, BACI), withheld figures and trade flows, open warnings,
   and the 50 largest changes since the last release. Every new warning ends handled (the site
   deals with it), confirmed (a reason in `mappings/confirmed_findings.csv`), fixed, or withheld.
2. **The review lists**, which carry human judgements about one release's figures. Each line has
   a date: check it still holds.
   - `mappings/withheld_by_review.csv`: balances withheld although they do not contradict
     themselves (Uruguay's and Cambodia's pulses).
   - `mappings/trade_withheld_by_review.csv`: trade flows found false (the Marshall Islands'
     cereal imports).
   - `mappings/confirmed_findings.csv`: warnings found right (very high SSRs, Botswana's trade).
3. **Mappings that follow the sources' codes**: `trade_items.csv` (FAO trade items),
   `hs_overrides.csv` and `cn8_items.csv` (Comext codes; `atlas crosswalk` stops on any new code it
   cannot place), `feed_items.csv` (new feed items would show as a lower `items_pct`),
   `comext_partners.csv` (a new Comext partner code is dropped from the partner lists until mapped).
4. **The methodology's numbers in words** (examples such as "Germany 53%", "Slovenia 213%") are
   from the 2021–2023 window. They describe how a rule was found; update them when the review
   above changes them. Numbers on the site itself are never typed: they come from the data.

## Known dates that will break something

- **HS 2027, from January 2027.** Comext reports each year in the HS version in force
  (`comext.hs_version`: 2017 up to 2021, 2022 after). From 2027 it will use HS 2027 codes, which
  `mappings/hs_items.csv` does not know: new codes would drop out of the Comext figures. Before
  the first refresh that includes 2027: add the UNSD HS 2027 → HS 2022 (or → HS 2017) conversion
  to `pipeline/crosswalk.py` the way HS 2022 is handled, extend `hs_version`, regenerate with
  `atlas crosswalk`. The FBS window will not include 2027 before late 2029, but the monthly
  imports and the money basis come from Comext's latest years sooner.
- **NUTS 2024 → next NUTS version.** `regions.py` matches codes to the NUTS 2024 boundaries, else
  2021: add the new version's GISCO file to `regions.NUTS` when Eurostat switches.
- **Ukraine's backfilled statistics** (2022–2025, published monthly since December 2025) change
  past years in FAO's next releases: expect large changes for Ukraine on the audit page.

## Where things live

- Raw files: `data/raw/<source>/` (never edited), hashes in `data/raw/manifest.json`.
- Derived: `data/interim/`, `data/processed/` (rebuilt by `atlas build`).
- Published: `web/public/data/` (`atlas export`), checked by `atlas validate`
  (`validation.json` holds each file's hash), recomputed by `verify/recompute.py`; the web build
  refuses files that differ from what was checked (`web/scripts/check-data.mjs`).
- Release baselines: `data/releases/<timestamp>/` (`atlas release-snapshot`), used by the audit
  page's "largest changes". None of `data/` is in git; everything is rebuilt from the sources.
