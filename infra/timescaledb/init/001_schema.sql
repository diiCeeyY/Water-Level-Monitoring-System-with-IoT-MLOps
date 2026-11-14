CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS devices (
  device_id        TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  shape            TEXT NOT NULL DEFAULT 'cylinder',
  diameter_cm      REAL NOT NULL,
  water_height_cm  REAL NOT NULL,
  sensor_offset_cm REAL NOT NULL,
  capacity_l       REAL NOT NULL,
  critical_pct     REAL NOT NULL,
  warning_pct      REAL NOT NULL,
  pump_on_pct      REAL NOT NULL,
  pump_off_pct     REAL NOT NULL
);

INSERT INTO devices (
  device_id, name, shape, diameter_cm, water_height_cm, sensor_offset_cm,
  capacity_l, critical_pct, warning_pct, pump_on_pct, pump_off_pct
)
VALUES (
  'tank-01', 'Water tank 01', 'cylinder', 100, 150, 15,
  1178.097, 15, 25, 35, 90
)
ON CONFLICT (device_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS measurements (
  time           TIMESTAMPTZ      NOT NULL,
  device_id      TEXT             NOT NULL,
  seq            BIGINT           NOT NULL CHECK (seq >= 0),
  distance_cm    DOUBLE PRECISION,
  level_pct      DOUBLE PRECISION,
  volume_l       DOUBLE PRECISION,
  pump_on        BOOLEAN          NOT NULL,
  sensor_ok      BOOLEAN          NOT NULL,
  rssi           SMALLINT,
  source         TEXT             NOT NULL CHECK (source IN ('wokwi', 'replay', 'synthetic')),
  schema_version SMALLINT         NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  ingested_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
  CHECK (
    (sensor_ok AND distance_cm IS NOT NULL AND level_pct IS NOT NULL AND volume_l IS NOT NULL)
    OR
    (NOT sensor_ok AND distance_cm IS NULL AND level_pct IS NULL AND volume_l IS NULL)
  ),
  CHECK (distance_cm IS NULL OR distance_cm BETWEEN 2 AND 400),
  CHECK (level_pct IS NULL OR level_pct BETWEEN 0 AND 100),
  CHECK (volume_l IS NULL OR volume_l BETWEEN 0 AND 2000),
  CHECK (rssi IS NULL OR rssi BETWEEN -120 AND 0),
  PRIMARY KEY (device_id, time)
);

SELECT create_hypertable(
  'measurements',
  by_range('time', INTERVAL '7 days'),
  if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS device_status (
  device_id   TEXT PRIMARY KEY,
  online      BOOLEAN     NOT NULL,
  last_seen   TIMESTAMPTZ NOT NULL,
  last_seq    BIGINT,
  fw_version  TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invalid_messages (
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  topic       TEXT,
  payload     TEXT,
  reason      TEXT NOT NULL
);
