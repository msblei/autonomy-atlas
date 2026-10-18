"""pipeline.scenario on tiny synthetic frames (docs/methodology.md, "Scenario")."""

import pandas as pd
import pytest

from pipeline import scenario


def _groups(rows):
    return pd.DataFrame(rows, columns=["iso3", "group", "production", "imports", "exports", "supply", "flag"]).assign(
        basis="tonnes")


def test_transit_does_not_count_as_use():
    # 100 produced, 900 bought (half grown in Ukraine), 800 sold on, 200 used: an even mix
    g = _groups([("SVN", "cereals", 100.0, 900.0, 800.0, 200.0, "")])
    p = pd.DataFrame([("SVN", "cereals", "grown", "UKR", 450_000.0), ("SVN", "cereals", "grown", "SRB", 450_000.0),
                      ("SVN", "cereals", "imports", "SRB", 900_000.0)],
                     columns=["iso3", "group", "flow", "partner", "tonnes"])
    items = pd.DataFrame([("SVN", "Wheat and products", 10.0)], columns=["iso3", "item", "protein"])
    out = scenario.compute(p, g, items, {"groups": {"cereals": {"items": ["Wheat and products"]}}})
    lack = out.set_index(["iso3", "group"])["lack"]
    assert lack[("SVN", "cereals")] == pytest.approx(45.0)  # 900 x 0.5 / (100 + 900), not / 200
    assert lack[("SVN", "all")] == pytest.approx(45.0)


def test_no_figure_for_the_two_sellers_or_withheld_foods():
    g = _groups([("RUS", "cereals", 100.0, 1.0, 50.0, 51.0, ""), ("XXX", "cereals", 1.0, 1.0, 0.0, 2.0, "parts_contradict")])
    p = pd.DataFrame(columns=["iso3", "group", "flow", "partner", "tonnes"])
    items = pd.DataFrame(columns=["iso3", "item", "protein"])
    assert scenario.compute(p, g, items, {"groups": {}}).empty
