#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <algorithm>
#include <math.h>
#include <time.h>

#include "config.h"

constexpr uint8_t TRIG_PIN = 5;
constexpr uint8_t ECHO_PIN = 18;
constexpr uint8_t RELAY_PIN = 26;
constexpr bool SIMULATE_NOISE = false;
constexpr uint32_t PUBLISH_INTERVAL_MS = 5000;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 10000;
constexpr uint32_t MQTT_RETRY_INTERVAL_MS = 5000;
constexpr uint8_t PING_COUNT = 5;
constexpr uint32_t ECHO_TIMEOUT_US = 30000;
constexpr char WIFI_SSID[] = "Wokwi-GUEST";
constexpr char MQTT_HOST[] = "broker.hivemq.com";
constexpr uint16_t MQTT_PORT = 1883;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
String telemetryTopic;
String statusTopic;
uint32_t sequenceNumber = 0;
uint32_t lastPublishAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastMqttAttemptAt = 0;
uint32_t pumpStartedAt = 0;
uint32_t dryRunLockoutStartedAt = 0;
float pumpStartLevelPct = 0;
bool pumpOn = false;
bool dryRunLockout = false;
bool wifiAttempted = false;
bool mqttAttempted = false;

bool getUtcTimestamp(char* output, size_t outputSize) {
  struct tm timeInfo;
  if (!getLocalTime(&timeInfo, 20)) {
    return false;
  }
  return strftime(output, outputSize, "%Y-%m-%dT%H:%M:%SZ", &timeInfo) > 0;
}

void setPump(bool enabled) {
  pumpOn = enabled;
  const bool relayPinHigh = RELAY_ACTIVE_LOW ? !enabled : enabled;
  digitalWrite(RELAY_PIN, relayPinHigh ? HIGH : LOW);
}

bool readMedianDistance(float* distanceCm) {
  float readings[PING_COUNT];
  for (uint8_t index = 0; index < PING_COUNT; ++index) {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    const uint32_t echoDuration = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
    if (echoDuration == 0) {
      Serial.printf(
          "HC-SR04 timeout on ping %u/%u (TRIG GPIO%u, ECHO GPIO%u). Check sensor wiring.\n",
          static_cast<unsigned>(index + 1), static_cast<unsigned>(PING_COUNT), TRIG_PIN,
          ECHO_PIN);
      return false;
    }

    float reading = static_cast<float>(echoDuration) * 0.0343f / 2.0f;
    if (SIMULATE_NOISE) {
      reading += static_cast<float>(random(-30, 31)) / 10.0f;
    }
    if (reading < SENSOR_MIN_DISTANCE_CM || reading > SENSOR_MAX_DISTANCE_CM) {
      Serial.printf("HC-SR04 out-of-range ping %u/%u: %.1f cm (echo %lu us).\n",
                    static_cast<unsigned>(index + 1), static_cast<unsigned>(PING_COUNT), reading,
                    static_cast<unsigned long>(echoDuration));
      return false;
    }
    readings[index] = reading;
    delay(30);
  }

  std::sort(readings, readings + PING_COUNT);
  *distanceCm = readings[PING_COUNT / 2];
  return true;
}

float distanceToLevelPct(float distanceCm) {
  const float waterHeightCm =
      constrain(SENSOR_DISTANCE_EMPTY_CM - distanceCm, 0.0f, TANK_HEIGHT_CM);
  return waterHeightCm / TANK_HEIGHT_CM * 100.0f;
}

float levelPctToVolumeL(float levelPct) {
  const float waterHeightCm = constrain(levelPct, 0.0f, 100.0f) * TANK_HEIGHT_CM / 100.0f;
  const float radiusCm = TANK_DIAMETER_CM / 2.0f;
  return PI * radiusCm * radiusCm * waterHeightCm / 1000.0f;
}

float roundedToTenth(float value) {
  return roundf(value * 10.0f) / 10.0f;
}

void updatePump(bool sensorOk, float levelPct) {
  const uint32_t now = millis();
  if (!sensorOk) {
    setPump(false);
    return;
  }

  if (dryRunLockout && now - dryRunLockoutStartedAt >= PUMP_RETRY_DELAY_MS) {
    dryRunLockout = false;
  }

  if (pumpOn) {
    if (levelPct >= PUMP_OFF_AT_OR_ABOVE_PCT) {
      setPump(false);
      Serial.println("Pump stopped: upper hysteresis threshold reached.");
      return;
    }
    if (now - pumpStartedAt >= PUMP_DRY_RUN_TIMEOUT_MS &&
        levelPct < pumpStartLevelPct + PUMP_DRY_RUN_MIN_RISE_PCT) {
      setPump(false);
      dryRunLockout = true;
      dryRunLockoutStartedAt = now;
      Serial.println("Pump dry-run protection tripped; retry is delayed.");
      return;
    }
  } else if (!dryRunLockout && levelPct <= PUMP_ON_AT_OR_BELOW_PCT) {
    setPump(true);
    pumpStartedAt = now;
    pumpStartLevelPct = levelPct;
    Serial.println("Pump started: lower hysteresis threshold reached.");
  }
}

