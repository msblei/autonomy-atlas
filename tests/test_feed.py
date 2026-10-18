"""pipeline.feed on small cases (docs/methodology.md, "Feed")."""

import pandas as pd
import pytest

from pipeline import feed


def test_feed_table_is_plausible():
    items = feed.load_items()
    assert all(0 < v["protein"] < 0.7 for v in items.values())
    assert items[238]["parent"] == 236  # soy cake is made from soybeans
    assert all(v["parent"] is None or v["parent"] != k for k, v in items.items())


def test_eu_extra_shares_count_only_imports_from_outside():
    raw = pd.DataFrame([
        ("DEU", "BRA", 238, "imports", 2022, 300.0),
        ("DEU", "NLD", 238, "imports", 2022, 100.0),  # intra-EU
        ("FRA", "ARG", 238, "imports", 2022, 100.0),
        ("USA", "BRA", 238, "imports", 2022, 999.0),  # not a member
        ("DEU", "BRA", 238, "exports", 2022, 999.0),  # not an import
    ], columns=["reporter", "partner", "item_code", "flow", "year", "value"])
    s = feed.eu_extra_shares(raw).set_index(["item_code", "year"])["share"]
    assert s[(238, 2022)] == pytest.approx(0.8)
