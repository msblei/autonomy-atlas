"""Plausibility verdicts (docs/methodology.md, "Plausibility"): figures whose balance adds up but
that a second reading moves by a lot are withheld like contradictory ones.

Runs in `atlas build` after the trade partners exist (the second reading needs the trade
records): writes data/processed/plausibility.parquet, then compute.run() builds the balances
again with these figures withheld, in the window and in every single year, and trade.run() the
partner lists from them (they use only production and trade, which the verdicts do not change).
"""

from __future__ import annotations

import logging

import pandas as pd

from . import checks, config

log = logging.getLogger(__name__)

OUT = "plausibility.parquet"


def trade_imports(partners: pd.DataFrame) -> pd.Series:
    """kt bought abroad per (iso3, group) in the trade records (yearly mean over the window)."""
    p = partners[partners["flow"] == "imports"]
    return p.groupby(["iso3", "group"])["tonnes"].sum() / 1000


def own_records(partners: pd.DataFrame) -> set[tuple[str, str]]:
    """(iso3, group) pairs whose import records rest on the country's own reports only. Where a
    partner row is a mirror or mixed flow (trade.py: partners' reports for a year the country did
    not report, or for a group it under-reports), the records are a stopgap for the partner
    lists, not a yardstick for the balance: Russia 2022-2023, partners' reports hold a tenth of
    its dairy imports (methodology, "Withheld as implausible"). Such pairs still count in the
    group's typical ratio, which is a statistic over every record; they are not read against it."""
    p = partners[partners["flow"] == "imports"]
    if "source" not in p:
        return set(p.groupby(["iso3", "group"]).size().index)
    # fish records come from Comext and BACI ("comext", "baci"): a country's own records too
    own = p.groupby(["iso3", "group"])["source"].agg(lambda s: not s.isin(["mirror", "mixed"]).any())
    return set(own[own].index)


def verdicts() -> pd.DataFrame:
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    groups = groups[groups["basis"] == "tonnes"]
    src = config.PROCESSED / "trade_partners.parquet"
    imports = trade_imports(pd.read_parquet(src)) if src.exists() else None
    own = own_records(pd.read_parquet(src)) if src.exists() else None
    return checks.plausibility(groups, imports, own)


def load() -> dict[tuple[str, str], tuple[float, float]]:
    """(iso3, group) -> (ssr_low, ssr_high) over the published and second readings."""
    path = config.PROCESSED / OUT
    if not path.exists():
        return {}
    v = pd.read_parquet(path)
    both = pd.concat([v[["iso3", "group", "ssr"]],
                      v[["iso3", "group", "ssr_alt"]].rename(columns={"ssr_alt": "ssr"})])
    lo = both.groupby(["iso3", "group"])["ssr"].min()
    # a second reading without use at home (ssr_alt NaN) has no upper end
    hi = both.groupby(["iso3", "group"])["ssr"].max().where(v.groupby(["iso3", "group"])["ssr_alt"].count()
                                                             == v.groupby(["iso3", "group"]).size())
    return {k: (float(lo[k]), float(hi[k]) if pd.notna(hi[k]) else float("nan")) for k in lo.index}


def run(*, years: tuple[int, int] | None = None) -> None:
    from . import compute, trade

    v = verdicts()
    v.to_parquet(config.PROCESSED / OUT, index=False)
    log.info("plausibility: %d figures withheld (%s)", v[["iso3", "group"]].drop_duplicates().shape[0],
             ", ".join(f"{r.iso3} {r.group}" for r in v.drop_duplicates(["iso3", "group"]).head(12).itertuples()))
    compute.run(years=years)
    trade.run()
