"""Internal-consistency tests on a food balance: is a figure fit to show at all?

FAO's balances are sometimes contradictory in themselves: Jordan's eggs 2021-2023 list more sold
abroad (114 kt) than produced and bought together (84 kt) with no stock change, and close the gap
with a -107 kt "Residuals" line, leaving a negative domestic supply. A ratio computed from such a
balance is not a fact about Jordan, so it is withheld everywhere (map, rankings, trends) and the
UI explains why. One verdict per balance; every view uses it (docs/methodology.md, "Withheld").

Two separate verdicts, because a balance has two sides:

    availability:  domestic supply = production + imports - exports - stock change
    utilisation:   domestic supply = food + feed + seed + losses + processing + other + residuals

SSR and IDR use only the availability side, so `problems` tests only that. A large "Residuals"
line means FAO's breakdown of what the food is used for does not add up; it does not make the
ratio wrong, so `uses_problem` withholds only the breakdown (food, feed, ... and kg eaten).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Reason codes, most fundamental first; a balance gets the first one that applies.
SUPPLY_MISSING = "supply_missing"
SUPPLY_NONPOSITIVE = "supply_nonpositive"
EXPORTS_EXCEED = "exports_exceed_available"
FOOD_EXCEEDS = "food_exceeds_supply"
PARTS_CONTRADICT = "parts_contradict"
RESIDUALS_LARGE = "residuals_large"
REVIEWED = "reviewed"  # withheld by a human review (mappings/withheld_by_review.csv), not by a test

# Tolerances: FAO rounds to 1 kt, so a few kt or per cent of slack is noise, not a contradiction.
EXPORT_SLACK = 0.02  # exports may exceed production + imports - stock change by 2% ...
EXPORT_SLACK_KT = 1.0  # ... plus 1 kt
# Food is one of the uses of domestic supply, so it cannot be larger. FAO closes such balances with a
# negative residual (Ireland beef 2016: 3 kt supply, ~50 kt eaten). Slack for rounding:
FOOD_SLACK = 0.25
FOOD_SLACK_KT = 1.0
# A group SSR that moves by more than this when its contradictory items are read generously.
PARTS_PP = 10.0
PARTS_REL = 0.10
# Uses whose unexplained remainder is more than a quarter of domestic supply are not shown.
RESIDUAL_SHARE = 0.25
RESIDUAL_MIN_KT = 1.0


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name] if name in df else pd.Series(np.nan, index=df.index)


def problems(df: pd.DataFrame) -> pd.Series:
    """Reason code per row ("" when the ratio can be shown). Needs production, imports, exports,
    supply; uses stock_variation when present. Quantities in the same unit.

    A very high SSR is not a reason: Iceland catches about 20 times the fish it eats."""
    p, m, x = (_col(df, c).fillna(0) for c in ("production", "imports", "exports"))
    d = _col(df, "supply")
    food = _col(df, "food")
    dstock = _col(df, "stock_variation").fillna(0)
    # D = P + M - X - dS, so what can leave the country is P + M - dS (a stock draw-down is dS < 0).
    available = p + m - dstock
    conds = [
        (d.isna(), SUPPLY_MISSING),
        (d <= 0, SUPPLY_NONPOSITIVE),
        (x > available * (1 + EXPORT_SLACK) + EXPORT_SLACK_KT, EXPORTS_EXCEED),
        (food > d * (1 + FOOD_SLACK) + FOOD_SLACK_KT, FOOD_EXCEEDS),
    ]
    out = np.select([c.fillna(False).to_numpy(bool) for c, _ in conds], [r for _, r in conds],
                    default="")
    return pd.Series(out, index=df.index, dtype=object)


def uses_problem(df: pd.DataFrame) -> pd.Series:
    """True where FAO's breakdown of uses does not add up to domestic supply: |residuals| above
    RESIDUAL_SHARE of it (and above RESIDUAL_MIN_KT)."""
    d = _col(df, "supply").abs()
    r = _col(df, "residuals").fillna(0).abs()
    return ((r > RESIDUAL_SHARE * d) & (r > RESIDUAL_MIN_KT)).fillna(False)


def parts_sensitivity(items: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Per `keys` (iso3, group, ...): the group SSR as published (all items summed) and with each
    contradictory item's (`flag` set by `problems`) domestic supply raised to at least its food
    line, the least FAO's own figures say was used. Columns: ssr_pub, ssr_adj, depends (True when
    they differ by more than PARTS_PP points or PARTS_REL of ssr_adj: the figure rests on the
    contradiction)."""
    bad = items["flag"].fillna("") != ""
    d = items["supply"].fillna(0)
    floor = pd.concat([d, items["food"].fillna(0) if "food" in items else d * 0,
                       pd.Series(0.0, index=items.index)], axis=1).max(axis=1)
    t = pd.DataFrame({**{k: items[k] for k in keys},
                      "p": items["production"].fillna(0), "d": d, "d_adj": floor.where(bad, d)})
    g = t.groupby(keys)[["p", "d", "d_adj"]].sum()
    out = pd.DataFrame({
        "ssr_pub": (100 * g["p"] / g["d"].where(g["d"] > 0)),
        "ssr_adj": (100 * g["p"] / g["d_adj"].where(g["d_adj"] > 0)),
    })
    diff = (out["ssr_pub"] - out["ssr_adj"]).abs()
    out["depends"] = (diff > np.maximum(PARTS_PP, PARTS_REL * out["ssr_adj"])) | (
        out["ssr_pub"].isna() != out["ssr_adj"].isna())
    return out


