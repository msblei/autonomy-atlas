"""checks.trade_verdicts and checks.unusual_years on tiny synthetic frames
(docs/methodology.md: "Trade records against the food balance", "Trends")."""

import pandas as pd

from pipeline import checks


def _partners(rows):
    return pd.DataFrame(rows, columns=["iso3", "group", "flow", "partner", "tonnes"])


def _groups(rows):
    return pd.DataFrame(rows, columns=["iso3", "group", "imports", "exports"]).assign(basis="tonnes")


def test_far_above_typical_and_above_balance_is_withheld():
    # Four countries at the dairy-typical ratio (records a fifth of the balance), one far above.
    p = _partners([(c, "dairy", "imports", "X", 20_000) for c in "ABCD"]
                  + [("E", "dairy", "imports", "X", 300_000)])
    g = _groups([(c, "dairy", 100.0, 0.0) for c in "ABCDE"])
    v = checks.trade_verdicts(p, g).set_index(["iso3", "group", "flow"])
    assert v.loc[("A", "dairy", "imports"), "verdict"] == ""
    assert v.loc[("E", "dairy", "imports"), "verdict"] == "withhold"  # 3.0 > 3 x 0.2 and > 1.5


def test_far_above_typical_but_below_balance_is_only_a_warning():
    # Raw milk weighs what it is: a ratio near 1 is far above dairy's typical but not implausible.
    p = _partners([(c, "dairy", "imports", "X", 20_000) for c in "ABCD"]
                  + [("E", "dairy", "imports", "X", 100_000)])
    g = _groups([(c, "dairy", 100.0, 0.0) for c in "ABCDE"])
    v = checks.trade_verdicts(p, g).set_index(["iso3", "group", "flow"])
    assert v.loc[("E", "dairy", "imports"), "verdict"] == "warn"


def test_far_below_typical_is_a_warning_and_small_pairs_are_skipped():
    p = _partners([(c, "cereals", "imports", "X", 100_000) for c in "ABCD"]
                  + [("E", "cereals", "imports", "X", 10_000), ("F", "cereals", "imports", "X", 5_000)])
    g = _groups([(c, "cereals", 100.0, 0.0) for c in "ABCDE"] + [("F", "cereals", 10.0, 0.0)])
    v = checks.trade_verdicts(p, g).set_index(["iso3", "group", "flow"])
    assert v.loc[("E", "cereals", "imports"), "verdict"] == "warn"
    assert ("F", "cereals", "imports") not in v.index  # neither side reaches 20 kt


def test_all_food_and_eu_bloc():
    p = _partners([("A", "sugar", "imports", "X", 50_000), ("A", "fruit", "imports", "X", 50_000),
                   ("EU27", "sugar", "imports", "X", 1_000_000)])
    g = _groups([("A", "sugar", 40.0, 0.0), ("A", "fruit", 60.0, 0.0), ("A", "fish", 900.0, 0.0),
                 ("EU27", "sugar", 1.0, 0.0)])
    v = checks.trade_verdicts(p, g).set_index(["iso3", "group", "flow"])
    assert v.loc[("A", "all", "imports"), "balance_kt"] == 100.0  # fish left out
    assert not (v.index.get_level_values("iso3") == "EU27").any()


def test_unusual_years():
    s = {2015: 63.0, 2016: 62.0, 2017: 292.0, 2018: 58.0, 2019: 52.0}
    assert checks.unusual_years(s) == [2017]
    assert checks.unusual_years({2015: 10.0, 2016: 2.0, 2017: 12.0}) == []  # below 5%
    assert checks.unusual_years({2015: 60.0, 2016: None, 2017: 200.0, 2018: 50.0}) == []  # gap
    assert checks.unusual_years({2015: 60.0, 2016: 15.0, 2017: 70.0}) == [2016]  # dip
