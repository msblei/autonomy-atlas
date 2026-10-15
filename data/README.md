# data/

Everything here is gitignored and reproducible with `make all`.

| Folder | Contents | Written by |
|---|---|---|
| `raw/<source>/` | untouched downloads (FAOSTAT ZIPs, Eurostat TSV.gz, GISCO GeoJSON, Natural Earth ZIP, BACI CSVs) | `atlas download` |
| `interim/` | tidy long-format Parquet, one file per source table (`fbs.parquet`, `eurostat_apro_cpshr.parquet`) | `atlas build` |
| `processed/` | indicators (`ssr_items.parquet`, `ssr_groups.parquet`) | `atlas build` |

Web-ready JSON goes to `web/public/data/` (`atlas export`).

Sizes to expect: FBS ZIP ~60 MB, Production ZIP ~150 MB, Detailed Trade Matrix ZIP ~2 GB
(phase 2 only; not downloaded by default).
