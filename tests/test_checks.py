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
    # Uruguay beef: residual -33 kt against 28 kt used. The uses do not add up; the ratio stands.
    df = frame(production=596, imports=56, exports=625, supply=27.7, residuals=-32.7)
    assert checks.problems(df).iloc[0] == ""
    assert bool(checks.uses_problem(df).iloc[0])
    small = frame(production=596, imports=56, exports=625, supply=27.7, residuals=-3)
    assert not bool(checks.uses_problem(small).iloc[0])
