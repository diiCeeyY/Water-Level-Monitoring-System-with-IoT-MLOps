"""Replay selected historical rows to the local MQTT ingestion pipeline."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from datetime import time as datetime_time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import pandas as pd


def _from_time(value: str) -> datetime:
    parsed_date = date.fromisoformat(value)
    return datetime.combine(parsed_date, datetime_time.min, tzinfo=timezone.utc)


def replay_frame(
    frame: pd.DataFrame,
    *,
    broker: str,
    port: int,
    topic_prefix: str,
    speed: float,
    username: str | None = None,
    password: str | None = None,
    start: datetime | None = None,
    days: float | None = None,
    device_id: str | None = None,
) -> int:
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("speed must be a positive finite number")
    prefix = topic_prefix.strip("/")
    if not prefix or any(not part for part in prefix.split("/")):
        raise ValueError("topic_prefix must be a non-empty MQTT path")
    required = {"ts", "device_id", "seq"}
    if not required.issubset(frame.columns):
        raise ValueError(f"replay data is missing columns: {sorted(required - set(frame.columns))}")

    selected = frame.copy()
    selected["time"] = pd.to_datetime(selected["ts"], utc=True, errors="raise")
    if start is not None:
        if days is None or not math.isfinite(days) or days <= 0:
            raise ValueError("days must be positive when --from is provided")
        end = start + timedelta(days=days)
        selected = selected.loc[
            selected["time"].ge(pd.Timestamp(start)) & selected["time"].lt(pd.Timestamp(end))
        ]
    if device_id:
        selected = selected.loc[selected["device_id"].eq(device_id)]
    selected = selected.sort_values(["time", "seq"], kind="stable")
    if selected.empty:
        raise ValueError("the selected time range/device has no rows")
    if selected["time"].duplicated().any():
        raise ValueError("selected telemetry timestamps must be unique")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"wlm-replay-{uuid.uuid4().hex[:12]}",
        protocol=mqtt.MQTTv311,
    )
    if username:
        client.username_pw_set(username, password)
    client.connect(broker, port, keepalive=30)
    client.loop_start()

    first_time = selected.iloc[0]["time"]
    start_monotonic = time.monotonic()
    count = 0
    try:
        for row in selected.to_dict(orient="records"):
            message_time = row.pop("time")
            delay = max(
                0.0,
                (message_time - first_time).total_seconds() / speed
                - (time.monotonic() - start_monotonic),
            )
            if delay:
                time.sleep(delay)
            payload: dict[str, Any] = {}
            for key, value in row.items():
                if pd.isna(value):
                    payload[key] = None
                elif isinstance(value, pd.Timestamp):
                    payload[key] = value.isoformat()
                elif hasattr(value, "item"):
                    payload[key] = value.item()
                else:
                    payload[key] = value
            payload["source"] = "replay"
            topic = f"{prefix}/{payload['device_id']}/telemetry"
            info = client.publish(
                topic,
                payload=json.dumps(payload, separators=(",", ":"), allow_nan=False),
                qos=1,
                retain=False,
            )
            info.wait_for_publish(timeout=10)
            if not info.is_published():
                raise TimeoutError(f"MQTT publish timed out for sequence {payload['seq']}")
            count += 1
    finally:
        client.disconnect()
        client.loop_stop()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--days", type=float)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--device", default=None)
    parser.add_argument("--broker", default=os.environ.get("MQTT_BROKER", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument(
        "--prefix",
        default=os.environ.get("MQTT_TOPIC_PREFIX"),
    )
    args = parser.parse_args()
    if args.from_date is None and args.days is not None:
        parser.error("--days requires --from")
    if args.prefix is None:
        parser.error("--prefix or MQTT_TOPIC_PREFIX is required")
    frame = pd.read_parquet(args.file)
    count = replay_frame(
        frame,
        broker=args.broker,
        port=args.port,
        topic_prefix=args.prefix,
        speed=args.speed,
        username=os.environ.get("MQTT_USER_REPLAY"),
        password=os.environ.get("MQTT_PASS_REPLAY"),
        start=_from_time(args.from_date) if args.from_date else None,
        days=args.days,
        device_id=args.device,
    )
    print(f"Published {count:,} replay messages to {args.broker}:{args.port}.")


if __name__ == "__main__":
    main()
