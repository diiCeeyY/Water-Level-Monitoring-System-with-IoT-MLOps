import json
import re
from pathlib import Path

import pytest
from tools.gen_firmware_config import generate_config, resolve_prefix

from wlm.tank import load_tank_config

ROOT = Path(__file__).resolve().parents[2]


def test_generated_firmware_constants_match_tank_yaml():
    generated = (ROOT / "iot" / "wokwi" / "config.h").read_text(encoding="utf-8")
    prefix_match = re.search(r'^#define MQTT_TOPIC_PREFIX "([^"]+)"$', generated, re.MULTILINE)
    configured_match = re.search(
        r"^#define MQTT_PREFIX_CONFIGURED (true|false)$", generated, re.MULTILINE
    )
    assert prefix_match is not None
    assert configured_match is not None

    prefix, configured = resolve_prefix(prefix_match.group(1))
    assert configured == (configured_match.group(1) == "true")
    assert generated == generate_config(prefix, configured)


def test_generated_firmware_config_uses_tank_yaml_constants():
    tank = load_tank_config()
    generated = generate_config("wlm/tdia2-ensa-a1b2c3", configured=True)

    assert f'#define DEVICE_ID "{tank.device_id}"' in generated
    assert f"constexpr float TANK_DIAMETER_CM = {tank.diameter_cm:g}.0f;" in generated
    assert f"constexpr float TANK_HEIGHT_CM = {tank.usable_height_cm:g}.0f;" in generated
    assert f"constexpr float SENSOR_DISTANCE_FULL_CM = {tank.distance_full_cm:g}.0f;" in generated
    assert f"constexpr float SENSOR_DISTANCE_EMPTY_CM = {tank.distance_empty_cm:g}.0f;" in generated
    assert (
        f"constexpr float PUMP_ON_AT_OR_BELOW_PCT = {tank.pump_on_at_or_below_pct:g}.0f;"
        in generated
    )
    assert (
        f"constexpr float PUMP_OFF_AT_OR_ABOVE_PCT = {tank.pump_off_at_or_above_pct:g}.0f;"
        in generated
    )


def test_prefix_resolution_accepts_unique_prefix_and_rejects_malformed_values():
    assert resolve_prefix("wlm/tdia2-ensa-a1b2c3") == ("wlm/tdia2-ensa-a1b2c3", True)
    assert resolve_prefix("wlm/tdia2-group-000000") == (
        "wlm/tdia2-group-000000",
        False,
    )
    with pytest.raises(ValueError, match="MQTT topic prefix"):
        resolve_prefix("wlm/shared")


def test_wokwi_diagram_wires_expected_pins_and_pump_indicator():
    diagram = json.loads((ROOT / "iot" / "wokwi" / "diagram.json").read_text(encoding="utf-8"))
    connections = {tuple(connection[:2]) for connection in diagram["connections"]}
    assert ("esp:D5", "sensor:TRIG") in connections
    assert ("esp:D18", "sensor:ECHO") in connections
    assert ("esp:26", "relay:IN") in connections
    assert ("relay:NO", "pump-led:A") in connections
