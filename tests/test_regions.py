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
