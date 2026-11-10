"""Measurement schema validation shared by tools and tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from wlm.tank import TankConfig, distance_to_level_pct, distance_to_volume_l

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "measurement.v1.schema.json"
DeviceId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{3,32}$")]


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    device_id: DeviceId
    ts: datetime = Field(strict=False)
    seq: int = Field(ge=0)
    distance_cm: float | None = Field(ge=2, le=400)
    level_pct: float | None = Field(ge=0, le=100)
    volume_l: float | None = Field(ge=0, le=2000)
    pump_on: bool
    sensor_ok: bool
    rssi: int | None = Field(default=None, ge=-120, le=0)
    source: Literal["wokwi", "replay", "synthetic"]

    @field_validator("ts")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("ts must be an ISO-8601 UTC timestamp")
        return value

    @model_validator(mode="after")
    def check_sensor_nullability(self) -> Measurement:
        values = (self.distance_cm, self.level_pct, self.volume_l)
        if self.sensor_ok and any(value is None for value in values):
            raise ValueError("valid sensor readings require distance_cm, level_pct, and volume_l")
        if not self.sensor_ok and any(value is not None for value in values):
            raise ValueError(
                "invalid sensor readings require null distance_cm, level_pct, and volume_l"
            )
        return self


@lru_cache(maxsize=1)
def _json_schema_validator() -> Draft202012Validator:
    with DEFAULT_SCHEMA_PATH.open(encoding="utf-8") as file:
        schema = json.load(file)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_json_schema(payload: Any) -> None:
    """Raise jsonschema.ValidationError when payload violates the JSON Schema."""
    _json_schema_validator().validate(payload)


def validate_measurement(
    payload: Any,
    *,
    tank: TankConfig | None = None,
) -> Measurement:
    """Validate with Pydantic, optionally checking derived values against tank geometry."""
    measurement = Measurement.model_validate(payload)
    if tank is not None and measurement.sensor_ok:
        assert measurement.distance_cm is not None
        assert measurement.level_pct is not None
        assert measurement.volume_l is not None
        expected_level = distance_to_level_pct(measurement.distance_cm, tank)
        expected_volume = distance_to_volume_l(measurement.distance_cm, tank)
        if abs(measurement.level_pct - expected_level) > 0.5:
            raise ValueError("level_pct is inconsistent with distance_cm and tank geometry")
        if abs(measurement.volume_l - expected_volume) > 0.6:
            raise ValueError("volume_l is inconsistent with distance_cm and tank geometry")
    return measurement


def validate_payload(
    payload: Any,
    *,
    tank: TankConfig | None = None,
) -> Measurement:
    """Require agreement from JSON Schema and Pydantic, then return the typed model."""
    validate_json_schema(payload)
    return validate_measurement(payload, tank=tank)
