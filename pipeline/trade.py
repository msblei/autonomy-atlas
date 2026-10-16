"""FAOSTAT Detailed Trade Matrix -> who each country buys its food from and sells it to.

Output data/processed/trade_partners.parquet, one row per country × group × flow × partner:
    iso3, group, flow (imports | exports), partner, tonnes, source (reported | mirror), years

`tonnes` is the yearly mean over the same window as the FBS figures, in product weight as traded
(a tonne of flour or cheese counts as a tonne; mappings/trade_items.csv). That is fine for "which
share comes from where" within one food group, not for comparing with FBS totals.

Flows come from the reporting country. When a country reported nothing for a flow in a year
(Russia, Belarus and others since 2022), its partners' reports are used instead: exports that
others say they sent it become its imports ("mirror" flows), and vice versa.

The EU27 bloc gets only trade with non-members: what the EU as a whole buys from and sells to the
rest of the world.
"""

from __future__ import annotations

import csv
import logging
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from . import config
from .compute import EU_BLOC
from .harmonise import load_countries

log = logging.getLogger(__name__)

TM_ZIP = config.FAOSTAT_FILES["trade_matrix"]
TM_CSV = "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).csv"
FLOWS = {"Import quantity": "imports", "Export quantity": "exports"}
MIRROR = {"imports": "exports", "exports": "imports"}

_COLS = {
    "Reporter Country Code (M49)": "reporter",
    "Partner Country Code (M49)": "partner",
    "Item Code": "item_code",
    "Element": "element",
    "Year": "year",
    "Unit": "unit",
    "Value": "value",
}


def load_item_groups() -> dict[int, str]:
    """Trade item code -> products.yaml group, for the items that belong to a group."""
    path = config.MAPPINGS / "trade_items.csv"
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {int(r["item_code"]): r["group"] for r in rows if r["group"]}


def read_matrix(years: tuple[int, int], items: dict[int, str]) -> pd.DataFrame:
    """Stream the 8.5 GB CSV out of the zip, keeping food quantities in tonnes for `years`."""
    path = config.RAW / "faostat" / TM_ZIP
    codes = pa.array(sorted(items), pa.int64())
    elements = pa.array(list(FLOWS))
    y0, y1 = years
    parts = []
    with zipfile.ZipFile(path) as zf, zf.open(TM_CSV) as fh:
        reader = pacsv.open_csv(
            fh,
            read_options=pacsv.ReadOptions(block_size=64 << 20),
            convert_options=pacsv.ConvertOptions(
                include_columns=list(_COLS),
                column_types={"Reporter Country Code (M49)": pa.string(),
                              "Partner Country Code (M49)": pa.string(),
                              "Item Code": pa.int64(), "Year": pa.int64(), "Value": pa.float64()},
            ),
        )
        for batch in reader:
            mask = pc.and_(
                pc.and_(pc.greater_equal(batch["Year"], y0), pc.less_equal(batch["Year"], y1)),
                pc.and_(pc.is_in(batch["Item Code"], value_set=codes),
                        pc.and_(pc.is_in(batch["Element"], value_set=elements),
                                pc.equal(batch["Unit"], "t"))),
            )
            kept = batch.filter(mask)
            if kept.num_rows:
                parts.append(kept.to_pandas())
    df = pd.concat(parts, ignore_index=True).rename(columns=_COLS)
    for c in ("reporter", "partner"):
        df[c] = df[c].str.lstrip("'").str.zfill(3)
    df["group"] = df["item_code"].map(items)
    df["flow"] = df["element"].map(FLOWS)
    log.info("trade matrix: %d food rows for %d-%d", len(df), y0, y1)
    return df


def load_trade_only() -> pd.DataFrame:
    """Trade partners without a Food Balance Sheet (Japan, Singapore, ...): m49, iso3, name."""
    return pd.read_csv(config.MAPPINGS / "trade_only.csv", comment="#", dtype=str,
                       encoding="utf-8").assign(m49=lambda d: d["m49"].str.zfill(3))


def to_iso3(df: pd.DataFrame) -> pd.DataFrame:
    """M49 -> ISO3 for reporter and partner; rows with an unknown area on either side go
    (regions, historical countries)."""
    m49 = pd.concat([load_countries()[["m49", "iso3"]], load_trade_only()[["m49", "iso3"]]])
    m49 = m49.set_index("m49")["iso3"]
    df = df.assign(reporter=df["reporter"].map(m49), partner=df["partner"].map(m49))
    lost = df["reporter"].isna() | df["partner"].isna()
    if lost.any():
        log.info("trade: %.1f%% of tonnes involve areas outside our country list (dropped)",
                 100 * df.loc[lost, "value"].sum() / df["value"].sum())
    return df[~lost & (df["reporter"] != df["partner"])]


def partners(df: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Reported flows, with mirror flows where a country reported nothing for a flow and year."""
    keys = ["reporter", "partner", "group", "flow", "year"]
    rep = df.groupby(keys, as_index=False)["value"].sum()
    reported = set(rep[["reporter", "flow", "year"]].itertuples(index=False, name=None))

    mirror = rep.rename(columns={"reporter": "partner", "partner": "reporter"})
    mirror["flow"] = mirror["flow"].map(MIRROR)
    gap = [(r, f, y) not in reported for r, f, y in
           mirror[["reporter", "flow", "year"]].itertuples(index=False, name=None)]
    mirror = mirror[gap]
    if len(mirror):
        log.info("trade: mirror flows for %d country-years without own reports",
                 mirror[["reporter", "flow", "year"]].drop_duplicates().shape[0])

    both = pd.concat([rep.assign(source="reported"), mirror.assign(source="mirror")],
                     ignore_index=True)
    n_years = years[1] - years[0] + 1
    out = (both.groupby(["reporter", "group", "flow", "partner"], as_index=False)
           .agg(tonnes=("value", "sum"), source=("source", lambda s: "mirror"
                                                  if (s == "mirror").all() else "reported")))
    out["tonnes"] /= n_years
    return out.rename(columns={"reporter": "iso3"})


def add_eu_bloc(p: pd.DataFrame) -> pd.DataFrame:
    """EU27 = members' trade with non-members, summed (intra-EU trade is not EU trade)."""
    eu = p[p["iso3"].isin(config.EU27) & ~p["partner"].isin(config.EU27)]
    bloc = (eu.groupby(["group", "flow", "partner"], as_index=False)["tonnes"].sum()
            .assign(iso3=EU_BLOC, source="reported"))
    return pd.concat([p, bloc], ignore_index=True)


def fbs_window() -> tuple[int, int]:
    """The window of the processed FBS figures, so trade and balances cover the same years."""
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet", columns=["years"])
    y0, y1 = (int(y) for y in groups["years"].iloc[0].split("-"))
    return y0, y1


def run() -> None:
    if not (config.RAW / "faostat" / TM_ZIP).exists():
        log.warning("no trade matrix; run `atlas download --source faostat` (420 MB)")
        return
    years = fbs_window()
    raw = to_iso3(read_matrix(years, load_item_groups()))
    out = add_eu_bloc(partners(raw, years)).assign(years=f"{years[0]}-{years[1]}")
    dest = config.PROCESSED / "trade_partners.parquet"
    out.to_parquet(dest, index=False)
    log.info("wrote %s (%d rows)", dest, len(out))
