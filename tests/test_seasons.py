"""pipeline.seasons on tiny synthetic frames (docs/methodology.md, "Seasons")."""

import numpy as np
import pandas as pd
import pytest

from pipeline import seasons


def test_month_of_day_on_a_365_day_year():
    m = seasons.month_of(np.array([1, 31, 32, 59, 60, 365, np.nan]))
    assert m.tolist() == [0, 0, 1, 1, 2, 11, -1]


def test_state_order_harvest_then_sowing_then_growing():
    assert seasons.state(sown=30, growing=100, harvest=25) == "harvest"
    assert seasons.state(sown=30, growing=100, harvest=10) == "sowing"
    assert seasons.state(sown=10, growing=60, harvest=10) == "growing"
    assert seasons.state(sown=10, growing=40, harvest=10) == ""


def _cal(iso3, crop, sown_m, harv_m, weight):
    rows = []
    for m in range(1, 13):
        rows.append((iso3, crop, m, 100.0 if m == sown_m else 0.0, 100.0, 100.0 if m == harv_m else 0.0, weight))
    return rows


def test_wheat_kinds_combine_by_area_and_rows_follow_production():
    s = pd.DataFrame(_cal("XXX", "wwh", 10, 8, 3.0) + _cal("XXX", "swh", 4, 9, 1.0)
                     + _cal("XXX", "mai", 4, 10, 1.0) + _cal("XXX", "rye", 10, 7, 1.0),
                     columns=["iso3", "crop", "month", "sown", "growing", "harvest", "weight"])
    items = pd.DataFrame([("XXX", "Wheat and products", 80.0), ("XXX", "Maize and products", 17.0),
                          ("XXX", "Rye and products", 3.0)], columns=["iso3", "item", "production"])
    groups = {"cereals": ["Wheat and products", "Maize and products", "Rye and products"]}
    rows = seasons.rows_for(s, items, groups)["XXX"]["cereals"]
    assert [r["label"] for r in rows] == ["Wheat", "Maize"]  # rye under 5% of the group
    wheat = rows[0]
    assert wheat["share"] == 80
    assert wheat["sown"][9] == 75 and wheat["sown"][3] == 25  # winter wheat has 3x the area
    assert wheat["harvest"][7] == 75 and wheat["harvest"][8] == 25


def test_sugar_shares_are_of_the_sugar_crops():
    s = pd.DataFrame(_cal("XXX", "sgb", 4, 10, 1.0),
                     columns=["iso3", "crop", "month", "sown", "growing", "harvest", "weight"])
    items = pd.DataFrame([("XXX", "Sugar beet", 10.0), ("XXX", "Sugar cane", 190.0)],
                         columns=["iso3", "item", "production"])
    assert seasons.rows_for(s, items, {})["XXX"]["sugar"][0]["share"] == pytest.approx(5)
    items.loc[0, "production"] = 5.0  # 2.5%: a cane country shows no strip
    assert "XXX" not in seasons.rows_for(s, items, {})
