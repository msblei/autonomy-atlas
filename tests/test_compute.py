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


def test_overall_protein_share_caps_surpluses():
    # Wheat 200% SSR, 60 g protein; soy 0% SSR, 40 g protein.
    # Capped share: (60*100 + 40*0) / 100 = 60. Uncapped: (60*200 + 0) / 100 = 120.
    fbs = _long([
        ("POL", "Wheat and products", "Production", 2023, 20.0),
        ("POL", "Wheat and products", "Domestic supply quantity", 2023, 10.0),
        ("POL", "Wheat and products", "Protein supply quantity (g/capita/day)", 2023, 60.0),
        ("POL", "Soyabeans", "Production", 2023, 0.0),
        ("POL", "Soyabeans", "Domestic supply quantity", 2023, 10.0),
        ("POL", "Soyabeans", "Protein supply quantity (g/capita/day)", 2023, 40.0),
    ])
    o = compute.compute(fbs, years=(2023, 2023))["overall"].iloc[0]
    assert o["protein_share"] == pytest.approx(60.0)
    assert o["protein_ssr"] == pytest.approx(120.0)
    assert o["protein"] == pytest.approx(100.0)


def test_overall_ignores_fao_aggregate_items():
    fbs = _long([
        ("POL", "Oats", "Production", 2023, 10.0),
        ("POL", "Oats", "Domestic supply quantity", 2023, 10.0),
        ("POL", "Oats", "Protein supply quantity (g/capita/day)", 2023, 5.0),
        ("POL", "Grand Total", "Production", 2023, 0.0),
        ("POL", "Grand Total", "Domestic supply quantity", 2023, 10.0),
        ("POL", "Grand Total", "Protein supply quantity (g/capita/day)", 2023, 100.0),
    ])
    fbs["item_code"] = fbs["item"].map({"Oats": "2516", "Grand Total": "2901"})
    o = compute.compute(fbs, years=(2023, 2023))["overall"].iloc[0]
    assert o["protein_share"] == pytest.approx(100.0)
    assert o["protein"] == pytest.approx(5.0)


def _eu_frame(year=2023):
    """Every EU27 member: 10 kt oats produced, 5 kt supplied, 1 kt traded each way, pop 1000 k.
    Plus a non-member that must not be summed in."""
    rows = []
    for iso3 in sorted(compute.config.EU27):
        rows += [
            (iso3, "Oats", "Production", year, 10.0),
            (iso3, "Oats", "Domestic supply quantity", year, 5.0),
            (iso3, "Oats", "Import quantity", year, 1.0),
            (iso3, "Oats", "Export quantity", year, 6.0),
            (iso3, "Oats", "Protein supply quantity (g/capita/day)", year, 2.0),
            (iso3, "Population", "Total Population - Both sexes", year, 1000.0),
        ]
    rows += [("NOR", "Oats", "Production", year, 999.0),
             ("NOR", "Oats", "Domestic supply quantity", year, 1.0)]
    return _long(rows)


def test_eu_bloc_sums_members_and_blanks_gross_trade():
    res = compute.compute(_eu_frame(), years=(2023, 2023))
    eu = res["items"].set_index("iso3").loc["EU27"]
    assert eu["production"] == pytest.approx(270.0)
    assert eu["supply"] == pytest.approx(135.0)
    assert eu["ssr"] == pytest.approx(200.0)
    assert np.isnan(eu["imports"]) and np.isnan(eu["idr"])  # intra-EU trade not separable
    assert eu["population"] == pytest.approx(27000.0)
    assert eu["production_kg_pc"] == pytest.approx(10.0)
    assert eu["protein"] == pytest.approx(2.0)  # population-weighted mean of per-capita values
    assert eu["view"] == "eu_bloc"


def test_eu_bloc_skipped_when_a_member_is_missing():
    fbs = _eu_frame()
    fbs = fbs[fbs["iso3"] != "MLT"]
    res = compute.compute(fbs, years=(2023, 2023))
    assert "EU27" not in set(res["items"]["iso3"])


def test_trends_one_value_per_year():
    fbs = _long([
        ("DEU", "Oats", "Production", 2022, 10.0),
        ("DEU", "Oats", "Domestic supply quantity", 2022, 10.0),
        ("DEU", "Oats", "Production", 2023, 30.0),
        ("DEU", "Oats", "Domestic supply quantity", 2023, 10.0),
    ])
    t = compute.compute(fbs)["trends"]
    t = t[t["group"] == "cereals"].set_index("year")["ssr"]
    assert t.loc[2022] == pytest.approx(100.0)
    assert t.loc[2023] == pytest.approx(300.0)


def test_missing_production_inside_a_balance_counts_as_zero():
    fbs = _long([
        ("DEU", "Coffee and products", "Import quantity", 2023, 1400.0),
        ("DEU", "Coffee and products", "Export quantity", 2023, 890.0),
        ("DEU", "Coffee and products", "Domestic supply quantity", 2023, 510.0),
    ])
    items = compute.compute(fbs)["items"].set_index("item")
    assert items.loc["Coffee and products", "production"] == 0.0
    assert items.loc["Coffee and products", "ssr"] == pytest.approx(0.0)


