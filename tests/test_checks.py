"""Consistency verdicts on single balances (pipeline/checks.py), with FAO's real figures."""

import pandas as pd

from pipeline import checks
from pipeline.compute import add_ratios


def frame(**cols):
    return pd.DataFrame({k: [v] for k, v in cols.items()})


# Jordan, eggs, 2021-2023 average (kt): exports exceed production + imports, no stock change.
JORDAN_EGGS = dict(production=81.3, imports=3.0, exports=114.3, supply=-30.0,
                   stock_variation=0.0, residuals=-107.3)


def test_jordan_eggs_is_withheld():
    assert checks.problems(frame(**JORDAN_EGGS)).iloc[0] == checks.SUPPLY_NONPOSITIVE
    out = add_ratios(frame(**JORDAN_EGGS))
    assert out["ssr"].isna().all() and out["idr"].isna().all()


def test_exports_beyond_what_was_available():
    # Positive supply, but more sold than produced and bought: still a contradiction.
    df = frame(production=80, imports=3, exports=110, supply=5, stock_variation=0)
    assert checks.problems(df).iloc[0] == checks.EXPORTS_EXCEED


def test_stock_drawdown_can_explain_exports():
    # Stock variation -40 (taken out of storage) makes 110 kt of exports possible.
    df = frame(production=80, imports=3, exports=110, supply=13, stock_variation=-40)
    assert checks.problems(df).iloc[0] == ""


def test_rounding_slack_is_not_a_contradiction():
    df = frame(production=100, imports=0, exports=101, supply=1, stock_variation=0)
    assert checks.problems(df).iloc[0] == ""


def test_big_exporter_is_not_withheld():
    # Iceland catches ~20x the fish it eats: a very high SSR is a fact, not an error.
    df = frame(production=1100, imports=60, exports=1110, supply=50, stock_variation=0)
    out = add_ratios(df)
    assert out["flag"].iloc[0] == "" and out["ssr"].iloc[0] > 1000


def test_large_residual_withholds_uses_not_ratio():
    # A large residual alone (no food line given) withholds the uses breakdown, not the ratio.
    df = frame(production=596, imports=56, exports=625, supply=27.7, residuals=-32.7)
    assert checks.problems(df).iloc[0] == ""
    assert bool(checks.uses_problem(df).iloc[0])
    small = frame(production=596, imports=56, exports=625, supply=27.7, residuals=-3)
    assert not bool(checks.uses_problem(small).iloc[0])


def test_more_eaten_than_available_is_withheld():
    # Ireland, beef 2016: 588 kt produced, 3 kt domestic supply, ~50 kt eaten (FAO's food line).
    df = frame(production=588, imports=40, exports=625, supply=3, stock_variation=0, food=50)
    assert checks.problems(df).iloc[0] == checks.FOOD_EXCEEDS


def test_group_ratio_that_rests_on_a_contradiction_is_withheld():
    # Uruguay meat: beef's supply (28 kt) is below what FAO says is eaten (60 kt).
    items = pd.DataFrame({
        "iso3": ["URY"] * 2, "group": ["meat"] * 2, "production": [596, 300],
        "supply": [27.7, 200], "food": [60.3, 150], "flag": [checks.FOOD_EXCEEDS, ""],
    })
    out = checks.parts_sensitivity(items, ["iso3", "group"]).iloc[0]
    assert bool(out["depends"]) and out["ssr_adj"] < out["ssr_pub"]
    assert out["ssr_adj"] > 100  # both readings: more than it uses


def test_small_contradiction_does_not_withhold_the_group():
    # Offals 1% of a big meat group: the group figure barely moves.
    items = pd.DataFrame({
        "iso3": ["NLD"] * 2, "group": ["meat"] * 2, "production": [300, 3200],
        "supply": [20, 1400], "food": [110, 1200], "flag": [checks.FOOD_EXCEEDS, ""],
    })
    assert not bool(checks.parts_sensitivity(items, ["iso3", "group"]).iloc[0]["depends"])
