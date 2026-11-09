# ROADMAP.md — Phase-by-phase build plan

> Companion to [`../PROJECT_GUIDE.md`](../PROJECT_GUIDE.md) (what and why) and [`CONCEPTS_GUIDE.md`](CONCEPTS_GUIDE.md) (learn first). This file is the **how and in what order**.

## 0. How to work with this roadmap

**Rules (from the brief).** One phase at a time · don't start phase N+1 until phase N's tests pass · complete code for every file, with its exact path · PowerShell commands in the VS Code terminal, run from the repository root · Docker commands are explained before you run them · no secrets in Git · tests for every important function.

**Rhythm for each phase:** (1) read the *Learn first* concepts → (2) read the matching guide sections → (3) build → (4) run the tests → (5) tick the *Definition of Done* → (6) commit and tag `phase-N-done` → (7) CI must be green.

### 0.1 What I changed compared with your proposed sequence — and why

| Your phase | In this roadmap | Change | Reason |
|---|---|---|---|
| 0 Environment | **0** | + CI skeleton | CI from day one costs 10 minutes now and saves a painful setup later |
| 1 IoT simulation | **1** | + data contract (schema, `tank.yaml`) first | One schema for firmware, MQTT, DB, ML (your requirement 9.A) — define it *before* the first producer |
| 2 MQTT infra | **2** | + TimescaleDB and the Compose core moved here | Live data cannot be stored until the DB exists; this is exactly the PDF's "socle commun" |
| 3 Historical data | **3** | + DVC, loader, replay publisher | The first dataset is the natural moment to start versioning it |
| 4 DB + dashboards | **4** (Grafana only) | DB part moved to phase 2 | Dashboards need data from phases 2-3 |
| 5 ML | **5** | + MLflow container started here | Track experiments from the first training instead of retro-fitting |
| 6 MLOps | **6** | registry, gate, API | Same content, cleaner scope |
| 7 Containerisation | **7** | incremental (Compose grows every phase); this phase adds the worker and full integration | "Dockerise at the end" is where projects stall |
| 8 Monitoring/retraining | **9** | swapped with alerts | Retraining notifications use the alert engine |
| 9 Alerts | **8** | swapped | Alerts give early visible value and are simpler than drift/retraining |
| 10 CI/CD + validation | **10** | hardening only | CI already exists since phase 0 |

### 0.2 Effort and risk (relative)

| Phase | Effort | Risk | Why |
|---|---|---|---|
| 0 | S | Low | Tool installation |
| 1 | M | Medium | Wokwi/PubSubClient details |
| 2 | L | **High** | Bridge, auth/ACL, Node-RED, Windows/Docker |
| 3 | L | Medium | Generator realism |
| 4 | M | Low | Mostly configuration |
| 5 | L-XL | Medium | Leakage and honest evaluation |
| 6 | L | Medium | MLflow ≥ 3.5 host check, registry/gate logic |
| 7 | L | Medium | RAM, data-time semantics |
| 8 | M | Low | Telegram setup, alert state machine |
| 9 | **XL** | **High** | Drift calibration, retrain deadlock, scheduling |
| 10 | M | Low | Polish |

Stop after **Phase 4** and you have the PDF's base chain; after **Phase 8**, the core of the brief; after **Phase 10**, everything (MVP cut line, Guide §1.4).

### 0.3 Learning order

| Phase | Read first in `CONCEPTS_GUIDE.md` |
|---|---|
| 0 | D2-D4, D9 |
| 1 | A1-A2 |
| 2 | A2-A6, D4-D7 |
| 3 | C7-C8 |
| 4 | A7 |
| 5 | B1-B7 |
| 6 | C4-C6, C9-C10, D11 |
| 7 | D5-D8 |
| 8 | (Guide §22) |
| 9 | C11-C14 |
| 10 | C15, D9-D10 |

---

## Phase 0 — Environment, repository, CI skeleton

