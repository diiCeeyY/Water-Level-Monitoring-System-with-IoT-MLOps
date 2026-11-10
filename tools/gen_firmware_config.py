"""Generate the Wokwi firmware constants from config/tank.yaml and the MQTT prefix."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from wlm.tank import DEFAULT_TANK_CONFIG, load_tank_config

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "iot" / "wokwi" / "config.h"
PLACEHOLDER_PREFIX = "wlm/tdia2-group-000000"
PREFIX_PATTERN = re.compile(r"^wlm/tdia2-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{6}$")


def _read_dotenv_prefix(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("MQTT_TOPIC_PREFIX="):
            return line.partition("=")[2].strip().strip("\"'")
    return None


def resolve_prefix(cli_prefix: str | None = None) -> tuple[str, bool]:
    prefix = cli_prefix or os.environ.get("MQTT_TOPIC_PREFIX") or _read_dotenv_prefix(ROOT / ".env")
    if not prefix:
        return PLACEHOLDER_PREFIX, False
    if not PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError(
            "MQTT topic prefix must match wlm/tdia2-<group>-<6 lowercase hex characters>"
        )
    configured = prefix != PLACEHOLDER_PREFIX
    return prefix, configured


def generate_config(prefix: str, configured: bool) -> str:
    if not PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError(
            "MQTT topic prefix must match wlm/tdia2-<group>-<6 lowercase hex characters>"
        )
    tank = load_tank_config(DEFAULT_TANK_CONFIG)

    def cpp_float(value: float) -> str:
        formatted = f"{value:.15g}"
        if "." not in formatted and "e" not in formatted:
            formatted += ".0"
        return f"{formatted}f"

    return f"""#pragma once

#define DEVICE_ID "{tank.device_id}"
#define MQTT_TOPIC_PREFIX "{prefix}"
#define MQTT_PREFIX_CONFIGURED {str(configured).lower()}

constexpr float TANK_DIAMETER_CM = {cpp_float(tank.diameter_cm)};
constexpr float TANK_HEIGHT_CM = {cpp_float(tank.usable_height_cm)};
constexpr float SENSOR_DISTANCE_FULL_CM = {cpp_float(tank.distance_full_cm)};
constexpr float SENSOR_DISTANCE_EMPTY_CM = {cpp_float(tank.distance_empty_cm)};
constexpr float SENSOR_MIN_DISTANCE_CM = {cpp_float(tank.valid_min_cm)};
constexpr float SENSOR_MAX_DISTANCE_CM = {cpp_float(tank.valid_max_cm)};
constexpr float PUMP_ON_AT_OR_BELOW_PCT = {cpp_float(tank.pump_on_at_or_below_pct)};
constexpr float PUMP_OFF_AT_OR_ABOVE_PCT = {cpp_float(tank.pump_off_at_or_above_pct)};
constexpr uint32_t PUMP_DRY_RUN_TIMEOUT_MS = {int(tank.dry_run_timeout_minutes * 60_000)}UL;
constexpr float PUMP_DRY_RUN_MIN_RISE_PCT = {cpp_float(tank.dry_run_min_rise_pct)};
constexpr uint32_t PUMP_RETRY_DELAY_MS = {int(tank.retry_after_dry_run_minutes * 60_000)}UL;
constexpr bool RELAY_ACTIVE_LOW = true;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", help="MQTT topic prefix (defaults to environment or .env)")
    args = parser.parse_args()
    try:
        prefix, configured = resolve_prefix(args.prefix)
    except ValueError as error:
        parser.error(str(error))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generate_config(prefix, configured), encoding="utf-8", newline="\n")
    print(f"Generated {OUTPUT.relative_to(ROOT)}")
    if not configured:
        print(
            "No unique MQTT prefix configured. Generate one with scripts/new-prefix.ps1, "
            "put it in .env, and regenerate before running Wokwi.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
