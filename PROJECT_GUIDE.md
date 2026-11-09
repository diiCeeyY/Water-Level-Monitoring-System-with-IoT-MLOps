# PROJECT_GUIDE.md — Water Level Monitoring System with AI & MLOps

> **Version:** 1.0 (architecture baseline) · **Date:** 2026-11-07 · **Course:** IoT & Cloud mini-projects (TDIA2)
> **Companion documents:** [`docs/CONCEPTS_GUIDE.md`](docs/CONCEPTS_GUIDE.md) (learn the technologies) · [`docs/ROADMAP.md`](docs/ROADMAP.md) (phase-by-phase build plan)

This is the single technical reference for the project. It answers four questions for every part of the system: **what it does, why it exists, how it talks to the rest, and how we know it works.**

**How to read it.** Sections 1-5 give the big picture. Sections 6-10 describe components, data and messages. Sections 11-14 cover data generation and machine learning. Sections 15-23 cover MLOps, containers, serving, monitoring, retraining, alerts and CI. Sections 24-28 cover security, testing, the demo, success criteria and troubleshooting. Appendices hold the repository tree, install checklist, risk register and resource budget.

**Verified facts (checked 2026-11-07).** Several design choices depend on current tool behaviour. These were checked against current docs:

| Fact | Consequence for the design |
|---|---|
| Wokwi **free** plan uses a shared **public IoT gateway**: outgoing connections only, connections monitored, slower. The private gateway (incoming connections, to reach `localhost`) is **paid**. | ESP32 cannot reach the laptop's Mosquitto → public broker + bridge (D15). Never put secrets in the firmware. |
| Wokwi free plan = unlimited **public** projects; custom WiFi access points are paid; the free network is `Wokwi-GUEST`. | The topic prefix inside a public Wokwi project is public. Treat the public leg as untrusted. |
| MLflow **≥ 3.5** ships security middleware: the `Host` header must match `--allowed-hosts` (default: localhost + private IPs). | Inside Docker the hostname `mlflow` is rejected unless configured (Section 18, Section 28). |
| MLflow model **stages are deprecated**; **aliases** (`champion`, `challenger`) are the supported pattern. | We use aliases (D7). |
| **Evidently ≥ 0.7** has a new API (`from evidently import Report`, `from evidently.presets import DataDriftPreset`, `report.run(current, reference)`); the 0.4 API in most tutorials is different. | Pin the exact 0.7.x version; ignore old tutorials (Section 20). |
| `timescale/timescaledb` has **no `latest` tag**; use `latest-pg17` or an explicit `2.x.y-pg17`. Hypertables are created with `create_hypertable('t', by_range('time'))`. Columnstore API exists since 2.18. | Pin an explicit tag (Section 16). |
| `node-red-contrib-postgresql` (0.16.x) supports parameterised queries (`$1`) and stores DB credentials as encrypted Node-RED credentials. | Use it for ingestion (Section 6). |
| Public brokers: `broker.hivemq.com:1883` (plain only), `test.mosquitto.org` (1883 plain, 8883 TLS), `broker.emqx.io` (1883/8883). No SLA. | HiveMQ primary, test.mosquitto.org fallback; TLS on the bridge only with a broker that offers it (Section 10). |
| GitHub Actions majors in use in 2026: `actions/checkout` v6+, `actions/setup-python` v6+, `docker/setup-buildx-action` v4, `docker/build-push-action` v7, `docker/login-action` v4, `docker/metadata-action` v6. | Used in Section 23; Dependabot keeps them current. |

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Functional requirements](#2-functional-requirements)
3. [Non-functional requirements](#3-non-functional-requirements)
4. [Technical architecture](#4-technical-architecture)
5. [Architecture diagrams](#5-architecture-diagrams)
6. [Component descriptions](#6-component-descriptions)
7. [Technologies and their responsibilities](#7-technologies-and-their-responsibilities)
8. [Complete data flow](#8-complete-data-flow)
9. [Database schema and data structure](#9-database-schema-and-data-structure)
10. [MQTT topic structure and message examples](#10-mqtt-topic-structure-and-message-examples)
11. [Synthetic dataset generation strategy](#11-synthetic-dataset-generation-strategy)
12. [Machine learning methodology](#12-machine-learning-methodology)
13. [Forecasting strategy and evaluation](#13-forecasting-strategy-and-evaluation)
14. [Anomaly detection methodology](#14-anomaly-detection-methodology)
15. [MLOps architecture and lifecycle](#15-mlops-architecture-and-lifecycle)
16. [Docker and Docker Compose architecture](#16-docker-and-docker-compose-architecture)
17. [FastAPI inference architecture](#17-fastapi-inference-architecture)
18. [MLflow experiment tracking and model registry](#18-mlflow-experiment-tracking-and-model-registry)
19. [DVC dataset versioning](#19-dvc-dataset-versioning)
20. [Evidently monitoring and drift detection](#20-evidently-monitoring-and-drift-detection)
21. [Automated retraining strategy](#21-automated-retraining-strategy)
22. [Telegram notification architecture](#22-telegram-notification-architecture)
23. [GitHub Actions CI pipeline](#23-github-actions-ci-pipeline)
24. [Security considerations](#24-security-considerations)
25. [Testing and validation strategy](#25-testing-and-validation-strategy)
26. [Final demonstration scenario](#26-final-demonstration-scenario)
27. [Success criteria and evaluation metrics](#27-success-criteria-and-evaluation-metrics)
28. [Troubleshooting guide](#28-troubleshooting-guide)

Appendices: [A. Repository structure](#appendix-a--repository-structure) · [B. Installation checklist](#appendix-b--installation-and-dependency-checklist) · [C. Risk register](#appendix-c--risk-register) · [D. Resource budget](#appendix-d--resource-budget)

---

## 1. Project overview

### 1.1 Problem

A household tank is refilled by a pump (from a cistern or the network) and drained by consumption. The owner finds out the tank is empty when the taps stop. The goal is to **know the level now, know when it will become critical, and be told early** — and to notice abnormal behaviour (a leak, a dead sensor) that a simple threshold cannot explain.

### 1.2 What the system does

1. **Measures** the distance from an HC-SR04 (mounted above the tank) to the water surface on an ESP32 simulated in Wokwi.
2. **Converts** distance → level (%) → volume (litres) using the tank geometry, and **controls a pump** through a relay.
3. **Transports** each measurement over MQTT (Wokwi → public broker → bridge → local Mosquitto), **validates and stores** it (Node-RED → TimescaleDB) and **displays** it (Grafana).
4. **Forecasts** the level 6 h and 24 h ahead (LightGBM vs naive baselines) and derives the **remaining autonomy** before the critical level.
5. **Detects anomalies** (leaks, frozen/blocked/invalid sensor, abnormal consumption) with Isolation Forest plus deterministic sensor-fault rules.
6. **Runs an MLOps loop**: experiments tracked in MLflow, data versioned with DVC, best model registered and served by FastAPI in Docker, drift/performance monitored with Evidently, **retraining triggered** when forecast error exceeds a threshold after a consumption-pattern change.
7. **Notifies** through a Telegram bot.

### 1.3 Constraints inherited from the course PDF (`Les_Consignes_des_Mini_projets_TDIA2.pdf`)

| PDF rule | How this project complies |
|---|---|
| Simulated sensors only (Wokwi, Python scripts, dataset replay). | Wokwi ESP32 + Python generator + Python replay publisher. |
| No paid cloud, no credit card; "cloud" reproduced locally with Docker Compose (k3s/k3d/Minikube only for hard topics). | Docker Compose only. Kubernetes is **not justified** (D11). |
| Free/open-source tools only. | Every tool in Section 7 is free; none needs a card. |
| 8 GB RAM minimum; 16 GB advised for Kubernetes / Kafka / Spark / local LLM. | We avoid all four; budget in Appendix D; Compose profiles keep RAM low. |
| **Common base stack**: Mosquitto + Node-RED + time-series DB (InfluxDB **or** TimescaleDB) + Grafana, in one `docker-compose.yml`; each group adds *its* layer. | We build exactly this base (Phase 2) and add the **AI/MLOps layer** on top. |
| Wokwi free → public gateway → publish to a public broker with a **unique topic prefix per group**, bridge to local Mosquitto; **no sensitive data** on public brokers. | Section 10; Section 24. |
| Code in a Git repository (GitHub/GitLab). | GitHub repo, DVC for data. |
| "Chain sensor → broker → processing → storage → visualisation with **a single advanced brick** each." | Our brief is larger (AI **and** MLOps). **Scope risk** — see the MVP cut line below. |

### 1.4 MVP cut line (scope control)

The PDF expects one advanced layer; the brief asks for a full AI + MLOps stack. To stay safe, build in value order and know where a defensible project already exists:

| Tier | Contains | Result if you stop here |
|---|---|---|
| **Tier 1 — passes the PDF** | Phases 0-4: Wokwi → bridge → Mosquitto → Node-RED → TimescaleDB → Grafana, plus generator and history | Complete base chain with rich data |
| **Tier 2 — core of the brief** | Phases 5-8: forecasting, anomaly detection, MLflow, DVC, FastAPI, Docker, Telegram | Working AI service with alerts |
| **Tier 3 — full brief** | Phase 9 (drift + automated retraining) and Phase 10 (CI, validation, demo polish) | Everything in Section 27 |

### 1.5 Canonical tank and thresholds (single source of truth: `config/tank.yaml`)

| Parameter | Value | Note |
|---|---|---|
| Device id | `tank-01` | Used in topics, DB, API |
| Shape | Vertical cylinder | Volume = π·r²·h |
| Diameter | 100 cm | |
| Usable water height `H` | 150 cm | |
| Sensor offset (distance when full) `d_full` | 15 cm | Keeps the water out of the HC-SR04 dead zone (< 2 cm) |
| Distance when empty `d_empty` | 165 cm | `d_full + H` |
| Capacity | ≈ 1 178 L | 11.78 L per 1 % |
| `level_pct` | `100 · clamp(d_empty − d, 0, H) / H` | |
| `volume_l` | `π · (D/2)² · h / 1000` with `h = clamp(d_empty − d, 0, H)` cm | |
| Critical level | 15 % (≈ 177 L) | `LEVEL_CRITICAL` alert |
| Warning level | 25 % (≈ 295 L) | Only reachable if refill is not working |
| Pump ON / OFF (hysteresis) | ≤ 35 % / ≥ 90 % | Firmware control |
| Pump dry-run protection | OFF after 10 min if level did not rise ≥ 1 pp; retry after 30 min | Realistic safety logic; creates a recognisable "no flow" signature |
| Nominal pump flow | 40 L/min | Refill 35 → 90 % ≈ 16 min |

> **Why the pump threshold (35 %) is above the warning level (25 %).** In normal operation the pump refills before the tank gets low. The *critical* level is only reached when refill **fails** (supply outage, pump failure). That is precisely the scenario the early-warning system must catch, and it makes forecasting non-trivial: the model must learn both the consumption pattern **and** the pump's control rule, and must notice when the pump is running without effect.

### 1.6 Out of scope

Real hardware, multi-tank fleets, a mobile app, cloud deployment, Kubernetes, authentication portals, and exact physical modelling (temperature compensation of the speed of sound, tank deformation, sloshing).

---

## 2. Functional requirements

| ID | Requirement | Acceptance test | Phase |
|---|---|---|---|
| FR-01 | Firmware reads the HC-SR04 (median of 5 pings) and computes `level_pct`, `volume_l` from `config/tank.yaml` constants | Serial log shows values matching Section 1.5 formulas at 3 known distances | 1 |
| FR-02 | Firmware controls the relay with hysteresis (ON ≤ 35 %, OFF ≥ 90 %) and dry-run protection | Slider test in Wokwi: relay LED toggles at thresholds | 1 |
| FR-03 | Firmware publishes telemetry JSON (schema v1) to `wlm/<prefix>/tank-01/telemetry`, plus retained online/offline status with LWT | `mosquitto_sub` on the public broker shows messages | 1 |
| FR-04 | Local Mosquitto receives public-broker messages through a one-way (`in`) bridge | Message published publicly appears on local subscriber | 2 |
| FR-05 | Node-RED validates every message (schema, ranges, clock skew), stores valid ones, quarantines invalid ones | Valid → row in `measurements`; malformed → row in `invalid_messages` | 2 |
| FR-06 | TimescaleDB stores measurements in a hypertable, idempotently (`ON CONFLICT DO NOTHING`) | Re-sending the same message creates no duplicate | 2 |
| FR-07 | Generator produces ~90 days at 60 s resolution with the same schema as live data, deterministic by seed | Same seed → identical file hash; `validate` command passes | 3 |
| FR-08 | Generator injects labelled events (leak, frozen, blocked, dropout, spike, supply outage, consumption surge) into a separate ground-truth file | Every event type present in every split per Section 11.4 | 3 |
| FR-09 | Replay publisher streams synthetic data to MQTT at accelerated speed | 1 simulated day replayed in ≤ 2 min, rows visible in DB and Grafana | 3 |
| FR-10 | Grafana shows: current level %, current volume L, history, remaining autonomy, forecast overlay, alerts/anomalies, pump state | Dashboard provisioned from files; all panels populated | 4 |
| FR-11 | Feature pipeline builds the 15-min grid and lag/time features **without future information** | Leakage test passes (Section 25) | 5 |
| FR-12 | Naive baselines (persistence, seasonal-naive) and LightGBM forecasts at +6 h and +24 h | Metrics table in MLflow for both horizons | 5 |
| FR-13 | LightGBM MAE < best naive baseline MAE at both horizons on the test period | Automated quality gate | 5 |
| FR-14 | Isolation Forest + sensor-fault rules detect anomalies and assign a diagnosis | Event-level recall ≥ target (Section 27) | 5 |
| FR-15 | Remaining autonomy computed two ways (rate/profile-based and forecast-based) | Both values returned by API and shown in Grafana | 6 |
| FR-16 | Experiments, parameters, metrics, artifacts logged to MLflow; best models registered with aliases | MLflow UI shows runs and registered versions | 6 |
| FR-17 | FastAPI serves forecasts and anomaly diagnoses from the **champion** model versions | `/docs` works; `/v1/models` shows served versions | 6 |
| FR-18 | Datasets and pipeline stages versioned with DVC (local remote) | `dvc repro` reproduces metrics; `dvc status` clean | 3, 6 |
| FR-19 | Whole system runs through Docker Compose with persistent volumes | `docker compose up -d` from a clean clone (plus `.env`) | 7 |
| FR-20 | Alert engine sends Telegram messages for: critical level, predicted low level, anomaly, sensor fault, pump no-flow, device offline | Each alert type triggered by a scenario and received | 8 |
| FR-21 | Monitoring job computes rolling forecast MAE against realised truth and an Evidently drift report | Metrics in `monitoring_metrics`; HTML report saved | 9 |
| FR-22 | Retraining triggers when rolling MAE exceeds the threshold; challenger is registered, gated, promoted, and the API reloaded | `retrain_events` row with `promoted=true`; API serves new version | 9 |
| FR-23 | CI runs lint + tests + Docker builds on every push | Green workflow badge | 0→10 |
| FR-24 | A validation report checks all 10 success criteria | `reports/success_criteria.md` generated | 10 |

> Phase numbers refer to the **improved roadmap** in [`docs/ROADMAP.md`](docs/ROADMAP.md): it moves the database earlier (Phase 2) and puts alerts (Phase 8) before monitoring and retraining (Phase 9).

---

## 3. Non-functional requirements

| ID | Category | Requirement | How it is met / verified |
|---|---|---|---|
| NFR-01 | **Cost** | 0 € and no credit card | Open-source images, free GitHub tier, Telegram Bot API (free) |
| NFR-02 | **Hardware** | Runs on 8 GB RAM laptop (16 GB preferred) | Compose profiles; Postgres tuned small; WSL2 memory cap; budget in Appendix D; `docker stats` check |
| NFR-03 | **Reproducibility** | Same seed + same params → same data, same metrics (within tolerance) | Seeded generator, DVC pipeline, pinned dependencies, MLflow tags with git commit + data hash |
| NFR-04 | **Consistency** | One measurement schema across firmware, generator, MQTT, Node-RED, DB, ML | JSON Schema + pydantic model + golden examples tested in CI (Section 25) |
| NFR-05 | **No training/serving skew** | Training and inference use the *same* feature code | One `wlm.features` module; skew test compares both paths |
| NFR-06 | **Latency** | Publish → row in DB ≤ 5 s (public broker path, normal conditions); API forecast ≤ 1 s | Timestamps `ts` vs `ingested_at`; API timing test |
| NFR-07 | **Availability (best effort)** | Containers restart on failure; services start in dependency order; public-broker outage must not break the local stack | `restart: unless-stopped`, healthchecks, fallback broker, replay publisher writes straight to local Mosquitto |
| NFR-08 | **Security (proportionate)** | No secrets in Git; auth + ACL on local broker; least-privilege DB roles; nothing sensitive on public broker | Section 24 checklist |
| NFR-09 | **Observability** | Every service has logs and a health check; pipeline health visible in Grafana | `last_seen`, messages/min panel, `/health` endpoints |
| NFR-10 | **Testability** | Business logic (conversion, features, alerts) unit-testable without Docker | Logic lives in the `wlm` Python package, not in Node-RED function nodes |
| NFR-11 | **Maintainability** | One package, one config source per concern, no unnecessary microservices | 7 long-running containers, 1 on-demand job |
| NFR-12 | **Portability** | Windows 10/11 + VS Code + Docker Desktop; same commands in CI (Linux) | PowerShell commands in roadmap; `.gitattributes` forcing LF for shell/YAML |
| NFR-13 | **Data quality** | Invalid data never silently enters training or serving | Node-RED validation, `sensor_ok` flag, grid completeness feature, drift/quality checks |
| NFR-14 | **Time correctness** | All timestamps UTC at rest; local-time features computed with `Africa/Casablanca` | Section 11/13 |

---

## 4. Technical architecture

### 4.1 Layers and responsibilities

| Layer | Question it answers | Components |
|---|---|---|
| **Edge** | "What is the water level right now?" | Wokwi ESP32, HC-SR04, relay + simulated pump; Python replay publisher (accelerated scenarios) |
| **Transport** | "How does a measurement reach the laptop?" | Public MQTT broker → one-way bridge → local Mosquitto |
| **Ingestion** | "Is this message valid, and where does it go?" | Node-RED (validate, route, store) |
| **Storage** | "Where is history kept, and what else needs persisting?" | TimescaleDB (measurements, forecasts, anomalies, alerts, monitoring metrics); Parquet files under DVC for training data |
| **Visualisation** | "What does the operator see?" | Grafana (provisioned dashboards) |
| **Intelligence** | "What will happen, and is something wrong?" | `wlm` Python package: features, baselines, LightGBM, Isolation Forest, sensor rules, autonomy |
| **MLOps** | "Which model is live, how good is it, when do we retrain?" | MLflow (tracking + registry), DVC (data), FastAPI (serving), Evidently (monitoring), worker (scheduler + retrain trigger) |
| **Notification** | "How is a human told?" | Telegram Bot API (outbound only) |
| **Delivery** | "How is it built, tested and shipped?" | Docker, Docker Compose, GitHub Actions |

### 4.2 Design principles

1. **Contract first.** The measurement schema (Section 9.1) is defined once (JSON Schema + pydantic) and every producer/consumer is tested against the same golden messages.
2. **Same code for training and serving.** Feature engineering lives in one module that both the trainer and the API import. This is the cheapest cure for training/serving skew.
3. **Raw is 60 s, models see a 15-minute grid.** Live data (any cadence) and historical data are resampled by the *same* function into the same grid before any ML.
4. **Data time, not wall-clock time.** Every job runs "as of" the latest measurement timestamp. Without this, accelerated replays break monitoring (Section 8.5).
5. **Layered defence for alerts.** ML forecasts *and* deterministic rules (pump no-flow, autonomy, thresholds). If the model is wrong, rules still protect the user.
6. **Register ≠ deploy.** A model version becomes live only when an explicit gate sets the `champion` alias **and** the API reloads.
7. **Keep what is small small.** No Kafka, Kubernetes, Airflow, MinIO or Evidently UI service. Every extra container costs RAM and explanation time.
8. **Everything reproducible from the repo** plus a `.env` file.

### 4.3 Decision log

| # | Decision | Alternatives considered | Why this one / trade-off |
|---|---|---|---|
| D1 | One shared Python package `wlm` installed in two images (`api`, `jobs`) | Separate scripts per service | Single place for schema, tank maths, features → no skew; slightly more packaging work |
| D2 | Raw cadence 60 s; ML grid 15 min, label = **right edge**, value = median of valid readings in `(t−15 min, t]` | Raw-resolution models; hourly grid | 15 min gives 24/96 steps for 6 h/24 h, small tables (~8.6 k rows for 90 days), robust to missing messages; median ignores spikes |
| D3 | **Direct** multi-horizon forecasting: one LightGBM model per horizon | Recursive (one-step model fed its own output); multi-output | No error accumulation; trivial to evaluate per horizon; two models instead of one |
| D4 | Intelligence + alert logic in a Python **worker** | Node-RED function nodes; Grafana alerting | Testable with pytest, one alert history table. Node-RED stays ingestion-only. Grafana alerting remains a valid alternative for pure thresholds |
| D5 | **API reads the recent window from TimescaleDB** (read-only role) and builds features itself | Caller sends the full window | Caller only sends `device_id` + `as_of`; features cannot diverge from training; API needs a DB credential |
| D6 | MLflow backend = **PostgreSQL** (a second database in the Timescale instance); artifacts on a local volume through the tracking server (`--serve-artifacts`) | SQLite + file store; MinIO/S3 | One fewer container than MinIO; Postgres avoids SQLite locking; local volume is enough for MBs of models |
| D7 | Registry **aliases** `champion` / `challenger` (+ `previous` for rollback) | Deprecated stages | Supported pattern in MLflow 3 |
| D8 | Explicit **promotion gate**, then `POST /admin/reload` on the API | Auto-deploy on registration | Prevents a worse model going live; matches "registration ≠ deployment" |
| D9 | Retraining runs **inside the worker's image** as a subprocess (`python -m wlm.training.retrain`) | Docker-socket from worker; Airflow/Prefect; GitHub Actions | No privileged socket, no extra service; GitHub runners cannot see local data |
| D10 | Evidently as a **library**: HTML reports to a volume + key numbers to `monitoring_metrics` | Evidently UI/Cloud service | Saves a container; Grafana already visualises the numbers |
| D11 | Docker Compose with **profiles**; no Kubernetes | k3s/k3d/Minikube | Kubernetes is explicitly unjustified: single host, 8 GB RAM, no scaling/HA requirement |
| D12 | Wokwi **and** a Python replay publisher | Wokwi only | Wokwi runs in real time (a tank takes days to drain) and its slider is manual. Replay gives accelerated, labelled, repeatable scenarios (PDF allows script replay) |
| D13 | Jobs use **data time** (`as_of = max(time)`) | Wall clock | Needed for accelerated replays and for deterministic tests |
| D14 | **Hybrid anomaly detection**: Isolation Forest + deterministic sensor rules + diagnosis layer | Isolation Forest alone | A frozen sensor at night looks like "no consumption" to a statistical model; a rule on zero variance is more reliable. IF still evaluated alone for the report |
| D15 | Bridge **inbound only**; no commands over the public broker; QoS 0 publish with `seq` for gap detection | Bidirectional bridge, remote pump commands | A public broker is open to everyone: anyone could publish a pump command. PubSubClient publishes QoS 0 only, so `seq` reveals loss |
| D16 | Timestamps in **UTC**; time features from `Africa/Casablanca` local time via `zoneinfo` | Local timestamps; fixed UTC+1 | Morocco is UTC+1 except during Ramadan (UTC+0); the tz database encodes this. Consumption follows the local clock |
| D17 | **Parquet + DVC** for training data; **TimescaleDB** for serving/monitoring | Train directly from DB | Reproducible, versioned training sets; DB remains the live source of truth |
| D18 | Telegram is **outbound only** (HTTPS to Bot API); optional `/status` via long polling | Webhooks | No public URL needed from a student laptop |

### 4.4 Stack evaluation — compatibility, dependencies, bottlenecks

**Potential problems and mitigations**

| # | Problem | Why it matters | Mitigation |
|---|---|---|---|
| 1 | Wokwi free cannot reach `localhost` | Direct ESP32 → local Mosquitto is impossible | Public broker + bridge (verified: public gateway = outgoing only) |
| 2 | Public brokers have no SLA, are open, share a global namespace, show retained messages to everyone | Lost/injected/visible data | Unique prefix, non-sensitive payload, validation + quarantine locally, fallback broker, replay publisher bypasses it |
| 3 | A *public* Wokwi project exposes the firmware **and the topic prefix** | Prefix is not a secret | Treat inbound data as untrusted; never embed credentials; rotate the prefix if abused |
| 4 | PubSubClient: QoS 0 publish, default 256-byte packet buffer | Silent truncation/loss of a ~230-byte JSON | `client.setBufferSize(512)`; use `seq` to detect gaps |
| 5 | Wokwi's HC-SR04 is **noise-free** | A static slider looks like a *frozen sensor* to the detector | Firmware option `SIMULATE_NOISE` (±0.3 cm Gaussian); detector thresholds derived from noisy data |
| 6 | MLflow ≥ 3.5 host validation | Containers get "Invalid Host header" | `MLFLOW_SERVER_ALLOWED_HOSTS=mlflow:5000,localhost:*,127.0.0.1:*` |
| 7 | Evidently API changed at 0.7 | Tutorials crash | Pin `evidently==0.7.x`; code against the new API |
| 8 | TimescaleDB: no `latest` tag; PK must include `time`; new `by_range` API | Failed init scripts | Pin tag; PK `(device_id, time)`; use `by_range` |
| 9 | Windows + Docker Desktop: WSL2 takes up to half the RAM, bind mounts to NTFS are slow, CRLF breaks shell entrypoints | OOM, slow Postgres, `exec format error` | `.wslconfig` memory cap, **named volumes** for Postgres, `.gitattributes` `* text=auto eol=lf` for `*.sh`, `*.yml` |
| 10 | LightGBM needs OpenMP (`libgomp1`) on slim Debian images | Import error in container | Install `libgomp1` in the Dockerfile |
| 11 | Node-RED credentials | Flow export may leak DB passwords | Credentials in `flows_cred.json` encrypted with `credentialSecret` (env var), both git-ignored; `flows.json` committed with env-var references |
| 12 | Grafana/containers use `localhost` wrongly | "Connection refused" | Inside the Compose network use service names (`timescaledb:5432`) |
| 13 | Synthetic-data circularity | A model trained on the generator's rules "learns the generator" | Add randomness (day-to-day variance, noise, outage durations), report results honestly as *simulation results*, test robustness on a changed regime |
| 14 | GitHub Actions cannot run Wokwi or your laptop's stack | CI proves less than the demo | CI = lint + unit/contract tests + DB integration + image builds + small model quality gate |
| 15 | Scope vs the PDF's "single advanced brick" | Risk of an unfinished project | MVP cut line (Section 1.4) |

**Service dependencies (start order).** `timescaledb` → (`mosquitto`, `nodered`, `grafana`, `mlflow`) → `api` (needs DB + MLflow + champion model) → `worker` (needs DB + API). The trainer job needs DB (optional), MLflow and data files.

**Bottlenecks.** (1) RAM — the Python ML images and Postgres dominate; (2) public-broker latency/availability; (3) Wokwi simulation speed (often below real time); (4) Node-RED single-threaded inserts — irrelevant at 1 msg/s, fine at 25 msg/s replay.

**Hardware.** Steady state ≈ 1.5-2.5 GB across containers + Docker/WSL2 overhead; training spikes to ~1-1.5 GB for a few minutes. Feasible on 8 GB only with a WSL2 cap (4 GB), profiles, and no browser-heavy multitasking (Appendix D).

**Can be simplified.** No MinIO (local artifact volume), no Evidently UI, no separate Postgres for MLflow, no Prometheus, no reverse proxy, no Kubernetes.

**Must stay separate.** Mosquitto vs Node-RED (broker vs processor), Grafana vs worker (display vs logic), MLflow server vs API (lifecycle vs serving), training job vs inference service (different resource profile and lifecycle).

---

## 5. Architecture diagrams

> Mermaid renders on GitHub and in VS Code with the extension **"Markdown Preview Mermaid Support"** (`bierner.markdown-mermaid`).

### 5.1 High-level architecture

```mermaid
flowchart LR
  subgraph EDGE["Edge (simulated)"]
    W["Wokwi ESP32<br/>HC-SR04 + relay"]
    R["Python replay publisher<br/>accelerated scenarios"]
  end
  PB(["Public MQTT broker<br/>broker.hivemq.com"])
  subgraph LOCAL["Student laptop - Docker Compose"]
    M["Mosquitto<br/>local broker + bridge"]
    N["Node-RED<br/>validate and route"]
    T[("TimescaleDB")]
    G["Grafana"]
    subgraph AI["AI and MLOps layer"]
      ML["MLflow<br/>tracking + registry"]
      API["FastAPI<br/>inference"]
      WK["Worker<br/>scheduler, alerts, monitoring"]
    end
  end
  TG["Telegram Bot API"]
  W -->|"MQTT publish"| PB
  PB -->|"bridge (inbound only)"| M
  R -->|"MQTT"| M
  M --> N
  N -->|"INSERT"| T
  T --> G
  T --> WK
  WK -->|"HTTP"| API
  API -->|"load champion models"| ML
  WK -->|"train, register"| ML
  WK -->|"forecasts, anomalies, alerts"| T
  WK -->|"HTTPS"| TG
```

**Reading it.** Data is *generated* at the edge (Wokwi or replay), *received* by Mosquitto, *processed/validated* by Node-RED, *stored* in TimescaleDB, *displayed* by Grafana. The worker reads the same database, asks the API for predictions, writes results back, and decides which alerts to send. Models are *trained and registered* through MLflow; the API *loads* the champion.

### 5.2 Detailed technical architecture (protocols and ports)

```mermaid
flowchart TB
  subgraph WOKWI["Wokwi cloud simulator"]
    FW["ESP32 firmware<br/>PubSubClient + ArduinoJson"]
  end
  subgraph INTERNET["Internet"]
    HQ(["broker.hivemq.com:1883"])
    TGA["api.telegram.org:443"]
  end
  subgraph NET["Docker network wlm-net"]
    MQ["mosquitto :1883<br/>auth + ACL"]
    NR["nodered :1880"]
    DB[("timescaledb :5432<br/>db wlm and db mlflow")]
    GF["grafana :3000"]
    MF["mlflow :5000"]
    AP["api :8000"]
    WRK["worker"]
    TRN["trainer<br/>on-demand job"]
  end
  VOL[("volumes<br/>pgdata, mlflow-artifacts,<br/>grafana-data, nodered-data,<br/>snapshots, reports")]
  FW -->|"MQTT QoS0 telemetry"| HQ
  MQ -->|"bridge: local broker connects out and subscribes"| HQ
  NR -->|"MQTT subscribe, user nodered"| MQ
  NR -->|"SQL role wlm_ingest"| DB
  GF -->|"SQL role wlm_grafana read-only"| DB
  AP -->|"SQL role wlm_ml read-only on measurements"| DB
  AP -->|"HTTP load models by alias"| MF
  WRK -->|"HTTP POST /v1/forecast, /v1/anomaly"| AP
  WRK -->|"SQL role wlm_ml writes forecasts, alerts"| DB
  WRK -->|"HTTPS sendMessage"| TGA
  WRK -->|"spawn on trigger"| TRN
  TRN -->|"HTTP log runs, register"| MF
  MF -->|"SQL backend store"| DB
  MF --- VOL
  DB --- VOL
  TRN --- VOL
```

### 5.3 Complete data flow (live path and inference loop)

```mermaid
sequenceDiagram
  autonumber
  participant D as ESP32 (Wokwi)
  participant PB as Public broker
  participant M as Mosquitto (local)
  participant NR as Node-RED
  participant DB as TimescaleDB
  participant G as Grafana
  participant W as Worker
  participant A as FastAPI
  participant TG as Telegram
  loop every 60 s (live demo may use 5-10 s)
    D->>D: read HC-SR04, median filter, compute level and volume, pump control
    D->>PB: publish telemetry JSON (QoS 0)
    PB-->>M: bridge forwards message (inbound)
    M-->>NR: deliver to subscriber
    NR->>NR: validate schema, ranges, clock skew
    NR->>DB: INSERT into measurements (ON CONFLICT DO NOTHING)
  end
  loop every 5-10 s
    G->>DB: SQL for dashboard panels
  end
  loop every 60 s (data time)
    W->>DB: latest row, last_seen, pump state
    W->>W: evaluate threshold and watchdog rules
  end
  loop every 15 min (data time)
    W->>A: POST /v1/forecast and /v1/anomaly with device_id and as_of
    A->>DB: read last 8 days of raw rows
    A->>A: resample to 15 min grid, build features, predict
    A-->>W: forecasts, autonomy, anomaly score and diagnosis
    W->>DB: store forecasts and anomaly_scores
    W->>W: evaluate alert rules with cooldown
    W->>TG: sendMessage when a rule fires
    W->>DB: store alert row
  end
```

### 5.4 AI / MLOps pipeline

```mermaid
flowchart TB
  subgraph DATA["Data layer"]
    GEN["Seeded generator"] --> RAW[("data/raw/*.parquet<br/>tracked by DVC")]
    LIVE[("TimescaleDB measurements")] --> SNAP["Snapshot export<br/>with sha256"]
  end
  RAW --> FE["Feature build<br/>wlm.features, shared code"]
  SNAP --> FE
  FE --> TR["Training job<br/>baselines, Ridge, LightGBM, Isolation Forest"]
  TR -->|"params, metrics, artifacts, data hash, git commit"| MLF[("MLflow tracking")]
  TR -->|"register version"| REG["MLflow Model Registry"]
  REG -->|"alias challenger"| GATE{"Promotion gate<br/>beats champion and baseline<br/>on recent holdout?"}
  GATE -->|"yes: alias champion"| CH["champion version"]
  GATE -->|"no"| KEEP["keep current champion"]
  CH -->|"load at startup or POST /admin/reload"| API["FastAPI inference"]
  API --> PRED[("forecasts and anomaly_scores")]
  PRED --> MON["Monitoring job<br/>MAE vs realised truth, Evidently drift"]
  LIVE --> MON
  MON -->|"writes metrics"| GRAF["Grafana panels and Telegram"]
  MON -->|"rolling MAE above threshold"| POL{"Retrain policy<br/>cooldown, enough new data"}
  POL -->|"yes"| SNAP
```

### 5.5 Deployment architecture (Docker)

```mermaid
flowchart LR
  subgraph HOST["Windows host - Docker Desktop with WSL2"]
    subgraph NET["network: wlm-net (bridge)"]
      mosquitto["mosquitto<br/>1883"]
      nodered["nodered<br/>1880"]
      tsdb["timescaledb<br/>5432"]
      grafana["grafana<br/>3000"]
      mlflow["mlflow<br/>5000"]
      api["api<br/>8000"]
      worker["worker<br/>no port"]
      trainer["trainer<br/>profile: train"]
      replay["replay<br/>profile: tools"]
    end
    V1[("pgdata")]
    V2[("mlflow-artifacts")]
    V3[("grafana-data")]
    V4[("nodered-data")]
    V5[("mosquitto-data")]
    V6[("snapshots and reports")]
  end
  tsdb --- V1
  mlflow --- V2
  grafana --- V3
  nodered --- V4
  mosquitto --- V5
  worker --- V6
  trainer --- V6
  replay -->|"MQTT"| mosquitto
  nodered -->|"MQTT"| mosquitto
  nodered -->|"SQL"| tsdb
  grafana -->|"SQL"| tsdb
  mlflow -->|"SQL"| tsdb
  api -->|"HTTP"| mlflow
  api -->|"SQL"| tsdb
  worker -->|"HTTP"| api
  worker -->|"SQL"| tsdb
  worker -->|"HTTP"| mlflow
  trainer -->|"HTTP"| mlflow
```

Only `1883`, `1880`, `3000`, `5000`, `8000` (and optionally `5432`) are published to the host, **bound to `127.0.0.1`**. Everything else talks over the internal network by service name.

### 5.6 Retraining and redeployment sequence

```mermaid
sequenceDiagram
  autonumber
  participant MJ as Monitor job (worker)
  participant DB as TimescaleDB
  participant TJ as Retrain subprocess
  participant ML as MLflow
  participant A as FastAPI
  participant TG as Telegram
  MJ->>DB: join forecasts with realised levels, compute rolling MAE
  MJ->>MJ: MAE above threshold on consecutive checks, cooldown ok, enough post-change days
  MJ->>TG: alert DRIFT_PERFORMANCE_DEGRADED
  MJ->>TJ: start retrain with trigger reason
  TJ->>DB: export snapshot (last 60 days) with sha256
  TJ->>TJ: build features, train challenger, evaluate champion and challenger on recent holdout
  TJ->>ML: log run, register new version, set alias challenger
  alt challenger passes gate
    TJ->>ML: set alias champion, keep previous alias for rollback
    TJ->>A: POST /admin/reload
    A->>ML: load models by alias champion
    A-->>TJ: now serving new version
    TJ->>DB: retrain_events promoted true
    TJ->>TG: MODEL_RETRAINED with before and after MAE
  else challenger fails gate
    TJ->>DB: retrain_events promoted false
    TJ->>TG: RETRAIN_REJECTED
  end
```

---

## 6. Component descriptions

Each component answers: **Role · Why necessary · Input · Output · Talks to · Implementation · Runs where.**

### 6.1 ESP32 firmware + HC-SR04 + relay/pump (Wokwi)

- **Role:** the simulated field device: measures, converts, controls the pump, publishes.
- **Why necessary:** it is the data source required by the brief and the PDF.
- **Input:** echo pulse from HC-SR04; WiFi/NTP time; (slider position set by you in the simulator).
- **Output:** telemetry JSON (schema v1) every `PUBLISH_INTERVAL_S`; retained `status` message (LWT); relay on/off.
- **Talks to:** public MQTT broker over `Wokwi-GUEST` WiFi.
- **Implementation:** Arduino C++ sketch; libraries `PubSubClient`, `ArduinoJson`. Pins: TRIG GPIO5, ECHO GPIO18, relay IN GPIO26 (polarity as a constant `RELAY_ACTIVE_LOW`), LED on the relay's NO contact = "pump powered". Median of 5 pings, 30 ms echo timeout, `0` ping = invalid → `sensor_ok=false`, `distance_cm=null`. Constants generated from `config/tank.yaml` into `config.h` by a tiny script (single source of truth). `setBufferSize(512)`. Optional `SIMULATE_NOISE`.
- **Runs:** **Wokwi** (browser or VS Code extension). Real-hardware note: ECHO is 5 V → use a 1 kΩ/2 kΩ divider before an ESP32 GPIO.

### 6.2 Public MQTT broker

- **Role:** rendezvous point reachable from Wokwi's public gateway.
- **Why necessary:** Wokwi free cannot reach the laptop (verified).
- **Input/Output:** MQTT publishes from the ESP32; forwards to subscribers (our bridge).
- **Talks to:** ESP32 (publisher), local Mosquitto bridge (subscriber).
- **Implementation:** nothing to deploy — `broker.hivemq.com:1883` (primary), `test.mosquitto.org:1883` (fallback). No auth, no SLA, everything visible to everyone.
- **Runs:** third-party internet service.

### 6.3 Mosquitto (local broker + bridge)

- **Role:** the project's own broker; entry point of the local infrastructure; hosts the bridge.
- **Why necessary:** decouples producers from consumers locally, gives auth/ACL, survives public-broker outages (the replay publisher talks to it directly), and is mandated by the PDF's common base.
- **Input:** messages from the bridge (public leg) and from local publishers (replay).
- **Output:** messages to subscribers (Node-RED).
- **Talks to:** public broker (bridge, outbound TCP), Node-RED, replay publisher.
- **Implementation:** `eclipse-mosquitto:2`; `mosquitto.conf` + `conf.d/bridge.conf` (inbound-only topic pattern); `passwd` and `aclfile`; persistence volume. Details in Section 10.
- **Runs:** Docker container.

### 6.4 Node-RED

- **Role:** ingestion and routing: subscribe → parse → validate → route → write to DB; maintain device status.
- **Why necessary:** required by the PDF; visual glue between MQTT and SQL; quarantines bad messages so the database stays clean.
- **Input:** MQTT messages on `wlm/<prefix>/+/telemetry` and `.../status`.
- **Output:** `INSERT` into `measurements`; `INSERT` into `invalid_messages`; `UPSERT` into `device_status`.
- **Talks to:** Mosquitto (subscribe), TimescaleDB (SQL).
- **Implementation:** `nodered/node-red` image + `node-red-contrib-postgresql`; flow: `mqtt in` → `json` → `function validate` → `switch` → `postgresql`. Validation logic is deliberately **tiny** (required fields, types, ranges, `|ts − now| ≤ 24 h` for live data); heavy logic stays in Python. `flows.json` committed, credentials encrypted and git-ignored.
- **Runs:** Docker container.

### 6.5 TimescaleDB

- **Role:** system of record for time series and for operational tables (forecasts, anomalies, alerts, monitoring metrics, retrain events); also hosts MLflow's backend database.
- **Why necessary:** efficient time-range queries (`time_bucket`), hypertable chunking, SQL for Grafana and for joins between forecasts and realised values.
- **Input:** inserts from Node-RED (live), bulk `COPY` (historical load), inserts from the worker.
- **Output:** query results to Grafana, API, worker.
- **Talks to:** Node-RED, Grafana, API, worker, MLflow.
- **Implementation:** `timescale/timescaledb:<2.x.y>-pg17` (pinned); init scripts in `infra/timescaledb/init/`; three roles (ingest / ml / grafana); `shared_buffers=128MB`, `max_connections=50`.
- **Runs:** Docker container, **named volume** `pgdata`.

### 6.6 Grafana

- **Role:** the operator's window: levels, volume, autonomy, forecasts, alerts, anomalies, pump state, model health.
- **Why necessary:** required by the brief and the PDF; the demo's visual proof.
- **Input:** SQL queries to TimescaleDB (read-only role).
- **Output:** dashboards (and optionally annotations from alerts/ground truth).
- **Talks to:** TimescaleDB only.
- **Implementation:** provisioned datasource (`timescaledb:5432`, "TimescaleDB" option on) and dashboards-as-JSON under `infra/grafana/`; variable `$device`. Timezone: browser (`Africa/Casablanca`).
- **Runs:** Docker container, volume `grafana-data`.

### 6.7 Synthetic data generator

- **Role:** produce ~3 months of realistic, **labelled** history, plus a drift scenario.
- **Why necessary:** Wokwi cannot yield enough data to train/evaluate ML; ground truth is needed to evaluate leak/fault detection.
- **Input:** `config/tank.yaml`, `params.yaml: generator` (seed, dates, event catalogue).
- **Output:** `data/raw/historical_90d.parquet` (schema v1 only) and `data/raw/events_90d.parquet` (ground-truth intervals); `regime_change_21d.parquet` for Phase 9.
- **Talks to:** nothing at runtime; loaded to DB by a loader; consumed by the feature pipeline and replay publisher.
- **Implementation:** `wlm.data.generator` (physics + consumption + pump control + sensor model + event injection), CLI `python -m wlm.data.generate`.
- **Runs:** local Python / `trainer` container; DVC stage `generate`.

### 6.8 Replay publisher

- **Role:** publish synthetic rows to MQTT at accelerated speed, same topics/payloads as the device (`source="replay"`).
- **Why necessary:** live demo of days of behaviour in minutes (leak, outage, regime change) through the **real** ingestion path.
- **Input:** a Parquet file, `--speed` factor, start offset, device id.
- **Output:** MQTT messages to local Mosquitto (or the public broker for a full-path test).
- **Talks to:** Mosquitto.
- **Implementation:** `wlm.data.replay` with `paho-mqtt`; sleeps `Δt/speed` between rows; handles gaps.
- **Runs:** Docker profile `tools` or local Python.

### 6.9 Feature pipeline (`wlm.features`)

- **Role:** turn raw 60 s rows into the 15-min grid and model-ready features (forecasting and anomaly).
- **Why necessary:** single implementation prevents training/serving skew and enforces leakage rules.
- **Input:** raw measurements DataFrame (+ tank config + train-period profile for "expected outflow").
- **Output:** grid DataFrame, forecast feature matrix `X` and targets `y_6h`, `y_24h`; anomaly feature matrix.
- **Talks to:** imported by trainer, API, worker.
- **Implementation:** pure pandas/NumPy functions, no I/O; unit tests with leakage guard.
- **Runs:** inside Python processes (trainer, API, tests).

### 6.10 Training job (`trainer`)

- **Role:** train and compare models, log to MLflow, register versions, apply the promotion gate.
- **Why necessary:** produces the artifacts that inference serves; also executes retraining.
- **Input:** Parquet dataset (DVC) or DB snapshot, `params.yaml`.
- **Output:** MLflow runs, registered model versions with aliases, `reports/*.json` metrics.
- **Talks to:** MLflow, (DB for snapshots).
- **Implementation:** `wlm.training.*`; same code for first training and retraining (only the data window differs).
- **Runs:** on demand — `docker compose --profile train run --rm trainer ...` or as a subprocess of the worker.

### 6.11 MLflow (tracking server + model registry)

- **Role:** lab notebook (runs, params, metrics, artifacts) **and** catalogue of model versions with aliases.
- **Why necessary:** answers "which model is live, how was it trained, how good was it?"
- **Input:** run logs and model artifacts from the trainer; alias changes.
- **Output:** model artifacts and metadata to the API; UI for humans.
- **Talks to:** trainer, API, worker, TimescaleDB (backend store).
- **Implementation:** `ghcr.io/mlflow/mlflow:<version>` + `psycopg2-binary` in a 3-line Dockerfile; `--backend-store-uri postgresql://…/mlflow --serve-artifacts --artifacts-destination /mlflow/artifacts`; `MLFLOW_SERVER_ALLOWED_HOSTS` set (≥ 3.5).
- **Runs:** Docker container, volume `mlflow-artifacts`.

### 6.12 DVC

- **Role:** version datasets and the reproducible offline pipeline; compare metrics across commits.
- **Why necessary:** Git cannot store large data; the brief requires dataset versioning; links data version ↔ code version ↔ results.
- **Input:** files under `data/`, `dvc.yaml`, `params.yaml`.
- **Output:** `.dvc` pointers and `dvc.lock` (committed to Git), cached data in `.dvc/cache`, a **local remote** (a folder outside the repo).
- **Talks to:** Git; no network service.
- **Implementation:** `dvc init`, `dvc remote add -d localremote ../dvc-remote`; stages `generate → build_dataset → train_forecast → train_anomaly`.
- **Runs:** local CLI on the laptop (not inside production containers; Section 19 explains why).

### 6.13 FastAPI inference service

- **Role:** the **delivery mechanism** for predictions: HTTP in, forecast/anomaly/autonomy out.
- **Why necessary:** decouples consumers (worker, Grafana, curl) from model internals; loads champion models; one place to version the API.
- **Input:** `POST /v1/forecast {device_id, as_of?}`, `POST /v1/anomaly {…}`, `POST /admin/reload`.
- **Output:** JSON with predictions, model versions, autonomy estimates, diagnosis.
- **Talks to:** TimescaleDB (read recent window), MLflow (load models by alias), called by worker.
- **Implementation:** FastAPI + pydantic v2 + uvicorn; models loaded at startup (cached to a volume as last-known-good); `wlm` package for features.
- **Runs:** Docker container.

### 6.14 Worker (scheduler, alert engine, monitor, retrain trigger)

- **Role:** the system's "operator": decides *when* to predict, *what* to alert, *whether* to retrain.
- **Why necessary:** something must run the periodic loops and own the alert state machine; keeping it in Python makes it testable.
- **Input:** DB state (latest data, forecasts, truth), API responses, configuration `config/alerts.yaml`.
- **Output:** rows in `forecasts`, `anomaly_scores`, `alerts`, `monitoring_metrics`, `retrain_events`; Telegram messages; retrain subprocess.
- **Talks to:** TimescaleDB, API, Telegram, MLflow (through the retrain subprocess).
- **Implementation:** APScheduler jobs: `watchdog` (60 s), `predict` (15 min), `monitor` (daily), all in **data time**.
- **Runs:** Docker container (same `jobs` image as the trainer).

### 6.15 Evidently

- **Role:** compute drift and data-quality statistics and HTML reports.
- **Why necessary:** distinguishes "inputs changed" from "model got worse" and documents it.
- **Input:** reference DataFrame (training window) and current DataFrame (last 7 days), optional predictions/truth.
- **Output:** HTML report, dict/JSON of metrics (drift share, per-column p-values), regression metrics.
- **Talks to:** library inside the worker.
- **Implementation:** `evidently==0.7.x`, new API (Section 20).
- **Runs:** inside worker/trainer processes.

### 6.16 Telegram bot

- **Role:** push notifications to the owner's phone.
- **Why necessary:** required; real-world alerting channel.
- **Input:** alert dicts from the alert engine.
- **Output:** `sendMessage` HTTPS calls; message ids stored in `alerts`.
- **Talks to:** `api.telegram.org` only (outbound).
- **Implementation:** bot created with BotFather; `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in `.env`; `httpx` client with retry/backoff; message templates (Section 22).
- **Runs:** nothing local; Telegram cloud.

### 6.17 Docker and Docker Compose

- **Role:** package each service reproducibly (Docker) and run them together with networks, volumes and env (Compose).
- **Why necessary:** the PDF's "local cloud"; reproducibility; isolates conflicting Python/Node stacks.
- **Input:** Dockerfiles, `docker-compose.yml`, `.env`.
- **Output:** running containers on `wlm-net`.
- **Talks to:** Docker Desktop engine.
- **Implementation:** Section 16.
- **Runs:** your laptop (Docker Desktop + WSL2).

### 6.18 GitHub Actions

- **Role:** automatic quality gate on every push/PR.
- **Why necessary:** required CI; protects `main`; builds images.
- **Input:** repository contents.
- **Output:** pass/fail, built images (optionally pushed to GHCR).
- **Talks to:** GitHub only.
- **Implementation:** `.github/workflows/ci.yml` (Section 23).
- **Runs:** GitHub-hosted runners (Linux).

### 6.19 The distinctions that matter

| Pair | First is… | Second is… | In this project |
|---|---|---|---|
| **Node-RED vs Mosquitto** | A *processor*: subscribes, transforms, routes, writes | A *broker*: accepts publishes, delivers to subscribers, stores nothing useful itself | Mosquitto moves bytes; Node-RED decides if they are valid and where they go. Node-RED is a *client* of Mosquitto |
| **TimescaleDB vs Grafana** | *Storage and query engine* | *Presentation layer* that holds no data | Grafana issues SQL; delete Grafana and no data is lost, delete the DB and Grafana is empty |
| **MLflow vs DVC** | Tracks **runs** (params, metrics, models) and the **model registry** | Versions **data and pipeline stages** | DVC says *which data*; MLflow says *which experiment and which model*. Linked by tagging each MLflow run with the dataset hash / git commit |
| **Docker vs Docker Compose** | Builds images and runs one container | Declares and runs **many** containers with networks/volumes together | `Dockerfile` per custom image; one `docker-compose.yml` for the whole stack |
| **Training vs inference** | Offline/batch, heavy, writes artifacts, needs labels | Online/light, reads artifacts, produces predictions | Trainer job (on demand) vs API (always on) — separate lifecycles and images |
| **Model registry vs model serving** | A **catalogue** of versions with metadata/aliases | A **running process** that answers requests | Registering a version changes nothing live. The gate sets the `champion` alias; the API then *loads* it |
| **Data drift vs performance degradation** | **Inputs changed** (distribution shift), detectable without labels | **Errors grew** (needs realised truth, delayed) | Drift is an early *warning*; the retrain *trigger* is performance. Drift without degradation → no retrain; degradation without detected drift (concept drift) → still retrain |
| **FastAPI vs the ML model** | A web framework exposing endpoints | A serialized function `features → prediction` | The model works without FastAPI (notebook, batch); FastAPI adds HTTP, validation, versioning, health |

---

## 7. Technologies and their responsibilities

### 7.1 Required stack

Pin **exact** versions at Phase 0 (after a successful install) in `pyproject.toml` / lock file and in Compose image tags. "Line" = major line to start from.

| Layer | Technology | Line / image | Responsibility here | RAM (idle→busy, approx.) |
|---|---|---|---|---|
| IoT simulation | Wokwi | web / VS Code extension | ESP32, HC-SR04, relay simulation | browser |
| Firmware libs | PubSubClient, ArduinoJson | current | MQTT client, JSON | — |
| Language | Python | 3.11 (broadest wheel support) | all backend code | — |
| Data | pandas, NumPy, pyarrow | 2.x / 1.26+-2.x / current | resampling, features, Parquet | — |
| ML | scikit-learn, LightGBM | 1.x / 4.x | Ridge, Isolation Forest; GBDT forecaster | training 0.5-1.5 GB |
| Broker | Eclipse Mosquitto | `eclipse-mosquitto:2` | local MQTT + bridge | 5-15 MB |
| Integration | Node-RED + `node-red-contrib-postgresql` | pinned tag / 0.16.x | ingestion, validation | 100-200 MB |
| TSDB | TimescaleDB (PostgreSQL 17) | `timescale/timescaledb:<2.x.y>-pg17` | storage, hypertables | 200-400 MB |
| Visualisation | Grafana | pinned tag | dashboards | 100-250 MB |
| Tracking | MLflow | ≥ 3.5, pinned | runs, registry, artifacts | 250-450 MB |
| Data versioning | DVC | 3.x | datasets, pipeline | CLI only |
| Monitoring | Evidently | 0.7.x (pinned) | drift + performance reports | in-process |
| Serving | FastAPI + uvicorn + pydantic v2 | current | inference API | 250-450 MB |
| Containers | Docker Desktop (WSL2), Compose v2 | current | packaging, orchestration | 1 GB+ overhead |
| CI | GitHub Actions | majors in Section 23 | tests, builds | cloud |
| Alerts | Telegram Bot API | n/a | notifications | cloud |
| VCS | Git + GitHub | n/a | code, CI | — |

### 7.2 Additional technologies (and whether they are optional)

| Addition | Why | Optional? |
|---|---|---|
| **pydantic v2** | One validated measurement model shared by API, generator, tests | No (already a FastAPI dependency) |
| **SQLAlchemy 2 + psycopg 3** | DB access from API/worker/trainer; `pandas.read_sql` | No |
| **paho-mqtt 2.x** | Replay publisher and integration tests | No |
| **APScheduler 3.x** | Periodic jobs in the worker (a `while True: sleep` loop also works) | Replaceable |
| **httpx** | Telegram and API calls; easy to mock in tests | No |
| **PyYAML** | Read `config/*.yaml`, `params.yaml` | No |
| **pytest, pytest-cov, ruff, pre-commit, gitleaks** | Tests, lint/format, secret scanning | Dev tooling — strongly recommended |
| **Optuna** | Hyperparameter search for LightGBM | **Optional** — a small manual grid is enough |
| **zoneinfo + `tzdata`** | Local-time features (Windows needs the `tzdata` package) | No |
| **MinIO / S3** | Artifact store | **No** — local volume suffices (PDF also flags MinIO as a licensing "point of attention") |
| **Kubernetes / Kafka / Airflow / Prefect / Prometheus** | — | **Not recommended**: no requirement they would satisfy |
| **LightGBM quantile models** | Prediction intervals → more conservative early warning | **Optional stretch** |

---

## 8. Complete data flow

### 8.1 Live path (device → dashboard)

| Step | Where | What happens | Output |
|---|---|---|---|
| 1 | ESP32 | Every `PUBLISH_INTERVAL_S`: 5 pings → median → `distance_cm`; convert to `level_pct`, `volume_l`; run pump control; build JSON | telemetry JSON |
| 2 | ESP32 → public broker | Publish QoS 0 on `wlm/<prefix>/tank-01/telemetry` | message on public broker |
| 3 | Public broker → local Mosquitto | Bridge (`in`) forwards matching topics | message on local broker |
| 4 | Mosquitto → Node-RED | Subscription delivers | `msg.payload` string |
| 5 | Node-RED | Parse JSON, validate schema/ranges/clock skew | valid / invalid |
| 6 | Node-RED → TimescaleDB | Valid: `INSERT … ON CONFLICT (device_id,time) DO NOTHING`; invalid: `INSERT INTO invalid_messages`; status topic: `UPSERT device_status` | rows |
| 7 | Grafana | Polls SQL every 5-10 s | panels update |
| 8 | Worker | 60 s watchdog reads latest row | threshold/offline alerts |

### 8.2 Historical path (generator → data → ML)

1. Generator writes `historical_90d.parquet` (schema v1 **only**) and `events_90d.parquet` (ground truth).
2. DVC tracks both files; Git tracks the `.dvc` pointers.
3. A loader `COPY`s the measurements into TimescaleDB (`source='synthetic'`) and events into `ground_truth_events` → history and annotations in Grafana.
4. The feature pipeline reads the Parquet (not the DB) → grid → features → training. The DB copy exists for visualisation and for API demos.

### 8.3 Inference path

Worker (every 15 min of data time) → `POST /v1/forecast {device_id, as_of}` and `/v1/anomaly` → API reads the last 8 days of raw rows (≥ 7 days for the weekly lag + margin) → `resample_to_grid` → features → champion models → forecasts (+6 h, +24 h), autonomy estimates, anomaly score/diagnosis → worker stores them in `forecasts`/`anomaly_scores` and evaluates alert rules.

### 8.4 Training path

Dataset (Parquet or DB snapshot) → grid → features/targets → chronological split → baselines + Ridge + LightGBM (+ Isolation Forest) → MLflow logging → register versions → alias `challenger` → promotion gate → alias `champion` → API reload.

### 8.5 Monitoring and retraining path — and the time-semantics trap

Truth for a forecast made at `t` with horizon `h` only exists at `t+h`. The monitor therefore joins `forecasts` with realised grid values **only for matured forecasts** (`target_time ≤ as_of`).

| Clock | Meaning | Used for |
|---|---|---|
| `ts` (event time) | When the device measured (UTC, from NTP) | the `time` column; all modelling |
| `ingested_at` | When the DB received it | latency measurement only |
| `as_of` (data time) | `max(time)` for the device | "now" for every job |
| Wall clock | Real time | scheduler wake-ups only |

> **The trap.** In an accelerated replay (1 day per 2 min), wall-clock "now" is meaningless: forecasts would never "mature" and the offline watchdog would fire constantly. Rule: **jobs compute "now" as `max(time)` in the DB** (option `CLOCK_MODE=data`, default) and run more often in demos. A device is "offline" when `wall_now − last_ingested_at > 5 min` **only if `source` is live** (`wokwi`).

### 8.6 Alert path

Rule evaluation (worker) → state machine (cooldown, re-arm) → `INSERT INTO alerts` → Telegram `sendMessage` → update `notified` / `telegram_message_id`. Failures stay `notified=false` and are retried with backoff.

### 8.7 Latency budget

| Hop | Typical | Budget |
|---|---|---|
| ESP32 → public broker → bridge → local | 0.2-1.5 s | 3 s |
| Node-RED validate + insert | < 50 ms | 200 ms |
| End-to-end publish → row | 0.5-2 s | **≤ 5 s** (NFR-06) |
| API forecast (feature build + 2 models + autonomy) | 100-400 ms | 1 s |
| Alert decision → Telegram delivery | 0.3-2 s | 10 s |

---

## 9. Database schema and data structure

### 9.1 Canonical measurement schema v1 (used by firmware, generator, MQTT, Node-RED, DB, ML)

| Field | Type | Unit | Meaning | Producer rule |
|---|---|---|---|---|
| `schema_version` | int | — | Always `1` | constant |
| `device_id` | string | — | `^[a-z0-9-]{3,32}$`, e.g. `tank-01` | config |
| `ts` | string ISO-8601 UTC | — | Measurement time, e.g. `2026-11-07T14:32:00Z` | NTP time; generator writes the same format |
| `seq` | int ≥ 0 | — | Monotonic counter, resets on reboot | detects loss and reboots |
| `distance_cm` | number or `null` | cm | Median distance sensor → water, range 2-400 | `null` iff `sensor_ok=false` |
| `level_pct` | number or `null` | % | `100·clamp(d_empty − d, 0, H)/H` | derived on device |
| `volume_l` | number or `null` | L | cylinder volume | derived on device |
| `pump_on` | bool | — | Relay state **after** this cycle's control step | |
| `sensor_ok` | bool | — | `false` for timeout / out-of-range / no echo | |
| `rssi` | int or `null` | dBm | WiFi signal | optional |
| `source` | enum | — | `wokwi` · `replay` · `synthetic` | provenance |

**Invariants** (checked by Node-RED, generator `validate`, and tests): `sensor_ok=false ⇔ distance_cm is null ⇔ level_pct is null ⇔ volume_l is null`; `|level_pct − f(distance_cm)| ≤ 0.5`; `0 ≤ level_pct ≤ 100`.

`distance_cm` is the **source of truth**; `level_pct` and `volume_l` are redundant by design (cheap consistency check).

JSON Schema (`schemas/measurement.v1.schema.json`, validated in CI against `schemas/examples/valid_*.json` and `invalid_*.json`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "WLM measurement v1",
  "type": "object",
  "required": ["schema_version","device_id","ts","seq","distance_cm","level_pct",
               "volume_l","pump_on","sensor_ok","source"],
  "properties": {
    "schema_version": {"const": 1},
    "device_id": {"type": "string", "pattern": "^[a-z0-9-]{3,32}$"},
    "ts": {"type": "string", "format": "date-time"},
    "seq": {"type": "integer", "minimum": 0},
    "distance_cm": {"type": ["number","null"], "minimum": 2, "maximum": 400},
    "level_pct": {"type": ["number","null"], "minimum": 0, "maximum": 100},
    "volume_l": {"type": ["number","null"], "minimum": 0, "maximum": 2000},
    "pump_on": {"type": "boolean"},
    "sensor_ok": {"type": "boolean"},
    "rssi": {"type": ["integer","null"], "minimum": -120, "maximum": 0},
    "source": {"enum": ["wokwi","replay","synthetic"]}
  },
  "additionalProperties": false
}
```

### 9.2 Ground-truth events (generator output only — never in the measurement stream)

| Column | Meaning |
|---|---|
| `event_id` | integer |
| `device_id` | string |
| `start_time`, `end_time` | UTC interval |
| `event_type` | `leak`, `sensor_frozen`, `sensor_blocked`, `sensor_dropout`, `sensor_spike`, `supply_outage`, `consumption_surge` |
| `magnitude` | e.g. L/h for leaks, cm for blocked distance |
| `params` | JSON with generator details |

Keeping labels out of the measurement file guarantees **training/inference see identical columns**; labels are joined by time interval only at evaluation.

### 9.3 TimescaleDB DDL (`infra/timescaledb/init/001_schema.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE devices (
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

CREATE TABLE measurements (
  time           TIMESTAMPTZ      NOT NULL,
  device_id      TEXT             NOT NULL,
  seq            BIGINT,
  distance_cm    DOUBLE PRECISION,
  level_pct      DOUBLE PRECISION,
  volume_l       DOUBLE PRECISION,
  pump_on        BOOLEAN          NOT NULL,
  sensor_ok      BOOLEAN          NOT NULL,
  rssi           SMALLINT,
  source         TEXT             NOT NULL CHECK (source IN ('wokwi','replay','synthetic')),
  schema_version SMALLINT         NOT NULL DEFAULT 1,
  ingested_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
  PRIMARY KEY (device_id, time)            -- must contain the partition column
);
SELECT create_hypertable('measurements', by_range('time', INTERVAL '7 days'));

CREATE TABLE device_status (
  device_id   TEXT PRIMARY KEY,
  online      BOOLEAN     NOT NULL,
  last_seen   TIMESTAMPTZ NOT NULL,
  last_seq    BIGINT,
  fw_version  TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invalid_messages (
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  topic       TEXT,
  payload     TEXT,
  reason      TEXT NOT NULL
);

CREATE TABLE ground_truth_events (
  event_id    BIGINT PRIMARY KEY,
  device_id   TEXT NOT NULL,
  start_time  TIMESTAMPTZ NOT NULL,
  end_time    TIMESTAMPTZ NOT NULL,
  event_type  TEXT NOT NULL,
  magnitude   DOUBLE PRECISION,
  params      JSONB
);

CREATE TABLE forecasts (
  made_at        TIMESTAMPTZ NOT NULL,      -- as_of (data time)
  device_id      TEXT        NOT NULL,
  horizon_h      SMALLINT    NOT NULL CHECK (horizon_h IN (6, 24)),
  target_time    TIMESTAMPTZ NOT NULL,      -- made_at + horizon_h
  pred_level_pct DOUBLE PRECISION NOT NULL,
  model_name     TEXT        NOT NULL,
  model_version  TEXT        NOT NULL,
  PRIMARY KEY (device_id, horizon_h, made_at)
);
SELECT create_hypertable('forecasts', by_range('made_at', INTERVAL '30 days'));

CREATE TABLE anomaly_scores (
  time          TIMESTAMPTZ NOT NULL,       -- grid timestamp (right edge)
  device_id     TEXT        NOT NULL,
  score         DOUBLE PRECISION NOT NULL,  -- higher = more anomalous
  is_anomaly    BOOLEAN     NOT NULL,
  diagnosis     TEXT        NOT NULL,       -- normal | leak_suspected | unexpected_consumption |
                                            -- sensor_frozen | sensor_blocked | sensor_invalid | sensor_spike
  features      JSONB,
  model_version TEXT,
  PRIMARY KEY (device_id, time)
);
SELECT create_hypertable('anomaly_scores', by_range('time', INTERVAL '30 days'));

CREATE TABLE alerts (
  id                  BIGSERIAL PRIMARY KEY,
  time                TIMESTAMPTZ NOT NULL,         -- data time of the trigger
  device_id           TEXT        NOT NULL,
  alert_type          TEXT        NOT NULL,
  severity            TEXT        NOT NULL CHECK (severity IN ('info','warning','critical')),
  message             TEXT        NOT NULL,
  payload             JSONB,
  notified            BOOLEAN     NOT NULL DEFAULT FALSE,
  telegram_message_id BIGINT,
  resolved_at         TIMESTAMPTZ
);
CREATE INDEX ON alerts (device_id, alert_type, time DESC);

CREATE TABLE monitoring_metrics (
  time          TIMESTAMPTZ NOT NULL,
  device_id     TEXT        NOT NULL,
  metric        TEXT        NOT NULL,   -- mae_6h_rolling | mae_24h_rolling | drift_share | n_drifted | completeness ...
  value         DOUBLE PRECISION NOT NULL,
  model_version TEXT,
  details       JSONB
);
SELECT create_hypertable('monitoring_metrics', by_range('time', INTERVAL '30 days'));

CREATE TABLE retrain_events (
  id                BIGSERIAL PRIMARY KEY,
  started_at        TIMESTAMPTZ NOT NULL,
  finished_at       TIMESTAMPTZ,
  trigger           TEXT        NOT NULL,   -- performance | manual | schedule
  reason            JSONB,
  champion_before   TEXT,
  challenger_version TEXT,
  mae_champion      DOUBLE PRECISION,
  mae_challenger    DOUBLE PRECISION,
  promoted          BOOLEAN,
  mlflow_run_id     TEXT
);

-- realised error of each matured forecast: truth = median of valid readings in (target-15min, target]
CREATE VIEW forecast_errors AS
SELECT f.device_id, f.horizon_h, f.made_at, f.target_time, f.model_version,
       f.pred_level_pct, a.level_actual,
       f.pred_level_pct - a.level_actual      AS error,
       abs(f.pred_level_pct - a.level_actual) AS abs_error
FROM forecasts f
JOIN LATERAL (
  SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY m.level_pct) AS level_actual
  FROM measurements m
  WHERE m.device_id = f.device_id AND m.sensor_ok
    AND m.time >  f.target_time - INTERVAL '15 minutes'
    AND m.time <= f.target_time
) a ON a.level_actual IS NOT NULL;
```

MLflow gets its own database (`CREATE DATABASE mlflow` + user) in `002_mlflow_db.sh`.

**Roles (least privilege)** — `003_roles.sql`:

| Role | Used by | Rights |
|---|---|---|
| `wlm_ingest` | Node-RED | `INSERT` on `measurements`, `invalid_messages`; `INSERT/UPDATE` on `device_status` |
| `wlm_ml` | API, worker, trainer | `SELECT` on `measurements`, `devices`, `ground_truth_events`; `INSERT/SELECT` on `forecasts`, `anomaly_scores`, `alerts`, `monitoring_metrics`, `retrain_events` (API: `SELECT` only) |
| `wlm_grafana` | Grafana | `SELECT` on everything, nothing else |
| `mlflow` | MLflow | owner of database `mlflow` only |

**Retention/compression.** 90 days × 1 440 rows ≈ 130 k rows — trivial. Compression (columnstore, TimescaleDB ≥ 2.18) is *optional*; enable it only as a talking point (`add_columnstore_policy('measurements', after => INTERVAL '14 days')`) and keep it off the critical path.

### 9.4 Files and data structures outside the database

| Path | Format | Content | Tracked by |
|---|---|---|---|
| `data/raw/historical_90d.parquet` | Parquet | schema v1 rows, 60 s | DVC |
| `data/raw/events_90d.parquet` | Parquet | ground-truth intervals | DVC |
| `data/raw/regime_change_21d.parquet` | Parquet | drift scenario | DVC |
| `data/processed/grid_15min.parquet` | Parquet | 15-min grid + split tag | DVC (stage output) |
| `data/snapshots/live_<date>_<sha8>.parquet` | Parquet | DB export used by retraining | volume; hash logged in MLflow |
| `reports/*.json` | JSON | metrics for DVC (`dvc metrics show`) | Git/DVC |
| `reports/evidently/*.html` | HTML | drift reports | volume |
| MLflow artifacts | MLflow format | models, plots, feature lists | `mlflow-artifacts` volume |

### 9.5 Example queries (Grafana, PostgreSQL datasource)

```sql
-- Current level (stat/gauge)
SELECT level_pct FROM measurements
WHERE device_id = '$device' AND sensor_ok ORDER BY time DESC LIMIT 1;

-- Level history
SELECT $__timeGroupAlias(time, $__interval), avg(level_pct) AS "level %"
FROM measurements
WHERE $__timeFilter(time) AND device_id = '$device' AND sensor_ok
GROUP BY 1 ORDER BY 1;

-- Forecast overlay: draw each prediction at the time it refers to
SELECT target_time AS time, pred_level_pct AS "forecast +6h"
FROM forecasts
WHERE $__timeFilter(target_time) AND device_id = '$device' AND horizon_h = 6
ORDER BY 1;

-- Alerts table panel
SELECT time, alert_type, severity, message FROM alerts
WHERE $__timeFilter(time) AND device_id = '$device' ORDER BY time DESC;

-- Rolling error of the live model
SELECT time, value AS "MAE 6h (pp)" FROM monitoring_metrics
WHERE $__timeFilter(time) AND metric = 'mae_6h_rolling' ORDER BY time;
```

---

## 10. MQTT topic structure and message examples

### 10.1 Topic tree

Prefix: `wlm/<groupid>` where `<groupid>` = course group + 6 random hex chars, e.g. `tdia2-ensa-7f3a9c`. Generate once, keep in `.env` (`MQTT_TOPIC_PREFIX`) and in the firmware config.

```text
wlm/<groupid>/<device_id>/telemetry     device → broker   QoS 0   retain no    telemetry JSON (schema v1)
wlm/<groupid>/<device_id>/status        device → broker   QoS 0   retain YES   {"online":true|false,...}  (LWT = offline)
wlm/<groupid>/<device_id>/event         device → broker   QoS 0   retain no    optional: pump_start, pump_stop, pump_dryrun_trip
(no cmd/ topics)                        remote commands are deliberately NOT supported (D15)
```

| Rule | Why |
|---|---|
| Subscribe locally with `wlm/+/+/telemetry` (not `#`) | Least privilege, easy ACL |
| `telemetry` is never retained | A public broker would replay stale levels to strangers |
| `status` is retained | Harmless, lets a new subscriber know the device state |
| Bridge direction `in` only | Public → local; nothing local goes out |
| Unique `<groupid>` | Avoids collisions with other groups; **not** a secret (Section 24) |

### 10.2 Message examples

Telemetry (valid, 87.4 cm → 77.6 cm of water → 51.7 % → 609.5 L):

```json
{"schema_version":1,"device_id":"tank-01","ts":"2026-11-07T14:32:00Z","seq":8412,
 "distance_cm":87.4,"level_pct":51.7,"volume_l":609.5,"pump_on":false,"sensor_ok":true,
 "rssi":-61,"source":"wokwi"}
```

Sensor fault (no echo):

```json
{"schema_version":1,"device_id":"tank-01","ts":"2026-11-07T14:33:00Z","seq":8413,
 "distance_cm":null,"level_pct":null,"volume_l":null,"pump_on":false,"sensor_ok":false,
 "rssi":-63,"source":"wokwi"}
```

Status (retained) and its Last-Will:

```json
{"device_id":"tank-01","online":true,"fw":"1.0.0","ts":"2026-11-07T14:30:02Z"}
{"device_id":"tank-01","online":false}
```

Invalid (quarantined by Node-RED, `reason = "level_pct out of range"`):

```json
{"schema_version":1,"device_id":"tank-01","ts":"2026-11-07T14:34:00Z","seq":8414,
 "distance_cm":60.0,"level_pct":140.0,"volume_l":900.0,"pump_on":false,"sensor_ok":true,"source":"wokwi"}
```

Payload size ≈ 230 bytes → PubSubClient's 256-byte default buffer is too small → `setBufferSize(512)`.

### 10.3 Local broker configuration

`infra/mosquitto/mosquitto.conf`:

```conf
persistence true
persistence_location /mosquitto/data/
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/aclfile
include_dir /mosquitto/config/conf.d
log_dest stdout
log_type error
log_type warning
log_type notice
connection_messages true
```

`infra/mosquitto/aclfile` (topic levels: `wlm / <groupid> / <device> / <kind>`):

```conf
user nodered
topic read wlm/+/+/telemetry
topic read wlm/+/+/status
user replay
topic write wlm/+/+/telemetry
topic write wlm/+/+/status
user healthcheck
topic read $SYS/#
```

Create the password file **interactively** (no password in shell history):

```powershell
docker run --rm -it -v "${PWD}/infra/mosquitto:/work" eclipse-mosquitto:2 mosquitto_passwd -c /work/passwd nodered
docker run --rm -it -v "${PWD}/infra/mosquitto:/work" eclipse-mosquitto:2 mosquitto_passwd /work/passwd replay
docker run --rm -it -v "${PWD}/infra/mosquitto:/work" eclipse-mosquitto:2 mosquitto_passwd /work/passwd healthcheck
```

(`-c` creates/overwrites the file — use it **only** for the first user.) `passwd` is git-ignored; `passwd.example` documents the format.

### 10.4 Bridge configuration

`infra/mosquitto/conf.d/bridge.conf` (rendered from a template so the prefix comes from `.env`, never hard-coded in Git):

```conf
connection public-bridge
address broker.hivemq.com:1883
bridge_protocol_version mqttv311
try_private false              # public brokers are not Mosquitto-specific
cleansession true              # QoS 0 inbound only: no queued session needed
start_type automatic
restart_timeout 5 30           # reconnect backoff in seconds
keepalive_interval 60
remote_clientid wlm-bridge-<6-random-hex>   # MUST be unique on a shared public broker
topic wlm/<groupid>/# in 0     # remote → local, same topic name on both sides
```

How to read the last line: `topic <pattern> <direction> <qos> [local-prefix remote-prefix]` — with `in`, the local broker *subscribes* on the public broker and republishes locally. Nothing published locally is sent out.

Optional hardening: use `address test.mosquitto.org:8883` (or `broker.emqx.io:8883`) with `bridge_cafile` set to the container's CA bundle to encrypt the **bridge leg**. The ESP32→public-broker leg stays plain unless you add TLS to the firmware (heavier; unnecessary for non-sensitive data). `broker.hivemq.com` public offers plain TCP only.

Fallback: switch `address` to `test.mosquitto.org:1883` and have the ESP32 publish there (change the firmware broker constant). Keep both hosts in `.env`.

### 10.5 How to test the communication (in this order)

Use `docker compose exec` (works with any project name) and a **file** for payloads: Windows PowerShell 5.1 strips inner double quotes when passing JSON to native commands (use PowerShell 7.3+ or `-f file`). Mount `schemas/examples/` read-only into the Mosquitto container at `/examples`.

| # | Test | Command (PowerShell) | Expected |
|---|---|---|---|
| T1 | Local broker + auth | Terminal A: `docker compose exec mosquitto mosquitto_sub -u nodered -P <pw> -t "wlm/+/+/telemetry" -v` · Terminal B: `docker compose exec mosquitto mosquitto_pub -u replay -P <pw> -t "wlm/<groupid>/tank-01/telemetry" -f /examples/valid_telemetry.json` | A prints the topic and JSON |
| T1b | Auth is enforced | Same publish **without** `-u/-P` | `Connection Refused: not authorised` |
| T2 | Bridge connected | `docker compose logs mosquitto --tail 50` | lines mentioning `public-bridge`, `CONNACK`, `SUBSCRIBE` and no repeating connection errors |
| T3 | Public → local | Terminal A as in T1. Terminal B: `docker run --rm -v "${PWD}/schemas/examples:/examples:ro" eclipse-mosquitto:2 mosquitto_pub -h broker.hivemq.com -t "wlm/<groupid>/tank-01/telemetry" -f /examples/valid_telemetry.json` | The same message appears in A within ~1-2 s |
| T4 | Prefix isolation | Publish T3 to `wlm/someone-else/tank-01/telemetry` | **Nothing** arrives locally |
| T5 | Wokwi → local | Run the simulation | A prints a new JSON each interval; `seq` increments by 1 |
| T6 | Validation path | Publish `invalid_telemetry.json` (T3 style) | Arrives locally; Node-RED writes `invalid_messages`, not `measurements` |
| T7 | Idempotency | Publish the same valid file twice | One row in `measurements` |
| T8 | Latency | Compare `ts` vs `ingested_at` for 20 rows | median < 2 s |

If T3 fails but T1 passes: bridge problem (Section 28). If T3 passes but T5 fails: firmware/WiFi/prefix problem.

---

## 11. Synthetic dataset generation strategy

### 11.1 Principles

1. **Simulate the physics, then the sensor.** First simulate the *true* tank volume minute by minute, then derive the *measured* distance by adding sensor noise/faults, then compute `level_pct`/`volume_l` with the **same conversion** as the firmware. Labels describe what was *injected*, not what was measured.
2. **Same schema as live data** (Section 9.1) — the generator emits exactly the MQTT message fields; labels live in a separate file.
3. **Closed loop.** The generator implements the *same pump controller as the firmware* (hysteresis 35 %/90 %, dry-run protection), so `pump_on` in the history is consistent with the level dynamics.
4. **Randomness with structure.** Daily/weekly patterns plus stochastic variation, so forecasting has something to learn but is not trivial.
5. **Deterministic by seed** and described entirely by `params.yaml: generator` → DVC reproducibility.
6. **Honest caveat.** Models trained on simulated data learn the simulator. Report results as simulation results, and test robustness through the regime-change scenario.

### 11.2 Simulation loop (1-minute steps, 90 days from `2026-07-01T00:00Z`)

For each minute `m`:

```text
demand_L      = consumption(m)                 # Section 11.3, zero while an outage drains only through demand
leak_L        = injected leak flow (if any)     # L/min
supply_ok     = not inside a supply_outage event
pump_cmd      = controller(level_true, pump_state, timers)      # same logic as firmware
inflow_L      = 40 L/min if (pump_cmd and supply_ok) else 0     # ±10 % flow variation
V_true        = clip(V_true + inflow_L − demand_L − leak_L, 0, capacity)
d_true        = d_empty − H · (V_true / capacity)               # volume → distance
d_meas        = sensor_model(d_true, active_sensor_events)      # Section 11.5
row           = firmware_conversion(d_meas) + pump_cmd + seq + rssi + source="synthetic"
```

The controller reads the *measured* level (as the firmware does), so sensor faults can mislead the pump — a realistic coupling (a blocked sensor reading "full" prevents refills, which is a good demo!).

### 11.3 Consumption model

- Daily mean volume ≈ **450 L/day**, multiplied by a **day factor** `~ LogNormal(0, 0.15)` and a weekend factor (1.15 Sat/Sun; parameterised).
- Intra-day shape (share of daily volume): night 00-05 ≈ 4 %, **morning peak 06-09 ≈ 30 %**, daytime 10-16 ≈ 22 %, **evening peak 17-21 ≈ 38 %**, late 22-23 ≈ 6 % (smooth mixture of two Gaussians + base level).
- Use **intermittent draw events** rather than a smooth curve: draws arrive as a Poisson process with an hour-dependent rate λ(h); each draw has volume `~ LogNormal` (flush ≈ 6-9 L, tap ≈ 3-10 L, shower ≈ 40-60 L) and lasts 0.5-10 min. This produces the zero-flow minutes at night that make **leaks detectable** and noise that makes forecasting non-trivial.
- Local-clock based: compute the hour from `Africa/Casablanca` so the generator and the models agree on "evening".

### 11.4 Event catalogue and allocation across splits

Events must not overlap each other (≥ 12 h gap). Dates are randomised from the seed but **constrained** so each split contains at least the counts below.

| Event (`event_type`) | Total | Train / Val / Test | Duration | Effect | Labelled as anomaly? |
|---|---|---|---|---|---|
| `leak` — slow | 4 | 2 / 1 / 1 | 24-72 h | constant extra outflow 4-10 L/h, never zero | yes |
| `leak` — burst | 2 | 1 / 0 / 1 | 2-6 h | 60-150 L/h | yes |
| `sensor_frozen` | 4 | 2 / 1 / 1 | 2-12 h | reading stuck at last value, **exactly** constant | yes |
| `sensor_blocked` | 3 | 1 / 1 / 1 | 3-18 h | near-constant small distance (≈ 3-6 cm ±0.05) → "tank full" | yes |
| `sensor_dropout` | 4 | 2 / 1 / 1 | 15 min-3 h | `sensor_ok=false`, values `null`; plus 5 pure network gaps (no rows) not labelled | yes (fault) |
| `sensor_spike` | 20 points | 12 / 4 / 4 | 1 sample | isolated reading ±30-200 cm | yes (point) |
| `supply_outage` | 7 | 3 / 2 / 2 (≥ 1 crosses critical in **each** split) | 14-40 h | pump runs but **no inflow**; dry-run protection cycles | hazard event (not a sensor anomaly) → target of early warning |
| `consumption_surge` | 4 | 2 / 1 / 1 | 1-4 h | +80-200 L/h (hose, pool filling) | yes |
| *refills* | ≈ 55-65 | emergent | ≈ 16 min | pump ON, +3.4 pp/min | no (normal; logged as info, not a label) |

### 11.5 Sensor model

`d_meas = round(d_true + N(0, 0.3 cm), 1)` (HC-SR04 resolution ≈ 0.3 cm); frozen = repeat last `d_meas`; blocked = constant ≈ 4 cm + `N(0, 0.05)`; dropout = `null`, `sensor_ok=false`; spike = `d_true ± U(30, 200)` clipped to 2-400; message loss = random rows missing (~0.3 %) plus the 5 gap episodes. `rssi ~ N(-62, 4)`.

### 11.6 Outputs

| File | Rows | Columns |
|---|---|---|
| `historical_90d.parquet` | ≈ 129 600 (minus gaps) | exactly the schema v1 fields; `source="synthetic"` |
| `events_90d.parquet` | ≈ 40 | `event_id, device_id, start_time, end_time, event_type, magnitude, params` |
| `regime_change_21d.parquet` | ≈ 30 240 | schema v1; continues the timeline after day 90 with new consumption pattern |

### 11.7 Validation checks (`python -m wlm.data.validate`)

1. Schema + invariants (Section 9.1) on every row; timestamps unique, strictly increasing per device.
2. **Mass balance:** `ΔV_true = inflow − demand − leak` within 1 L per day (checked on the generator's internal trace in tests).
3. **Controller consistency:** every `pump_on` rising edge happens at measured level ≤ 35 % (± noise margin) or after a cooldown retry; every falling edge at ≥ 90 % or by the dry-run rule.
4. Plausible statistics: mean daily consumption 400-500 L; 55-65 refills; no negative volume; level never > 100 %.
5. **Event coverage per split** matches Section 11.4; no overlapping events; every event window contains the expected signature (e.g., frozen windows have `std = 0`).
6. Plots saved to `reports/data_validation/` (daily profile, level trace with events shaded, refill timing histogram).

### 11.8 Drift scenario (`regime_change_21d`)

From day 91: consumption ×**1.5** (guests / larger household), morning peak shifted **+1.5 h** later, evening peak amplitude ×1.3, plus some night usage. Everything else (sensor, pump, thresholds) unchanged.

> **Calibration knob.** The point of this scenario is to produce a *clearly detectable* degradation of the 6 h forecast (target: rolling MAE ≥ 1.5× the validation MAE). In Phase 9 you tune `consumption_multiplier` and the shift until this holds, and you document it as an experimental design choice. A mild change may not trigger retraining — that is correct behaviour, not a bug.

### 11.9 Replay publisher

`python -m wlm.data.replay --file data/raw/historical_90d.parquet --from 2026-08-10 --days 3 --speed 720 --device tank-01 --broker mosquitto` publishes rows with their original `ts` (so the DB sees realistic event times) at `1/speed` of real time (720× → one day in two minutes). It sets `source="replay"` in the payload. Use `--speed 1` for a "real-time" test.

---

## 12. Machine learning methodology

### 12.1 Two tasks, two paradigms

| | **A. Forecasting** | **B. Anomaly detection** |
|---|---|---|
| Question | "What will the level be in 6 h / 24 h? When does it become critical?" | "Is what I observe *right now* abnormal?" |
| Learning type | **Supervised regression** (targets = future levels) | **Unsupervised** (no labels needed to train) |
| Input | History up to `t` (levels, flows, pump, calendar) | Short windows of recent behaviour |
| Output | Numbers: `ŷ(t+6h)`, `ŷ(t+24h)` | Score + decision (+ diagnosis by rules) |
| Strength | Planning; early warning of *expected* shortage | Catches *unexpected* events never seen before |
| Blind spot | Cannot foresee a leak or sensor death; learned from normal behaviour | Does not know the future; flags "unusual", not "dangerous" |
| Typical failure | Drift in consumption → growing error | Threshold too tight → alert fatigue |

**Why both are appropriate here.** Forecasting answers "will we run dry?" under expected behaviour; anomaly detection answers "is the data or the household behaving abnormally?". A leak makes the tank run dry *faster than forecast* — the forecaster alone only notices once the level has already departed; the detector notices the abnormal outflow *rate* hours earlier. A frozen sensor makes forecasts meaningless — the detector must tell the forecaster not to trust the input.

**How they interlock:** (1) sensor-fault diagnoses (rule layer) mask invalid grid values before forecasting; (2) predicted-low alerts are suppressed or flagged "low confidence" when the current window is diagnosed as a sensor fault; (3) persistent forecast residuals can be fed back as an optional anomaly feature (stretch).

### 12.2 Data → model pipeline

```text
raw 60 s rows (Parquet or DB window)
  → resample_to_grid(15 min, label=right edge, value=median of sensor_ok readings)   [wlm.features.grid]
  → forecasting features / targets                                                   [wlm.features.forecasting]
  → anomaly features (from raw statistics per grid window)                           [wlm.features.anomaly]
  → chronological split → train / validate / test
```

### 12.3 Splits (chronological, no shuffling — ever)

| Period | Days | Dates | Used for |
|---|---|---|---|
| Warm-up | 1-7 | 07-01 → 07-07 | needed only to compute the 7-day lag; not used as targets |
| **Train** | 8-60 | 07-08 → 08-29 | fitting models, fitting the consumption profile |
| **Validation** | 61-75 | 08-30 → 09-13 | hyper-parameters, early stopping, anomaly threshold |
| **Test** | 76-90 | 09-14 → 09-28 | final report, touched once per experiment family |
| Regime change | 91-111 | 09-29 → 10-19 | Phase 9 drift/retraining |

### 12.4 Leakage checklist (enforced by tests)

- Features at grid time `t` use only readings with `time ≤ t`; targets are `level(t+h)` obtained by a **negative shift** applied *only* to the target column.
- Train/validation boundary respects a **gap ≥ horizon** (a training row at `t` has a target at `t+h`; without a gap it overlaps validation inputs).
- The consumption profile (`expected_outflow_*`) and any scaler/imputer are fit on **train only** and stored with the model.
- Calendar features are known in advance (legitimate); weather is not used.
- No label (`events_*`) is used as a feature. Labels are used only to *evaluate* detectors (and never to clean data in production-equivalent paths).
- Rolling windows are **backward-looking** (`closed='right'`, no `center=True`).

### 12.5 Model families and why

| Model | Role |
|---|---|
| Persistence, seasonal-naive, rate-extrapolation | Baselines (the bar to beat) |
| Ridge regression (lags + time + pump features) | Simple ML reference; shows what LightGBM adds beyond linear structure |
| **LightGBM** (L2 and L1 objectives) | Chosen forecaster: handles non-linearities (the pump's threshold rule!), missing values, interactions, small data, fast on CPU |
| **Isolation Forest** | Unsupervised detector, no labels, fast, no scaling needed, works on small tabular windows |
| Sensor rules | Deterministic guard-rails and diagnosis |

### 12.6 What gets logged for every training run (MLflow)

Parameters (all of `params.yaml` sections used, feature list hash, horizon), metrics (MAE, RMSE, bias, skill, `MAE_low`, per split), artifacts (model, feature list, profile JSON, scaler, residual plots, feature importance), tags (`git_commit`, `data_sha256`, `dvc_rev`, `trigger`, `pipeline_version`).

---

## 13. Forecasting strategy and evaluation

### 13.1 Formulation

- **Strategy:** *direct* — two independent models, `f6` and `f24`, each predicting `level(t+h)` from features at `t`.
- **Grid:** 15 minutes. Horizon 6 h = **24 steps**, 24 h = **96 steps**.
- **Prediction time `t`:** the right edge of the latest complete 15-min bucket (`as_of` rounded down).
- **Target:** `y_h(t) = level_grid(t + h)` (median of valid readings in `(t+h−15min, t+h]`).

### 13.2 Features (≈ 50)

| Group | Features | Notes |
|---|---|---|
| Level state | `level`, `lag_1,2,3,4,8,12,24,48,96,192,672` (steps), `delta_1h/3h/6h/24h` | `lag_96` = same time yesterday, `lag_672` = same time last week |
| Level rolling | mean/std/min/max over 1 h, 6 h, 24 h (backward) | |
| Flow | `outflow_lph_1h/6h/24h/7d` (mean outflow **on pump-off steps**), `max_hourly_outflow_24h`, `net_rate_pph_1h/3h/6h` | refill steps excluded from consumption estimates |
| Pump | `pump_frac_now`, `pump_frac_1h/6h`, `steps_since_pump_on`, `rise_during_pump_6h`, `pump_noflow_flag` | lets the model recognise an outage (pump on, level not rising) |
| Calendar (local time) | `hour_sin/cos`, `dow_sin/cos`, `is_weekend` | `Africa/Casablanca` via `zoneinfo` |
| Expected demand (**known ahead**) | `expected_outflow_next6h_L`, `expected_outflow_next24h_L` | from the **train-only** hour × weekend profile; scaled by a recent-activity ratio |
| Quality | `valid_frac_1h` | completeness of the last hour |

Missing values: forward-fill ≤ 1 h; remaining NaN stay NaN (LightGBM handles them; Ridge uses a train-fitted median imputer).

### 13.3 Baselines (and the bar the model must clear)

| ID | Baseline | Formula |
|---|---|---|
| B1 | **Persistence** | `ŷ(t+h) = level(t)` |
| B2 | **Seasonal naive** (period 24 h) | `ŷ(t+h) = level(t + h − 24h·⌈h/24h⌉)` → 6 h: level 18 h ago; 24 h: equals B1 |
| B3 | Rate extrapolation (reported, not part of pass/fail) | `ŷ = clip(level(t) − h·r, 0, 100)` with `r` = recent mean net outflow on pump-off steps |

**Pass criterion (mandatory):** `MAE(LightGBM) < min(MAE(B1), MAE(B2))` at both horizons on the **test** period. **Stretch target:** skill ≥ 20 % where `skill = 1 − MAE_model / MAE_best_naive`. B3 is reported so the claim "better than a physical estimate" is honest.

### 13.4 Training procedure

1. Build grid + features for train/val/test; drop rows with NaN target or target inside diagnosed sensor-fault windows (rule-based, same rule as production).
2. Fit baselines (no fitting for B1/B2; `r` for B3).
3. Ridge: `SimpleImputer → StandardScaler → Ridge` with `TimeSeriesSplit(n_splits=4, gap=h_steps)` for `alpha`.
4. LightGBM: start from `n_estimators=800, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8`, **early stopping (50 rounds) on the validation period**; compare `objective="regression"` (L2) vs `"regression_l1"` (optimises MAE directly). Small random search (20-30 trials) logged as nested MLflow runs. Optuna is optional.
5. Select by **validation MAE**; then refit on **train + validation** with the chosen settings (fixed number of iterations from early stopping) and evaluate **once** on test.
6. Log, register versions `wlm-forecast-6h`, `wlm-forecast-24h` (alias `challenger`), apply the promotion gate (Section 15).

### 13.5 Metrics

| Metric | Why |
|---|---|
| **MAE** (pp and litres = pp × 11.78) | Primary, same units as the target, robust |
| RMSE | Penalises big misses — the dangerous ones near critical |
| Bias (mean error) | Systematic over/under-prediction |
| Skill vs best naive | One number for "is ML worth it" |
| `MAE_low` (rows with `level(t) < 40 %`) | The zone where errors cost something |
| **Early-warning metrics** (13.8) | The business goal: lead time, hit rate, false alarms |

Always report **per horizon** and **per split**, and a regime breakdown: *normal*, *refill window*, *supply outage*.

### 13.6 Inference

`as_of` (default `max(time)`) → last 8 days of raw rows → `resample_to_grid` → feature row at `t` → `f6`, `f24` → clip to `[0, 100]` → store in `forecasts` with `model_version`. Refuse (and flag low confidence) if the last hour has `valid_frac_1h < 0.5` or a sensor fault is diagnosed.

### 13.7 Remaining autonomy — three estimates, three meanings

Let `V_now`, `V_crit = capacity × critical_pct / 100`.

| Estimate | How | Answers | Used for |
|---|---|---|---|
| **A1 current-rate** | `(V_now − V_crit) / r`, `r` = median outflow over the last 6 h on pump-off steps (floored at 2 L/h); `0` if already critical | "At the current pace, no refill?" — crude | Display only |
| **A2 profile-based (worst case, no refill)** | Integrate the expected hourly consumption profile × a recent-activity ratio forward from `as_of` until `V_crit`; cap 72 h | "If refilling fails *now*, how long do we have?" — handles peaks | `AUTONOMY_LOW` alert (gated) |
| **A3 forecast-based** | Piecewise-linear path through `(0, level_now)`, `(6 h, f6)`, `(24 h, f24)`; first crossing of `critical_pct` → ETA, else ">24 h" | "Given expected behaviour (including expected refills), will we reach critical?" | `LEVEL_LOW_PREDICTED` alert |

A1/A2 assume **no refill**; A3 includes the refills the model has learned to expect. They are *complementary*: A3 can say "fine, pump will refill" while A2 says "12 h if the pump fails" — which is exactly the right message when the pump is actually failing.

### 13.8 Early-warning evaluation (success criterion 5)

- **Critical-crossing event** (ground truth): first minute where the *true* simulated level ≤ `critical_pct` after ≥ 6 h above it.
- **Lead time** = `t_cross − t_first_alert`, where `t_first_alert` is the earliest `LEVEL_LOW_PREDICTED`, `AUTONOMY_LOW` or `PUMP_NO_FLOW`-escalation alert in `[t_cross − 48 h, t_cross]`.
- **Success:** lead time ≥ **6 h** for **every** crossing in the test period (and ≥ 90 % over val + test).
- **False alarms:** alerts of these types with no crossing within 48 h, counted per week.

Worked sanity check (so you can reason about feasibility): pump ON at 35 % → usable water down to 15 % ≈ 235 L. At the generator's average ≈ 19 L/h that is ≈ 12 h; in the evening peak (≈ 34 L/h) ≈ 7 h. A `PUMP_NO_FLOW` flag appears within ≈ 10 min (first dry-run trip), so even a worst-case start leaves several hours of warning — *provided detection is fast*. That is why early warning is **rule + model**, not model alone.

### 13.9 Pitfalls to remember

- A 24 h forecast cannot see a refill failure that begins after `t`; it only sees symptoms (pump on, no rise). Test with outages starting *just after* a prediction.
- Metrics on simulated data measure the simulator. State that in the report.
- Do not tune on the test period; do not report the best of many test runs.

---

## 14. Anomaly detection methodology

### 14.1 Situations and how to tell them apart

| Situation | Level / pump / sensor signals | Distinguishing signal | Detected by |
|---|---|---|---|
| **Normal consumption** | Level decreases, pump off, drop follows the hour profile, **flow returns to ≈ 0 at night** | `outflow ≈ expected`, `min_outflow_6h ≈ 0` | (baseline) |
| **Refill** | Level rises ≈ +3.4 pp/min, `pump_on=true` | positive Δ with pump on | not an anomaly |
| **Slow leak** | Extra constant outflow 4-10 L/h, pump off | **`min_outflow_6h` stays > 0**, night outflow high | Isolation Forest + `leak_suspected` rule |
| **Burst leak** | 60-150 L/h sustained | `excess_outflow` ≫ 0, persists > 2 h | Isolation Forest |
| **Consumption surge** | Similar to a burst, daytime, shorter | `excess_outflow` high but flow reaches 0 afterwards, no night signature | Isolation Forest → `unexpected_consumption` |
| **Frozen sensor** | `distance_cm` **exactly** constant while demand is expected | `dist_std_1h = 0`, `dist_nunique_1h = 1` (real sensors have noise) | **rule** (+ IF) |
| **Blocked sensor** | Near-constant small distance (≈ 4 cm) → level reads ≈ 98 %; pump never starts; level does not fall in peaks | very low std + level inconsistent with outflow expectation | rule + IF |
| **Invalid / missing** | `sensor_ok=false`, `null`, or no messages | `invalid_frac_1h > 0`; gap length; `last_seen` age | rule |
| **Spike** | One reading far from neighbours | `max_abs_step_1h` large, bucket median unaffected | rule (info severity) |
| **Pump no-flow** | `pump_on` but no rise over the dry-run window | pump on ≥ 10 min and `Δlevel < +1 pp` | rule (`PUMP_NO_FLOW`) |

> **Caveat to remember.** A frozen sensor at night looks identical to "nobody is using water" in level terms. Only the **absence of measurement noise** reveals it. This is why the firmware's `SIMULATE_NOISE` option matters in Wokwi (Section 4.4 #5).

### 14.2 Anomaly feature vector (per 15-min grid step, windows ending at `t`)

`d_level_15m`, `d_level_1h`, `outflow_lph_1h`, `expected_outflow_lph` (hour × weekend profile from train), `excess_outflow = outflow − expected`, `min_outflow_6h`, `min_outflow_24h`, `night_outflow_lph` (00-05 local, rolling), `dist_std_1h`, `dist_nunique_1h`, `invalid_frac_1h`, `max_abs_step_1h`, `pump_frac_1h`, `level`, `hour_sin`, `hour_cos`.

### 14.3 Model and training policy

- `IsolationForest(n_estimators=200, max_samples=256, contamination="auto", random_state=42)`; no feature scaling needed (trees).
- **Trained on the unlabeled train split as-is** (production has no labels; it contains ≈ 2-3 % anomalous steps). An MLflow experiment compares against training on a "clean" subset to show sensitivity.
- **Threshold:** the decision threshold on `score` is chosen on the **validation** period so that *normal* stretches (labels used only here, for evaluation) produce **≤ 1 false alarm per week**; then check event recall on validation. Never tune on test.
- **Persistence rule:** an anomaly is raised when the score exceeds the threshold in ≥ 2 of the last 3 grid steps. Frozen / invalid rules fire on their own thresholds (they are deterministic).

### 14.4 Diagnosis layer (decision list, first match wins)

```text
1. sensor_ok false for ≥ 15 min or valid_frac_1h < 0.5      → sensor_invalid
2. dist_std_1h < 0.02 and dist_nunique_1h == 1 (≥ 60 min)    → sensor_frozen
3. dist_std_1h < 0.10 and level ≥ 90 and pump never starts   → sensor_blocked   (stuck high with tiny variance)
4. max_abs_step_1h > 25 cm and neighbours normal             → sensor_spike     (info)
5. IF anomalous and (min_outflow_6h > leak_floor or night_outflow > night_thr)
                                                              → leak_suspected
6. IF anomalous                                               → unexpected_consumption
7. otherwise                                                  → normal
```

Thresholds live in `config/alerts.yaml`, derived from the **noisy** simulated data, and are unit-tested with golden windows.

### 14.5 Evaluation protocol

Use **event-level** metrics (points are misleading because events last hours):

| Metric | Definition | Target (validation → report on test) |
|---|---|---|
| Event recall per type | fraction of injected events with ≥ 1 detection inside `[start, end + 30 min]` | leaks ≥ 90 %, frozen/blocked ≥ 95 % |
| Detection delay | `first_detection − start` | sensor faults ≤ 1 h, bursts ≤ 1 h, slow leaks ≤ 6 h |
| False alarms | alerts outside any labelled event, per week | ≤ 1 / week |
| Diagnosis accuracy | fraction of detected events with the correct diagnosis | ≥ 80 % |
| Point-level precision/recall, PR-AUC | context only | reported |

Report **IF alone** vs **IF + rules** so the value of the hybrid design (D14) is measured, not asserted.

### 14.6 Limitations (say them in the report)

A slow leak hidden inside heavy daytime use is only caught through the night/minimum-flow features; thresholds fitted on synthetic noise need re-tuning on real sensors; IF scores are not calibrated probabilities; the detector sees one device (no fleet comparison).

---

## 15. MLOps architecture and lifecycle

### 15.1 Lifecycle stages

| Stage | Who performs it | Input | Output | Recorded in |
|---|---|---|---|---|
| 1. Data arrival | Node-RED / loader | MQTT messages / Parquet | rows in `measurements` | TimescaleDB, DVC (files) |
| 2. Dataset versioning | DVC | files in `data/` | `.dvc`, `dvc.lock`, cache | Git + local DVC remote |
| 3. Training | `trainer` job | grid + features | candidate models | MLflow run |
| 4. Experiment tracking | trainer → MLflow | params, metrics, artifacts, tags | run history | MLflow backend DB + artifacts |
| 5. Evaluation | trainer | validation/test/holdout | metrics, pass/fail | MLflow metrics, `reports/*.json` |
| 6. Registration | trainer → registry | best model artifact | new **version** `N` | MLflow Model Registry |
| 7. Promotion | gate (in trainer) | challenger vs champion metrics | alias `champion` moved (or not) | Registry aliases, `retrain_events` |
| 8. Deployment | API reload | alias `champion` | API serves version `N` | API `/v1/models`, `forecasts.model_version` |
| 9. Inference | API ← worker | `device_id`, `as_of` | predictions | `forecasts`, `anomaly_scores` |
| 10. Monitoring | monitor job | forecasts + realised truth + features | MAE, drift, quality | `monitoring_metrics`, Evidently HTML |
| 11. Retraining decision | policy in worker | monitoring metrics | trigger or not | `retrain_events`, Telegram |

### 15.2 Training pipeline vs inference pipeline

| | **Training pipeline** | **Inference pipeline** |
|---|---|---|
| Frequency | Rare (first time, then on trigger) | Every 15 min of data time |
| Data | Months of history, labelled for evaluation | Last 8 days, unlabeled |
| Compute | Heavy (≈ 1 GB, minutes) | Light (≈ 100 ms) |
| Container | `trainer` (on demand) | `api` (always on) |
| Output | Model artifacts + metrics | Predictions |
| Shared code | `wlm.features`, `wlm.models` | same |
| Failure impact | No new model; champion keeps serving | Missing forecast; rules still alert |

### 15.3 How everything interacts (narrative)

1. **New data enters** continuously through MQTT → Node-RED → TimescaleDB; nothing triggers training by itself.
2. **First training** is run manually (roadmap Phase 5/6) on the DVC-tracked synthetic dataset; it logs runs, registers `wlm-forecast-6h/24h` and `wlm-anomaly-iforest`, and — because no champion exists yet — promotes the first model that passes the absolute checks.
3. **The API** loads the models behind alias `champion` at startup. It is stateless: it holds model objects in memory and reads recent data from the DB for each request.
4. **The worker** calls the API every 15 min of data time; predictions are stored with the model version that produced them.
5. **Truth arrives** `h` hours later. The monitor job joins matured forecasts with realised values and computes rolling MAE; Evidently compares recent feature distributions with the training reference.
6. **Retraining is triggered** only by the policy in Section 21 (performance threshold + guards). The same training code runs on a recent snapshot and produces a **challenger**.
7. **The gate** compares challenger and champion on the same recent holdout. Only a better model gets the `champion` alias; the API is told to reload.
8. **Rollback**: alias `previous` points to the last champion; moving `champion` back + reload restores it in seconds.

### 15.4 Registration ≠ deployment

| Event | Changes what is served? | Why |
|---|---|---|
| `register_model` → version 8 exists | **No** | Nothing references version 8 yet |
| alias `challenger` → 8 | **No** | Only tells humans/gate "candidate under evaluation" |
| Gate passes, alias `champion` → 8 | **Not yet** | The API still holds version 7 in memory |
| API `POST /admin/reload` (or restart) | **Yes** | The API loads `models:/…@champion` |

This separation means a bad registration can never break production, and every deployment is an explicit, logged act (`retrain_events`, `forecasts.model_version`).

### 15.5 Conventions

| Item | Convention |
|---|---|
| Experiments | `wlm-forecasting`, `wlm-anomaly`, `wlm-retraining` |
| Registered models | `wlm-forecast-6h`, `wlm-forecast-24h`, `wlm-anomaly-iforest` |
| Aliases | `challenger`, `champion`, `previous` |
| Run tags | `git_commit`, `data_sha256`, `dvc_rev` (if available), `trigger` (`manual`/`performance`/`schedule`), `feature_set_hash`, `horizon_h` |
| Model version tags | `validated=true/false`, `gate_reason`, `train_window` |
| Model artifact bundle | model + `feature_list.json` + `profile.json` (train-only consumption profile) + imputer/scaler + `thresholds.json` (anomaly) |

### 15.6 Promotion gate

```text
forecast challenger (horizon h) is promoted only if ALL hold on the recent holdout:
  A. MAE_challenger < MAE_persistence                      (absolute sanity)
  B. MAE_challenger ≤ 0.95 × MAE_champion                  (relative improvement; skipped if no champion)
  C. |bias_challenger| ≤ 2 pp
  D. feature_list.json compatible with the serving code    (hash check)
  E. smoke test: load from registry, predict 10 rows without error
anomaly challenger: score-threshold file present AND (labels available → recall/false-alarm targets)
                    OR (no labels → alert rate within 0.5-2× of the reference rate)
```

### 15.7 Reproducibility

Every run is traceable to: Git commit (code) + `data_sha256` (data) + `params.yaml` (hyper-parameters) + library versions (lock file, logged as artifact) + seed. `dvc repro` rebuilds the offline pipeline; `dvc metrics diff` compares commits.

---

## 16. Docker and Docker Compose architecture

### 16.1 Containers

| Service | Image | Host port | Volumes | Needs | Profile | RAM cap |
|---|---|---|---|---|---|---|
| `timescaledb` | `timescale/timescaledb:<2.x.y>-pg17` | 127.0.0.1:5432 | `pgdata`, init scripts (ro) | — | default | 512 MB |
| `mosquitto` | `eclipse-mosquitto:2` | 127.0.0.1:1883 | config (ro), `mosquitto-data` | — | default | 64 MB |
| `nodered` | `nodered/node-red:<pinned>` + custom `Dockerfile` (adds palette node) | 127.0.0.1:1880 | `nodered-data` | `mosquitto`, `timescaledb` | default | 384 MB |
| `grafana` | `grafana/grafana:<pinned>` | 127.0.0.1:3000 | `grafana-data`, provisioning (ro) | `timescaledb` | default | 384 MB |
| `mlflow` | custom (`ghcr.io/mlflow/mlflow:<ver>` + `psycopg2-binary`) | 127.0.0.1:5000 | `mlflow-artifacts` | `timescaledb` | default | 512 MB |
| `api` | custom `docker/api.Dockerfile` | 127.0.0.1:8000 | `model-cache`, config (ro) | `timescaledb`, `mlflow` | default | 512 MB |
| `worker` | custom `docker/jobs.Dockerfile` | — | `snapshots`, `reports`, config (ro) | `api`, `timescaledb` | default | 768 MB |
| `trainer` | same `jobs` image | — | `snapshots`, `reports`, `./data` (ro) | `mlflow` | `train` | 1.5 GB |
| `replay` | same `jobs` image | — | `./data` (ro) | `mosquitto` | `tools` | 256 MB |

One network `wlm-net` (default bridge). **Services address each other by service name** (`timescaledb:5432`, `mlflow:5000`, `api:8000`, `mosquitto:1883`).

### 16.2 Environment variables (`.env.example`, committed; `.env`, git-ignored)

```dotenv
# --- MQTT ---
MQTT_TOPIC_PREFIX=wlm/tdia2-CHANGEME-000000
MQTT_PUBLIC_HOST=broker.hivemq.com
MQTT_PUBLIC_PORT=1883
MQTT_BRIDGE_CLIENT_ID=wlm-bridge-CHANGEME
MQTT_USER_NODERED=nodered
MQTT_PASS_NODERED=CHANGEME
MQTT_USER_REPLAY=replay
MQTT_PASS_REPLAY=CHANGEME
# --- Database ---
POSTGRES_USER=postgres
POSTGRES_PASSWORD=CHANGEME
POSTGRES_DB=wlm
DB_PASS_INGEST=CHANGEME
DB_PASS_ML=CHANGEME
DB_PASS_GRAFANA=CHANGEME
MLFLOW_DB_PASSWORD=CHANGEME
# --- MLflow / API ---
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_SERVER_ALLOWED_HOSTS=mlflow:5000,localhost:*,127.0.0.1:*
API_ADMIN_TOKEN=CHANGEME
# --- Node-RED / Grafana ---
NODERED_CREDENTIAL_SECRET=CHANGEME
GRAFANA_ADMIN_PASSWORD=CHANGEME
# --- Telegram ---
TELEGRAM_BOT_TOKEN=CHANGEME
TELEGRAM_CHAT_ID=CHANGEME
# --- Behaviour ---
CLOCK_MODE=data
DEVICE_ID=tank-01
```

### 16.3 Image sketches

`docker/api.Dockerfile` (the `jobs` image is the same with `.[jobs]` and no `uvicorn` CMD):

```dockerfile
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*              # LightGBM needs OpenMP
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[api]"
RUN useradd -m app && mkdir -p /models && chown app /models
USER app
EXPOSE 8000
CMD ["uvicorn", "wlm.serving.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`infra/mlflow/Dockerfile`:

```dockerfile
FROM ghcr.io/mlflow/mlflow:<pinned-version>
RUN pip install --no-cache-dir psycopg2-binary
```

### 16.4 Compose skeleton (reference — the real file grows phase by phase)

```yaml
name: wlm

services:
  timescaledb:
    image: timescale/timescaledb:<2.x.y>-pg17        # pin; there is no "latest" tag
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      DB_PASS_INGEST: ${DB_PASS_INGEST}               # consumed by the init shell script
      DB_PASS_ML: ${DB_PASS_ML}
      DB_PASS_GRAFANA: ${DB_PASS_GRAFANA}
      MLFLOW_DB_PASSWORD: ${MLFLOW_DB_PASSWORD}
    command: ["postgres", "-c", "shared_buffers=128MB", "-c", "max_connections=50"]
    volumes:
      - pgdata:/var/lib/postgresql/data               # named volume, NOT a Windows bind mount
      - ./infra/timescaledb/init:/docker-entrypoint-initdb.d:ro
    ports: ["127.0.0.1:5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      retries: 10
    mem_limit: 512m

  mosquitto:
    image: eclipse-mosquitto:2
    restart: unless-stopped
    volumes:
      - ./infra/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - ./infra/mosquitto/passwd:/mosquitto/config/passwd:ro
      - ./infra/mosquitto/aclfile:/mosquitto/config/aclfile:ro
      - ./infra/mosquitto/conf.d:/mosquitto/config/conf.d:ro
      - ./schemas/examples:/examples:ro
      - mosquitto-data:/mosquitto/data
    ports: ["127.0.0.1:1883:1883"]
    mem_limit: 64m

  nodered:
    build: ./infra/nodered
    restart: unless-stopped
    environment:
      NODE_RED_CREDENTIAL_SECRET: ${NODERED_CREDENTIAL_SECRET}
      MQTT_TOPIC_PREFIX: ${MQTT_TOPIC_PREFIX}
    volumes: ["nodered-data:/data"]
    ports: ["127.0.0.1:1880:1880"]
    depends_on:
      timescaledb: {condition: service_healthy}
      mosquitto:   {condition: service_started}
    mem_limit: 384m

  grafana:
    image: grafana/grafana:<pinned>
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      DB_PASS_GRAFANA: ${DB_PASS_GRAFANA}
    volumes:
      - grafana-data:/var/lib/grafana
      - ./infra/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./infra/grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports: ["127.0.0.1:3000:3000"]
    depends_on: {timescaledb: {condition: service_healthy}}
    mem_limit: 384m

  mlflow:
    build: ./infra/mlflow
    restart: unless-stopped
    environment:
      MLFLOW_SERVER_ALLOWED_HOSTS: ${MLFLOW_SERVER_ALLOWED_HOSTS}
    command: >
      mlflow server --host 0.0.0.0 --port 5000
      --backend-store-uri postgresql+psycopg2://mlflow:${MLFLOW_DB_PASSWORD}@timescaledb:5432/mlflow
      --serve-artifacts --artifacts-destination /mlflow/artifacts
    volumes: ["mlflow-artifacts:/mlflow/artifacts"]
    ports: ["127.0.0.1:5000:5000"]
    depends_on: {timescaledb: {condition: service_healthy}}
    mem_limit: 512m

  api:
    build: {context: ., dockerfile: docker/api.Dockerfile}
    restart: unless-stopped
    env_file: .env
    volumes: ["model-cache:/models", "./config:/app/config:ro"]
    ports: ["127.0.0.1:8000:8000"]
    depends_on: {timescaledb: {condition: service_healthy}, mlflow: {condition: service_started}}
    mem_limit: 512m

  worker:
    build: {context: ., dockerfile: docker/jobs.Dockerfile}
    command: ["python", "-m", "wlm.worker.scheduler"]
    restart: unless-stopped
    env_file: .env
    volumes: ["snapshots:/data/snapshots", "reports:/reports", "./config:/app/config:ro"]
    depends_on: [api]
    mem_limit: 768m

  trainer:
    profiles: ["train"]
    build: {context: ., dockerfile: docker/jobs.Dockerfile}
    env_file: .env
    volumes: ["./data:/app/data:ro", "snapshots:/data/snapshots", "reports:/reports"]
    mem_limit: 1536m

  replay:
    profiles: ["tools"]
    build: {context: ., dockerfile: docker/jobs.Dockerfile}
    env_file: .env
    volumes: ["./data:/app/data:ro"]
    depends_on: [mosquitto]

volumes: {pgdata: {}, mosquitto-data: {}, nodered-data: {}, grafana-data: {},
          mlflow-artifacts: {}, model-cache: {}, snapshots: {}, reports: {}}
```

### 16.5 Commands (each explained before you run it)

| Command | What it does |
|---|---|
| `docker compose config` | Validates the file and prints the resolved configuration (variables substituted) — run it first after every edit |
| `docker compose up -d --build` | Builds custom images, creates network/volumes, starts default-profile services in the background |
| `docker compose ps` | State and health of each container |
| `docker compose logs -f <service>` | Follow one service's logs (`Ctrl+C` stops following, not the service) |
| `docker compose exec <service> <cmd>` | Run a command inside a running container |
| `docker compose --profile train run --rm trainer python -m wlm.training.train_forecast` | Run the on-demand job once; `--rm` deletes the container afterwards |
| `docker compose --profile tools run --rm replay python -m wlm.data.replay …` | Start the replay publisher |
| `docker compose stop` / `down` | `stop` pauses; `down` removes containers and network but **keeps volumes** |
| `docker compose down -v` | ⚠ Also deletes volumes = **deletes your database and models** |
| `docker stats --no-stream` | RAM/CPU per container — compare with Appendix D |

### 16.6 Windows + 8 GB RAM

`%UserProfile%\.wslconfig` (apply with `wsl --shutdown` then restart Docker Desktop):

```ini
[wsl2]
memory=4GB      # 6-8GB if you have 16 GB RAM
processors=4
swap=4GB
```

Keep the repo on the WSL2 or NTFS drive as you prefer, but **Postgres data stays on a named volume**. Force LF endings for shell/YAML with `.gitattributes`.

### 16.7 Health and persistence checks

| Check | How | Expected |
|---|---|---|
| DB ready | `docker compose exec timescaledb pg_isready` | `accepting connections` |
| Data persists | `docker compose restart timescaledb`, then `SELECT count(*) FROM measurements` | same count |
| Down/up persists | `docker compose down` → `up -d` | dashboards, runs, models still there |
| Startup order | `docker compose up -d` on a clean machine | `nodered`, `mlflow`, `grafana` wait for DB health |

---

## 17. FastAPI inference architecture

### 17.1 Role and boundaries

FastAPI is the **delivery mechanism**; the models are *artifacts* it loads. The API owns: input validation, loading champion models, building features from DB data (using shared `wlm.features`), computing autonomy, versioned HTTP contracts, health endpoints. It does **not** train, register, schedule, alert, or write predictions (the worker stores them — keeps the API's DB role read-only).

### 17.2 Endpoints

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness (process is up) |
| `GET /ready` | none | Readiness: DB reachable **and** models loaded |
| `GET /v1/models` | none | Served model names, versions, load time, `feature_set_hash` |
| `POST /v1/forecast` | none (internal network) | Body `{"device_id": "tank-01", "as_of": null}` → forecasts + autonomy + data quality |
| `POST /v1/anomaly` | none | Body same → anomaly score, decision, diagnosis |
| `POST /admin/reload` | header `X-Admin-Token` | Re-resolve alias `champion` and swap models atomically |

Response of `/v1/forecast`:

```json
{
  "device_id": "tank-01",
  "as_of": "2026-09-20T03:15:00Z",
  "level_now_pct": 41.2,
  "forecasts": [
    {"horizon_h": 6,  "target_time": "2026-09-20T09:15:00Z", "pred_level_pct": 24.8,
     "model": "wlm-forecast-6h",  "version": "7"},
    {"horizon_h": 24, "target_time": "2026-09-21T03:15:00Z", "pred_level_pct": 13.9,
     "model": "wlm-forecast-24h", "version": "5"}
  ],
  "autonomy": {"rate_h": 10.4, "profile_h": 8.9, "forecast_eta_h": 19.2, "critical_pct": 15.0},
  "data_quality": {"valid_frac_1h": 1.0, "sensor_fault": null, "low_confidence": false}
}
```

Response of `/v1/anomaly`:

```json
{
  "device_id": "tank-01",
  "as_of": "2026-09-20T03:15:00Z",
  "anomaly_score": 0.71,
  "threshold": 0.62,
  "is_anomaly": true,
  "diagnosis": "leak_suspected",
  "features": {"min_outflow_6h": 6.3, "excess_outflow": 9.8, "dist_std_1h": 0.29},
  "model": "wlm-anomaly-iforest",
  "version": "3"
}
```

(`anomaly_score = −score_samples`, so larger means more anomalous.)

Errors: `404` unknown device, `409` not enough history (< 8 days) → body explains, `422` validation error, `503` models not loaded.

### 17.3 Lifecycle

1. **Startup**: resolve `models:/wlm-forecast-6h@champion` (and 24h, anomaly) through MLflow; on success copy artifacts to `/models` (last-known-good cache).
2. If MLflow is down at startup: load from `/models` and mark `/ready` as degraded but ok.
3. **Reload**: load new models into a fresh container object, then swap the reference under a lock (no request sees a half-loaded state).
4. **Per request**: read last 8 days from the DB (read-only role) → grid → features → predict → respond. Cost ≈ 100-400 ms.

### 17.4 Code layout (`src/wlm/serving/`)

`app.py` (FastAPI instance, lifespan loading), `routes.py`, `schemas.py` (pydantic request/response), `registry.py` (alias resolution + cache), `service.py` (feature build + predict + autonomy), `deps.py` (DB engine, settings).

### 17.5 Tests

`TestClient` with tiny fixture models (trained in `conftest.py` on 3 days of generated data); tests for validation errors, `409` on short history, reload swap, version fields, response schema. API contract file exported to `docs/openapi.json` in CI (diff = intentional change).

---

## 18. MLflow experiment tracking and model registry

### 18.1 Server

```text
mlflow server --host 0.0.0.0 --port 5000
  --backend-store-uri postgresql+psycopg2://mlflow:<pw>@timescaledb:5432/mlflow
  --serve-artifacts --artifacts-destination /mlflow/artifacts
```

- **Backend store:** PostgreSQL (separate `mlflow` database). **Artifacts:** proxied through the server onto the `mlflow-artifacts` volume, so clients (trainer, API) never need filesystem access to it. After the first run, check that an experiment's artifact location starts with `mlflow-artifacts:/`.
- **MLflow ≥ 3.5 host validation:** the default allows only localhost and private IPs; the container hostname `mlflow` is neither. Set `MLFLOW_SERVER_ALLOWED_HOSTS=mlflow:5000,localhost:*,127.0.0.1:*` (symptom otherwise: *Invalid Host header — possible DNS rebinding attack detected*).
- No authentication by default → published only on `127.0.0.1`.

### 18.2 What a training session logs

| Level | Logged |
|---|---|
| **Parent run** `forecast-<date>-<trigger>` | tags (`git_commit`, `data_sha256`, `trigger`, `feature_set_hash`), `params.yaml` as artifact, library lock file, comparison table CSV, plots |
| **Child run per model** (`persistence`, `seasonal_naive`, `rate_extrap`, `ridge`, `lgbm_l2`, `lgbm_l1`, trials) × horizon | params (hyper-parameters, horizon, window), metrics `val_mae`, `val_rmse`, `val_bias`, `val_mae_low`, `test_*` (final only), `skill_vs_naive`; artifacts: model (signature + input example), `feature_list.json`, `profile.json`, residual plot, feature importance |
| **Anomaly run** | params (`n_estimators`, `max_samples`, threshold policy), metrics per split (event recall by type, delay, false alarms/week), `thresholds.json`, score histogram |

Use **manual logging** (not autolog) so every logged thing is intentional and explainable.

### 18.3 Registry

| Registered model | Flavor | Contents |
|---|---|---|
| `wlm-forecast-6h`, `wlm-forecast-24h` | `mlflow.lightgbm` (or a thin `pyfunc` that bundles imputer/profile) | LightGBM booster + artifacts from 15.5 |
| `wlm-anomaly-iforest` | `mlflow.sklearn` / `pyfunc` | IsolationForest + `thresholds.json` |

Aliases: `challenger` (set by every training session) → `champion` (set only by the gate) → `previous` (set to the old champion when promoting).

```python
# register + mark as candidate (trainer)
mv = mlflow.register_model(f"runs:/{run_id}/model", "wlm-forecast-6h")
client.set_registered_model_alias("wlm-forecast-6h", "challenger", mv.version)

# promotion (gate passed)
old = client.get_model_version_by_alias(
    "wlm-forecast-6h", "champion"
)  # may not exist the first time
client.set_registered_model_alias("wlm-forecast-6h", "previous", old.version)
client.set_registered_model_alias("wlm-forecast-6h", "champion", mv.version)

# serving (API)
model = mlflow.pyfunc.load_model("models:/wlm-forecast-6h@champion")
```

### 18.4 How to read it in the demo

Experiments tab → compare runs by `val_mae` → open the winning run → registered model page → versions with aliases → show `forecasts.model_version` in Grafana matching the `champion` version.

---

## 19. DVC dataset versioning

### 19.1 What DVC tracks here

| Tracked by DVC | Why |
|---|---|
| `data/raw/*.parquet` (generator output) | Dataset versions; regenerate or restore exactly |
| `data/processed/grid_15min.parquet` | Stage output; cache-skipped if inputs unchanged |
| Pipeline stages in `dvc.yaml` | Reproduce data → features → training metrics with one command |
| `params.yaml` values | `dvc params diff` between commits |
| `reports/*.json` metrics | `dvc metrics diff` between commits |

**Not tracked by DVC:** models (MLflow registry), live DB data, Evidently reports, Docker volumes.

### 19.2 Pipeline sketch (`dvc.yaml`)

```yaml
stages:
  generate:
    cmd: python -m wlm.data.generate --params params.yaml --out data/raw
    deps: [src/wlm/data, config/tank.yaml]
    params: [generator]
    outs: [data/raw/historical_90d.parquet, data/raw/events_90d.parquet,
           data/raw/regime_change_21d.parquet]
  build_dataset:
    cmd: python -m wlm.features.build_dataset --params params.yaml
    deps: [data/raw/historical_90d.parquet, src/wlm/features]
    params: [features, split]
    outs: [data/processed/grid_15min.parquet]
  train_forecast:
    cmd: python -m wlm.training.train_forecast --params params.yaml
    deps: [data/processed/grid_15min.parquet, src/wlm/models, src/wlm/training]
    params: [forecast]
    metrics: [reports/forecast_metrics.json: {cache: false}]
  train_anomaly:
    cmd: python -m wlm.training.train_anomaly --params params.yaml
    deps: [data/processed/grid_15min.parquet, data/raw/events_90d.parquet]
    params: [anomaly]
    metrics: [reports/anomaly_metrics.json: {cache: false}]
```

(`train_*` stages log to MLflow too; the DVC `metrics` file is the small, Git-diffable summary.)

### 19.3 Setup and daily commands

```powershell
dvc init
dvc remote add -d localremote ..\dvc-remote     # a folder OUTSIDE the repo = free "remote storage"
dvc repro                                        # run/skip stages as needed
dvc push                                         # copy cache to the remote
git add dvc.yaml dvc.lock params.yaml data\raw\.gitignore ; git commit -m "dataset v1"
dvc metrics show ; dvc params diff               # inspect
```

### 19.4 DVC vs MLflow (and how they link)

| | DVC | MLflow |
|---|---|---|
| Unit | file/dataset, pipeline stage | run, model version |
| Answers | "Which exact data and code produced this?" | "How did this experiment/model perform, which one is live?" |
| Storage | cache + remote folder; pointers in Git | DB + artifact store |
| Link | each MLflow run is tagged with `data_sha256` (and `dvc_rev` when run from the repo) | |

### 19.5 Honest limitation

Automated retraining runs **inside a container**, where Git/DVC are not driving the pipeline. It exports a DB snapshot, computes its `sha256`, logs that hash in MLflow and keeps the file in the `snapshots` volume. Provenance is therefore **hash-based**, not DVC-based, for retrained models. If you want a DVC audit trail, copy a snapshot to `data/snapshots/` and `dvc add` it manually — optional and worth one sentence in the report.

### 19.6 Windows notes

Set `git config core.autocrlf false` and use `.gitattributes`; keep the DVC remote on a different path than the cache; antivirus can slow `dvc add` on large folders (not an issue at this data size).

---

## 20. Evidently monitoring and drift detection

### 20.1 What is monitored

| # | What | Needs truth? | Tool | Frequency (data time) | Stored as |
|---|---|---|---|---|---|
| 1 | **Forecast performance** — rolling MAE of matured forecasts per horizon and model version | **Yes** (delayed `h` hours) | SQL view `forecast_errors` + pandas | hourly (cheap) and in the daily check | `monitoring_metrics.mae_6h_rolling`, `mae_24h_rolling` |
| 2 | **Input data drift** — feature distributions: last 7 days vs training reference | No | **Evidently** `DataDriftPreset` | daily | `drift_share`, `n_drifted`, HTML report |
| 3 | **Prediction drift** — distribution of predicted levels vs reference | No | Evidently | daily | `pred_drift` metric |
| 4 | **Data quality** — completeness, invalid fraction, range violations, `seq` gaps | No | pandas (+ Evidently quality metrics, optional) | hourly | `completeness`, `invalid_frac` |

The MAE in (1) is **authoritative for the retraining trigger**; Evidently results (2-3) are diagnostics and early warnings.

### 20.2 Reference and current data

- **Reference:** the feature rows of the **training period of the current champion** (stored as `reference_features.parquet` inside the model bundle — so monitoring always compares against what the *serving* model learned).
- **Current:** feature rows of the last 7 days up to `as_of`.
- **Columns tested** (≈ 10, not all 50 lag columns — redundant lags inflate the drift share): `level`, `outflow_lph_6h`, `outflow_lph_24h`, `max_hourly_outflow_24h`, `net_rate_pph_6h`, `pump_frac_6h`, `expected_outflow_next24h_L`, `valid_frac_1h`, plus the daily consumption total and the hour-of-day of the morning peak (derived).

### 20.3 API usage (Evidently ≥ 0.7 — verified against the current docs)

```python
from evidently import Report
from evidently.presets import DataDriftPreset

report = Report([DataDriftPreset()])  # PSI or other methods are configurable
snapshot = report.run(current_df, reference_df)  # NOTE the order: current first, then reference
snapshot.save_html("/reports/evidently/drift_2026-10-05.html")
result = snapshot.dict()  # also .json()
```

Do **not** copy tutorials using `from evidently.report import Report` / `column_mapping` / `run(reference_data=…, current_data=…)` — that is the pre-0.7 API. Pin `evidently==0.7.x`. Inspect `snapshot.dict()` once, then write `wlm.monitoring.drift.parse_result()` (drift share = drifted columns / tested columns) with a unit test on a frozen sample dict, so a library upgrade fails a test instead of silently breaking monitoring.

For regression quality, compute MAE yourself (authoritative) and optionally add Evidently's regression metrics to the report — check the 0.7 documentation for the `DataDefinition` regression mapping when you reach Phase 9.

### 20.4 Data drift vs performance degradation — four cases

| Drift detected? | MAE degraded? | Meaning | Action |
|---|---|---|---|
| No | No | Healthy | none |
| **Yes** | **No** | Inputs moved but the model still copes (or drift is harmless) | log + info; **no retrain** |
| **Yes** | **Yes** | Classic regime change (our demo) | retrain |
| No | **Yes** | **Concept drift** — relationship changed without visible input shift (e.g., pump behaviour, new usage rule) or truth quality issue | retrain **and** investigate; also check sensor faults first |

### 20.5 Thresholds (`params.yaml: monitoring`)

| Parameter | Default | Meaning |
|---|---|---|
| `drift_share_warn` | 0.5 | Evidently dataset-level drift share ≥ 50 % of tested columns → `DRIFT_DETECTED` info alert |
| `mae_window_h` | 48 | Window of matured forecasts for rolling MAE |
| `mae_min_points` | 96 | Do not evaluate with fewer matured points |
| `reference_mae` | from champion's `val_mae` tag | Baseline expectation |

### 20.6 Pitfalls

Truth for the 24 h model matures a day later than for the 6 h model — **use the 6 h model's error as the primary trigger**; compute `mae_24h_rolling` for display. Sensor faults corrupt truth: exclude windows diagnosed as sensor faults from MAE. In accelerated demos, all jobs run in data time (Section 8.5).

---

## 21. Automated retraining strategy

### 21.1 Trigger policy (`params.yaml: retrain`)

```yaml
retrain:
  check_every: 1d              # data time
  metric: mae_6h_rolling
  threshold_ratio: 1.5         # trigger when rolling MAE > 1.5 × reference MAE ...
  threshold_abs_pp: 1.0        # ... and at least 1 pp above it
  consecutive_checks: 2        # on 2 consecutive daily checks
  holdout_days: 2              # most recent days reserved for the gate
  train_window_days: 60        # snapshot length (before the holdout)
  cooldown_days: 3             # after a PROMOTION
  max_attempts: 7              # daily attempts while degraded
```

**Trigger:** `rolling_mae > max(threshold_ratio × ref_mae, ref_mae + threshold_abs_pp)` on `consecutive_checks` consecutive daily checks. The first of them is the **onset**.

### 21.2 Procedure

1. **Detect** → insert `DRIFT_PERFORMANCE_DEGRADED` alert (Telegram) and a `retrain_events` row (`trigger='performance'`, reason JSON with MAE values and the Evidently drift share).
2. **Snapshot:** export the last `train_window_days + holdout_days` of raw rows (exclude diagnosed sensor-fault windows) to `/data/snapshots/live_<asof>_<sha8>.parquet`; compute `sha256`.
3. **Train challenger** with the *same code and `params.yaml`* as the first training (only the data differs), `trigger=performance` tag; optional light random search.
4. **Evaluate on the holdout** (last `holdout_days`): champion and challenger on the *same* rows, plus persistence.
5. **Gate** (Section 15.6). Pass → `previous ← champion`, `champion ← challenger`, `POST /admin/reload`, `MODEL_RETRAINED` alert with before/after MAE. Fail → keep champion, `RETRAIN_REJECTED` alert.
6. **Retry:** while degradation persists, repeat daily up to `max_attempts` (each day adds post-change data). After a promotion, `cooldown_days` blocks new attempts.

> **Why "retry daily"?** Right after a regime change, the snapshot contains almost no post-change data, so the challenger cannot beat the champion on a post-change holdout and the gate correctly rejects it. As days accumulate, the challenger improves and eventually passes. This is the honest dynamic of adaptation; trying to "retrain immediately and promote" would deploy models that learned nothing new. Optional speed-up: weight recent days more heavily (time-decay sample weights).

### 21.3 Guard rails

| Guard | Reason |
|---|---|
| Minimum matured points (`mae_min_points`) | Avoid triggering on noise |
| Two consecutive checks | One bad day (a leak, an outage) is not a regime change |
| Exclude diagnosed sensor-fault windows from snapshot and from MAE | Do not "learn" a broken sensor |
| Promotion gate, never auto-promote | Prevents regressions |
| Cooldown after promotion; `max_attempts` | Prevents retrain loops and resource drain on an 8 GB laptop |
| Retrain runs in a **subprocess** with a hard timeout (30 min) | A hung training must not freeze alerting |
| Alerts keep working during retrain | Rules do not depend on the model |

### 21.4 Where it runs

`worker` → `monitor` job → `subprocess.run([python, -m, wlm.training.retrain, …])` inside the same container (the `jobs` image contains training code). No Docker socket, no scheduler service. The DB and MLflow are reached over the Compose network.

### 21.5 Demo recipe (accelerated)

1. Healthy replay of the last test days (`--speed 720`) → MAE ≈ reference (Grafana panel flat).
2. Switch the replay to `regime_change_21d.parquet` → rolling MAE rises over the next simulated days; Evidently drift share climbs.
3. Trigger fires after two daily checks → Telegram alert → retrain attempts → first may be rejected → a later attempt promotes → API reload → Grafana shows new `model_version` and MAE falling back.

---

## 22. Telegram notification architecture

### 22.1 Setup

1. In Telegram, talk to **@BotFather** → `/newbot` → copy the token.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` once and read `message.chat.id`. (Do **not** paste that URL, with the token, in screenshots, issues or logs.)
3. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` only. A `python -m wlm.alerts.telegram --test` command sends a harmless test message.

### 22.2 Architecture

`rules (pure functions) → alert state machine (cooldown, re-arm, severity) → alerts table → Telegram sender (httpx) → update notified/message_id`. The alert **logic** has no Telegram knowledge (injectable sender) → unit-testable with a fake.

### 22.3 Alert catalogue (`config/alerts.yaml`)

| Type | Trigger | Severity | Cooldown | Re-arm when |
|---|---|---|---|---|
| `LEVEL_WARNING` | latest valid level ≤ 25 % | warning | 3 h | level ≥ 35 % |
| `LEVEL_CRITICAL` | latest valid level ≤ 15 % | critical | 3 h | level ≥ 25 % |
| `LEVEL_LOW_PREDICTED` | forecast-based ETA to critical (A3) ≤ **X h** (default 24; ≤ 6 → critical), and `low_confidence = false` | warning / critical | 6 h | forecasts above critical on 2 consecutive runs |
| `AUTONOMY_LOW` | A2 autonomy ≤ 12 h **and** (`PUMP_NO_FLOW` active **or** level ≤ 25 %) | critical | 3 h | pump effective again and level ≥ 40 % |
| `PUMP_NO_FLOW` | pump ON ≥ 10 min with Δlevel < +1 pp, twice in a row | warning | 2 h | a refill with ≥ +5 pp rise |
| `ANOMALY_LEAK` | diagnosis `leak_suspected` (≥ 2 of last 3 steps) | critical | 6 h | 6 h of `normal` |
| `ANOMALY_CONSUMPTION` | diagnosis `unexpected_consumption` | warning | 3 h | 3 h of `normal` |
| `SENSOR_FROZEN` / `SENSOR_BLOCKED` / `SENSOR_INVALID` | diagnosis rule | warning | 6 h | 1 h healthy |
| `DEVICE_OFFLINE` | LWT `online:false`, or no live message for 5 min (wall clock, live sources only) | warning | 1 h | next message |
| `DRIFT_PERFORMANCE_DEGRADED` | retrain policy fired | warning | per event | — |
| `MODEL_RETRAINED` / `RETRAIN_REJECTED` | end of a retrain attempt | info | none | — |
| `SENSOR_SPIKE` | spikes counted ≥ 5 per hour | info | 6 h | — |

> **Why `AUTONOMY_LOW` is gated.** Just before every normal refill the "no-refill autonomy" is ≈ 12 h; alerting on it alone would fire every cycle. Gating on "pump not effective" or "already at the warning level" turns it into an actionable signal.

### 22.4 Message format (plain text; no Markdown parsing → no escaping bugs)

```text
🔴 CRITICAL · tank-01
Level 14.8 % (174 L) — below the critical 15 %.
Autonomy if no refill: ~3 h · Pump: OFF (last refill 31 h ago)
2026-09-20 05:15 (Africa/Casablanca)
```

```text
🟠 LOW LEVEL PREDICTED · tank-01
Forecast reaches the critical level in ~7 h (6 h: 21 %, 24 h: 9 %).
Now 38 % (448 L) · Pump: ON but not filling (no-flow detected)
```

```text
🛠 SENSOR FROZEN · tank-01
Distance reading has not changed for 75 min. Forecasts are paused.
```

### 22.5 Delivery

`POST https://api.telegram.org/bot<token>/sendMessage` with `chat_id`, `text`, `disable_web_page_preview=true`; 10 s timeout; 3 retries with exponential backoff; honour `retry_after` on HTTP 429; ≤ 1 message/s; if > 5 alerts arrive in a minute, send one digest. Failures leave `notified=false` and are retried at the next loop. The token is never logged (log the chat id and message id only).

### 22.6 Security and tests

Only the configured `chat_id` receives messages; the bot **ignores incoming commands** in the MVP (optional stretch: `/status` via `getUpdates` long polling restricted to that chat id). Tests use `httpx.MockTransport`; a `--dry-run` flag prints instead of sending.

---

## 23. GitHub Actions CI pipeline

### 23.1 What CI proves — and what it cannot

| Proves | Cannot prove |
|---|---|
| Lint passes, unit + contract tests pass | The Wokwi simulation behaves (no browser simulator in CI) |
| DB schema loads; Mosquitto accepts auth; ingestion SQL works (integration) | Public-broker connectivity (non-deterministic) |
| A small model beats the baseline (quality gate) | Real-world accuracy |
| Docker images build | That the whole stack fits in 8 GB (measured manually) |

**CI vs CD.** CI = build + test on every change (automatic, here). CD = deliver to an environment. There is no remote environment (no paid cloud), so "CD" here means: CI builds and (optionally) pushes images to GHCR; **deployment is `docker compose pull && up -d` on your laptop**. Say so explicitly in the report rather than overclaiming.

### 23.2 Workflow (`.github/workflows/ci.yml`)

Action majors used (checked in 2026): `checkout@v6`, `setup-python@v6`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/metadata-action@v6`, `docker/build-push-action@v7`. Newer majors may exist — Dependabot proposes them.

```yaml
name: CI
on:
  push: {branches: [main]}
  pull_request:
concurrency: {group: "ci-${{ github.ref }}", cancel-in-progress: true}
permissions: {contents: read}

jobs:
  lint-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: {python-version: "3.11", cache: pip}
      - run: pip install -e ".[dev,api,jobs]"
      - run: ruff check . && ruff format --check src tests
      - run: pytest -m "not integration and not slow" --cov=src/wlm --cov-report=term-missing

  integration:
    needs: lint-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: {python-version: "3.11", cache: pip}
      - run: cp .env.example .env
      - name: Create throw-away Mosquitto credentials (CI-only dummy values)
        run: |
          docker run --rm -v "$PWD/infra/mosquitto:/work" eclipse-mosquitto:2 \
            mosquitto_passwd -b -c /work/passwd nodered ci-dummy
          docker run --rm -v "$PWD/infra/mosquitto:/work" eclipse-mosquitto:2 \
            mosquitto_passwd -b /work/passwd replay ci-dummy
      - run: docker compose up -d --wait timescaledb mosquitto
      - run: pip install -e ".[dev,jobs]"
      - run: pytest -m integration
      - if: failure()
        run: docker compose logs --no-color

  model-quality-gate:
    needs: lint-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: {python-version: "3.11", cache: pip}
      - run: pip install -e ".[dev,jobs]"
      - run: pytest -m slow tests/model_quality     # 30-day seeded dataset, quick LightGBM, asserts MAE < naive

  docker-build:
    needs: [lint-test]
    runs-on: ubuntu-latest
    permissions: {contents: read, packages: write}
    strategy:
      matrix:
        image: [{name: api, file: docker/api.Dockerfile}, {name: jobs, file: docker/jobs.Dockerfile}]
    steps:
      - uses: actions/checkout@v6
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        if: github.ref == 'refs/heads/main'
        with: {registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}"}
      - id: meta
        uses: docker/metadata-action@v6
        with: {images: "ghcr.io/${{ github.repository }}/${{ matrix.image.name }}"}
      - uses: docker/build-push-action@v7
        with:
          context: .
          file: ${{ matrix.image.file }}
          push: ${{ github.ref == 'refs/heads/main' }}
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

`.github/dependabot.yml` (keeps actions, pip and Docker bases current): ecosystems `github-actions`, `pip`, `docker`, weekly.

### 23.3 Practices

Branch protection on `main` requiring `lint-test`; no secrets needed by CI (Telegram is mocked, passwords are dummy); status badge in `README.md`; free-tier minutes are plentiful for public repos — check the current limits for private repos; keep the quality gate small (≈ 2-4 min).

---

## 24. Security considerations

### 24.1 Threat model (proportionate to a student project)

| Asset / path | Threat | Mitigation |
|---|---|---|
| Public broker leg | Eavesdropping, **injection of fake telemetry**, topic collision, outage | Non-sensitive payload; local **validation + quarantine**; unique prefix (not a secret); bridge **inbound only**; TLS on the bridge leg where the broker offers it; replay publisher as local fallback |
| Public Wokwi project | Firmware and topic prefix are public | No credentials in firmware; rotate the prefix if abused; the local side never trusts inbound data |
| Water-usage data | Consumption patterns reveal **when people are home** (privacy even if "just water") | Simulated data here, but design as if real: minimal payload, no location/names, no retained telemetry |
| Local Mosquitto | Unauthenticated access | `allow_anonymous false`, per-client users, ACL, bound to `127.0.0.1` |
| Pump control | Remote command injection | **No command topics** over the public broker; control logic on the device |
| Secrets | Tokens/passwords in Git or logs | `.env` git-ignored, `.env.example` with placeholders, gitleaks pre-commit + CI check, never log tokens |
| TimescaleDB | Over-privileged apps, exposed port | Three least-privilege roles, port bound to localhost, strong passwords |
| MLflow | No auth by default | Localhost only; host validation configured (≥ 3.5); no public exposure |
| FastAPI | Unauthenticated admin | `/admin/*` needs `X-Admin-Token`; admin routes not mapped outside localhost |
| Grafana / Node-RED | Default credentials | Change admin passwords via env; Node-RED credentials encrypted with `credentialSecret` |
| Containers | Root user, privileged mode, Docker socket | Non-root user in custom images; no `--privileged`; **no Docker socket mounts** (D9) |
| Supply chain | Malicious/updated packages and images | Pin versions; Dependabot; official images; review new dependencies |
| Telegram | Token leak → someone sends as your bot | Token only in `.env`; revoke via BotFather if leaked; send only to one `chat_id` |

### 24.2 Hardening checklist

- [ ] All published ports bound to `127.0.0.1`
- [ ] `.env` and `infra/mosquitto/passwd` in `.gitignore`; `git log -p | gitleaks` clean
- [ ] Mosquitto: auth + ACL tested (T1b in Section 10.5)
- [ ] DB roles verified (`wlm_grafana` cannot `INSERT`)
- [ ] `API_ADMIN_TOKEN` set; `/admin/reload` rejects missing/wrong token
- [ ] Node-RED `credentialSecret` set; `flows_cred.json` git-ignored
- [ ] No secret in the Wokwi project; topic prefix considered public
- [ ] Containers run as non-root (`docker compose exec api id`)
- [ ] Images pinned; Dependabot enabled

---

## 25. Testing and validation strategy

### 25.1 Test pyramid

| Level | Marker | Runs where | What it protects |
|---|---|---|---|
| Unit | *(default)* | laptop + CI | Business logic: tank maths, features, rules, alerts, policy |
| Contract | *(default)* | laptop + CI | One schema everywhere (Python ⇄ Node-RED ⇄ firmware constants) |
| Integration | `integration` | laptop + CI (DB + Mosquitto) | SQL schema, roles, broker auth/ACL |
| Stack | `stack` | laptop only (full Compose) | MQTT → Node-RED → DB, API, worker |
| Model quality | `slow` | laptop + CI (small seeded data) | "ML beats baseline", "detectors find injected events" |
| End-to-end / demo | manual | laptop | Success criteria (Section 27) |

### 25.2 Test inventory

| File | Asserts |
|---|---|
| `tests/unit/test_tank_conversion.py` | `d_full → 100 %`, `d_empty → 0 %`, midpoint, clamping; volume at 50 % = capacity/2; constants in `iot/wokwi/config.h` equal `config/tank.yaml` |
| `tests/unit/test_schema.py` | pydantic **and** JSON Schema accept `valid_*.json`, reject `invalid_*.json`; invariants (null ⇔ `sensor_ok=false`) |
| `tests/unit/test_grid_resample.py` | Right-edge labels, median, spike immunity, gap handling, 15-min alignment |
| `tests/unit/test_features_no_leakage.py` | **Leakage guard:** mutate all rows after `t` → features(t) unchanged; target equals `level(t+h)`; splits keep `gap ≥ horizon` |
| `tests/unit/test_train_serve_parity.py` | Features from the Parquet path equal features from the DB-window path for the same period |
| `tests/unit/test_baselines.py` | Persistence; seasonal-naive offset `h − 24h·⌈h/24h⌉`; B3 formula |
| `tests/unit/test_generator.py` | Same seed → same SHA-256; schema; event coverage per split; mass balance; pump controller consistency; no overlapping events |
| `tests/unit/test_autonomy.py` | A1/A2/A3 on constructed traces with known answers; `0` if already critical; cap at 72 h |
| `tests/unit/test_anomaly_rules.py` | Golden windows → `sensor_frozen`, `sensor_blocked`, `sensor_invalid`, `sensor_spike`, `normal` |
| `tests/unit/test_alert_engine.py` | Cooldown, re-arm, **`AUTONOMY_LOW` gating**, suppression when `low_confidence`, severity escalation ≤ 6 h |
| `tests/unit/test_telegram.py` | Request payload, retry on 5xx, `retry_after` on 429, token never in logs |
| `tests/unit/test_retrain_policy.py` | Trigger on synthetic MAE series; two-consecutive rule; cooldown; `max_attempts` |
| `tests/unit/test_promotion_gate.py` | Each condition A-E independently blocks promotion |
| `tests/unit/test_drift_parse.py` | `parse_result()` on a frozen Evidently `dict()` sample (catches library upgrades) |
| `tests/contract/test_golden_messages.py` | The Node-RED validation function (run with `node` on a stubbed `msg`) and the Python validator **agree** on every golden message |
| `tests/unit/test_api.py` | `TestClient`: schema of responses, `409` on short history, `422`, reload swap, version fields, admin token |
| `tests/integration/test_db_schema.py` | Init scripts apply; hypertables exist; `wlm_grafana` cannot `INSERT`; `ON CONFLICT` idempotency |
| `tests/integration/test_mqtt_auth_acl.py` | Anonymous refused; `nodered` can read, cannot write; `replay` can write |
| `tests/stack/test_ingestion_flow.py` | Publish valid → row ≤ 5 s; invalid → `invalid_messages`; duplicate → one row |
| `tests/model_quality/test_forecast_beats_baseline.py` | On a seeded 30-day set: LightGBM MAE < best naive at both horizons |
| `tests/model_quality/test_anomaly_event_recall.py` | Injected leaks and frozen/blocked windows detected; false alarms below limit |

### 25.3 How to verify each service is running

| Service | Check (PowerShell) | Healthy result |
|---|---|---|
| Docker stack | `docker compose ps` | all `running`/`healthy` |
| Mosquitto | T1-T3 of Section 10.5 | messages flow; anonymous refused |
| Node-RED | open `http://localhost:1880` → flow deployed; debug sidebar | one message per publish |
| TimescaleDB | `docker compose exec timescaledb psql -U postgres -d wlm -c "SELECT count(*), max(time) FROM measurements;"` | count increases, `max(time)` recent |
| Grafana | `http://localhost:3000` → Connections → datasource → *Save & test* | green "Database Connection OK"; panels populated |
| MLflow | `http://localhost:5000` | experiments listed; models page shows aliases |
| API | `Invoke-RestMethod http://localhost:8000/ready` and `http://localhost:8000/docs` | `ready`; Swagger UI |
| Worker | `docker compose logs worker --tail 20` | `predict ok as_of=…` lines every 15 min of data time |
| Telegram | `docker compose run --rm worker python -m wlm.alerts.telegram --test` | message on your phone |
| Evidently | `reports/evidently/*.html` exists after the daily job | opens in browser |
| CI | GitHub → Actions | green |

### 25.4 Automated validation report

`python -m wlm.validation.report` evaluates the ten criteria of Section 27 from the DB, `reports/*.json` and MLflow, and writes `reports/success_criteria.md` (pass/fail table with numbers). Run it before the demo and attach it to the report.

---

## 26. Final demonstration scenario (≈ 20 minutes)

### 26.1 Before you start (10 min)

`docker compose up -d` → check `/ready` → history loaded (90 days visible in Grafana) → Wokwi project open and *stopped* → phone with Telegram visible → one terminal ready with the replay command → browser tabs: Grafana, MLflow, API `/docs`, GitHub Actions. Close everything else (RAM).

### 26.2 Script

| Time | Step | What you show | Expected result |
|---|---|---|---|
| 0:00 | Context | Diagram 5.1; one sentence per layer | audience understands the chain |
| 2:00 | **Live IoT chain** | Start Wokwi. Set the HC-SR04 distance to 60 cm → Grafana gauge ≈ 70 % / 827 L within 5 s. Raise distance to **120 cm** (level 30 %) → relay LED ON. Lower to **25 cm** (level ≈ 93 %) → relay OFF | criteria 1-2, FR-02 |
| 5:00 | **Critical alert** | Set distance **150 cm** (level 10 %) | Telegram `LEVEL_CRITICAL` |
| 6:00 | **Leak + frozen sensor** (accelerated replay of test-period events) | `replay --from <leak start − 6h> --speed 720`; show anomaly panel and annotations (ground-truth shading) | `ANOMALY_LEAK`, later `SENSOR_FROZEN` on the phone |
| 9:00 | **Supply outage / early warning** | Replay an outage: `PUMP_NO_FLOW`, forecast overlay dropping, autonomy stat falling | `LEVEL_LOW_PREDICTED` and/or `AUTONOMY_LOW` **≥ 6 h (data time) before** the critical crossing; show `reports/early_warning.json` |
| 12:00 | **MLOps** | MLflow: compare runs, registered models with aliases; API `/v1/models` | versions match `forecasts.model_version` |
| 14:00 | **Forecast quality** | Grafana forecast overlay vs actual; table MAE vs baseline | criterion 4 |
| 15:00 | **Drift → retrain** | Replay `regime_change_21d` (fast): MAE rises, Evidently report, trigger, retrain, gate, API reload | new `champion`, MAE back down (use the pre-recorded run if short on time) |
| 19:00 | **Engineering proof** | CI green, images built, `reports/success_criteria.md` | all ten criteria pass |
| 20:00 | Q&A | | |

### 26.3 Fallbacks

| Failure | Fallback |
|---|---|
| Public broker down | Run `replay` straight into local Mosquitto; show the Wokwi path from a recording |
| Wokwi slow/unavailable | 60-second screen recording of the live chain |
| Telegram unreachable | Show `alerts` table with `notified=false` and the retry log; phone screenshots from rehearsal |
| Retraining slow | Show the pre-run `retrain_events` row, MLflow versions, and Grafana before/after |
| RAM pressure | `docker compose stop nodered grafana` during training, restart afterwards |

### 26.4 Questions you should be ready for

| Question | Short answer |
|---|---|
| Why not just a threshold? | A threshold tells you the tank *is* low; the forecast and autonomy tell you it *will be*, and the detector says *why* it is draining abnormally |
| Aren't you just learning your own simulator? | Yes for absolute numbers — stated openly. The point is the pipeline and the robustness test under a regime change, plus randomness/noise in the generator |
| Why direct multi-horizon forecasting? | No error accumulation, one metric per horizon, simple to evaluate |
| Why Isolation Forest *and* rules? | A frozen sensor at night looks like zero use; zero variance is a stronger signal. We measured IF alone vs hybrid |
| What if the public broker drops messages? | QoS 0 + `seq` reveals gaps; the grid and `valid_frac` tolerate them; the local fallback path exists |
| How do you avoid training/serving skew? | One feature module + a parity test + data-time jobs |
| Registered vs deployed? | Registration creates a version; only the gate-set `champion` alias plus an API reload changes what is served |
| Why not Kubernetes? | Single host, 8 GB, no scaling/HA requirement — Compose is the honest choice |
| What would change on real hardware? | Voltage divider on ECHO, temperature compensation, thresholds re-tuned on real noise, TLS to the broker |

---

## 27. Success criteria and evaluation metrics

| # | Criterion (from the brief) | Measure | Pass threshold | Evidence |
|---|---|---|---|---|
| 1 | **Wokwi ↔ local infrastructure** | 30-minute live run: `seq` continuity; median `ingested_at − ts` | ≥ 95 % of expected messages received; median latency < 2 s | `reports/success/01_comms.json`, Node-RED debug screenshot |
| 2 | **Real-time storage and visualisation** | Row in `measurements` and on Grafana after a publish | ≤ 5 s; all panels of FR-10 populated | SQL output, dashboard screenshot |
| 3 | **Forecasts at 6 h and 24 h** | `forecasts` rows for both horizons during a 3-day test replay | one pair per 15 min of data time, no gaps | `forecasts` count query |
| 4 | **MAE < naive baseline** | Test-period MAE per horizon vs best of B1/B2 | **both** horizons strictly lower; stretch: skill ≥ 20 % | `reports/forecast_metrics.json`, MLflow compare view |
| 5 | **Early warning ≥ 6 h before critical** | Lead time for every critical crossing in the test replay | all ≥ 6 h; false alarms ≤ 1/week | `reports/early_warning.json` |
| 6 | **Detect injected leaks and blocked sensors** | Event-level recall and delay on the test period | leaks ≥ 90 % (target: all injected), frozen/blocked ≥ 95 %; delays within Section 14.5 | `reports/anomaly_metrics.json` |
| 7 | **Experiment tracking and versioning** | MLflow runs, registered models with aliases, DVC status | ≥ 6 runs per horizon; 3 registered models with `champion`; `dvc status` clean; `dvc dag` printed | MLflow screenshots, terminal |
| 8 | **FastAPI + Docker deployment** | Fresh clone + `.env` → `docker compose up -d --build` | `/ready` OK and valid `/v1/forecast` response ≤ 10 min after the build | recorded terminal session |
| 9 | **Drift monitoring and automated retraining** | Regime-change scenario | trigger fires; challenger promoted (or rejection logged); API serves the new version; rolling MAE returns to ≤ 1.2× reference | `retrain_events`, Grafana, Evidently HTML |
| 10 | **Telegram alerts** | Scenario-triggered alerts | `LEVEL_CRITICAL`, `LEVEL_LOW_PREDICTED`, `ANOMALY_LEAK`, `SENSOR_FROZEN`, `PUMP_NO_FLOW` received | `alerts.telegram_message_id` populated + phone screenshots |

---

## 28. Troubleshooting guide

### 28.1 Wokwi / firmware

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Serial stuck on "Connecting to WiFi" | Wrong SSID or password | Use `Wokwi-GUEST`, empty password; channel 6 speeds connection |
| WiFi OK, MQTT `rc=-2` | Public broker unreachable, wrong host/port | `broker.hivemq.com:1883`; try `test.mosquitto.org`; Wokwi public gateway is slower — retry |
| Publish returns false / message truncated | PubSubClient 256-byte buffer | `client.setBufferSize(512)` |
| Level stuck / always the same | Slider not moved; or distance 0 | Click the HC-SR04 during simulation to move the slider; check `sensor_ok` |
| Detector flags a frozen sensor while testing | Wokwi sensor has no noise | Enable `SIMULATE_NOISE`, or move the slider periodically |
| Relay never toggles | Polarity | Flip `RELAY_ACTIVE_LOW`; check wiring to IN pin |
| `ts` is 1970 | NTP not synced yet | Wait for sync before publishing; do not publish until `time()` is plausible |
| Simulation runs slower than real time | Wokwi load | Use `seq`/`ts` (NTP), never `millis()`, for time |

### 28.2 MQTT / bridge

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Local broker refuses clients | Auth/ACL | T1b; confirm `passwd`, `aclfile` mounted; file permissions warning in logs |
| Bridge never connects | No internet from container, DNS, typo in `address` | `docker compose logs mosquitto`; try `test.mosquitto.org` |
| Bridge connected but nothing arrives locally | Topic pattern/direction/prefix mismatch; ACL blocks local republish | Pattern must be `wlm/<groupid>/# in 0`; test with ACL temporarily relaxed; check the exact prefix |
| Bridge disconnects repeatedly | Duplicate `remote_clientid` on the public broker | Make the id unique (random suffix) |
| Messages from strangers arrive | Prefix exposed (public Wokwi project) | Expected risk: validation quarantines; rotate prefix |
| Duplicate rows | Publisher retries / replay overlap | PK + `ON CONFLICT DO NOTHING` — verify the clause exists |

### 28.3 Node-RED / TimescaleDB / Grafana

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Node-RED: Postgres node `ECONNREFUSED` | Using `localhost` | Host must be `timescaledb`, port 5432 |
| `password authentication failed` | Role password mismatch; init scripts only run on an **empty** volume | Recreate volume (`down -v`, ⚠ data loss) or `ALTER ROLE` manually |
| Init script error `must be owner` / hypertable error | Old `create_hypertable` syntax, PK without `time` | Use `by_range`; PK `(device_id, time)` |
| `exec format error` / `\r` in shell scripts | CRLF line endings | `.gitattributes` `*.sh text eol=lf`; re-checkout |
| Grafana "No data" | Time range, timezone, `$device` variable, datasource host | Last 24 h; host `timescaledb:5432`; run the query in the Explore tab |
| Grafana forecast line looks shifted | Plotting `made_at` instead of `target_time` | Use `target_time AS time` |
| Dashboard works then breaks after restart | Provisioning path/volume wrong | Check mounted `provisioning/` and `dashboards/` paths |

### 28.4 ML / MLflow / API

| Symptom | Likely cause | Check / fix |
|---|---|---|
| MAE suspiciously perfect | **Leakage** | Run `test_features_no_leakage`; check `closed='right'`, no `center=True`, target shift only on the target |
| LightGBM worse than baseline | Too few features/trees, bad split, outage underrepresented | Check per-regime metrics; verify pump/no-flow features; enough outage events in train |
| `ImportError: libgomp.so.1` | OpenMP missing in slim image | `apt-get install libgomp1` in the Dockerfile |
| MLflow `Invalid Host header` | MLflow ≥ 3.5 host validation | `MLFLOW_SERVER_ALLOWED_HOSTS=mlflow:5000,localhost:*,127.0.0.1:*` |
| MLflow can't connect to DB | Missing driver or wrong URI | `psycopg2-binary` in image; `postgresql+psycopg2://…@timescaledb:5432/mlflow` |
| Model artifacts "not found" | Artifact root mismatch | Experiment artifact location should start with `mlflow-artifacts:/`; use `--serve-artifacts` |
| API `/ready` not ready | No `champion` alias yet, or MLflow down | Register + promote first model; API falls back to `/models` cache |
| API `409 not enough history` | < 8 days of data for `as_of` | Load history/replay first |
| Evidently `ImportError`/`TypeError` | Old-API tutorial code | Use `from evidently import Report`; pin 0.7.x |
| Worker never "matures" forecasts during replay | Wall-clock instead of data time | `CLOCK_MODE=data` (Section 8.5) |
| Retrain rejected repeatedly | Not enough post-change data in the snapshot | Expected for the first days; retry continues; check holdout size |

### 28.5 Docker / Windows / Telegram / CI / DVC

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Laptop freezes / containers killed | WSL2 using too much RAM | `.wslconfig` cap; `docker stats`; stop unused services; use profiles |
| Port already in use | Another process | `netstat -ano | findstr :5432`; change the host port |
| Postgres very slow | Data on a Windows bind mount | Use the named volume `pgdata` |
| Telegram `401 Unauthorized` | Wrong token | Re-copy token from BotFather |
| Telegram `400 chat not found` | Bot never messaged / wrong `chat_id` | Send `/start` to the bot, redo `getUpdates` |
| No Telegram message but alert row exists | Network/429; retry pending | `notified=false` rows; worker logs |
| CI: DB service not ready | Healthcheck missing | `docker compose up -d --wait`; add `healthcheck` |
| CI: Mosquitto fails to start | `passwd` missing (git-ignored) | The workflow creates dummy credentials (Section 23.2) |
| `dvc push` permission error | Remote folder path | Create the folder; use an absolute path; check antivirus |
| `git push` rejected large file | Data committed by mistake | `git rm --cached`; `dvc add`; rewrite history if already pushed |

---

## Appendix A — Repository structure

Phase numbers refer to [`docs/ROADMAP.md`](docs/ROADMAP.md).

```text
water-level-mlops/
├── README.md                     # project pitch, quick start, badges, screenshots
├── PROJECT_GUIDE.md              # this document
├── .env.example                  # all variables with placeholders (committed)
├── .gitignore  .gitattributes  .dvcignore  .pre-commit-config.yaml
├── pyproject.toml                # package `wlm` + extras: [ml] [api] [jobs] [dev]
├── params.yaml                   # single source for generator/features/split/forecast/anomaly/monitoring/retrain
├── dvc.yaml                      # offline reproducible pipeline        (dvc.lock is generated)
├── docker-compose.yml
├── config/
│   ├── tank.yaml                 # geometry, thresholds, pump rules (single source of truth)
│   └── alerts.yaml               # alert catalogue: thresholds, cooldowns, texts
├── schemas/
│   ├── measurement.v1.schema.json
│   └── examples/                 # valid_*.json, invalid_*.json (golden messages)
├── iot/wokwi/
│   ├── sketch.ino  config.h  diagram.json  libraries.txt  README.md
├── infra/
│   ├── mosquitto/                # mosquitto.conf, aclfile, passwd.example, conf.d/bridge.conf.template
│   ├── nodered/                  # Dockerfile, package.json, settings.js, flows.json
│   ├── timescaledb/init/         # 001_schema.sql 002_mlflow_db.sh 003_roles.sh 004_seed_device.sql
│   ├── grafana/                  # provisioning/{datasources,dashboards}, dashboards/{wlm-main,wlm-mlops}.json
│   └── mlflow/Dockerfile
├── docker/                       # api.Dockerfile, jobs.Dockerfile
├── src/wlm/
│   ├── config.py  schema.py  tank.py  timeutils.py  db.py
│   ├── data/        generator.py scenarios.py generate.py validate.py loader.py replay.py
│   ├── features/    grid.py forecasting.py anomaly.py build_dataset.py
│   ├── models/      baselines.py forecaster.py anomaly.py autonomy.py rules.py bundle.py
│   ├── training/    train_forecast.py train_anomaly.py evaluate.py gate.py retrain.py
│   ├── serving/     app.py routes.py schemas.py registry.py service.py deps.py
│   ├── monitoring/  performance.py drift.py policy.py
│   ├── alerts/      rules.py engine.py telegram.py
│   ├── worker/      scheduler.py jobs.py
│   └── validation/  report.py
├── data/            raw/ processed/ snapshots/        # DVC-tracked; contents git-ignored
├── reports/         forecast_metrics.json anomaly_metrics.json early_warning.json
│                    success_criteria.md evidently/ data_validation/
├── notebooks/       01_eda.ipynb 02_forecasting_experiments.ipynb 03_anomaly_experiments.ipynb
├── tests/           unit/ contract/ integration/ stack/ model_quality/ conftest.py
├── scripts/         new-prefix.ps1 make-passwd.ps1 wait-for-stack.ps1
├── docs/            CONCEPTS_GUIDE.md ROADMAP.md openapi.json demo-script.md screenshots/
└── .github/         workflows/ci.yml  dependabot.yml
```

| Path | Purpose | Contains | Created in | Depended on by |
|---|---|---|---|---|
| `config/tank.yaml` | Single source of truth for geometry and thresholds | diameter, heights, offsets, critical/warning/pump levels, pump timing | P1 | firmware `config.h`, `wlm.tank`, generator, Node-RED, Grafana seed |
| `config/alerts.yaml` | Alert catalogue | thresholds, cooldowns, re-arm rules, message templates | P8 | alert engine, tests |
| `schemas/` | Data contract | JSON Schema + golden messages | P1 | Node-RED, Python validator, CI contract tests |
| `iot/wokwi/` | Simulated device | sketch, generated `config.h`, `diagram.json` | P1 | public broker path (P2), demo |
| `infra/mosquitto/` | Broker + bridge config | `mosquitto.conf`, `aclfile`, bridge template | P2 | Node-RED, replay, integration tests |
| `infra/nodered/` | Ingestion flows | Dockerfile, `flows.json` (credentials excluded) | P2 | TimescaleDB |
| `infra/timescaledb/init/` | Schema + roles | DDL, roles, MLflow DB | P2 (extended in P6, P8, P9) | everything that stores data |
| `infra/grafana/` | Dashboards as code | provisioning + JSON | P4 (extended P6-P9) | demo |
| `infra/mlflow/` | MLflow image | 2-line Dockerfile | P6 | trainer, API |
| `src/wlm/` | The one Python package | all logic | P1 → P10 | API, worker, trainer, tests |
| `src/wlm/data/` | Generator, loader, replay | see Section 11 | P3 | DVC pipeline, demo |
| `src/wlm/features/` | Grid + features (shared) | `grid.py`, `forecasting.py`, `anomaly.py` | P5 | trainer, API, worker |
| `src/wlm/models/` | Baselines, forecaster, IF, autonomy, rules, bundle | | P5-P6 | trainer, API |
| `src/wlm/training/` | Training, gate, retrain | | P5-P6, P9 | worker (retrain) |
| `src/wlm/serving/` | FastAPI | | P6 | worker, tests |
| `src/wlm/monitoring/` | Performance, Evidently, policy | | P9 | worker |
| `src/wlm/alerts/` | Rules, engine, Telegram | | P8 | worker |
| `src/wlm/worker/` | Scheduler and jobs | | P7-P9 | Compose |
| `params.yaml`, `dvc.yaml` | Parameters and pipeline | | P3 → P6 | trainer, DVC |
| `docker/`, `docker-compose.yml` | Images and orchestration | | P2 (core) → P7 (full) | all services |
| `tests/` | All tests | | every phase | CI |
| `data/` | Datasets | Parquet | P3 | features, replay |
| `reports/` | Metrics and reports | JSON, HTML, MD | P5 → P10 | DVC metrics, demo, validation report |
| `docs/` | Documentation | guides, OpenAPI, screenshots | P0 → P10 | reader |
| `.github/` | CI | workflow, Dependabot | P0 (skeleton) → P10 | GitHub |

Avoided on purpose: one folder per microservice, a separate `models/` folder (the registry is the source of truth), duplicated config files.

---

## Appendix B — Installation and dependency checklist

### B.1 Tools (Windows 10/11)

| Tool | Notes | Verify |
|---|---|---|
| **Git** | `git config core.autocrlf false` | `git --version` |
| **VS Code** + extensions: Python, Pylance, Ruff, Docker, YAML, **Markdown Preview Mermaid Support**, (optional) Wokwi Simulator, GitLens | | |
| **Python 3.11** (64-bit) | create `.venv` in the repo | `python --version` |
| **Docker Desktop** (WSL2 backend) | cap RAM with `.wslconfig` (Section 16.6) | `docker --version`, `docker compose version` |
| **DVC** | `pip install dvc` (host only) | `dvc --version` |
| **Node.js LTS** | optional; only to run the Node-RED function tests locally | `node --version` |
| Accounts | GitHub, Wokwi (free), Telegram | |

### B.2 Python dependencies by extra (pin exact versions after the first successful install)

| Extra | Packages |
|---|---|
| core | `pandas`, `numpy`, `pyarrow`, `pyyaml`, `pydantic>=2`, `sqlalchemy>=2`, `psycopg[binary]`, `paho-mqtt>=2`, `tzdata` |
| `ml` | `scikit-learn`, `lightgbm` |
| `api` | `ml` + `fastapi`, `uvicorn[standard]`, `mlflow-skinny` (fall back to `mlflow` if a flavor needs more) |
| `jobs` | `ml` + `mlflow`, `evidently==0.7.*`, `apscheduler`, `httpx`, `matplotlib` |
| `dev` | `pytest`, `pytest-cov`, `ruff`, `pre-commit`, `dvc`, `httpx` |

### B.3 Docker images (pin exact tags)

`timescale/timescaledb:<2.x.y>-pg17` · `eclipse-mosquitto:2` · `nodered/node-red:<tag>` · `grafana/grafana:<tag>` · `ghcr.io/mlflow/mlflow:<tag>` (≥ 3.5 line) · `python:3.11-slim`.

### B.4 Node-RED palette

`node-red-contrib-postgresql` (installed in `infra/nodered/Dockerfile`, not by clicking in the UI, so the build is reproducible).

---

## Appendix C — Risk register

| # | Risk | Likelihood | Impact | Mitigation | Early signal |
|---|---|---|---|---|---|
| R1 | Scope too large for the schedule | High | High | MVP cut line (1.4); phases with Definition of Done; no gold-plating | Phase slips > 1 week |
| R2 | 8 GB RAM insufficient | Medium | High | WSL cap, profiles, stop idle services, measure early (P2, P7) | Swap thrashing, OOM kills |
| R3 | Public broker unavailable/rate-limited | Medium | Medium | Fallback broker; replay directly to local Mosquitto; recording | Bridge reconnect loops |
| R4 | Wokwi free tier slow or limits change | Medium | Medium | Short publish interval for demo; recording; Python replay covers scale | Long connect times |
| R5 | Models trained on simulator "look" too good | High | Medium | Randomness, noise, regime-change test, explicit caveat in report | MAE near zero |
| R6 | Data leakage | Medium | High | Leakage test, chronological split, train-only profile | Too-good metrics |
| R7 | Training/serving skew | Medium | High | Shared feature module + parity test | Live MAE ≫ test MAE with no drift |
| R8 | Drift scenario too mild → retrain never triggers | Medium | Medium | Calibrate scenario (11.8); document | Rolling MAE barely moves |
| R9 | Library API breaks (Evidently, MLflow security) | Medium | Medium | Pin versions; parsing tests; Section 28 entries | Import errors after upgrade |
| R10 | Secrets leaked to Git | Low-Medium | High | `.env` ignored, gitleaks, CI check | Scanner alert |
| R11 | Public Wokwi project leaks prefix; spoofed telemetry | Medium | Low-Medium | Local validation/quarantine; rotate prefix | Foreign messages in `invalid_messages` |
| R12 | Alert fatigue | Medium | Medium | Cooldown/re-arm, gating (`AUTONOMY_LOW`), persistence rule, false-alarm KPI | > 1 false alarm/week |
| R13 | Time-zone / Ramadan offset bugs | Low | Medium | Store UTC; local features through `zoneinfo`; test around the shift | Consumption peaks shifted by 1 h |
| R14 | Retraining deadlock (challenger never beats champion right after change) | Medium | Medium | Daily retries with growing data; holdout of 2 days; optional recency weights | Repeated `RETRAIN_REJECTED` |
| R15 | Retrain job hangs or exhausts RAM | Low | Medium | Subprocess timeout; memory cap; cooldown | Worker unresponsive |
| R16 | CI too slow/flaky | Low | Low | Small seeded dataset; cache; split jobs | Runs > 10 min |

---

## Appendix D — Resource budget

Approximate figures to be **verified with `docker stats`** on your machine in Phase 2 and Phase 7.

| Service | Idle RAM | Busy RAM | Cap (`mem_limit`) | Disk |
|---|---|---|---|---|
| mosquitto | 5-15 MB | 20 MB | 64 MB | < 50 MB |
| nodered | 100-150 MB | 200 MB | 384 MB | image ≈ 0.5 GB |
| timescaledb | 150-300 MB | 400 MB | 512 MB | image ≈ 0.5 GB; data < 200 MB |
| grafana | 100-150 MB | 250 MB | 384 MB | image ≈ 0.5 GB |
| mlflow | 250-350 MB | 450 MB | 512 MB | image ≈ 1 GB; artifacts < 200 MB |
| api | 250-350 MB | 450 MB | 512 MB | image ≈ 1 GB |
| worker | 250-350 MB | 600 MB (monitor/Evidently) | 768 MB | shares `jobs` image ≈ 1.3 GB |
| trainer (on demand) | — | 0.8-1.5 GB | 1.5 GB | — |
| replay (on demand) | — | 100-200 MB | 256 MB | — |

| Scenario | Containers running | Approx. total |
|---|---|---|
| Daily dev (no training) | all default services | ≈ 1.5-2.2 GB |
| Training day | + trainer; stop `grafana`, `nodered` if tight | ≈ 2.5-3.2 GB |
| Demo | all default + replay | ≈ 2-2.6 GB |

**Plus** Docker/WSL2 overhead (≈ 0.5-1 GB), VS Code (≈ 1 GB) and a browser (1-2 GB). With a 4 GB WSL2 cap, containers fit; the host stays usable if you keep browser tabs under control. **16 GB** removes the pressure; **8 GB** works with discipline.

**Disk:** ≈ 6-8 GB for images + volumes + build cache; clean with `docker image prune` / `docker builder prune` (never `docker volume prune` blindly — it deletes your database).

**Cost-saving tactics:** build the `api` and `jobs` images from one base; `--no-cache-dir` for pip; stop `mlflow`/`api`/`worker` when only working on firmware or dashboards; run the trainer once and stop everything non-essential; keep Evidently reports to the columns that matter.

---

*End of PROJECT_GUIDE.md — next: [`docs/CONCEPTS_GUIDE.md`](docs/CONCEPTS_GUIDE.md) to learn the technologies, then [`docs/ROADMAP.md`](docs/ROADMAP.md) to start Phase 0.*