- **Objective:** a working toolchain and a repository that tests itself on every push.
- **Learn first:** Git basics; Docker (D2-D3); Compose (D4); GitHub Actions (D9).
- **Technologies:** Git, VS Code, Python 3.11, Docker Desktop (WSL2), GitHub Actions.
- **Depends on:** nothing.
- **Tasks**
  1. Install the tools in Guide Appendix B; create `%UserProfile%\.wslconfig` (Guide §16.6) and run `wsl --shutdown`.
  2. Create the GitHub repository `water-level-mlops`; clone it; create the folder skeleton of Appendix A (empty folders with `.gitkeep`).
  3. Add `.gitignore` (`.env`, `infra/mosquitto/passwd`, `.venv/`, `data/`, `__pycache__/`, `node_modules/`, `mlruns/`, `reports/evidently/`), `.gitattributes` (`* text=auto eol=lf`), `.env.example` (Guide §16.2), copy `PROJECT_GUIDE.md` and `docs/`.
  4. Create `pyproject.toml` (package `wlm`, extras `ml`, `api`, `jobs`, `dev`), `src/wlm/__init__.py`, `tests/unit/test_smoke.py`.
  5. Configure `ruff`; add `.pre-commit-config.yaml` (ruff + gitleaks).
  6. Add `.github/workflows/ci.yml` with the `lint-test` job only (Guide §23.2) and `dependabot.yml`.
- **Files:** `.gitignore`, `.gitattributes`, `.env.example`, `pyproject.toml`, `src/wlm/__init__.py`, `tests/unit/test_smoke.py`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `README.md` (stub).
- **Commands**

```powershell
git --version ; python --version ; docker --version ; docker compose version
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev]"
pytest -q ; ruff check .
docker run --rm hello-world           # pulls a tiny image and runs it once, then deletes the container
pre-commit install
```

- **Expected output:** `1 passed`; Docker prints "Hello from Docker!"; the GitHub Actions run is green.
- **Tests:** smoke test; CI run.
- **Definition of Done:** fresh `git clone` + `pip install -e ".[dev]"` + `pytest` works · CI green · `.env` is untracked (`git status` shows nothing after you create it) · WSL2 memory cap applied.

---

## Phase 1 — Data contract and IoT simulation

- **Objective:** one measurement schema everywhere, and a simulated ESP32 publishing valid telemetry to a public broker.
- **Learn first:** MQTT and brokers (A1-A2); HC-SR04 basics (echo time × 0.0343 / 2 cm).
- **Technologies:** Wokwi, ESP32 (Arduino), PubSubClient, ArduinoJson, Python (pydantic, jsonschema).
- **Depends on:** phase 0.
- **Tasks**
  1. `config/tank.yaml` (Guide §1.5); `src/wlm/tank.py` (distance ↔ level ↔ volume) + tests.
  2. `schemas/measurement.v1.schema.json`, golden `schemas/examples/valid_*.json` / `invalid_*.json`; `src/wlm/schema.py` (pydantic) + tests; both validators must agree on all examples.
  3. `scripts/new-prefix.ps1` → prints `wlm/tdia2-<group>-<6hex>`; put it in `.env` (`MQTT_TOPIC_PREFIX`).
  4. `tools/gen_firmware_config.py` → generates `iot/wokwi/config.h` from `tank.yaml`.
  5. Wokwi project (ESP32 DevKit, HC-SR04 on TRIG GPIO5/ECHO GPIO18, relay IN GPIO26, LED on the relay NO contact). Sketch: WiFi `Wokwi-GUEST`, NTP, 5-ping median, conversion, pump hysteresis (≤ 35 % ON, ≥ 90 % OFF) + dry-run protection, MQTT publish + LWT, `setBufferSize(512)`, `SIMULATE_NOISE` switch, `RELAY_ACTIVE_LOW` constant.
  6. `tools/validate_stream.py`: subscribe to the public broker for 60 s and validate every message against the schema.
