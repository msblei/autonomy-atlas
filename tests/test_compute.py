import numpy as np
import pandas as pd
import pytest

from pipeline import compute


def _long(rows):
    """rows: (iso3, item, element, year, value) -> long FBS frame."""
    return pd.DataFrame(rows, columns=["iso3", "item", "element", "year", "value"])


def test_ratio_basic_and_guards():
    num = pd.Series([50.0, 10.0, 5.0, 1.0])
    sup = pd.Series([100.0, 0.0, -3.0, np.nan])
    r = compute.ratio(num, sup)
    assert r.iloc[0] == pytest.approx(50.0)
    assert np.isnan(r.iloc[1])  # zero supply -> NaN, not inf
    assert np.isnan(r.iloc[2])  # negative supply -> NaN
    assert np.isnan(r.iloc[3])


def test_ssr_idr_single_year():
    fbs = _long([
        ("FRA", "Wheat and products", "Production", 2023, 40.0),
        ("FRA", "Wheat and products", "Import quantity", 2023, 2.0),
        ("FRA", "Wheat and products", "Export quantity", 2023, 22.0),
        ("FRA", "Wheat and products", "Domestic supply quantity", 2023, 20.0),
        ("FRA", "Wheat and products", "Food supply (kcal/capita/day)", 2023, 600.0),
    ])
    res = compute.compute(fbs, years=(2023, 2023))
    row = res["items"].iloc[0]
    assert row["ssr"] == pytest.approx(200.0)
    assert row["idr"] == pytest.approx(10.0)
    assert row["group"] == "cereals"


def test_window_averages_components_not_ratios():
    # Year 1: P=10, D=10 (SSR 100). Year 2: P=30, D=10 (SSR 300).
    # Component average: P=20, D=10 -> SSR 200. Averaging ratios would also give 200 here,
    # so use unequal supply to tell them apart: Year 2 D=30 (SSR 100).
    fbs = _long([
        ("DEU", "Oats", "Production", 2022, 10.0),
        ("DEU", "Oats", "Domestic supply quantity", 2022, 10.0),
        ("DEU", "Oats", "Production", 2023, 30.0),
        ("DEU", "Oats", "Domestic supply quantity", 2023, 30.0),
    ])
    res = compute.compute(fbs, years=(2022, 2023))
    row = res["items"].iloc[0]
    # components: P=20, D=20 -> 100. (ratio-of-averages == average-of-ratios here; the
    # point is that it does not blow up and uses the window label)
    assert row["ssr"] == pytest.approx(100.0)
    assert row["years"] == "2022-2023"


def test_group_tonnes_sums_components():
    fbs = _long([
        ("ESP", "Apples and products", "Production", 2023, 50.0),
        ("ESP", "Apples and products", "Domestic supply quantity", 2023, 50.0),
        ("ESP", "Bananas", "Production", 2023, 0.0),
        ("ESP", "Bananas", "Domestic supply quantity", 2023, 50.0),
    ])
    res = compute.compute(fbs, years=(2023, 2023))
    g = res["groups"]
    t = g[(g["group"] == "fruit") & (g["basis"] == "tonnes")].iloc[0]
    assert t["ssr"] == pytest.approx(50.0)  # (50+0)/(50+50)


def test_group_kcal_weights_by_calories():
    fbs = _long([
        ("ESP", "Apples and products", "Production", 2023, 50.0),
        ("ESP", "Apples and products", "Domestic supply quantity", 2023, 50.0),
        ("ESP", "Apples and products", "Food supply (kcal/capita/day)", 2023, 30.0),
        ("ESP", "Bananas", "Production", 2023, 0.0),
        ("ESP", "Bananas", "Domestic supply quantity", 2023, 50.0),
        ("ESP", "Bananas", "Food supply (kcal/capita/day)", 2023, 10.0),
    ])
    res = compute.compute(fbs, years=(2023, 2023))
    g = res["groups"]
    k = g[(g["group"] == "fruit") & (g["basis"] == "kcal")].iloc[0]
    assert k["ssr"] == pytest.approx(75.0)  # (100*30 + 0*10) / 40


def test_nonpositive_supply_is_flagged_not_clipped():
    fbs = _long([
        ("NLD", "Cocoa Beans and products", "Production", 2023, 0.0),
        ("NLD", "Cocoa Beans and products", "Import quantity", 2023, 900.0),
        ("NLD", "Cocoa Beans and products", "Export quantity", 2023, 950.0),
        ("NLD", "Cocoa Beans and products", "Domestic supply quantity", 2023, -50.0),
    ])
    res = compute.compute(fbs, years=(2023, 2023))
    row = res["items"].iloc[0]
    assert np.isnan(row["ssr"]) and np.isnan(row["idr"])
    assert row["flag"] == "supply_nonpositive"


def test_per_capita_uses_fbs_population():
    # 8000 kt of wheat for 80 million people (80 000 thousand) -> 100 kg/person/year.
    fbs = _long([
        ("DEU", "Wheat and products", "Production", 2023, 8000.0),
        ("DEU", "Wheat and products", "Domestic supply quantity", 2023, 4000.0),
        ("DEU", "Wheat and products", "Food", 2023, 1600.0),
        ("DEU", "Population", "Total Population - Both sexes", 2023, 80000.0),
    ])
    res = compute.compute(fbs, years=(2023, 2023))
    row = res["items"].iloc[0]
    assert len(res["items"]) == 1  # Population is not an item of its own
    assert row["production_kg_pc"] == pytest.approx(100.0)
    assert row["supply_kg_pc"] == pytest.approx(50.0)
    assert row["food_kg_pc"] == pytest.approx(20.0)
    g = res["groups"]
    t = g[(g["group"] == "cereals") & (g["basis"] == "tonnes")].iloc[0]
    assert t["production_kg_pc"] == pytest.approx(100.0)


def test_per_capita_is_nan_without_population():
    fbs = _long([
        ("DEU", "Oats", "Production", 2023, 10.0),
        ("DEU", "Oats", "Domestic supply quantity", 2023, 10.0),
    ])
    res = compute.compute(fbs, years=(2023, 2023))
    assert np.isnan(res["items"].iloc[0]["production_kg_pc"])