# ------------------------------------------------------------------------------------------------
# Trade records against the food balance (docs/methodology.md, same section). Trade records count
# product weight, the balance primary equivalent, so each food group has its own typical ratio
# between them (dairy about a fifth: a tonne of cheese is about eight of milk). A country far
# from it is worth a look; one whose records are far above it and above the balance itself
# describes transit or misreporting, not its own trade, and is withheld.

TRADE_BAND = 3.0  # warn beyond 3x either side of the group's typical ratio
TRADE_OVER_BALANCE = 1.5  # withhold only if, above the band, the records exceed the balance by half
TRADE_MIN_KT = 20.0  # compare a pair only if either side reaches this


def trade_verdicts(partners: pd.DataFrame, groups: pd.DataFrame, eu_bloc: str = "EU27") -> pd.DataFrame:
    """One row per compared country × group × flow (imports, exports; group "all" for all food):
    iso3, group, flow, trade_kt, balance_kt, ratio, typical, verdict ("" | "warn" | "withhold").

    `partners`: trade_partners rows (iso3, group, flow, partner, tonnes); `groups`: ssr_groups rows
    on the tonnes basis (iso3, group, imports, exports in kt, as published or listed as withheld).
    """
    t = partners[partners["flow"].isin(["imports", "exports"]) & (partners["iso3"] != eu_bloc)]
    g = groups[(groups["basis"] == "tonnes") & (groups["iso3"] != eu_bloc) & (groups["group"] != "fish")]
    rows = []
    for flow in ("imports", "exports"):
        tf = t[t["flow"] == flow]
        trade = tf.groupby(["iso3", "group"])["tonnes"].sum() / 1000
        bal = g.set_index(["iso3", "group"])[flow]
        pairs = [pd.concat([trade.rename("trade_kt"), bal.rename("balance_kt")], axis=1, join="inner")]
        trade_all = tf.groupby("iso3")["tonnes"].sum() / 1000
        bal_all = g.groupby("iso3")[flow].sum(min_count=1)
        a = pd.concat([trade_all.rename("trade_kt"), bal_all.rename("balance_kt")], axis=1, join="inner")
        a.index = pd.MultiIndex.from_arrays([a.index, ["all"] * len(a)], names=["iso3", "group"])
        pairs.append(a)
        j = pd.concat(pairs).dropna()
        j = j[(j["balance_kt"] > 0) & ((j["balance_kt"] > TRADE_MIN_KT) | (j["trade_kt"] > TRADE_MIN_KT))]
        j = j.assign(ratio=j["trade_kt"] / j["balance_kt"], flow=flow)
        j["typical"] = j.groupby(level="group")["ratio"].transform("median")
        high, low = j["ratio"] > TRADE_BAND * j["typical"], j["ratio"] < j["typical"] / TRADE_BAND
        # "" = nothing to say (pandas would turn None into NaN)
        j["verdict"] = np.where(high & (j["ratio"] > TRADE_OVER_BALANCE), "withhold",
                                np.where(high | low, "warn", ""))
        rows.append(j.reset_index())
    out = pd.concat(rows, ignore_index=True)
    return out[["iso3", "group", "flow", "trade_kt", "balance_kt", "ratio", "typical", "verdict"]]


# ------------------------------------------------------------------------------------------------
# Unusual years in a trend (docs/methodology.md, "Trends"): a single year more than 3x, or less
# than a third of, both neighbours (all three at least 5%) is far more likely an error in FAO's
# figures than a harvest. Kept in the series, marked for the chart.

TREND_JUMP = 3.0
TREND_MIN = 5.0


def unusual_years(by_year: dict) -> list[int]:
    """Years of {year: value} (None/NaN = missing) that stand out from both neighbours."""
    def val(y):
        v = by_year.get(y)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else v

    out = []
    for y in sorted(by_year):
        a, b, c = val(y - 1), val(y), val(y + 1)
        if a is None or b is None or c is None or min(a, b, c) < TREND_MIN:
            continue
        if b > TREND_JUMP * max(a, c) or b * TREND_JUMP < min(a, c):
            out.append(int(y))
    return out



def reviewed_withholds() -> dict[tuple[str, str], str]:
    """(iso3, group) -> note, from mappings/withheld_by_review.csv (methodology, "Withheld by
    review"): figures withheld after a human review although their balance adds up."""
    import csv

    from . import config

    path = config.MAPPINGS / "withheld_by_review.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {(r["iso3"], r["group"]): r["note"] for r in rows}
