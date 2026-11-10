import math

import pytest

from wlm.tank import (
    distance_to_level_height_cm,
    distance_to_level_pct,
    distance_to_volume_l,
    level_pct_to_distance_cm,
    level_pct_to_volume_l,
    load_tank_config,
)


@pytest.fixture
def tank():
    return load_tank_config()


def test_canonical_capacity_and_full_distance(tank):
    assert tank.capacity_l == pytest.approx(1178.0972)
    assert distance_to_level_pct(tank.distance_full_cm, tank) == pytest.approx(100)
    assert distance_to_volume_l(tank.distance_full_cm, tank) == pytest.approx(tank.capacity_l)


def test_midpoint_conversion(tank):
    assert distance_to_level_height_cm(90, tank) == pytest.approx(75)
    assert distance_to_level_pct(90, tank) == pytest.approx(50)
    assert distance_to_volume_l(90, tank) == pytest.approx(tank.capacity_l / 2)


def test_empty_distance_conversion(tank):
    assert distance_to_level_pct(tank.distance_empty_cm, tank) == pytest.approx(0)
    assert distance_to_volume_l(tank.distance_empty_cm, tank) == pytest.approx(0)


@pytest.mark.parametrize(
    ("distance_cm", "expected_pct"),
    [(0, 100), (5, 100), (200, 0), (500, 0)],
)
def test_distance_conversion_clamps_to_usable_tank_height(distance_cm, expected_pct):
    assert distance_to_level_pct(distance_cm, load_tank_config()) == pytest.approx(expected_pct)


@pytest.mark.parametrize("level_pct", [-10, 0, 30, 50, 100, 110])
def test_percent_conversions_clamp_and_round_trip(level_pct, tank):
    distance_cm = level_pct_to_distance_cm(level_pct, tank)
    clamped_pct = min(max(level_pct, 0), 100)
    assert distance_to_level_pct(distance_cm, tank) == pytest.approx(clamped_pct)
    assert level_pct_to_volume_l(level_pct, tank) == pytest.approx(
        tank.capacity_l * clamped_pct / 100
    )


@pytest.mark.parametrize("distance_cm", [math.nan, math.inf, -math.inf, True])
def test_distance_conversion_rejects_non_finite_or_boolean_values(distance_cm, tank):
    with pytest.raises(ValueError, match="finite number"):
        distance_to_level_pct(distance_cm, tank)


def test_tank_config_rejects_inconsistent_empty_distance(tmp_path):
    config_path = tmp_path / "tank.yaml"
    config_path.write_text(
        "device: {id: tank-01}\n"
        "tank: {shape: vertical_cylinder, diameter_cm: 100, usable_height_cm: 150}\n"
        "sensor: {distance_full_cm: 15, distance_empty_cm: 160, "
        "valid_min_cm: 2, valid_max_cm: 400}\n"
        "pump: {on_at_or_below_pct: 35, off_at_or_above_pct: 90, "
        "dry_run_timeout_minutes: 10, dry_run_min_rise_pct: 1, "
        "retry_after_dry_run_minutes: 30, nominal_flow_lpm: 40}\n"
        "alerts: {critical_level_pct: 15, warning_level_pct: 25}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="distance_empty_cm"):
        load_tank_config(config_path)
