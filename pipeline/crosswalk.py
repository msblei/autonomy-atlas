"""HS6 product codes (Eurostat Comext) -> products.yaml groups, through FAO's trade items.

Writes pipeline/mappings/hs_items.csv, one row per HS version and HS6 code in chapters 01-24:
    version (2017 | 2022), hs, hs2017, group ("" = left out), to_primary, how

How a code is decided (methodology, "Comext"):
1. UN Statistics Division's CPC 2.1 <-> HS 2017 correspondence gives the CPC classes of each HS
   2017 code. FAO's trade items carry CPC 2.1 codes (some extended, "23120.01"; some one level
   up, "0111"): the items of those classes are the code's FAO items (trade_items.csv).
2. One group among them (FAO items left out of every group count as "-") and one factor: taken.
3. Everything else is decided by hand in mappings/hs_overrides.csv (longest prefix wins, and an
   override also wins over step 2). A code with several groups or factors and no override stops
   the generator; a code with no FAO item and no override is left out ("no FAO item").
4. HS 2022 codes take the decision of the HS 2017 code they convert to (UNSD conversion table);
   Comext reports 2021 in HS 2017 codes and 2022 on in HS 2022 codes.

Run `atlas crosswalk` after changing trade_items.csv or hs_overrides.csv; the raw tables come
with `atlas download --source comext`.
"""

from __future__ import annotations

import csv
import logging

import pandas as pd

from . import config

log = logging.getLogger(__name__)

UNSD_DIR = config.RAW / "unsd"
CPC_HS = UNSD_DIR / "CPC21-HS2017.csv"
HS22_17 = UNSD_DIR / "HS2022toHS2017ConversionAndCorrelationTables.xlsx"
OUT = config.MAPPINGS / "hs_items.csv"
FOOD_CHAPTERS = 24


def _rows(path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def load_overrides() -> dict[str, dict]:
    return {r["hs"]: r for r in _rows(config.MAPPINGS / "hs_overrides.csv")}


def override_for(hs: str, overrides: dict[str, dict]) -> dict | None:
    for n in range(len(hs), 1, -1):
        if hs[:n] in overrides:
            return overrides[hs[:n]]
    return None


def cpc_by_hs() -> dict[str, list[str]]:
    d = pd.read_csv(CPC_HS, dtype=str)
    d.columns = ["hs", "hs_partial", "cpc", "cpc_partial"]
    d["hs"] = d["hs"].str.replace(".", "", regex=False)
    d = d[d["hs"].str[:2].astype(int) <= FOOD_CHAPTERS]
    return d.groupby("hs")["cpc"].apply(list).to_dict()


def fao_items_for(cpc: str, items: list[dict]) -> list[dict]:
    """FAO trade items of a CPC 2.1 class: same class (FAO's extensions "23120.01" included), or a
    four-digit FAO code one level up ("0111" covers 01111 and 01112)."""
    out = []
    for it in items:
        base = it["cpc"].split(".")[0]
        if base == cpc or (len(base) == 4 and base.isdigit() and cpc.startswith(base)):
            out.append(it)
    return out


def decide(hs: str, cpcs: list[str], items: list[dict], overrides: dict) -> tuple[str, str, str]:
    """(group, to_primary, how) for one HS 2017 code; raises on an undecided mix."""
    o = override_for(hs, overrides)
    if o is not None:
        return o["group"], o["to_primary"], f"override: {o['note']}"
    cand = [it for c in cpcs for it in fao_items_for(c, items)]
    if not cand:
        return "", "", "no FAO item"
    groups = {it["group"] or "-" for it in cand}
    if len(groups) > 1:
        raise ValueError(f"{hs}: FAO items in several groups {sorted(groups)}; add it to hs_overrides.csv")
    group = groups.pop()
    if group == "-":
        return "", "", "FAO items outside the groups: " + "; ".join(sorted({it["item"] for it in cand}))
    factors = {it["to_primary"] or "1" for it in cand}
    if len(factors) > 1:
        raise ValueError(f"{hs}: factors {sorted(factors)}; add it to hs_overrides.csv")
    f = factors.pop()
    names = "; ".join(sorted({it["item"] for it in cand}))
    return group, "" if f == "1" else f, f"FAO items: {names}"


def build() -> pd.DataFrame:
    items = _rows(config.MAPPINGS / "trade_items.csv")
    overrides = load_overrides()
    by_hs = cpc_by_hs()
    rows, errors = [], []
    for hs, cpcs in sorted(by_hs.items()):
        try:
            g, f, how = decide(hs, cpcs, items, overrides)
        except ValueError as e:
            errors.append(str(e))
            continue
        rows.append({"version": 2017, "hs": hs, "hs2017": hs, "group": g, "to_primary": f, "how": how})
    if errors:
        raise ValueError("undecided HS codes:\n" + "\n".join(errors))
    d17 = pd.DataFrame(rows)
    conv = pd.read_excel(HS22_17, sheet_name="HS2022-HS2017 Conversions", dtype=str)
    conv.columns = ["hs", "hs2017"]
    # nicotine products (2404) came from outside the food chapters: not food either way
    conv = conv[(conv["hs"].str[:2].astype(int) <= FOOD_CHAPTERS)
                & (conv["hs2017"].str[:2].astype(int) <= FOOD_CHAPTERS)]
    d22 = conv.merge(d17.drop(columns=["version", "hs"]), on="hs2017", how="left")
    lost = d22["how"].isna()
    if lost.any():
        raise ValueError(f"HS 2022 codes converting to unknown HS 2017 codes: {list(d22.loc[lost, 'hs'])}")
    d22 = d22.assign(version=2022)
    return pd.concat([d17, d22[d17.columns]], ignore_index=True)


HEADER = """\
# HS6 codes (HS 2017 and HS 2022, chapters 01-24) -> products.yaml groups, for Eurostat Comext.
# GENERATED by `atlas crosswalk` (pipeline/crosswalk.py) from the UNSD CPC 2.1 <-> HS 2017
# correspondence, the UNSD HS 2022 -> HS 2017 conversion, trade_items.csv and hs_overrides.csv.
# Do not edit by hand: change hs_overrides.csv and regenerate. group empty = left out;
# to_primary empty = 1, "eumofa" = EUMOFA's live-weight factor per CN8 code and year, "cn8" =
# per CN8 code in cn8_items.csv.
"""


def run() -> None:
    d = build()
    with OUT.open("w", encoding="utf-8", newline="") as f:
        f.write(HEADER)
        d.to_csv(f, index=False)
    kept = d[d["group"] != ""]
    log.info("wrote %s: %d HS6 codes, %d in a group (%s)", OUT, len(d), len(kept),
             ", ".join(f"{g} {n}" for g, n in kept.groupby("group").size().items()))


def load() -> pd.DataFrame:
    """hs_items.csv with group set: version, hs, group, to_primary ("" = 1, "eumofa")."""
    d = pd.read_csv(OUT, comment="#", dtype=str, keep_default_na=False)
    d["version"] = d["version"].astype(int)
    return d[d["group"] != ""]
