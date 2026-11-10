# Water Level Monitoring System with IoT and MLOps

An IoT water-level monitoring project with telemetry ingestion, forecasting, and operational
automation. The project is being built phase by phase; see the project guide and roadmap for the
architecture and implementation plan.

## Development setup

Requires Python 3.11 or newer (up to 3.13).

```powershell
python -m venv .venv              
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
ruff check .
ruff format --check src tests
```

## Project documentation

- [Project guide](PROJECT_GUIDE.md)
- [Roadmap](docs/ROADMAP.md)




