"""pipeline.comext and pipeline.crosswalk on tiny synthetic frames (docs/methodology.md, "Comext")."""

import pandas as pd
import pytest

from pipeline import checks, comext, crosswalk

PARTNERS = {"DE": "DEU", "FR": "FRA", "NO": "NOR", "ES": "ESP", "XB": "ESP", "XU": "GBR"}


def _raw(rows):
    """reporter, partner, product, flow, year, q100 (100 kg), eur"""
    return pd.DataFrame(rows, columns=["reporter", "partner", "product", "flow", "year", "q100", "eur"])


HS = pd.DataFrame([
    {"version": 2017, "hs": "100199", "group": "cereals", "to_primary": ""},
    {"version": 2022, "hs": "100199", "group": "cereals", "to_primary": ""},
    {"version": 2017, "hs": "040221", "group": "dairy", "to_primary": "7.56"},
    {"version": 2022, "hs": "040221", "group": "dairy", "to_primary": "7.56"},
])
CF = pd.DataFrame([{"year": 2021, "cn8": "03044100", "cf": 1.6}, {"year": 2023, "cn8": "03044100", "cf": 1.7}])


def test_hs6_groups_and_factors():
    w = _raw([("DE", "FR", "040221", "1", 2021, 10.0, 1.0), ("DE", "FR", "100199", "2", 2023, 100.0, 1.0)])
    out = comext.convert(w, HS, CF, PARTNERS).set_index(["group", "flow"])
    assert out.loc[("dairy", "imports"), "tonnes"] == 1.0  # 10 x 100 kg
    assert out.loc[("dairy", "imports"), "primary"] == pytest.approx(7.56)
    assert out.loc[("cereals", "exports"), "primary"] == 10.0


def test_fish_takes_eumofa_factor_of_the_year_or_the_nearest_year():
    w = _raw([("DE", "NO", "03044100", "1", 2021, 10.0, 1.0),
              ("DE", "NO", "03044100", "1", 2022, 10.0, 1.0),  # not listed: nearest year
              ("DE", "NO", "03044100", "1", 2023, 10.0, 1.0)])
    out = comext.convert(w, HS, CF, PARTNERS).set_index("year")["primary"]
    assert out[2021] == pytest.approx(1.6)
    assert out[2022] == pytest.approx(1.6)  # equally near: the earlier year
    assert out[2023] == pytest.approx(1.7)


def test_fish_without_a_factor_is_left_out():
    w = _raw([("DE", "NO", "03011100", "1", 2021, 10.0, 1.0)])  # ornamental fish: no factor above 0
    assert comext.convert(w, HS, CF, PARTNERS).empty


def test_partner_codes_and_self_trade():
    w = _raw([("ES", "XB", "100199", "1", 2021, 10.0, 1.0),  # Spain with its Canary Islands
              ("DE", "XU", "100199", "1", 2021, 10.0, 1.0),  # the United Kingdom
              ("DE", "QV", "100199", "1", 2021, 10.0, 1.0)])  # confidential, intra-EU
    out = comext.convert(w, HS, CF, PARTNERS)
    assert set(out["reporter"]) == {"DEU"}
    assert dict(zip(out["partner"], out["country"])) == {"GBR": True, "QV": False}


def test_fish_extra_shares_count_unnamed_partners():
    y = pd.DataFrame([
        ("DEU", "NOR", True, "fish", "imports", 2021, 0, 60.0, 0),
        ("DEU", "FRA", True, "fish", "imports", 2021, 0, 20.0, 0),
        ("DEU", "QV", False, "fish", "imports", 2021, 0, 10.0, 0),  # intra-EU, unnamed
        ("DEU", "QZ", False, "fish", "imports", 2021, 0, 10.0, 0),  # extra-EU, unnamed
    ], columns=["reporter", "partner", "country", "group", "flow", "year", "tonnes", "primary", "eur"])
    s = comext.fish_extra_shares(y)
    assert s["share"].iloc[0] == pytest.approx(0.7)
    p = comext.fish_partners(y, (2021, 2021))
    assert set(p["partner"]) == {"NOR", "FRA"}  # unnamed partners are no list entries


def test_crosswalk_override_longest_prefix_wins_and_mixes_stop():
    overrides = {"0302": {"group": "fish", "to_primary": "eumofa", "note": "fresh fish"},
                 "030211": {"group": "", "to_primary": "", "note": "test"}}
    assert crosswalk.decide("030211", [], [], overrides)[0] == ""
    assert crosswalk.decide("030219", [], [], overrides)[0] == "fish"
    items = [{"cpc": "01234", "item": "A", "group": "vegetables", "to_primary": ""},
             {"cpc": "01234.01", "item": "B", "group": "fruit", "to_primary": ""}]
    with pytest.raises(ValueError):
        crosswalk.decide("070999", ["01234"], items, {})
    g, f, _ = crosswalk.decide("070999", ["01234"], items[:1], {})
    assert (g, f) == ("vegetables", "")


def test_all_food_trade_check_leaves_fish_out():
    p = pd.DataFrame([("A", "fish", "imports", "N", 900_000.0), ("A", "meat", "imports", "N", 100_000.0)],
                     columns=["iso3", "group", "flow", "partner", "tonnes"])
    g = pd.DataFrame([("A", "fish", 900.0, 0.0), ("A", "meat", 100.0, 0.0)],
                     columns=["iso3", "group", "imports", "exports"]).assign(basis="tonnes")
    v = checks.trade_verdicts(p, g).set_index(["iso3", "group", "flow"])
    assert v.loc[("A", "all", "imports"), "trade_kt"] == 100.0
    assert v.loc[("A", "all", "imports"), "balance_kt"] == 100.0
    assert ("A", "fish", "imports") in v.index


def test_hs_items_csv_is_what_the_generator_makes():
    if not (crosswalk.CPC_HS.exists() and crosswalk.HS22_17.exists()):
        pytest.skip("UNSD tables not downloaded (atlas download --source comext)")
    built = crosswalk.build()
    saved = pd.read_csv(crosswalk.OUT, comment="#", dtype=str, keep_default_na=False)
    assert saved.to_dict("records") == built.astype(str).to_dict("records"), "run `atlas crosswalk`"


def test_value_partners_mean_over_window_and_eu_bloc_outside_only():
    y = pd.DataFrame([
        ("DEU", "BRA", True, "stimulants", "imports", 2021, 1.0, 1.0, 300.0),
        ("DEU", "BRA", True, "stimulants", "imports", 2022, 1.0, 1.0, 600.0),
        ("DEU", "NLD", True, "stimulants", "imports", 2021, 1.0, 1.0, 900.0),
        ("DEU", "QV", False, "stimulants", "imports", 2021, 1.0, 1.0, 999.0),  # no country: left out
        ("FRA", "BRA", True, "stimulants", "imports", 2022, 1.0, 1.0, 300.0),
    ], columns=["reporter", "partner", "country", "group", "flow", "year", "tonnes", "primary", "eur"])
    v = comext.value_partners(y, (2021, 2023)).set_index(["iso3", "partner"])["eur"]
    assert v[("DEU", "BRA")] == pytest.approx(300.0)  # (300 + 600) / 3 years
    assert v[("DEU", "NLD")] == pytest.approx(300.0)
    assert ("DEU", "QV") not in v.index
    assert v[("EU27", "BRA")] == pytest.approx(400.0)  # members' purchases from outside the EU
    assert ("EU27", "NLD") not in v.index
