# Phase 2 — Start the Docker core

Run these commands from the repository root in a VS Code PowerShell terminal. Docker
Desktop must be running with the **Linux containers** engine.

## 1. Prepare local configuration

Copy `.env.example` only if you do not already have `.env`:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

In `.env`, set the database passwords, Node-RED credential secret, and MQTT passwords
to local values. Keep `.env` out of Git. The three MQTT passwords must exactly match
the passwords entered by the next command. Use the same `MQTT_TOPIC_PREFIX` as the
Wokwi firmware.

Add `MQTT_PASS_HEALTHCHECK=<your-local-password>` to `.env` if it is missing; older
`.env` files created before Phase 2 will not have this setting.

Set `MQTT_BRIDGE_CLIENT_ID` to a unique client ID for this running bridge, for example
`wlm-bridge-<random>`. The public broker is shared: a second bridge connecting with the
same client ID can disconnect the first one.
The Compose stack maps Postgres to host port `5433` by default to avoid conflicts with
local PostgreSQL services. Change `POSTGRES_HOST_PORT` in `.env` only if you need a
different available host port; containers still use port `5432` internally.

Create the Mosquitto password file. Docker starts a temporary Mosquitto utility
container and prompts for each password; it does not put passwords in the command line:

```powershell
.\scripts\make-passwd.ps1
```

The script preserves existing users and adds any missing accounts, so it is safe to rerun
after an interrupted setup. To change a password later, use the matching
`mosquitto_passwd` command from the Phase 2 roadmap; do not use the create (`-c`) option
on an existing file.

Render the local MQTT bridge configuration from `.env`:

```powershell
.\scripts\render-bridge.ps1
```

## 2. Validate and start the services

`docker compose config --quiet` checks YAML, interpolation, and service configuration
without starting containers:

```powershell
docker compose config --quiet
```

Pull/build the pinned images and start TimescaleDB, Mosquitto, and Node-RED in the
background:

```powershell
docker compose up -d --build
```

Check container health and startup logs:

```powershell
docker compose ps
docker compose logs --tail 50 timescaledb mosquitto nodered
```

Expected: TimescaleDB and Mosquitto become healthy; Node-RED becomes healthy after
startup. The bridge should log its connection/subscription to the public broker.

Measure the containers' current memory use:

```powershell
docker stats --no-stream
```

Stop the services without deleting their persistent data:

```powershell
docker compose down
```

Do **not** add `-v` to `docker compose down` unless you intentionally want to delete
the database and broker volumes.

## 3. Create the schema and ingest role

The SQL scripts run automatically when Postgres initializes a **new** data volume.
For an already-running stack, apply them once without removing the volume:

```powershell
docker compose exec -T timescaledb sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/001_schema.sql'
docker compose exec -T timescaledb sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/002_roles.sql'
```

The scripts create the `measurements` hypertable, `device_status`,
`invalid_messages`, and the `tank-01` device row. The second script creates the
least-privilege `wlm_ingest` role using `DB_PASS_INGEST` from the container environment.
Both scripts are safe to rerun.

## 4. Import and configure the Node-RED ingestion flow

Recreate the services so the new database and credential environment settings are
available, then open Node-RED:

```powershell
docker compose up -d --build
Start-Process http://localhost:1880
```

In the Node-RED editor, use **Menu → Import → select a file** and choose
`infra/nodered/flows.json`. Before deploying, open either MQTT input, edit the shared
**Local Mosquitto** broker configuration, and set:

- Server: `mosquitto`, port `1883`
- Username: `nodered`
- Password: the local `MQTT_PASS_NODERED` value from your `.env`

The database connection is preconfigured to use `wlm_ingest` and the `DB_PASS_INGEST`
environment variable; no database password needs to be added to the flow. Click
**Deploy**. The credential encryption key is read from
`NODERED_CREDENTIAL_SECRET`; `flows_cred.json` remains in the persistent Node-RED
volume and must not be committed.

The flow subscribes to the telemetry and status topics derived from
`MQTT_TOPIC_PREFIX` in `.env`, validates JSON shape, field types, ranges,
topic/device agreement, and UTC timestamps within 24 hours. Valid telemetry is
inserted idempotently and updates device status; status messages update `device_status`;
invalid messages are recorded in `invalid_messages`. SQL uses parameters rather than
building queries from payload data.

## 5. Verify ingestion

Keep the Wokwi simulation running and check that the database count increases:

```powershell
docker compose exec -T timescaledb sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*), max(time) FROM measurements;"'
docker compose exec -T timescaledb sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT device_id, online, last_seen, last_seq FROM device_status;"'
```

You should see new rows for `tank-01`; stopping Wokwi should eventually publish its
retained offline status. Check invalid-message handling with a deliberately malformed
test publish only if you intend to add a test row to `invalid_messages`.
