"""Seeded placement of labelled synthetic events across chronological data splits."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np


def allocate_events(
    *,
    start: datetime,
    interval_seconds: int,
    total_steps: int,
    split_days: list[int],
    split_names: list[str],
    catalogue: dict[str, dict[str, Any]],
    gap_hours: float,
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    """Allocate non-overlapping events, with the configured counts in each split."""
    steps_per_day = 86400 // interval_seconds
    split_bounds: list[tuple[str, int, int]] = []
    split_start = 0
    for name, days in zip(split_names, split_days, strict=True):
        split_end = split_start + days * steps_per_day
        split_bounds.append((name, split_start, split_end))
        split_start = split_end
    if split_start != total_steps:
        raise ValueError("split.days must sum to generator.days")

    events: list[dict[str, Any]] = []
    gap_steps = int(np.ceil(gap_hours * 3600 / interval_seconds))
    for split_index, (split_name, lower, upper) in enumerate(split_bounds):
        split_events: list[dict[str, Any]] = []
        for scenario_name, spec in catalogue.items():
            count = int(spec["split_counts"][split_index])
            for event_index in range(count):
                duration_range = spec["duration_hours"]
                targets_critical = event_index == 0 and "critical_duration_hours" in spec
                if targets_critical:
                    duration_range = spec["critical_duration_hours"]
                duration_min, duration_max = duration_range
                min_steps = max(1, int(np.ceil(duration_min * 3600 / interval_seconds)))
                max_steps = max(min_steps, int(np.ceil(duration_max * 3600 / interval_seconds)))
                event_params = {"subtype": spec.get("subtype", scenario_name)}
                if targets_critical:
                    event_params["target_critical"] = True
                split_events.append(
                    {
                        "scenario": scenario_name,
                        "event_type": spec["event_type"],
                        "split": split_name,
                        "duration_min": min_steps,
                        "duration_max": max_steps,
                        "params": event_params,
                        "spec": spec,
                    }
                )

        leading_gap = gap_steps if split_index and split_events and events else 0
        available = upper - lower - leading_gap
        for _attempt in range(1000):
            durations = [
                int(rng.integers(event["duration_min"], event["duration_max"] + 1))
                for event in split_events
            ]
            if sum(durations) + gap_steps * max(0, len(durations) - 1) <= available:
                break
        else:
            raise ValueError(
                f"configured events cannot fit in split {split_name} with {gap_hours}h gaps"
            )

        order = rng.permutation(len(split_events))
        slack = available - sum(durations) - gap_steps * max(0, len(durations) - 1)
        extra_gaps = (
            rng.multinomial(slack, np.full(len(split_events), 1 / len(split_events))).tolist()
            if split_events and slack
            else [0] * len(split_events)
        )
        cursor = lower + leading_gap
        for position, event_index in enumerate(order):
            event = split_events[int(event_index)]
            cursor += extra_gaps[position]
            event_start = cursor
            event_end = event_start + durations[int(event_index)]
            cursor = event_end + gap_steps
            spec = event.pop("spec")
            for parameter in ("flow_lph", "extra_flow_lph"):
                if parameter in spec:
                    low, high = spec[parameter]
                    event["params"][parameter] = float(rng.uniform(low, high))
            event["start_step"] = event_start
            event["end_step"] = event_end
            events.append(event)

    for event_id, event in enumerate(sorted(events, key=lambda item: item["start_step"]), 1):
        event["event_id"] = event_id
        event["start_time"] = start + timedelta(seconds=event["start_step"] * interval_seconds)
        event["end_time"] = start + timedelta(seconds=event["end_step"] * interval_seconds)
    return sorted(events, key=lambda item: item["start_step"])
