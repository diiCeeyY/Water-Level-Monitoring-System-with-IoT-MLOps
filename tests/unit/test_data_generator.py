import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from wlm.data.generator import _consumption, generate_dataset
from wlm.data.scenarios import allocate_events
from wlm.data.validate import save_validation_plots, validate_frames
from wlm.tank import load_tank_config

ROOT = Path(__file__).resolve().parents[2]


def _params():
    with (ROOT / "params.yaml").open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return {**config["generator"], "split": config["split"]}


def test_scenario_allocator_covers_configured_counts_by_split():
    config = _params()
    params = config
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    total_steps = params["days"] * 1440
    events = allocate_events(
        start=start,
        interval_seconds=60,
        total_steps=total_steps,
        split_days=params["split"]["days"],
        split_names=params["split"]["names"],
        catalogue=params["event_catalogue"],
        gap_hours=params["event_gap_hours"],
        rng=np.random.default_rng(params["seed"]),
    )
    counts = {
        (split, scenario): 0
        for split in params["split"]["names"]
        for scenario in params["event_catalogue"]
    }
    for event in events:
        counts[(event["split"], event["scenario"])] += 1
    for scenario, spec in params["event_catalogue"].items():
        for split, expected in zip(params["split"]["names"], spec["split_counts"], strict=True):
            assert counts[(split, scenario)] == expected


def test_generator_is_seeded_and_emits_schema_v1_rows():
    params = _params()
    params["days"] = 2
    params["split"] = {"names": ["train", "validation", "test"], "days": [1, 1, 0]}
    params["event_catalogue"] = {}
    params["network_gap_count"] = 0
    params["message_loss_fraction"] = 0
    tank = load_tank_config()

    measurements, events = generate_dataset(params, tank)
    repeat, repeat_events = generate_dataset(params, tank)

    pd.testing.assert_frame_equal(measurements, repeat)
    pd.testing.assert_frame_equal(events, repeat_events)
    assert len(measurements) == 2 * 1440
    assert measurements["source"].eq("synthetic").all()
    assert measurements["ts"].str.endswith("Z").all()
    assert events.empty
    pump = measurements["pump_on"].astype(bool)
    rising = pump & ~pump.shift(1, fill_value=False)
    falling = ~pump & pump.shift(1, fill_value=False)
    assert measurements.loc[rising, "level_pct"].le(35.5).all()
    assert measurements.loc[falling, "level_pct"].ge(89.5).all()
    validate_frames(measurements, events)


def test_event_parameters_are_valid_json():
    events = pd.DataFrame(
        [
            {
                "event_id": 1,
                "device_id": "tank-01",
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-01T01:00:00Z",
                "event_type": "leak",
                "magnitude": 5.0,
                "params": json.dumps({"subtype": "slow", "flow_lph": 5.0}),
            }
        ]
    )
    measurements = pd.DataFrame(
        columns=[
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
        ]
    )
    # Event format is checked independently; valid empty measurement frames are accepted.
    validate_frames(measurements, events)


def test_seeded_consumption_has_daily_volume_and_peak_hours():
    demand = _consumption(
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        steps=90 * 1440,
        interval_seconds=60,
        daily_mean_l=450,
        weekend_factor=1.15,
        day_sigma=0.15,
        draw_mean_l=8.8,
        rng=np.random.default_rng(20261112),
    )
    daily_totals = demand.reshape(90, 1440).sum(axis=1)
    assert 400 <= daily_totals.mean() <= 500
    by_hour = demand.reshape(90, 24, 60).mean(axis=(0, 2))
    assert by_hour[7:10].mean() > by_hour[0:6].mean()
    assert by_hour[18:21].mean() > by_hour[0:6].mean()


def test_validation_plots_are_written(tmp_path):
    params = _params()
    params["days"] = 2
    params["split"] = {"names": ["train", "validation", "test"], "days": [1, 1, 0]}
    params["event_catalogue"] = {}
    params["network_gap_count"] = 0
    params["message_loss_fraction"] = 0
    measurements, events = generate_dataset(params, load_tank_config())

    save_validation_plots(measurements, events, tmp_path)

    assert {path.name for path in tmp_path.glob("*.png")} == {
        "daily_profile.png",
        "level_with_events.png",
        "refill_timing.png",
    }
