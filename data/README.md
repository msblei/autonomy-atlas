# data/

Everything here is gitignored and reproducible with `make all`.

| Folder | Contents | Written by |
|---|---|---|
| `raw/<source>/` | untouched downloads (FAOSTAT FBS and Detailed Trade Matrix ZIPs, catalogue XML, JRC balance sheets, GISCO GeoJSON); `manifest.json` pins their sha256 | `atlas download` / `atlas manifest` |
| `interim/` | `fbs.parquet` (tidy long FBS), `FoodBalanceSheets_fao_eu27.parquet` (FAO's own EU27 row, for checks), `trade_yearly.parquet`, `eu_extra_shares.parquet` | `atlas build` |
| `processed/` | `ssr_items`, `ssr_groups`, `ssr_overall`, `ssr_trends`, `trade_partners` (Parquet); `validation.parquet`; `audit.html` | `atlas build`, `atlas validate`, `atlas report` |
| `releases/<stamp>/` | the web data as published, baseline for the next audit's "changes" | `atlas release-snapshot` |

Web-ready JSON goes to `web/public/data/` (`atlas export`).

Sizes to expect: FBS ZIP ~55 MB, Detailed Trade Matrix ZIP ~420 MB (8.5 GB CSV inside, streamed,
never unzipped), Production ZIP ~150 MB.
