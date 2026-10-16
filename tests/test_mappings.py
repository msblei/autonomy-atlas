from pipeline.harmonise import load_countries


def test_countries_unique_and_europe_core_kept():
    c = load_countries()
    assert not c["iso3"].duplicated().any()
    assert not c["m49"].duplicated().any()
    assert c["europe"].sum() == 41
    assert len(c) > 170
    # Europe rows keep their hand-maintained names and groups, not the FAO/world ones.
    nld = c.set_index("iso3").loc["NLD"]
    assert nld["name"] == "Netherlands" and nld["group"] == "EU27"


def test_exported_groups_carry_fao_items_and_plain_notes():
    from pipeline.export import group_entries
    from pipeline.harmonise import load_products

    groups = {g["key"]: g for g in group_entries(load_products()["groups"])}
    assert next(iter(groups)) == "all"
    assert "Wheat and products" in groups["cereals"]["items"]
    assert all(g["items"] for k, g in groups.items() if k != "all")
    # Plain notes are what non-experts read: no jargon from the expert notes.
    for g in groups.values():
        assert "SSR" not in (g.get("plain") or "")
    assert groups["meat"]["plain"]


def test_require_fresh_flags_outputs_older_than_inputs(tmp_path):
    import os

    import pytest

    from pipeline import config

    out, inp = tmp_path / "out.parquet", tmp_path / "mapping.csv"
    out.write_text("x")
    inp.write_text("y")
    os.utime(out, (1, 1))
    with pytest.raises(config.StaleError, match="older than mapping.csv"):
        config.require_fresh(out, [inp])
    os.utime(out, None)
    config.require_fresh(out, [inp, tmp_path / "missing"])
