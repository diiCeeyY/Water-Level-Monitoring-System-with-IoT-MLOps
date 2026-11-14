"""Validate generated measurement and ground-truth Parquet files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from wlm.schema import validate_payload
from wlm.tank import TankConfig, load_tank_config

MEASUREMENT_COLUMNS = {
    "schema_version",
    "device_id",
    "ts",
    "seq",
    "distance_cm",
    "level_pct",
    "volume_l",
    "pump_on",
    "sensor_ok",
    "rssi",
    "source",
}
EVENT_COLUMNS = {
    "event_id",
    "device_id",
    "start_time",
    "end_time",
    "event_type",
    "magnitude",
    "params",
}


def validate_frames(
    measurements: pd.DataFrame,
    events: pd.DataFrame,
    params: dict[str, Any] | None = None,
) -> None:
    if set(measurements.columns) != MEASUREMENT_COLUMNS:
        raise ValueError("measurement columns do not match schema v1")
    if not measurements["ts"].is_monotonic_increasing or measurements["ts"].duplicated().any():
        raise ValueError("measurement timestamps must be strictly increasing")
    tank = load_tank_config()
    previous_seq = -1
    for payload in measurements.to_dict(orient="records"):
        payload = {key: None if pd.isna(value) else value for key, value in payload.items()}
        validate_payload(payload, tank=tank)
        if payload["seq"] <= previous_seq:
            raise ValueError("measurement seq values must be strictly increasing")
        previous_seq = payload["seq"]

    if set(events.columns) != EVENT_COLUMNS:
        raise ValueError("event columns do not match the ground-truth contract")
    if events["event_id"].duplicated().any():
        raise ValueError("event_id values must be unique")
    parsed_starts = pd.to_datetime(events["start_time"], utc=True)
    parsed_ends = pd.to_datetime(events["end_time"], utc=True)
    if (parsed_ends <= parsed_starts).any():
        raise ValueError("every event must have positive duration")
    event_order = (
        pd.DataFrame({"start": parsed_starts, "end": parsed_ends})
        .sort_values("start")
        .reset_index(drop=True)
    )
    gap = timedelta(hours=12)
    for index in range(1, len(event_order)):
        if event_order.loc[index, "start"] < event_order.loc[index - 1, "end"] + gap:
            raise ValueError("events must be separated by at least 12 hours")
    if events["device_id"].nunique() > 1:
        raise ValueError("events must target one configured device")
    for value in events["params"]:
        if not isinstance(value, str) or not isinstance(json.loads(value), dict):
            raise ValueError("event params must be JSON objects")

    if params is not None:
        _validate_event_coverage(events, params)
        _validate_simulation_acceptance(measurements, events, params, tank)


def _validate_event_coverage(events: pd.DataFrame, params: dict[str, Any]) -> None:
    generator = params["generator"]
    split = params["split"]
    start = datetime.fromisoformat(generator["start_time"].replace("Z", "+00:00"))
    if start.tzinfo is None or start.utcoffset() != timedelta(0):
        raise ValueError("generator.start_time must be UTC")
    bounds = []
    elapsed_days = 0
    for name, days in zip(split["names"], split["days"], strict=True):
        bounds.append((name, elapsed_days, elapsed_days + int(days)))
        elapsed_days += int(days)
    if elapsed_days != int(generator["days"]):
        raise ValueError("split.days must sum to generator.days")

    counts = {
        (name, scenario): 0 for name, *_ in bounds for scenario in generator["event_catalogue"]
    }
    for row in events.to_dict(orient="records"):
        event_start = datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
        elapsed = (event_start - start).total_seconds() / 86400
        split_name = next(
            (name for name, lower, upper in bounds if lower <= elapsed < upper),
            None,
        )
        if split_name is None:
            raise ValueError("event start_time lies outside the configured dataset splits")
        event_params = json.loads(row["params"])
        subtype = event_params.get("subtype", row["event_type"])
        scenario = f"leak_{subtype}" if row["event_type"] == "leak" else subtype
        if scenario not in generator["event_catalogue"]:
            raise ValueError(f"unconfigured event scenario: {scenario}")
        counts[(split_name, scenario)] += 1

    for scenario, spec in generator["event_catalogue"].items():
        for split_name, expected in zip(split["names"], spec["split_counts"], strict=True):
            if counts[(split_name, scenario)] != int(expected):
                raise ValueError(
                    f"{scenario} in {split_name}: expected {expected}, "
                    f"found {counts[(split_name, scenario)]}"
                )


def _validate_simulation_acceptance(
    measurements: pd.DataFrame,
    events: pd.DataFrame,
    params: dict[str, Any],
    tank: TankConfig,
) -> None:
    pump = measurements["pump_on"].astype(bool)
    falling_edges = ~pump & pump.shift(1, fill_value=False)
    refill_count = int(
        (falling_edges & measurements["level_pct"].ge(tank.pump_off_at_or_above_pct)).sum()
    )
    if not 55 <= refill_count <= 65:
        raise ValueError(f"expected 55-65 completed refills; found {refill_count}")

    generator = params["generator"]
    split = params["split"]
    start = datetime.fromisoformat(generator["start_time"].replace("Z", "+00:00"))
    split_bounds = []
    elapsed_days = 0
    for name, days in zip(split["names"], split["days"], strict=True):
        split_bounds.append((name, elapsed_days, elapsed_days + int(days)))
        elapsed_days += int(days)
    critical_outage_by_split = {name: False for name, *_ in split_bounds}
    measurement_times = pd.to_datetime(measurements["ts"], utc=True)
    for row in events[events["event_type"].eq("supply_outage")].to_dict(orient="records"):
        event_start = datetime.fromisoformat(row["start_time"].replace("Z", "+00:00"))
        event_end = datetime.fromisoformat(row["end_time"].replace("Z", "+00:00"))
        elapsed = (event_start - start).total_seconds() / 86400
        split_name = next(
            (name for name, lower, upper in split_bounds if lower <= elapsed < upper),
            None,
        )
        if split_name is None:
            continue
        during_outage = measurements.loc[
            measurement_times.ge(event_start) & measurement_times.lt(event_end), "level_pct"
        ].dropna()
        if not during_outage.empty and during_outage.min() <= tank.critical_level_pct:
            critical_outage_by_split[split_name] = True
    missing_splits = [
        name for name, reached_critical in critical_outage_by_split.items() if not reached_critical
    ]
    if missing_splits:
        raise ValueError(
            "at least one supply outage must reach the critical level in each split; "
            f"missing: {', '.join(missing_splits)}"
        )


def save_validation_plots(
    measurements: pd.DataFrame,
    events: pd.DataFrame,
    output_dir: Path,
) -> None:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    frame = measurements.copy()
    frame["time"] = pd.to_datetime(frame["ts"], utc=True)
    frame["local_time"] = frame["time"].dt.tz_convert("Africa/Casablanca")
    frame["local_hour"] = frame["local_time"].dt.hour
    profile = frame.groupby("local_hour", observed=True)["level_pct"].mean()

    figure, axis = plt.subplots(figsize=(10, 4))
    axis.plot(profile.index, profile.values, marker="o")
    axis.set(title="Average tank level by local hour", xlabel="Local hour", ylabel="Level (%)")
    axis.set_xticks(range(24))
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_dir / "daily_profile.png", dpi=150)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(14, 5))
    axis.plot(frame["time"], frame["level_pct"], linewidth=0.6)
    for event in events.itertuples(index=False):
        start = pd.to_datetime(event.start_time, utc=True)
        end = pd.to_datetime(event.end_time, utc=True)
        axis.axvspan(start, end, alpha=0.14, label=event.event_type)
    handles, labels = axis.get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=True))
    if unique:
        axis.legend(unique.values(), unique.keys(), loc="upper right", fontsize="small")
    axis.set(title="90-day tank level and labelled events", xlabel="UTC", ylabel="Level (%)")
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    axis.grid(alpha=0.2)
    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(output_dir / "level_with_events.png", dpi=150)
    plt.close(figure)

    pump = frame["pump_on"].astype(bool)
    starts = frame.loc[pump & ~pump.shift(1, fill_value=False), "time"]
    intervals_minutes = starts.diff().dt.total_seconds().dropna() / 60
    figure, axis = plt.subplots(figsize=(8, 4))
    if intervals_minutes.empty:
        axis.text(0.5, 0.5, "Not enough completed refill cycles", ha="center", va="center")
    else:
        axis.hist(intervals_minutes, bins=20)
    axis.set(title="Time between pump starts", xlabel="Minutes", ylabel="Refill count")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_dir / "refill_timing.png", dpi=150)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--params", type=Path, default=Path("params.yaml"))
    parser.add_argument(
        "--plots-dir",
        type=Path,
        default=Path("reports/data_validation"),
    )
    args = parser.parse_args()
    measurements = pd.read_parquet(args.data)
    events = pd.read_parquet(args.events)
    with args.params.open(encoding="utf-8") as file:
        params = yaml.safe_load(file)
    if not isinstance(params, dict):
        raise ValueError("params file must contain a YAML mapping")
    validate_frames(measurements, events, params=params)
    save_validation_plots(measurements, events, args.plots_dir)
    print(f"Valid: {len(measurements):,} measurements and {len(events):,} events.")
    elapsed_days = 0
    for split_name, days in zip(params["split"]["names"], params["split"]["days"], strict=True):
        lower = pd.Timestamp(params["generator"]["start_time"]) + pd.Timedelta(days=elapsed_days)
        elapsed_days += int(days)
        upper = pd.Timestamp(params["generator"]["start_time"]) + pd.Timedelta(days=elapsed_days)
        in_split = events[
            pd.to_datetime(events["start_time"], utc=True).ge(lower)
            & pd.to_datetime(events["start_time"], utc=True).lt(upper)
        ]
        counts = in_split["event_type"].value_counts().sort_index().to_dict()
        print(f"{split_name} events: {counts}")


if __name__ == "__main__":
    main()
