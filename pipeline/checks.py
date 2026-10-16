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
