import pandas as pd
import pytest

from pipeline import trade

YEARS = (2022, 2023)


def _rows(rows):
    return pd.DataFrame(rows, columns=["reporter", "partner", "group", "flow", "year", "value"])


def test_mirror_flows_fill_only_unreported_country_years():
    df = _rows([
        # DEU reports its own imports in both years.
        ("DEU", "FRA", "cereals", "imports", 2022, 100.0),
        ("DEU", "FRA", "cereals", "imports", 2023, 300.0),
        # RUS reports nothing; KAZ and DEU say they sold to it.
        ("KAZ", "RUS", "cereals", "exports", 2022, 50.0),
        ("DEU", "RUS", "cereals", "exports", 2023, 10.0),
        # FRA's own export report must not be added to DEU's reported imports.
        ("FRA", "DEU", "cereals", "exports", 2022, 999.0),
    ])
    p = trade.partners(df, YEARS).set_index(["iso3", "flow", "partner"])
    assert p.loc[("DEU", "imports", "FRA"), "tonnes"] == pytest.approx(200.0)  # (100 + 300) / 2
    assert p.loc[("DEU", "imports", "FRA"), "source"] == "reported"
    assert p.loc[("RUS", "imports", "KAZ"), "tonnes"] == pytest.approx(25.0)
    assert p.loc[("RUS", "imports", "KAZ"), "source"] == "mirror"
    assert p.loc[("RUS", "imports", "DEU"), "tonnes"] == pytest.approx(5.0)


def test_eu_bloc_keeps_only_trade_with_non_members():
    p = pd.DataFrame([
        ("DEU", "fruit", "imports", "ESP", 500.0, "reported"),
        ("DEU", "fruit", "imports", "COL", 40.0, "reported"),
        ("FRA", "fruit", "imports", "COL", 60.0, "reported"),
        ("NOR", "fruit", "imports", "ESP", 10.0, "reported"),
    ], columns=["iso3", "group", "flow", "partner", "tonnes", "source"])
    eu = trade.add_eu_bloc(p)
    eu = eu[eu["iso3"] == "EU27"].set_index("partner")["tonnes"]
    assert eu.to_dict() == {"COL": 100.0}


def test_trade_item_mapping_covers_the_main_foods():
    items = trade.load_item_groups()
    assert items[15] == "cereals"  # Wheat
    assert items[236] == "oilseeds"  # Soya beans
    assert items[486] == "fruit"  # Bananas
    assert 238 not in items  # Cake of soya beans: feed, left out
    assert set(items.values()) <= {
        "cereals", "potatoes_roots", "sugar", "pulses", "oilseeds", "vegetable_oils", "vegetables",
        "fruit", "meat", "dairy", "eggs", "fish", "stimulants", "wine_beer",
    }


def test_trace_origins_sees_through_a_hub():
    # Brazil grows coffee and sells it to the Netherlands; the Netherlands grows none and sells
    # half of what it has to Germany. Germany's coffee "from the Netherlands" was grown in Brazil.
    p = pd.DataFrame([
        ("NLD", "stimulants", "imports", "BRA", 100.0, "reported"),
        ("DEU", "stimulants", "imports", "NLD", 50.0, "reported"),
        ("DEU", "stimulants", "imports", "COL", 50.0, "reported"),
    ], columns=["iso3", "group", "flow", "partner", "tonnes", "source"])
    fbs = pd.DataFrame([
        ("BRA", "stimulants", 1.0, 0.0),
        ("COL", "stimulants", 1.0, 0.0),
        ("NLD", "stimulants", 0.0, 0.1),
        ("DEU", "stimulants", 0.0, 0.1),
    ], columns=["iso3", "group", "production", "imports"])  # 1000 t
    o = trade.trace_origins(p, fbs)
    deu = o[o["iso3"] == "DEU"].set_index("partner")["tonnes"]
    assert set(deu.index) == {"BRA", "COL"}
    assert deu["BRA"] == pytest.approx(50.0)
    assert deu["COL"] == pytest.approx(50.0)
    assert (o["flow"] == "grown").all()
