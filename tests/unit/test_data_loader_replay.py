import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from wlm.data import loader, replay


def test_event_ids_are_stable_and_in_a_separate_namespace():
    time_value = "2026-07-01T00:00:00Z"
    first = loader.namespaced_event_id(1, time_value)
    assert first == loader.namespaced_event_id(1, time_value)
    assert first > 1_000_000_000
    assert first != loader.namespaced_event_id(2, time_value)


def test_event_id_rejects_non_utc_timestamp():
    with pytest.raises(ValueError, match="must be UTC"):
        loader.namespaced_event_id(1, "2026-07-01T01:00:00+01:00")


def test_replay_preserves_event_time_and_marks_source(monkeypatch):
    published = []

    class FakeInfo:
        def wait_for_publish(self, timeout):
            assert timeout == 10

        def is_published(self):
            return True

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["callback_api_version"] is replay.mqtt.CallbackAPIVersion.VERSION2

        def username_pw_set(self, username, password):
            assert (username, password) == ("replay", "private")

        def connect(self, broker, port, keepalive):
            assert (broker, port, keepalive) == ("localhost", 1883, 30)

        def loop_start(self):
            pass

        def publish(self, topic, payload, qos, retain):
            published.append((topic, json.loads(payload), qos, retain))
            return FakeInfo()

        def disconnect(self):
            pass

        def loop_stop(self):
            pass

    monkeypatch.setattr(replay.mqtt, "Client", FakeClient)
    frame = pd.DataFrame(
        [
            {
                "ts": "2026-07-01T00:00:00Z",
                "device_id": "tank-01",
                "seq": 0,
                "source": "synthetic",
                "level_pct": 80.0,
                "sensor_ok": True,
            },
            {
                "ts": "2026-07-01T00:01:00Z",
                "device_id": "tank-01",
                "seq": 1,
                "source": "synthetic",
                "level_pct": 79.9,
                "sensor_ok": True,
            },
        ]
    )
    count = replay.replay_frame(
        frame,
        broker="localhost",
        port=1883,
        topic_prefix="wlm/group",
        speed=1e9,
        username="replay",
        password="private",
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        days=1 / 24,
        device_id="tank-01",
    )

    assert count == 2
    assert [item[0] for item in published] == [
        "wlm/group/tank-01/telemetry",
        "wlm/group/tank-01/telemetry",
    ]
    assert [item[1]["ts"] for item in published] == [
        "2026-07-01T00:00:00Z",
        "2026-07-01T00:01:00Z",
    ]
    assert all(item[1]["source"] == "replay" for item in published)
    assert all(item[2:] == (1, False) for item in published)