void publishStatus(bool online) {
  StaticJsonDocument<128> document;
  document["device_id"] = DEVICE_ID;
  document["online"] = online;
  if (online) {
    document["fw"] = "1.0.0";
    char timestamp[25];
    if (getUtcTimestamp(timestamp, sizeof(timestamp))) {
      document["ts"] = timestamp;
    }
  }
  char payload[128];
  const size_t length = serializeJson(document, payload, sizeof(payload));
  if (length == 0 || !mqttClient.publish(statusTopic.c_str(), payload, true)) {
    Serial.println("Failed to publish device status.");
  }
}

void connectMqttIfNeeded() {
  if (mqttClient.connected() || !MQTT_PREFIX_CONFIGURED || WiFi.status() != WL_CONNECTED) {
    return;
  }
  const uint32_t now = millis();
  if (mqttAttempted && now - lastMqttAttemptAt < MQTT_RETRY_INTERVAL_MS) {
    return;
  }
  lastMqttAttemptAt = now;
  mqttAttempted = true;

  char clientId[48];
  snprintf(clientId, sizeof(clientId), "%s-%08lx", DEVICE_ID,
           static_cast<unsigned long>(ESP.getEfuseMac() & 0xffffffff));
  char offlinePayload[64];
  snprintf(offlinePayload, sizeof(offlinePayload),
           "{\"device_id\":\"%s\",\"online\":false}", DEVICE_ID);
  if (mqttClient.connect(clientId, statusTopic.c_str(), 0, true, offlinePayload)) {
    Serial.printf("Connected to MQTT broker %s:%u\n", MQTT_HOST, MQTT_PORT);
    publishStatus(true);
  } else {
    Serial.printf("MQTT connection failed, state=%d\n", mqttClient.state());
  }
}

void connectWifiIfNeeded() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  const uint32_t now = millis();
  if (wifiAttempted && now - lastWifiAttemptAt < WIFI_RETRY_INTERVAL_MS) {
    return;
  }
  lastWifiAttemptAt = now;
  wifiAttempted = true;
  Serial.printf("Connecting to WiFi %s...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, "", 6);
}

void publishMeasurement(bool sensorOk, float distanceCm, float levelPct, float volumeL) {
  if (!mqttClient.connected()) {
    return;
  }
  char timestamp[25];
  if (!getUtcTimestamp(timestamp, sizeof(timestamp))) {
    Serial.println("NTP time is not ready; telemetry was not published.");
    return;
  }

  StaticJsonDocument<512> document;
  document["schema_version"] = 1;
  document["device_id"] = DEVICE_ID;
  document["ts"] = timestamp;
  document["seq"] = sequenceNumber++;
  if (sensorOk) {
    document["distance_cm"] = roundedToTenth(distanceCm);
    document["level_pct"] = roundedToTenth(levelPct);
    document["volume_l"] = roundedToTenth(volumeL);
  } else {
    document["distance_cm"] = nullptr;
    document["level_pct"] = nullptr;
    document["volume_l"] = nullptr;
  }
  document["pump_on"] = pumpOn;
  document["sensor_ok"] = sensorOk;
  document["rssi"] = WiFi.RSSI();
  document["source"] = "wokwi";

  char payload[384];
  const size_t length = serializeJson(document, payload, sizeof(payload));
  if (length == 0 || !mqttClient.publish(telemetryTopic.c_str(), payload, false)) {
    Serial.println("Failed to publish telemetry.");
    return;
  }
  Serial.println(payload);
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);
  setPump(false);

  telemetryTopic = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/telemetry";
  statusTopic = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/status";
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setBufferSize(512);
  mqttClient.setKeepAlive(30);

  if (!MQTT_PREFIX_CONFIGURED) {
    Serial.println("MQTT is disabled until a unique topic prefix is configured.");
  } else {
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    WiFi.mode(WIFI_STA);
  }
}

void loop() {
  connectWifiIfNeeded();
  connectMqttIfNeeded();
  mqttClient.loop();

  const uint32_t now = millis();
  if (now - lastPublishAt < PUBLISH_INTERVAL_MS) {
    delay(5);
    return;
  }
  lastPublishAt = now;

  float distanceCm = 0;
  const bool sensorOk = readMedianDistance(&distanceCm);
  float levelPct = 0;
  float volumeL = 0;
  if (sensorOk) {
    levelPct = distanceToLevelPct(distanceCm);
    volumeL = levelPctToVolumeL(levelPct);
  }

  updatePump(sensorOk, levelPct);
  if (sensorOk) {
    Serial.printf("distance=%.1f cm level=%.1f%% volume=%.1f L pump=%s\n",
                  distanceCm, levelPct, volumeL, pumpOn ? "ON" : "OFF");
  } else {
    Serial.println("Sensor reading invalid; pump switched off.");
  }
  publishMeasurement(sensorOk, distanceCm, levelPct, volumeL);
}
