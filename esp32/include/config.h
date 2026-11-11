#pragma once

#include <Arduino.h>

#define FIRMWARE_VERSION "2.0.0"

// --- Підключення локальних секретів (якщо є) ---
#if __has_include("secrets.h")
#include "secrets.h"
#endif

// --- Значення за замовчуванням для Wi-Fi ---
#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_WIFI_SSID"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#endif

#ifndef MODEM_BSSID_DEFINED
const uint8_t DEFAULT_MODEM_BSSID[6] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
#endif

// --- Smart Garage Backend Server & MQTT Broker ---
#ifndef SERVER_TELEMETRY_URL
#define SERVER_TELEMETRY_URL "http://192.168.100.198:5000/api/esp32/telemetry"
#endif

#ifndef MQTT_BROKER
#define MQTT_BROKER "192.168.100.198"
#endif

#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif

#ifndef MQTT_CLIENT_ID
#define MQTT_CLIENT_ID "SmartGarage-ESP32-S3"
#endif

#ifndef MQTT_USER
#define MQTT_USER "smartgarage"
#endif

#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD "YOUR_MQTT_PASSWORD"
#endif

#ifndef ESP32_API_KEY
#define ESP32_API_KEY "YOUR_ESP32_API_KEY"
#endif

#define ENABLE_WEB_OTA 0

#define TOPIC_TELEMETRY "smartgarage/esp32/telemetry"
#define TOPIC_COMMAND   "smartgarage/esp32/command"
#define TOPIC_STATUS    "smartgarage/esp32/status"

// --- Pin Definitions (Relays, I2C Sensor & SPI Transceiver) ---
#if CONFIG_IDF_TARGET_ESP32S3
#define PIN_RELAY_DOOR   4   // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  5   // Garage Lighting Relay
#define PIN_RELAY_FAN    6   // Exhaust Fan Relay
#else
#define PIN_RELAY_DOOR   25  // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  26  // Garage Lighting Relay
#define PIN_RELAY_FAN    27  // Exhaust Fan Relay
#endif

// AHT10 (I2C) & CC1101 (SPI 433MHz) Pins
#define PIN_I2C_SDA      8
#define PIN_I2C_SCL      9

#define PIN_CC1101_SCK   12
#define PIN_CC1101_MISO  13
#define PIN_CC1101_MOSI  11
#define PIN_CC1101_CSN   10
#define PIN_CC1101_GDO0  7

#ifndef PIN_RGB_LED
  #ifdef RGB_BUILTIN
    #define PIN_RGB_LED RGB_BUILTIN
  #else
    #define PIN_RGB_LED 48
  #endif
#endif

// --- Радіочастотні константи (433.92 МГц) ---
#define RF_FREQUENCY       433.92
#define RF_PULSE_LENGTH    320
#define RF_CODE_LIGHT_ON   0xF1A101
#define RF_CODE_LIGHT_OFF  0xF1A102

// --- Таймінги та інтервали ---
#define TELEMETRY_INTERVAL (10000UL)              // 10 секунд
#define BLE_POLL_INTERVAL  (2UL * 60UL * 1000UL)  // 2 хвилини

// --- MAC-адреси BLE датчиків ---
#ifndef BLE_MAC_FLOOR2
#define BLE_MAC_FLOOR2 "00:11:22:33:44:04"
#endif

#ifndef BLE_MAC_BASEMENT
#define BLE_MAC_BASEMENT "00:11:22:33:44:03"
#endif