- **Files:** `config/tank.yaml`, `schemas/*`, `src/wlm/tank.py`, `src/wlm/schema.py`, `tools/*.py`, `iot/wokwi/{sketch.ino,config.h,diagram.json,libraries.txt,README.md}`, `scripts/new-prefix.ps1`, tests.
- **Commands**

```powershell
python tools/gen_firmware_config.py
pytest tests/unit/test_tank_conversion.py tests/unit/test_schema.py -q
# watch the public broker without installing anything (runs a throw-away container):
docker run --rm eclipse-mosquitto:2 mosquitto_sub -h broker.hivemq.com -t "wlm/<groupid>/#" -v
python tools/validate_stream.py --prefix $env:MQTT_TOPIC_PREFIX --seconds 60
```

- **Expected output:** a JSON line per interval, `seq` increasing by 1, e.g. `{"schema_version":1,"device_id":"tank-01",…,"level_pct":51.7,…}`; moving the slider to 120 cm (level 30 %) turns the relay LED ON; to 25 cm (≈ 93 %) turns it OFF; stopping the simulation produces the retained `online:false` status.
- **Tests:** conversions at `d_full`, midpoint, `d_empty`, clamping; schema accepts/rejects goldens; constants in `config.h` equal `tank.yaml`; manual slider checks.
- **Definition of Done:** FR-01..03 · `validate_stream` reports 0 invalid messages in 60 s · the Wokwi project README documents pins and the prefix handling (**no secrets** in the project — it is public).

---

## Phase 2 — Core stack: Mosquitto + bridge, Node-RED, TimescaleDB

