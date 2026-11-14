"""Idempotently load generated history and event labels into TimescaleDB."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from wlm.schema import validate_payload
from wlm.tank import load_tank_config

_EVENT_ID_NAMESPACE = 2_000_000_000_000_000_000


def _nullable(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _parse_utc(value: str | datetime) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
        raise ValueError(f"timestamp must be UTC: {value!r}")
    return timestamp.to_pydatetime()


def namespaced_event_id(event_id: int, start_time: str | datetime) -> int:
    """Keep these deterministic event IDs separate from small hand-entered IDs."""
    timestamp = _parse_utc(start_time)
    value = _EVENT_ID_NAMESPACE + int(timestamp.timestamp()) * 100 + int(event_id)
    if value > 9_223_372_036_854_775_807:
        raise ValueError("namespaced event ID exceeds PostgreSQL BIGINT")
    return value


def _validate_measurements(frame: pd.DataFrame) -> None:
    tank = load_tank_config()
    previous_timestamp: datetime | None = None
    previous_seq = -1
    for row in frame.to_dict(orient="records"):
        row = {key: _nullable(value) for key, value in row.items()}
        measurement = validate_payload(row, tank=tank)
        if previous_timestamp is not None and measurement.ts <= previous_timestamp:
            raise ValueError("measurement timestamps must be strictly increasing")
        if measurement.seq <= previous_seq:
            raise ValueError("measurement seq values must be strictly increasing")
        previous_timestamp = measurement.ts
        previous_seq = measurement.seq


def load_frames(
    connection: psycopg.Connection[Any],
    measurements: pd.DataFrame,
    events: pd.DataFrame,
) -> tuple[int, int]:
    """Transactionally COPY measurements and idempotently insert event truth."""
    _validate_measurements(measurements)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TEMP TABLE measurement_stage (
                    time TIMESTAMPTZ NOT NULL,
                    device_id TEXT NOT NULL,
                    seq BIGINT NOT NULL,
                    distance_cm DOUBLE PRECISION,
                    level_pct DOUBLE PRECISION,
                    volume_l DOUBLE PRECISION,
                    pump_on BOOLEAN NOT NULL,
                    sensor_ok BOOLEAN NOT NULL,
                    rssi SMALLINT,
                    source TEXT NOT NULL,
                    schema_version SMALLINT NOT NULL
                ) ON COMMIT DROP
                """
            )
            with cursor.copy(
                """
                COPY measurement_stage (
                    time, device_id, seq, distance_cm, level_pct, volume_l,
                    pump_on, sensor_ok, rssi, source, schema_version
                ) FROM STDIN
                """
            ) as copy:
                for row in measurements.to_dict(orient="records"):
                    row = {key: _nullable(value) for key, value in row.items()}
                    copy.write_row(
                        (
                            _parse_utc(row["ts"]),
                            row["device_id"],
                            row["seq"],
                            row["distance_cm"],
                            row["level_pct"],
                            row["volume_l"],
                            row["pump_on"],
                            row["sensor_ok"],
                            row["rssi"],
                            row["source"],
                            row["schema_version"],
                        )
                    )
            cursor.execute(
                """
                INSERT INTO measurements (
                    time, device_id, seq, distance_cm, level_pct, volume_l,
                    pump_on, sensor_ok, rssi, source, schema_version
                )
                SELECT
                    time, device_id, seq, distance_cm, level_pct, volume_l,
                    pump_on, sensor_ok, rssi, source, schema_version
                FROM measurement_stage
                ON CONFLICT (device_id, time) DO NOTHING
                """
            )
            inserted_measurements = cursor.rowcount

            expected_events: dict[int, tuple[Any, ...]] = {}
            inserted_events = 0
            for event in events.to_dict(orient="records"):
                event_id = namespaced_event_id(event["event_id"], event["start_time"])
                params = json.loads(event["params"])
                values = (
                    event["device_id"],
                    _parse_utc(event["start_time"]),
                    _parse_utc(event["end_time"]),
                    event["event_type"],
                    _nullable(event["magnitude"]),
                    params,
                )
                expected_events[event_id] = values
                cursor.execute(
                    """
                    INSERT INTO ground_truth_events (
                        event_id, device_id, start_time, end_time,
                        event_type, magnitude, params
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (event_id, *values[:-1], Jsonb(values[-1])),
                )
                inserted_events += cursor.rowcount

            if expected_events:
                cursor.execute(
                    """
                    SELECT event_id, device_id, start_time, end_time,
                           event_type, magnitude, params
                    FROM ground_truth_events
                    WHERE event_id = ANY(%s)
                    """,
                    (list(expected_events),),
                )
                stored_events = {row[0]: row[1:] for row in cursor.fetchall()}
                for event_id, expected in expected_events.items():
                    stored = stored_events.get(event_id)
                    if stored is None or tuple(stored) != expected:
                        raise ValueError(f"ground-truth event ID collision or mismatch: {event_id}")
    return inserted_measurements, inserted_events


def _database_settings() -> dict[str, Any]:
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise ValueError("POSTGRES_PASSWORD must be set in the environment")
    return {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", os.environ.get("POSTGRES_HOST_PORT", "5433"))),
        "dbname": os.environ.get("POSTGRES_DB", "wlm"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": password,
        "connect_timeout": 10,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    args = parser.parse_args()

    measurements = pd.read_parquet(args.data)
    events = pd.read_parquet(args.events)
    with psycopg.connect(**_database_settings()) as connection:
        inserted_measurements, inserted_events = load_frames(
            connection,
            measurements,
            events,
        )
    print(
        f"Loaded {inserted_measurements:,} new measurements and "
        f"{inserted_events:,} new ground-truth events."
    )


if __name__ == "__main__":
    main()
