# Phase 1 command sheet

Run the commands below in the VS Code PowerShell terminal. Unless a step says
otherwise, start from the repository root:

```powershell
Set-Location C:\path\to\Water-Level-Monitoring-System-with-IoT-MLOps
```

Replace the example group name `ensa` with your own group identifier. The generated
MQTT prefix is public, so it is not a password or other secret.

## One-time setup

Create `.env` only if you do not already have one. This avoids overwriting an existing
file:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Generate a unique MQTT topic prefix and print the line to add to `.env`:

```powershell
$prefix = .\scripts\new-prefix.ps1 -Group tdia2
"MQTT_TOPIC_PREFIX=$prefix"
```

Open `.env`, replace its example `MQTT_TOPIC_PREFIX` value with the printed value, and
save it. Do not copy any unrelated secrets into the public Wokwi project.

Install or refresh the project dependencies after checking out changes to `pyproject.toml`:

```powershell
python -m pip install -e ".[dev]"
```

Generate `config.h` from `config/tank.yaml` and the prefix saved in `.env`:

```powershell
$prefix = .\scripts\new-prefix.ps1 -Group tdia2
python tools/gen_firmware_config.py --prefix $prefix

python tools/gen_firmware_config.py
Get-Content iot\wokwi\config.h
```

Confirm `MQTT_PREFIX_CONFIGURED true` is in the generated header. If it says `false`,
check `.env` and generate again.

## Run the ESP32 sketch

The current project setup does not provide a terminal command to launch Wokwi. Run the
firmware in the Wokwi simulator UI:

1. Open the saved Wokwi project (or open this folder using the Wokwi VS Code extension).
2. Ensure the project has the latest `sketch.ino`, `diagram.json`, `libraries.txt`, and
   generated `config.h`. The HC-SR04 must be wired **D5 → TRIG**, **D18 → ECHO**,
   **VIN → VCC**, and **GND → GND**.
3. Start the simulation with Wokwi's play button. Keep it running while checking telemetry.
4. Move the distance slider and watch the serial monitor. With the configured tank:
   - `120 cm` should show about `30.0%` and turn the pump indicator on.
   - `25 cm` should show about `93.3%` and turn the pump indicator off.
   - `87 cm` should show about `52.0%` and leave the pump off.

## Test Phase 1

Run all unit tests from the repository root:

```powershell
python -m pytest -q
```

Run only the Phase 1 tests:

```powershell
python -m pytest tests\unit\test_tank_conversion.py tests\unit\test_schema.py tests\unit\test_firmware_config.py tests\unit\test_stream_validation.py -q
```

Lint the Python implementation:

```powershell
python -m ruff check .
```

Check that the Wokwi diagram and measurement schema are valid JSON:

```powershell
Get-Content iot\wokwi\diagram.json -Raw | ConvertFrom-Json | Out-Null
Get-Content schemas\measurement.v1.schema.json -Raw | ConvertFrom-Json | Out-Null
```

## Validate live MQTT messages

Start the Wokwi simulation first, then open a second VS Code terminal at the repository
root. Subscribe for 60 seconds:

```powershell
python tools\validate_stream.py --prefix $env:MQTT_TOPIC_PREFIX --seconds 60
```

The command prints one JSON result per received telemetry message and a final summary.
Exit code `0` means messages arrived and passed validation; exit code `1` means at least
one was invalid; exit code `2` means no message arrived or the broker connection failed.
The public broker is best-effort, so a connection failure can be temporary.

If PowerShell says the environment variable is empty, the `.env` file is not automatically
loaded into the terminal environment. Pass the prefix directly instead:

```powershell
python tools\validate_stream.py --prefix wlm/tdia2-ensa-a1b2c3 --seconds 60
```

Replace that sample prefix with the exact value from your `.env` and generated `config.h`.

check status  :{"device_id":"tank-01","online":false}
```powershell
python -c "import paho.mqtt.client as m; c=m.Client(m.CallbackAPIVersion.VERSION2); c.on_connect=lambda client,userdata,flags,reason,properties: client.subscribe('wlm/tdia2-tdia2-d75171/tank-01/status'); c.on_message=lambda client,userdata,msg: print(msg.topic, msg.payload.decode(), flush=True); c.connect('broker.hivemq.com',1883,60); c.loop_forever()"
```