- **Objective:** a measurement published from Wokwi appears as a row in TimescaleDB within 5 s (the PDF's common base, minus Grafana).
- **Learn first:** brokers/topics/bridge (A2-A3), Node-RED (A4), time-series DB and hypertables (A5-A6), Compose, networking, volumes, env vars (D4-D7).
- **Technologies:** Docker Compose, Eclipse Mosquitto, Node-RED + `node-red-contrib-postgresql`, TimescaleDB.
- **Depends on:** phase 1.
- **Tasks**
  1. `docker-compose.yml` with `timescaledb`, `mosquitto`, `nodered` (Guide §16.4); named volumes; ports on `127.0.0.1`; healthchecks.
  2. `infra/timescaledb/init/` scripts: schema (Guide §9.3), MLflow DB creation, roles, seed `devices` from `tank.yaml`.
  3. `infra/mosquitto/`: `mosquitto.conf`, `aclfile`, `passwd` (interactive, git-ignored), bridge template + a render script using `.env`.
  4. `infra/nodered/Dockerfile` (installs the palette node), flow `flows.json` (validate/insert/quarantine/status), `NODE_RED_CREDENTIAL_SECRET`.
  5. Run the 8 communication tests of Guide §10.5.
  6. Add the `integration` job to CI (DB + Mosquitto); record `docker stats`.
- **Files:** `docker-compose.yml`, `infra/{timescaledb,mosquitto,nodered}/*`, `scripts/make-passwd.ps1`, `tests/integration/*`, `tests/contract/*`.
- **Commands (each explained)**

```powershell
docker compose config                       # validate the file and show resolved variables
docker compose up -d --build                # build custom images, create network + volumes, start services
docker compose ps                           # states and health
docker compose logs mosquitto --tail 50     # look for the bridge connecting (CONNACK, SUBSCRIBE)
docker compose exec timescaledb psql -U postgres -d wlm -c "SELECT count(*), max(time) FROM measurements;"
docker stats --no-stream                    # RAM per container
```

- **Expected output:** `timescaledb` healthy; bridge lines in the Mosquitto log; Node-RED debug shows one message per publish; the SQL count increases; invalid messages land in `invalid_messages`.
- **Tests:** `test_db_schema`, `test_mqtt_auth_acl`, `test_golden_messages` (Python vs Node-RED validator), `stack/test_ingestion_flow`; T1-T8.
- **Definition of Done:** FR-04..06 · T1-T8 pass · a 30-minute Wokwi run shows ≥ 95 % of messages received (criterion 1) · RAM numbers recorded in `docs/`.

---

## Phase 3 — Historical data: generator, DVC, loader, replay

- **Objective:** a reproducible, labelled 90-day dataset, versioned with DVC, loaded into the DB and replayable.
- **Learn first:** DVC and data vs model versioning (C7-C8); Guide §11.
- **Technologies:** Python (NumPy, pandas, pyarrow), DVC, paho-mqtt.
- **Depends on:** phase 1 (schema, tank), phase 2 (DB, broker).
- **Tasks**
  1. `params.yaml` (`generator`, `split` sections); `src/wlm/data/generator.py`, `scenarios.py`, `generate.py` (physics, intermittent consumption, pump controller identical to firmware, sensor model, event injection with split allocation).
  2. `src/wlm/data/validate.py` (checks of Guide §11.7) + plots to `reports/data_validation/`.
  3. `dvc init`; local remote; `dvc.yaml` stage `generate`.
  4. `src/wlm/data/loader.py` (`COPY` into `measurements`, events into `ground_truth_events`).
  5. `src/wlm/data/replay.py` + Compose profile `tools` (service `replay`).
  6. `notebooks/01_eda.ipynb`: daily profile, refill timing, event overlays.
- **Commands**

```powershell
python -m wlm.data.generate --params params.yaml --out data/raw
python -m wlm.data.validate --data data/raw/historical_90d.parquet --events data/raw/events_90d.parquet
dvc init ; dvc remote add -d localremote ..\dvc-remote
dvc repro ; dvc push
git add dvc.yaml dvc.lock params.yaml .dvc data/raw/.gitignore ; git commit -m "dataset v1"
python -m wlm.data.loader --data data/raw/historical_90d.parquet --events data/raw/events_90d.parquet
docker compose --profile tools run --rm replay python -m wlm.data.replay --file data/raw/historical_90d.parquet --from 2026-08-10 --days 1 --speed 720
```

- **Expected output:** ≈ 129 k rows; validation prints PASS with event counts per split; `dvc status` clean; Grafana-ready history in the DB; one replayed day takes ≈ 2 minutes and rows keep their original `ts`.
- **Tests:** determinism (same seed → same SHA-256), schema/invariants, mass balance, controller consistency, event coverage per split, no overlapping events.
- **Definition of Done:** FR-07, 08, 09 and the first half of FR-18 · figures look physically plausible in the EDA notebook (sawtooth levels, evening/morning peaks, flat frozen segments).

---

## Phase 4 — Grafana dashboards

- **Objective:** a provisioned dashboard showing live and historical state.
- **Learn first:** Grafana (A7); `time_bucket`, Grafana macros.
- **Technologies:** Grafana, TimescaleDB.
- **Depends on:** phases 2-3.
- **Tasks**
  1. Add `grafana` to Compose with provisioning/dashboards mounted read-only; read-only DB role `wlm_grafana`.
  2. Dashboard `wlm-main.json`: gauge *Current level %*, stat *Volume L*, time series *Level history*, state timeline *Pump*, table *Alerts* (empty for now), panel *Pipeline health* (age of last message, messages/min), annotations from `ground_truth_events`; placeholders for *Forecast overlay*, *Autonomy*, *Anomaly score* (filled in phase 7).
  3. Variable `$device`; browser timezone.
- **Commands**

```powershell
docker compose up -d grafana
start http://localhost:3000
```

- **Expected output:** the 90-day history with shaded ground-truth events; with Wokwi running, gauge and volume update within ~5 s of a slider change.
- **Tests:** a script asserts the dashboard JSON loads and references the provisioned datasource; manual check against SQL results.
- **Definition of Done:** FR-10 for current level/volume/history/pump · criterion 2 (≤ 5 s) · dashboard survives `docker compose down` / `up`.

---

## Phase 5 — Machine learning

- **Objective:** honest forecasting at +6 h and +24 h that beats the naive baselines, and an anomaly detector with diagnosis; everything tracked in MLflow from the first run.
- **Learn first:** all of B1-B7; Guide §12-14.
- **Technologies:** pandas, scikit-learn, LightGBM, MLflow, matplotlib.
- **Depends on:** phase 3.
- **Tasks**
  0. Add the `mlflow` service to Compose now (`infra/mlflow/Dockerfile`, Postgres backend, `MLFLOW_SERVER_ALLOWED_HOSTS`) so runs are tracked from the beginning.
  1. `src/wlm/features/grid.py` (right-edge 15-min grid, median of valid readings) and `forecasting.py` (lags, rolling, flow, pump, calendar, expected-demand profile fit on train only) + **leakage and parity tests**.
  2. `src/wlm/models/baselines.py`; `training/evaluate.py` (MAE, RMSE, bias, skill, `MAE_low`, per-regime).
  3. Ridge and LightGBM training for both horizons with `TimeSeriesSplit(gap=h)`, early stopping, small random search; nested MLflow runs.
  4. Anomaly: `features/anomaly.py`, `models/anomaly.py` (IsolationForest), `models/rules.py` (frozen/invalid/blocked/spike + diagnosis), threshold selection on validation, event-level evaluation (Guide §14.5).
  5. `models/autonomy.py` (A1/A2/A3) + offline early-warning simulation over the test period (`reports/early_warning.json`).
  6. `notebooks/02_forecasting_experiments.ipynb`, `03_anomaly_experiments.ipynb` (exploration only; final code in modules).
- **Commands**

```powershell
pytest tests/unit -q
python -m wlm.training.train_forecast --params params.yaml
python -m wlm.training.train_anomaly --params params.yaml
start http://localhost:5000        # MLflow UI: compare runs by val_mae
```

- **Expected output:** a comparison table (B1, B2, B3, Ridge, LightGBM) per horizon on validation and test; LightGBM MAE strictly below the best naive at both horizons; anomaly event-recall table per type with false alarms/week.
- **Tests:** `test_features_no_leakage`, `test_train_serve_parity`, `test_baselines`, `test_autonomy`, `test_anomaly_rules`, `model_quality/*`.
- **Definition of Done:** FR-11..15 · criterion 4 satisfied on the test period · criterion 6 targets met offline · lead-time simulation reports ≥ 6 h for every test-period crossing (criterion 5, offline) · results written to `reports/*.json`.

---

## Phase 6 — MLOps: registry, promotion gate, FastAPI

- **Objective:** registered model versions with aliases, a gate that promotes them, and an API that serves the champion.
- **Learn first:** experiment tracking, MLflow, registry, deployment, inference, REST/FastAPI (C4-C6, C9-C10, D11).
- **Technologies:** MLflow (registry, aliases), FastAPI, pydantic, DVC.
- **Depends on:** phase 5.
- **Tasks**
  1. `models/bundle.py` (model + `feature_list.json` + `profile.json` + imputer + `thresholds.json` + `reference_features.parquet`).
  2. Registration and aliases (`challenger`, `champion`, `previous`); `training/gate.py` with conditions A-E (Guide §15.6) + unit tests.
  3. Tag every run (`git_commit`, `data_sha256`, `trigger`, `feature_set_hash`).
  4. `src/wlm/serving/*` (endpoints of Guide §17.2, startup loading, cache, `/admin/reload`).
  5. Complete `dvc.yaml` (`build_dataset`, `train_forecast`, `train_anomaly`) with metrics files.
  6. Export `docs/openapi.json`.
- **Commands**

```powershell
python -m wlm.training.train_forecast --params params.yaml --register
python -m wlm.training.gate --model wlm-forecast-6h
$env:MLFLOW_TRACKING_URI="http://localhost:5000" ; uvicorn wlm.serving.app:app --port 8000
Invoke-RestMethod http://localhost:8000/v1/models
Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/forecast -ContentType "application/json" -Body '{"device_id":"tank-01"}'
dvc repro ; dvc metrics show
```

- **Expected output:** ≥ 6 runs per horizon in MLflow; three registered models with `champion`; `/v1/models` lists versions; `/v1/forecast` returns the JSON of Guide §17.2.
- **Tests:** gate conditions, API tests (`409`, `422`, reload swap, admin token), registry integration test.
- **Definition of Done:** FR-16, 17, 18 · criterion 7 · `dvc status` clean.

---

## Phase 7 — Containerisation and full integration (worker)

- **Objective:** the whole system in Compose; the worker predicts every 15 minutes of data time and stores results; Grafana shows forecasts, autonomy and anomalies.
- **Learn first:** networking, volumes, env vars, Dockerfiles (D5-D8).
- **Technologies:** Docker, Compose profiles, APScheduler.
- **Depends on:** phases 4 and 6.
- **Tasks**
  1. `docker/api.Dockerfile`, `docker/jobs.Dockerfile` (with `libgomp1`, non-root); add `api`, `worker`, `trainer`, `replay` services with memory limits and profiles.
  2. `src/wlm/worker/scheduler.py`, `jobs.py`: `predict` (15 min, data time) and `watchdog` (60 s); `CLOCK_MODE=data`.
  3. Persist forecasts and anomaly scores; add the *Forecast overlay*, *Autonomy*, *Anomaly* panels to the dashboard.
  4. Persistence tests (restart, down/up); measure RAM with `docker stats`.
- **Commands**

```powershell
docker compose up -d --build
docker compose --profile tools run --rm replay python -m wlm.data.replay --file data/raw/historical_90d.parquet --from 2026-09-14 --days 3 --speed 1440
docker compose logs worker --tail 20
docker stats --no-stream
docker compose down ; docker compose up -d       # volumes keep your data
```

- **Expected output:** `forecasts` gets a pair of rows every 15 min of data time; Grafana overlay follows the level; `/ready` OK; totals within the budget of Guide Appendix D.
- **Tests:** stack tests; parity through the container; data-time behaviour (accelerated replay does not trigger offline alerts).
- **Definition of Done:** FR-19 · criterion 3 · criterion 8 (partially: runs from your machine) · RAM table updated.

---

## Phase 8 — Alerts and Telegram

- **Objective:** actionable alerts with cooldowns, delivered to Telegram.
- **Learn first:** Guide §22; alert fatigue.
- **Technologies:** Telegram Bot API, httpx.
- **Depends on:** phase 7.
- **Tasks**
  1. Create the bot with @BotFather; get `chat_id`; put both in `.env`.
  2. `config/alerts.yaml`; `alerts/rules.py` (pure functions), `alerts/engine.py` (state machine: cooldown, re-arm, gating, escalation), `alerts/telegram.py` (retry, 429, no token in logs).
  3. Wire into the worker (`watchdog`, `predict`); `alerts` table panel in Grafana.
  4. Scenario runs with replay: critical level, predicted low, leak, frozen sensor, pump no-flow, device offline.
- **Commands**

```powershell
docker compose run --rm worker python -m wlm.alerts.telegram --test
docker compose --profile tools run --rm replay python -m wlm.data.replay --file data/raw/historical_90d.parquet --from <outage start - 12h> --days 2 --speed 720
```

- **Expected output:** messages on your phone formatted as in Guide §22.4; `alerts.telegram_message_id` populated; no repeated spam inside cooldowns.
- **Tests:** engine (cooldown, re-arm, `AUTONOMY_LOW` gating), Telegram mock, rules.
- **Definition of Done:** FR-20 · criterion 10 · criterion 5 measured end-to-end (lead time ≥ 6 h in data time for every test-period crossing) · ≤ 1 false alarm/week on the replayed normal period.

---

## Phase 9 — Monitoring, drift detection, automated retraining

- **Objective:** detect a consumption-pattern change, trigger retraining, gate and deploy the new model automatically.
- **Learn first:** monitoring, drift types, Evidently, retraining (C11-C14); Guide §20-21.
- **Technologies:** Evidently 0.7.x, MLflow, worker subprocess.
- **Depends on:** phases 6 and 8.
- **Tasks**
  1. `monitoring/performance.py` (rolling MAE from `forecast_errors`), `monitoring/drift.py` (Evidently report + `parse_result` with a frozen-sample test), `monitoring/policy.py` (trigger logic, Guide §21.1).
  2. `training/retrain.py` (snapshot + sha256, train challenger, evaluate champion vs challenger on the holdout, gate, promote, reload API, notify, `retrain_events`).
  3. Worker `monitor` job (daily, data time); hourly performance metric; Grafana *MLOps* dashboard (rolling MAE, drift share, model version, retrain events).
  4. **Calibrate the regime-change scenario** so rolling MAE reaches ≥ 1.5× reference; document the chosen parameters.
  5. Full scenario run (Guide §21.5); record it.
- **Commands**

```powershell
docker compose --profile tools run --rm replay python -m wlm.data.replay --file data/raw/regime_change_21d.parquet --speed 1440
docker compose logs -f worker
Invoke-RestMethod http://localhost:8000/v1/models        # version changes after promotion
```

- **Expected output:** rolling MAE climbs; Evidently HTML appears in `reports/evidently/`; `DRIFT_PERFORMANCE_DEGRADED` alert; one or more retrain attempts; `MODEL_RETRAINED`; API serves the new version; MAE returns to ≤ 1.2× reference.
- **Tests:** policy (two-consecutive rule, cooldown, max attempts), gate, drift parsing, a small end-to-end scenario test.
- **Definition of Done:** FR-21, 22 · criterion 9 · scenario parameters and results documented.

---

## Phase 10 — CI/CD hardening, final validation, demonstration

- **Objective:** a project you can defend: automated checks, an evidence report, a rehearsed demo.
- **Learn first:** CI vs CD (C15, D10).
- **Technologies:** GitHub Actions, GHCR (optional).
- **Depends on:** all previous phases.
- **Tasks**
  1. Complete `ci.yml` (`integration`, `model-quality-gate`, `docker-build` with caching; push to GHCR on `main` optional).
  2. `src/wlm/validation/report.py` → `reports/success_criteria.md`.
  3. Clean-clone test: `docker compose down -v`, fresh clone, `.env` from the example, build and run; time it (criterion 8).
  4. README: architecture diagram, quick start, results table, screenshots, honest limitations.
  5. Record a 60-second fallback video of the Wokwi chain; rehearse the demo twice (Guide §26).
  6. Tag `v1.0`.
- **Commands**

```powershell
python -m wlm.validation.report
docker compose down -v ; docker compose up -d --build     # ⚠ deletes volumes: only for the clean-start test
```

- **Expected output:** all ten criteria marked PASS with numbers; CI green with badge; images built.
- **Tests:** the whole suite (unit, contract, integration, model quality) in CI.
- **Definition of Done:** Guide §27 table fully green · fresh-clone start ≤ 10 minutes after the build · demo rehearsed · `v1.0` tagged.

---

## Phase review checklist (use at the end of every phase)

- [ ] All tests of the phase pass locally and in CI
- [ ] No secrets in the diff (`pre-commit` and `git status` clean)
- [ ] `docker compose ps` all healthy; `docker stats` within the budget
- [ ] Documentation updated (README progress table, any changed parameter in `params.yaml`)
- [ ] Definition of Done items ticked, tag `phase-N-done` created
