#pragma once

#define DEVICE_ID "tank-01"
#define MQTT_TOPIC_PREFIX "wlm/tdia2-tdia2-d75171"
#define MQTT_PREFIX_CONFIGURED true

constexpr float TANK_DIAMETER_CM = 100.0f;
constexpr float TANK_HEIGHT_CM = 150.0f;
constexpr float SENSOR_DISTANCE_FULL_CM = 15.0f;
constexpr float SENSOR_DISTANCE_EMPTY_CM = 165.0f;
constexpr float SENSOR_MIN_DISTANCE_CM = 2.0f;
constexpr float SENSOR_MAX_DISTANCE_CM = 400.0f;
constexpr float PUMP_ON_AT_OR_BELOW_PCT = 35.0f;
constexpr float PUMP_OFF_AT_OR_ABOVE_PCT = 90.0f;
constexpr uint32_t PUMP_DRY_RUN_TIMEOUT_MS = 600000UL;
constexpr float PUMP_DRY_RUN_MIN_RISE_PCT = 1.0f;
constexpr uint32_t PUMP_RETRY_DELAY_MS = 1800000UL;
constexpr bool RELAY_ACTIVE_LOW = true;
