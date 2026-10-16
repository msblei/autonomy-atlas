"""Pipeline data against values read from FAOSTAT's live website (tests/golden/). Skipped when
the data has not been built (`make all`)."""

import pandas as pd
import pytest

from pipeline import config

GOLDEN = config.ROOT / "tests" / "golden" / "fao_live_fbs_2021_2023.csv"
ELEMENT = {"P": "Production", "M": "Import quantity", "X": "Export quantity",
           "D": "Domestic supply quantity", "POP": "Total Population - Both sexes",
           "KCAL": "Food supply (kcal/capita/day)", "PROT": "Protein supply quantity (g/capita/day)"}
COMPONENT = {"P": "production", "M": "imports", "X": "exports", "D": "supply"}


@pytest.fixture(scope="module")
def golden():
    return pd.read_csv(GOLDEN, comment="#", dtype={"item_code": str})


def _need(path):
    if not path.exists():
        pytest.skip(f"{path.name} not built")
    return pd.read_parquet(path)


def test_harmonised_fbs_matches_fao_live(golden):
    fbs = _need(config.INTERIM / "fbs.parquet")
    fbs = fbs[fbs["year"].between(2021, 2023)].assign(
        code=fbs["item_code"].astype(str).str.lstrip("'S"))
    ours = fbs.groupby(["iso3", "code", "element"])["value"].sum()
    bad = []
    for r in golden.itertuples():
        v = ours.get((r.iso3, r.item_code, ELEMENT[r.element]), 0.0)
        if abs(v - r.sum_2021_2023) > 0.006:
            bad.append((r.iso3, r.item_code, r.element, v, r.sum_2021_2023))
    assert not bad, f"{len(bad)} values differ from FAOSTAT, e.g. {bad[:5]}"


def test_window_averages_match_fao_live(golden):
    """ssr_items holds 3-year means: FAO's sum / 3, wherever FAO is the source (not the JRC). A year
    FAO leaves out inside an existing balance counts as zero (Jordan's sunflower oil exports 2023),
    so the divisor is the window, not the number of FAO rows."""
    items = _need(config.PROCESSED / "ssr_items.parquet")
    fbs = _need(config.INTERIM / "fbs.parquet")
    names = (fbs.assign(code=fbs["item_code"].astype(str).str.lstrip("'S"))
             .drop_duplicates("code").set_index("code")["item"])
    if "jrc_food" in items:
        items = items[items["jrc_food"].isna()]
    it = items.set_index(["iso3", "item"])
    checked, bad = 0, []
    for r in golden[golden["element"].isin(COMPONENT)].itertuples():
        key = (r.iso3, names.get(r.item_code))
        if key not in it.index:
            continue
        v = it.loc[key, COMPONENT[r.element]]
        checked += 1
        if abs(v - r.sum_2021_2023 / 3) > 0.006:
            bad.append((*key, r.element, round(v, 3), r.sum_2021_2023 / 3))
    assert checked > 1000
    assert not bad, f"{len(bad)} averages differ from FAOSTAT, e.g. {bad[:5]}"
