"""Subscribe to a public MQTT topic prefix and validate telemetry for a fixed duration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt
from jsonschema import ValidationError as JsonSchemaValidationError
from paho.mqtt.client import MQTTMessage

from wlm.schema import validate_payload
from wlm.tank import load_tank_config


class StreamValidator:
    def __init__(self) -> None:
        self.message_count = 0
        self.invalid_count = 0
        self.errors: list[str] = []
        self.last_sequence: dict[str, int] = {}
        self.tank = load_tank_config()
        self._lock = threading.Lock()

    def process(self, topic: str, payload: bytes) -> dict[str, Any]:
        try:
            data = json.loads(payload.decode("utf-8"))
            measurement = validate_payload(data, tank=self.tank)
            error = None
            with self._lock:
                previous = self.last_sequence.get(topic)
                if previous is not None and measurement.seq != previous + 1:
                    error = f"sequence expected {previous + 1}, got {measurement.seq}"
                self.last_sequence[topic] = measurement.seq
        except (
            JsonSchemaValidationError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
        ) as exception:
            data = None
            error = str(exception)

        with self._lock:
            self.message_count += 1
            if error is not None:
                self.invalid_count += 1
                self.errors.append(error)
        return {
            "topic": topic,
            "valid": error is None,
            "error": error,
            "seq": data.get("seq") if isinstance(data, dict) else None,
        }


def _positive_seconds(value: str) -> int:
    seconds = int(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("seconds must be a positive integer")
    return seconds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix",
        default=os.environ.get("MQTT_TOPIC_PREFIX"),
        help="topic prefix such as wlm/tdia2-ensa-a1b2c3 (or set MQTT_TOPIC_PREFIX)",
    )
    parser.add_argument("--seconds", type=_positive_seconds, default=60)
    parser.add_argument("--host", default="broker.hivemq.com")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    if not args.prefix:
        parser.error("provide --prefix or set MQTT_TOPIC_PREFIX")

    validator = StreamValidator()
    connected = threading.Event()
    subscription = f"{args.prefix}/+/telemetry"

    def on_connect(
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code == 0:
            client.subscribe(subscription, qos=0)
            connected.set()
        else:
            print(f"MQTT connection failed: {reason_code}", file=sys.stderr, flush=True)

    def on_message(client: mqtt.Client, userdata: Any, message: MQTTMessage) -> None:
        result = validator.process(message.topic, message.payload)
        print(json.dumps(result, separators=(",", ":")), flush=True)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"wlm-validator-{int(time.time())}",
    )
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(args.host, args.port, keepalive=30)
        client.loop_start()
        if not connected.wait(timeout=15):
            print("Timed out connecting to the MQTT broker", file=sys.stderr)
            return 2
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            time.sleep(min(0.25, deadline - time.monotonic()))
    except (OSError, ValueError) as error:
        print(f"MQTT stream validation failed: {error}", file=sys.stderr)
        return 2
    finally:
        if client.is_connected():
            client.disconnect()
        client.loop_stop()

    result = {
        "messages": validator.message_count,
        "invalid": validator.invalid_count,
        "seconds": args.seconds,
    }
    print(json.dumps(result, separators=(",", ":")))
    if validator.message_count == 0:
        print("No telemetry received; is the Wokwi simulation publishing?", file=sys.stderr)
        return 2
    return 1 if validator.invalid_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
