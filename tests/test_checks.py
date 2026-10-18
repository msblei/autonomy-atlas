"""Consistency verdicts on single balances (pipeline/checks.py), with FAO's real figures."""

import pandas as pd

from pipeline import checks
from pipeline.compute import add_ratios


def frame(**cols):
    return pd.DataFrame({k: [v] for k, v in cols.items()})


# Jordan, eggs, 2021-2023 average (kt): exports exceed production + imports, no stock change.
JORDAN_EGGS = {"production": 81.3, "imports": 3.0, "exports": 114.3, "supply": -30.0,
               "stock_variation": 0.0, "residuals": -107.3}


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


def test_usda_comparison_flags_large_gaps_only():
    from pipeline import usda

    fao = pd.DataFrame({"iso3": ["TUR", "DEU"], "item": ["Wheat and products"] * 2,
                        "production": [19800, 22000], "imports": [0, 0], "exports": [0, 0],
                        "supply": [32400, 19500], "ssr": [61.1, 112.8], "flag": ["", ""]})
    psd = pd.DataFrame({"iso3": ["TUR", "DEU"], "item": ["Wheat and products"] * 2,
                        "psd_commodity": ["Wheat"] * 2, "production": [18083, 22000],
                        "imports": [0, 0], "exports": [0, 0], "supply": [19600, 19000]})
    c = usda.compare(fao, psd).set_index("iso3")
    assert bool(c.loc["TUR", "large_gap"]) and not bool(c.loc["DEU", "large_gap"])
    assert round(c.loc["TUR", "ssr_usda"]) == 92


# ---- plausibility (docs/methodology.md, "Withheld as implausible") ----

def groups_frame(rows):
    cols = ["iso3", "group", "production", "imports", "supply", "population", "flag"]
    return pd.DataFrame(rows, columns=cols)


def test_use_per_person_above_ceiling_is_withheld():
    # New Zealand dairy before the milk-equivalent fix: 9.8 Mt used by 5.1 M people (1.9 t each)
    g = groups_frame([["NZL", "dairy", 22007, 417, 9814, 5130, ""]])
    v = checks.plausibility(g)
    assert list(v["test"]) == ["use_per_person"]
    # second reading: use at home at the ceiling, 550 kg x 5.13 M people
    assert abs(v["ssr_alt"].iloc[0] - 100 * 22007 / (0.55 * 5130)) < 1e-6


def test_ceiling_that_does_not_move_the_ratio_asks_nothing():
    # 10 kt over the ceiling on a big balance: the SSR barely moves
    g = groups_frame([["AAA", "meat", 100, 1600, 1610, 10000, ""]])  # 161 kg a person, ceiling 150
    assert checks.plausibility(g).empty  # 6.2% -> 6.7%: under 10 points and 10%


def test_imports_far_above_trade_records_against_the_typical_ratio():
    # four countries at 1.2x their records, one at 2.7x (United States fruit)
    rows = [[c, "fruit", 100, 120, 220, 1000, ""] for c in ("AAA", "BBB", "CCC", "DDD")]
    rows.append(["USA", "fruit", 19968, 50974, 64649, 333000, ""])
    trade = pd.Series({(c, "fruit"): 100.0 for c in ("AAA", "BBB", "CCC", "DDD")} | {("USA", "fruit"): 18813.0})
    v = checks.plausibility(groups_frame(rows), trade)
    assert list(v["iso3"]) == ["USA"]
    m_alt = 18813 * 1.2
    assert abs(v["ssr_alt"].iloc[0] - 100 * 19968 / (64649 - (50974 - m_alt))) < 1e-6


def test_withheld_for_another_reason_is_not_tested_but_own_verdict_is_retested():
    g = groups_frame([["NZL", "dairy", 22007, 417, 9814, 5130, "supply_nonpositive"],
                      ["IRL", "dairy", 8960, 1279, 4588, 5110, checks.IMPLAUSIBLE]])
    assert list(checks.plausibility(g)["iso3"]) == ["IRL"]
