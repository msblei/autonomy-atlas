"""Known facts about the real data (2021-2023 window), so a pipeline change that breaks them fails
loudly. Bounds are wide on purpose: they encode what is established outside this project (CLAUDE.md
pitfalls, DG AGRI, national statistics), not today's exact numbers. Skipped until `make all`."""

import pandas as pd
import pytest

from pipeline import config


def _load(name):
    path = config.PROCESSED / name
    if not path.exists():
        pytest.skip(f"{name} not built")
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def items():
    return _load("ssr_items.parquet").set_index(["iso3", "item"])


@pytest.fixture(scope="module")
def groups():
    g = _load("ssr_groups.parquet")
    return g[g["basis"] == "tonnes"].set_index(["iso3", "group"])


def test_poultry_france_below_eu_above(items):
    # CLAUDE.md: France below 100% in poultry since 2014, the EU as a bloc above.
    assert items.loc[("FRA", "Poultry Meat"), "ssr"] < 100
    assert items.loc[("EU27", "Poultry Meat"), "ssr"] > 100


def test_eu_soybeans_mostly_imported(items):
    # Beans only (FBS item); with soy meal the EU is near 15%.
    assert 10 < items.loc[("EU27", "Soyabeans"), "ssr"] < 30


def test_eu_cereals_about_self_sufficient(groups):
    assert 95 < groups.loc[("EU27", "cereals"), "ssr"] < 125


def test_netherlands_imports_most_cereals(groups):
    # Rotterdam: imports above domestic use, production a small share.
    r = groups.loc[("NLD", "cereals")]
    assert r["ssr"] < 25 and r["idr"] > 90


def test_jrc_replaces_fao_where_faos_trade_fails(items, groups):
    # Italy exports tomato paste: FAO 556%, the JRC about 200%.
    t = items.loc[("ITA", "Tomatoes and products")]
    assert t["jrc_food"] == "tomatoes" and 180 < t["ssr"] < 220
    # Germany exports cheese and powder: FAO makes it a net importer (89%), JRC-based above 100%.
    d = groups.loc[("DEU", "dairy")]
    assert d["source"] == "jrc_bal" and d["ssr"] > 100
    assert items.loc[("ESP", "Olive Oil"), "ssr"] > 150


def test_contradictory_balances_are_withheld(items, groups):
    # Jordan eggs: more exported than produced and imported.
    assert groups.loc[("JOR", "eggs"), "flag"] != ""
    assert pd.isna(groups.loc[("JOR", "eggs"), "ssr"])
    # Ukraine sunflower oil: more eaten than domestic supply. The group is withheld, but on any
    # reading Ukraine produces far more vegetable oil than it uses.
    assert items.loc[("UKR", "Sunflowerseed Oil"), "flag"] == "food_exceeds_supply"
    v = groups.loc[("UKR", "vegetable_oils")]
    assert pd.isna(v["ssr"]) and v["ssr_low"] > 500


def test_big_exporters_are_not_withheld(groups):
    # Iceland catches about 20 times the fish it eats: a fact, not an error.
    f = groups.loc[("ISL", "fish")]
    assert f["flag"] == "" and f["ssr"] > 1000
