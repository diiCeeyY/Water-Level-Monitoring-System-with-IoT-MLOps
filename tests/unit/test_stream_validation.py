import json
from pathlib import Path

from tools.validate_stream import StreamValidator

ROOT = Path(__file__).resolve().parents[2]
VALID = json.loads((ROOT / "schemas" / "examples" / "valid_midlevel.json").read_text())


def test_stream_validator_accepts_valid_messages_with_increasing_sequence():
    validator = StreamValidator()
    first = validator.process("wlm/test/tank-01/telemetry", json.dumps(VALID).encode())
    next_payload = {**VALID, "seq": VALID["seq"] + 1}
    second = validator.process("wlm/test/tank-01/telemetry", json.dumps(next_payload).encode())

    assert first["valid"] is True
    assert second["valid"] is True
    assert validator.message_count == 2
    assert validator.invalid_count == 0


def test_stream_validator_reports_invalid_json_and_schema():
    validator = StreamValidator()
    malformed = validator.process("wlm/test/tank-01/telemetry", b"{")
    invalid = validator.process(
        "wlm/test/tank-01/telemetry",
        json.dumps({**VALID, "schema_version": 2}).encode(),
    )

    assert malformed["valid"] is False
    assert invalid["valid"] is False
    assert validator.invalid_count == 2


def test_stream_validator_reports_sequence_gaps():
    validator = StreamValidator()
    validator.process("wlm/test/tank-01/telemetry", json.dumps(VALID).encode())
    gap = validator.process(
        "wlm/test/tank-01/telemetry",
        json.dumps({**VALID, "seq": VALID["seq"] + 2}).encode(),
    )

    assert gap["valid"] is False
    assert "sequence expected" in gap["error"]
