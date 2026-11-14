CREATE TABLE IF NOT EXISTS ground_truth_events (
  event_id   BIGINT PRIMARY KEY,
  device_id  TEXT NOT NULL,
  start_time TIMESTAMPTZ NOT NULL,
  end_time   TIMESTAMPTZ NOT NULL,
  event_type TEXT NOT NULL,
  magnitude  DOUBLE PRECISION,
  params     JSONB NOT NULL DEFAULT '{}'::jsonb,
  CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS ground_truth_events_device_start_idx
  ON ground_truth_events (device_id, start_time);

GRANT SELECT, INSERT ON ground_truth_events TO wlm_ingest;
