"""CLI for generating the deterministic Phase 3 historical dataset."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from wlm.data.generator import generate_dataset
from wlm.tank import load_tank_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, default=Path("params.yaml"))
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    with args.params.open(encoding="utf-8") as file:
        config: dict[str, Any] = yaml.safe_load(file)
    if not isinstance(config, dict) or not isinstance(config.get("generator"), dict):
        raise ValueError("params file must contain a generator mapping")
    if not isinstance(config.get("split"), dict):
        raise ValueError("params file must contain a split mapping")
    generator_params = {**config["generator"], "split": config["split"]}
    measurements, events = generate_dataset(generator_params, load_tank_config())

    args.out.mkdir(parents=True, exist_ok=True)
    measurements_path = args.out / "historical_90d.parquet"
    events_path = args.out / "events_90d.parquet"
    measurements.to_parquet(measurements_path, index=False)
    events.to_parquet(events_path, index=False)
    print(
        f"Wrote {len(measurements):,} measurements to {measurements_path} "
        f"and {len(events):,} events to {events_path}."
    )


if __name__ == "__main__":
    main()
