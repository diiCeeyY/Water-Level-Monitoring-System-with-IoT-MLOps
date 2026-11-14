"""Deterministic physical tank and sensor simulator for labelled historical telemetry."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from wlm.data.scenarios import allocate_events
from wlm.tank import (
    TankConfig,
    distance_to_level_pct,
    distance_to_volume_l,
)

_DAILY_SHARES = (
    0.04 / 6,
    0.04 / 6,
    0.04 / 6,
    0.04 / 6,
    0.04 / 6,
    0.04 / 6,
    0.075,
    0.085,
    0.085,
    0.055,
    0.22 / 7,
    0.22 / 7,
    0.22 / 7,
    0.22 / 7,
    0.22 / 7,
    0.22 / 7,
    0.22 / 7,
    0.38 / 5,
    0.38 / 5,
    0.38 / 5,
    0.38 / 5,
    0.38 / 5,
    0.03,
    0.03,
)


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("generator.start_time must be an ISO-8601 UTC timestamp")
    return parsed.astimezone(timezone.utc)


def _consumption(
    *,
    start: datetime,
    steps: int,
    interval_seconds: int,
    daily_mean_l: float,
    weekend_factor: float,
    day_sigma: float,
    draw_mean_l: float,
    rng: np.random.Generator,
) -> np.ndarray:
    minutes_per_step = interval_seconds / 60
    hourly_shares = np.asarray(_DAILY_SHARES, dtype=float)
    hourly_shares /= hourly_shares.sum()
    demand = np.zeros(steps, dtype=float)
    local_times = pd.date_range(
        start=start,
        periods=steps,
        freq=pd.Timedelta(seconds=interval_seconds),
    ).tz_convert(ZoneInfo("Africa/Casablanca"))
    local_dates = local_times.date
    day_factors: dict[date, float] = {}
    for day_date in sorted(set(local_dates)):
        day_factor = rng.lognormal(mean=-(day_sigma**2) / 2, sigma=day_sigma)
        if day_date.weekday() >= 5:
            day_factor *= weekend_factor
        day_factors[day_date] = day_factor
    for step, local_time in enumerate(local_times):
        target_l = daily_mean_l * day_factors[local_dates[step]]
        rate_per_minute = target_l * hourly_shares[local_time.hour] / 60 / draw_mean_l
        draw_count = rng.poisson(rate_per_minute * minutes_per_step)
        if draw_count:
            sizes = rng.choice(
                [6.0, 8.0, 48.0],
                size=draw_count,
                p=[0.60, 0.35, 0.05],
            )
            demand[step] = sizes.sum()
    return demand


def generate_dataset(
    params: dict[str, Any],
    tank: TankConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return schema-v1 synthetic measurements and a separate event truth table."""
    seed = int(params["seed"])
    days = int(params["days"])
    interval_seconds = int(params["interval_seconds"])
    if days <= 0 or interval_seconds <= 0 or 86400 % interval_seconds:
        raise ValueError("days and interval_seconds must be positive; interval must divide a day")
    start = _utc_datetime(str(params["start_time"]))
    steps_per_day = 86400 // interval_seconds
    steps = days * steps_per_day
    split = params["split"]
    split_days = [int(value) for value in split["days"]]
    if sum(split_days) != days:
        raise ValueError("split.days must sum to generator.days")

    rng = np.random.default_rng(seed)
    events = allocate_events(
        start=start,
        interval_seconds=interval_seconds,
        total_steps=steps,
        split_days=split_days,
        split_names=list(split["names"]),
        catalogue=params["event_catalogue"],
        gap_hours=float(params["event_gap_hours"]),
        rng=rng,
    )
    demand = _consumption(
        start=start,
        steps=steps,
        interval_seconds=interval_seconds,
        daily_mean_l=float(params["daily_consumption_l"]),
        weekend_factor=float(params["weekend_factor"]),
        day_sigma=float(params["consumption_day_sigma"]),
        draw_mean_l=float(params["draw_mean_l"]),
        rng=rng,
    )

    event_at_step: list[list[dict[str, Any]]] = [[] for _ in range(steps)]
    for event in events:
        for step in range(event["start_step"], event["end_step"]):
            event_at_step[step].append(event)

    loss_mask = rng.random(steps) < float(params["message_loss_fraction"])
    gap_count = int(params["network_gap_count"])
    gap_min = max(1, int(params["network_gap_min_minutes"]) * 60 // interval_seconds)
    gap_max = max(gap_min, int(params["network_gap_max_minutes"]) * 60 // interval_seconds)
    gap_ranges: list[tuple[int, int]] = []
    for _ in range(gap_count):
        gap_length = int(rng.integers(gap_min, gap_max + 1))
        gap_start = int(rng.integers(0, max(1, steps - gap_length)))
        gap_ranges.append((gap_start, gap_start + gap_length))
        loss_mask[gap_start : gap_start + gap_length] = True

    capacity = tank.capacity_l
    true_volume = capacity * float(params["initial_level_pct"]) / 100
    flow_lpm = tank.nominal_flow_lpm * interval_seconds / 60
    pump_on = False
    pump_started_step = 0
    pump_start_level = 0.0
    lockout_until = 0
    previous_distance = tank.distance_empty_cm - tank.usable_height_cm * (true_volume / capacity)
    rows: list[dict[str, Any]] = []
    for step in range(steps):
        step_events = event_at_step[step]
        true_level_pct = true_volume / capacity * 100
        true_distance = tank.distance_empty_cm - tank.usable_height_cm * true_level_pct / 100
        sensor_ok = True
        measured_distance = round(
            true_distance + rng.normal(0, float(params["sensor_noise_sigma_cm"])), 1
        )
        leak_lpm = 0.0
        extra_demand = 0.0
        supply_ok = True
        for event in step_events:
            scenario = event["scenario"]
            if scenario in ("leak_slow", "leak_burst"):
                leak_lpm += float(event["params"]["flow_lph"]) / 60
            elif scenario == "consumption_surge":
                extra_demand += (
                    float(event["params"]["extra_flow_lph"]) / 60 * interval_seconds / 60
                )
            elif scenario == "sensor_frozen":
                measured_distance = previous_distance
            elif scenario == "sensor_blocked":
                measured_distance = round(float(rng.normal(4.0, 0.05)), 1)
            elif scenario == "sensor_dropout":
                sensor_ok = False
            elif scenario == "sensor_spike":
                sign = -1 if rng.random() < 0.5 else 1
                measured_distance = round(
                    float(np.clip(true_distance + sign * rng.uniform(30, 200), 2, 400)),
                    1,
                )
            elif scenario == "supply_outage":
                supply_ok = False

        measured_distance = float(np.clip(measured_distance, tank.valid_min_cm, tank.valid_max_cm))
        measured_level = distance_to_level_pct(measured_distance, tank) if sensor_ok else None
        if not sensor_ok:
            pump_on = False
        else:
            if lockout_until and step >= lockout_until:
                lockout_until = 0
            if pump_on:
                if measured_level >= tank.pump_off_at_or_above_pct:
                    pump_on = False
                elif (
                    step - pump_started_step
                    >= int(np.ceil(tank.dry_run_timeout_minutes * 60 / interval_seconds))
                    and measured_level < pump_start_level + tank.dry_run_min_rise_pct
                ):
                    pump_on = False
                    lockout_until = step + int(
                        np.ceil(tank.retry_after_dry_run_minutes * 60 / interval_seconds)
                    )
            elif not lockout_until and measured_level <= tank.pump_on_at_or_below_pct:
                pump_on = True
                pump_started_step = step
                pump_start_level = measured_level

        time_value = start + timedelta(seconds=step * interval_seconds)
        if not loss_mask[step]:
            if sensor_ok:
                level_pct = round(distance_to_level_pct(measured_distance, tank), 1)
                volume_l = round(distance_to_volume_l(measured_distance, tank), 1)
                distance_value: float | None = measured_distance
            else:
                level_pct = volume_l = distance_value = None
            rows.append(
                {
                    "schema_version": 1,
                    "device_id": tank.device_id,
                    "ts": time_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "seq": step,
                    "distance_cm": distance_value,
                    "level_pct": level_pct,
                    "volume_l": volume_l,
                    "pump_on": bool(pump_on),
                    "sensor_ok": bool(sensor_ok),
                    "rssi": int(np.clip(round(rng.normal(-62, 4)), -120, 0)),
                    "source": "synthetic",
                }
            )

        previous_distance = measured_distance
        inflow = flow_lpm if pump_on and supply_ok else 0.0
        demand_this_step = demand[step] + extra_demand
        true_volume = float(
            np.clip(
                true_volume + inflow - demand_this_step - leak_lpm * interval_seconds / 60,
                0,
                capacity,
            )
        )

    event_rows = [
        {
            "event_id": event["event_id"],
            "device_id": tank.device_id,
            "start_time": event["start_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": event["end_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event_type": event["event_type"],
            "magnitude": event["params"].get("flow_lph", event["params"].get("extra_flow_lph")),
            "params": json.dumps(event["params"], sort_keys=True),
        }
        for event in events
    ]
    return pd.DataFrame(rows), pd.DataFrame(
        event_rows,
        columns=[
            "event_id",
            "device_id",
            "start_time",
            "end_time",
            "event_type",
            "magnitude",
            "params",
        ],
    )
