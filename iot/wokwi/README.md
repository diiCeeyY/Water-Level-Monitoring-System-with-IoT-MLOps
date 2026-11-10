# Wokwi ESP32 water-level simulator

This project simulates the Phase 1 device: an ESP32 DevKit, HC-SR04 ultrasonic sensor,
relay module, and a green LED wired through the relay's normally-open (NO) contact. The
LED represents a powered pump; it is only a visual indicator, not a real pump.

For copy/paste PowerShell setup, test, and MQTT commands, see [COMMANDS.md](COMMANDS.md).

## Configure and run

1. From the repository root, copy `.env.example` to `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Generate a group-specific public MQTT topic prefix:

   ```powershell
   .\scripts\new-prefix.ps1 -Group ensa
   ```

   Copy the printed `wlm/tdia2-ensa-<6-hex>` value into `.env` as `MQTT_TOPIC_PREFIX`
   (replace the example value).
   The prefix is public, not a credential. Never put broker credentials or other secrets
   in this public Wokwi project.
3. Generate the firmware constants:

   ```powershell
   python tools/gen_firmware_config.py
   ```

4. Create an ESP32 project in Wokwi (browser or VS Code extension), then copy in
   `sketch.ino`, `diagram.json`, `libraries.txt`, and the generated `config.h`.
5. Start the simulation and use the HC-SR04 distance control. The telemetry topic is
   `<MQTT_TOPIC_PREFIX>/tank-01/telemetry`; status is retained on
   `<MQTT_TOPIC_PREFIX>/tank-01/status`.
6. In another repository-root terminal, validate the public stream for 60 seconds:

   ```powershell
   python tools/validate_stream.py --prefix $env:MQTT_TOPIC_PREFIX --seconds 60
   ```

The public broker is best-effort and unauthenticated. Its messages are visible to others;
use only synthetic readings and the unique prefix. MQTT/Wi-Fi credentials are not embedded
in the sketch.

## Wiring

| Component | Pin | ESP32 connection |
|---|---|---|
| HC-SR04 | TRIG | GPIO 5 |
| HC-SR04 | ECHO | GPIO 18 |
| HC-SR04 | VCC / GND | VIN (5 V) / GND |
| Relay module | IN | GPIO 26 |
| Relay module | VCC / GND | VIN / GND |
| Pump indicator LED | Relay COM → NO | VIN → LED → 220 Ω → GND |

For real hardware, do **not** connect the HC-SR04's 5 V ECHO directly to an ESP32 GPIO;
use a voltage divider. Real hardware and pump power wiring are outside this simulation.

## Firmware behavior

- Reads five HC-SR04 echoes and uses their median. A timeout or out-of-range ping marks
  the reading invalid and forces the relay off.
- Converts distance to level and cylinder volume using `config/tank.yaml` constants.
- Turns the relay on at or below 35% and off at or above 90% (hysteresis).
- Trips dry-run protection if the level has not risen by 1 percentage point within
  10 minutes of pumping, then delays another attempt for 30 minutes.
- Uses `Wokwi-GUEST`, NTP, HiveMQ's public broker, a retained Last-Will status, and a
  512-byte MQTT packet buffer. Telemetry is published every 5 seconds and is not retained.
- Set `SIMULATE_NOISE` to `true` in `sketch.ino` to add small per-ping noise and observe
  the median filter.

If `config.h` was generated before setting a unique prefix, MQTT stays disabled rather
than publishing to the shared placeholder topic. Add the prefix to `.env` and regenerate
the header before starting Wokwi.
