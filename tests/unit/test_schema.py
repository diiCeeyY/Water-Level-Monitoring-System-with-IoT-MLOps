import json
from pathlib import Path

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from wlm.schema import validate_json_schema, validate_measurement, validate_payload
from wlm.tank import load_tank_config

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "schemas" / "examples"


def _examples(prefix):
    return sorted(EXAMPLES.glob(f"{prefix}_*.json"))


@pytest.mark.parametrize("example_path", _examples("valid"), ids=lambda path: path.name)
def test_valid_golden_examples_pass_both_validators(example_path):
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    validate_json_schema(payload)
    measurement = validate_measurement(payload)
    assert measurement.device_id == "tank-01"


@pytest.mark.parametrize("example_path", _examples("invalid"), ids=lambda path: path.name)
def test_invalid_golden_examples_fail_both_validators(example_path):
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema(payload)
    with pytest.raises(PydanticValidationError):
        validate_measurement(payload)


@pytest.mark.parametrize("example_path", _examples("valid"), ids=lambda path: path.name)
def test_valid_measurements_match_canonical_tank_when_sensor_is_valid(example_path):
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    measurement = validate_payload(payload, tank=load_tank_config())
    assert measurement.device_id == "tank-01"


def test_measurement_rejects_level_derived_from_wrong_distance():
    payload = json.loads((EXAMPLES / "valid_midlevel.json").read_text(encoding="utf-8"))
    payload["level_pct"] = 60
    with pytest.raises(ValueError, match="level_pct is inconsistent"):
        validate_payload(payload, tank=load_tank_config())


def test_measurement_rejects_non_utc_timestamp():
    payload = json.loads((EXAMPLES / "valid_midlevel.json").read_text(encoding="utf-8"))
    payload["ts"] = "2026-11-07T14:32:00+01:00"
    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema(payload)
    with pytest.raises(PydanticValidationError):
        validate_measurement(payload)
