"""Canonical tank configuration and distance/level/volume conversions."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TANK_CONFIG = Path(__file__).resolve().parents[2] / "config" / "tank.yaml"


@dataclass(frozen=True)
class TankConfig:
    device_id: str
    diameter_cm: float
    usable_height_cm: float
    distance_full_cm: float
    distance_empty_cm: float
    valid_min_cm: float
    valid_max_cm: float
    pump_on_at_or_below_pct: float
    pump_off_at_or_above_pct: float
    dry_run_timeout_minutes: float
    dry_run_min_rise_pct: float
    retry_after_dry_run_minutes: float
    nominal_flow_lpm: float
    critical_level_pct: float
    warning_level_pct: float

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9-]{3,32}", self.device_id):
            raise ValueError("device_id must match ^[a-z0-9-]{3,32}$")
        positive_values = {
            "diameter_cm": self.diameter_cm,
            "usable_height_cm": self.usable_height_cm,
            "dry_run_timeout_minutes": self.dry_run_timeout_minutes,
            "retry_after_dry_run_minutes": self.retry_after_dry_run_minutes,
            "nominal_flow_lpm": self.nominal_flow_lpm,
        }
        for name, value in positive_values.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")

        if not math.isclose(
            self.distance_empty_cm,
            self.distance_full_cm + self.usable_height_cm,
            abs_tol=1e-6,
        ):
            raise ValueError("distance_empty_cm must equal distance_full_cm + usable_height_cm")
        if not 0 < self.valid_min_cm < self.valid_max_cm:
            raise ValueError("sensor distance bounds must be positive and increasing")
        if not 0 <= self.pump_on_at_or_below_pct < self.pump_off_at_or_above_pct <= 100:
            raise ValueError("pump thresholds must satisfy 0 <= ON < OFF <= 100")
        if not 0 <= self.critical_level_pct < self.warning_level_pct <= 100:
            raise ValueError("alert thresholds must satisfy 0 <= critical < warning <= 100")
        if self.dry_run_min_rise_pct < 0:
            raise ValueError("dry_run_min_rise_pct cannot be negative")

    @property
    def capacity_l(self) -> float:
        radius_cm = self.diameter_cm / 2
        return math.pi * radius_cm**2 * self.usable_height_cm / 1000


def load_tank_config(path: str | Path | None = None) -> TankConfig:
    """Load and validate tank.yaml."""
    config_path = Path(path) if path is not None else DEFAULT_TANK_CONFIG
    with config_path.open(encoding="utf-8") as file:
        raw: Any = yaml.safe_load(file)

    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} must contain a YAML mapping")

    try:
        device = raw["device"]
        tank = raw["tank"]
        sensor = raw["sensor"]
        pump = raw["pump"]
        alerts = raw["alerts"]
        if tank["shape"] != "vertical_cylinder":
            raise ValueError("tank.shape must be 'vertical_cylinder'")
        return TankConfig(
            device_id=str(device["id"]),
            diameter_cm=float(tank["diameter_cm"]),
            usable_height_cm=float(tank["usable_height_cm"]),
            distance_full_cm=float(sensor["distance_full_cm"]),
            distance_empty_cm=float(sensor["distance_empty_cm"]),
            valid_min_cm=float(sensor["valid_min_cm"]),
            valid_max_cm=float(sensor["valid_max_cm"]),
            pump_on_at_or_below_pct=float(pump["on_at_or_below_pct"]),
            pump_off_at_or_above_pct=float(pump["off_at_or_above_pct"]),
            dry_run_timeout_minutes=float(pump["dry_run_timeout_minutes"]),
            dry_run_min_rise_pct=float(pump["dry_run_min_rise_pct"]),
            retry_after_dry_run_minutes=float(pump["retry_after_dry_run_minutes"]),
            nominal_flow_lpm=float(pump["nominal_flow_lpm"]),
            critical_level_pct=float(alerts["critical_level_pct"]),
            warning_level_pct=float(alerts["warning_level_pct"]),
        )
    except (KeyError, TypeError) as error:
        raise ValueError(
            f"Missing or invalid tank configuration field in {config_path}: {error}"
        ) from error


def _finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def distance_to_level_height_cm(distance_cm: float, tank: TankConfig) -> float:
    distance = _finite_number(distance_cm, "distance_cm")
    return _clamp(tank.distance_empty_cm - distance, 0, tank.usable_height_cm)


def distance_to_level_pct(distance_cm: float, tank: TankConfig) -> float:
    return distance_to_level_height_cm(distance_cm, tank) / tank.usable_height_cm * 100


def level_pct_to_distance_cm(level_pct: float, tank: TankConfig) -> float:
    percent = _finite_number(level_pct, "level_pct")
    height_cm = _clamp(percent, 0, 100) / 100 * tank.usable_height_cm
    return tank.distance_empty_cm - height_cm


def level_pct_to_volume_l(level_pct: float, tank: TankConfig) -> float:
    percent = _finite_number(level_pct, "level_pct")
    height_cm = _clamp(percent, 0, 100) / 100 * tank.usable_height_cm
    radius_cm = tank.diameter_cm / 2
    return math.pi * radius_cm**2 * height_cm / 1000


def distance_to_volume_l(distance_cm: float, tank: TankConfig) -> float:
    return level_pct_to_volume_l(distance_to_level_pct(distance_cm, tank), tank)
