"""Mirrors tests/testthat/test-sparklines.R."""

from __future__ import annotations

import math

import pytest

from cardargus import create_sparkline
from conftest import SVG_NS, find_all, parse


def test_well_formed_standalone_svg():
    root = parse(create_sparkline([3, 5, 2, 8, 7]))
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("width") == "120" and root.get("height") == "36"
    assert root.get("viewBox") == "0 0 120 36"
    assert root.get("aria-hidden") == "true"
    assert len(find_all(root, "polyline")) == 1


def test_marks_per_type():
    area = parse(create_sparkline([1, 4, 2, 6], type="area"))
    assert len(find_all(area, "polygon")) == 1
    assert len(find_all(area, "polyline")) == 1
    bars = parse(create_sparkline([5, 2, 8, 3, 7], type="bar"))
    assert len(find_all(bars, "rect")) == 5
    assert find_all(bars, "polyline") == [] and find_all(bars, "circle") == []


def test_line_geometry():
    root = parse(create_sparkline([2, 4, 3, 6, 5, 8], width=55, height=34))
    pts = find_all(root, "polyline")[0].get("points")
    # Same coordinates as the R reference card (theme gallery).
    assert pts == "3.00,31.00 12.80,21.67 22.60,26.33 32.40,12.33 42.20,17.00 52.00,3.00"
    dot = find_all(root, "circle")[0]
    assert (dot.get("cx"), dot.get("cy"), dot.get("r")) == ("52.00", "3.00", "3.00")


def test_area_closes_on_baseline():
    root = parse(create_sparkline([1, 2], width=20, height=10, type="area"))
    pts = find_all(root, "polygon")[0].get("points").split(" ")
    assert pts[-2:] == ["17.00,7.00", "3.00,7.00"]


def test_show_last_point():
    assert "<circle" in create_sparkline([1, 2, 3])
    assert "<circle" not in create_sparkline([1, 2, 3], show_last_point=False)


def test_constant_series_is_flat_mid_height():
    root = parse(create_sparkline([5, 5, 5]))
    ys = {p.split(",")[1] for p in find_all(root, "polyline")[0].get("points").split(" ")}
    assert ys == {"18.00"}


def test_single_and_zero_bars():
    one = parse(create_sparkline([7], type="bar"))
    assert len(find_all(one, "rect")) == 1
    zeros = parse(create_sparkline([0, 0], type="bar"))
    heights = [float(r.get("height")) for r in find_all(zeros, "rect")]
    assert heights == [1.0, 1.0]  # zero bars still show as a sliver


def test_bars_scale_from_min_zero_or_negative():
    pos = parse(create_sparkline([2, 4], type="bar", height=36))
    hs = [float(r.get("height")) for r in find_all(pos, "rect")]
    assert hs == [15.0, 30.0]  # scaled from 0, not from min(values)
    neg = parse(create_sparkline([-2, 2], type="bar", height=36))
    hs = [float(r.get("height")) for r in find_all(neg, "rect")]
    assert hs == [1.0, 30.0]  # scaled from the negative minimum


@pytest.mark.parametrize(
    "values", [None, [1, math.nan, 3], "abc", [], [1, None], [True, False], ["1", "2"]]
)
def test_validates_values(values):
    with pytest.raises(ValueError, match="numeric"):
        create_sparkline(values)


def test_validation_messages():
    with pytest.raises(ValueError, match="at least 2"):
        create_sparkline([1])  # line needs 2 points
    with pytest.raises(ValueError, match="at least 2"):
        create_sparkline(1, type="area")
    with pytest.raises(ValueError, match="positive"):
        create_sparkline([1, 2], width=-10)
    with pytest.raises(ValueError, match="positive"):
        create_sparkline([1, 2], height=0)
    with pytest.raises(ValueError, match="type"):
        create_sparkline([1, 2], type="pie")  # type: ignore[arg-type]


def test_accepts_generators_and_tuples():
    assert create_sparkline((1, 2, 3)) == create_sparkline(x for x in [1, 2, 3])
