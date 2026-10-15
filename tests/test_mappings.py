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