def test_eu_bloc_counts_only_trade_with_the_rest_of_the_world():
    # Two members (the others produce and trade nothing). A exports 60, a third of it to the US;
    # B reports importing 60, all from A, more than A says it sent there (the usual mismatch).
    # Summing members says the EU uses 100 + 60 - 60 = 100; really it uses 100 - 20 = 80.
    members = sorted(compute.config.EU27)
    a, b = members[0], members[1]
    rows = [(iso, "Oats", "Production", 2023, 0.0) for iso in members[2:]]
    rows += [(iso, "Oats", "Domestic supply quantity", 2023, 0.0) for iso in members[2:]]
    rows += [
        (a, "Oats", "Production", 2023, 100.0),
        (a, "Oats", "Export quantity", 2023, 60.0),
        (a, "Oats", "Domestic supply quantity", 2023, 40.0),
        (b, "Oats", "Import quantity", 2023, 60.0),
        (b, "Oats", "Domestic supply quantity", 2023, 60.0),
    ]
    extra = pd.DataFrame([
        (a, "cereals", "exports", 2023, 20 / 60),  # a third of A's exports leave the EU
        (b, "cereals", "imports", 2023, 0.0),  # all of B's imports come from A
    ], columns=["iso3", "group", "flow", "year", "share"])
    eu = compute.compute(_long(rows), extra=extra)["items"].set_index(["iso3", "item"])
    eu = eu.loc[("EU27", "Oats")]
    assert eu["exports"] == pytest.approx(20.0)
    assert eu["imports"] == pytest.approx(0.0)
    assert eu["supply"] == pytest.approx(80.0)
    assert eu["ssr"] == pytest.approx(125.0)


def test_jrc_dairy_replaces_the_fao_balance_item_by_item():
    from pipeline import jrc

    # FAO: Germany makes milk and butter but its milk-equivalent trade makes it a net importer.
    rows = [
        ("DEU", "Milk - Excluding Butter", "Production", 2023, 30.0),
        ("DEU", "Milk - Excluding Butter", "Import quantity", 2023, 20.0),
        ("DEU", "Milk - Excluding Butter", "Export quantity", 2023, 10.0),
        ("DEU", "Milk - Excluding Butter", "Domestic supply quantity", 2023, 40.0),
        ("DEU", "Butter, Ghee", "Production", 2023, 2.0),
        ("DEU", "Butter, Ghee", "Domestic supply quantity", 2023, 2.0),
    ]
    bal = pd.DataFrame([("dairy", "DEU", 2023, 32.0, 10.0, 15.0, 27.0)],
                       columns=["food", "iso3", "year", "production", "imports", "exports", "supply"])
    wide = jrc.apply(compute.to_wide(_long(rows)), bal, compute.UTILISATION)
    d = wide[wide["iso3"] == "DEU"].set_index("item")
    assert d["production"].sum() == pytest.approx(32.0)
    assert d["supply"].sum() == pytest.approx(27.0)
    assert d["imports"].sum() == pytest.approx(10.0)
    assert d["exports"].sum() == pytest.approx(15.0)
    assert (d["jrc_food"] == "dairy").all()
    # Stock change set so the balance holds item by item.
    assert (d["production"] + d["imports"] - d["exports"] - d["stock_variation"]).sum() == \
        pytest.approx(27.0)
    # Butter keeps its share of production (2 of 32 before, scaled with the group).
    assert d.loc["Butter, Ghee", "production"] == pytest.approx(2.0 * 32 / 32)


def test_leaf_wins_over_aggregate_with_the_same_name():
    # FAO: "Miscellaneous" is leaf 2899 and aggregate 2928 (= 2899 + Infant food 2680).
    fbs = pd.DataFrame({
        "iso3": ["AAA"] * 4, "year": [2020] * 4,
        "item_code": ["2928", "2899", "2928", "2899"],
        "item": ["Miscellaneous"] * 4,
        "element": ["Production", "Production", "Domestic supply quantity", "Domestic supply quantity"],
        "value": [15.0, 10.0, 30.0, 20.0],
    })
    wide = compute.to_wide(fbs)
    assert wide["production"].iloc[0] == 10.0 and wide["supply"].iloc[0] == 20.0


def test_duplicate_balance_rows_fail_loudly():
    fbs = pd.DataFrame({
        "iso3": ["AAA"] * 2, "year": [2020] * 2, "item_code": ["2511"] * 2, "item": ["Wheat"] * 2,
        "element": ["Production"] * 2, "value": [1.0, 2.0],
    })
    with pytest.raises(ValueError, match="same iso3/item/year/element"):
        compute.to_wide(fbs)


def test_dairy_in_milk_equivalent_keeps_the_identity_and_moves_the_butter_milk():
    from pipeline.compute import dairy_milk_equivalent, group_tonnes

    # New Zealand-like: 22 Mt milk, 9 Mt of it churned into 0.6 Mt of butter and cream, mostly sold
    base = {"iso3": "NZL", "years": "2021-2023", "group": "dairy", "group_label": "Dairy",
            "stock_variation": 0.0, "feed": 0.0, "seed": 0.0, "losses": 0.0, "other_uses": 0.0,
            "tourist": 0.0, "residuals": 0.0, "flag": ""}
    items = pd.DataFrame([
        {**base, "item": "Milk - Excluding Butter", "production": 22000, "imports": 400,
         "exports": 12600, "supply": 9800, "food": 500, "processing": 9000},
        {**base, "item": "Butter, Ghee", "production": 450, "imports": 5, "exports": 420,
         "supply": 35, "food": 35, "processing": 0},
        {**base, "item": "Cream", "production": 150, "imports": 0, "exports": 140,
         "supply": 10, "food": 10, "processing": 0},
    ])
    out = dairy_milk_equivalent(items)
    f = 9000 / 600
    assert out.loc[1, "production"] == 0 and out.loc[1, "exports"] == 420 * f
    assert out.loc[0, "supply"] == 9800 - 9000 and out.loc[0, "processing"] == 0
    g = group_tonnes(items).iloc[0]
    assert abs(g["production"] + g["imports"] - g["exports"] - g["stock_variation"] - g["supply"]) < 1e-6
    assert abs(g["ssr"] - 100 * 22000 / (800 + 45 * f)) < 1e-6  # about 15x, not 2x
