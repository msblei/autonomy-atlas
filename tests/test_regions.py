"""pipeline.regions on small cases (docs/methodology.md, "Where it is grown")."""

import pytest

from pipeline import regions


def test_area_of_a_one_degree_square_at_the_equator():
    ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert regions.ring_area_km2(ring) == pytest.approx(12364, rel=0.01)  # 111.2 km x 111.2 km


def test_holes_are_taken_out():
    outer = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    hole = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
    g = {"type": "Polygon", "coordinates": [outer, hole]}
    assert regions.geometry_area_km2(g) == pytest.approx(regions.ring_area_km2(outer) - regions.ring_area_km2(hole))


def test_two_significant_digits():
    assert regions.nice(0.03456) == pytest.approx(0.035)
    assert regions.nice(123.4) == 120
    assert regions.nice(0) == 0


def test_crop_map_shades_and_transparency():
    import numpy as np

    from pipeline import cropmap

    v = np.array([np.nan, 0.0, 0.019, 0.02, 0.1, 0.2, 0.35, 0.5, 0.99])
    assert cropmap.shade(v).tolist() == [-1, -1, -1, 0, 1, 2, 3, 4, 4]
    assert len(cropmap.STEPS) == len(cropmap.COLORS)


def test_topology_check_catches_a_moved_border():
    from pipeline import validate

    geo = {"features": [{"properties": {"iso3": "AAA"},
                         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}
    topo = {"transform": {"scale": [0.001, 0.001], "translate": [0, 0]},
            "arcs": [[[0, 0], [1000, 0], [0, 1000], [-1000, 0], [0, -1000]]],
            "objects": {"countries": {"geometries": [{"properties": {"iso3": "AAA"}, "arcs": [[0]]}]}}}
    assert validate.check_topology(topo, geo) == []
    topo["arcs"][0][1] = [1100, 0]  # the east border 0.1 degrees out
    assert [f.check for f in validate.check_topology(topo, geo)] == ["topology_outline"]
