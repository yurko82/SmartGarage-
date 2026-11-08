/*
 * Smart Garage Infrastructure — ESP32 / ESP32-S3 Firmware
 * Hardware controller for Gate/Door Relay, Lighting, Fan, and Sensors.
 * Supports dual-channel communication: Wi-Fi HTTP API + USB Serial.
 * Reads Xiaomi LYWSD03MMC BLE climate sensors every 15 minutes.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLERemoteService.h>
#include <BLERemoteCharacteristic.h>
#include <Update.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <ELECHOUSE_CC1101_SRC_DRV.h>
#include <RCSwitch.h>
#include "esp_wifi.h"
#include "soc/rtc_cntl_reg.h"

// --- Wi-Fi Credentials (Configure via build_flags or local credentials.h) ---
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const uint8_t MODEM_BSSID[6] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

// --- Smart Garage Backend Server & MQTT Broker ---
const char* SERVER_TELEMETRY_URL = "http://192.168.100.198:5000/api/esp32/telemetry";
const char* MQTT_BROKER = "192.168.100.198";
const int MQTT_PORT = 1883;
const char* MQTT_CLIENT_ID = "SmartGarage-ESP32-S3";
const char* MQTT_USER = "smartgarage";
const char* MQTT_PASSWORD = "YOUR_MQTT_PASSWORD";

// ESP32 API Key for local HTTP control endpoints
const char* ESP32_API_KEY = "YOUR_ESP32_API_KEY";

// Web OTA is disabled by default for security to prevent unauthenticated remote firmware overwrite
#define ENABLE_WEB_OTA 0

const char* TOPIC_TELEMETRY = "smartgarage/esp32/telemetry";
const char* TOPIC_COMMAND   = "smartgarage/esp32/command";
const char* TOPIC_STATUS    = "smartgarage/esp32/status"; // LWT: online/offline

WiFiClient espMqttClient;
PubSubClient mqttClient(espMqttClient);
unsigned long lastMqttRetryTime = 0;

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

uint8_t g_pin_cc1101_sck  = PIN_CC1101_SCK;
uint8_t g_pin_cc1101_miso = PIN_CC1101_MISO;
uint8_t g_pin_cc1101_mosi = PIN_CC1101_MOSI;
uint8_t g_pin_cc1101_csn  = PIN_CC1101_CSN;
uint8_t g_pin_cc1101_gdo0 = PIN_CC1101_GDO0;

#ifndef PIN_RGB_LED
  #ifdef RGB_BUILTIN
    #define PIN_RGB_LED RGB_BUILTIN
  #else
    #define PIN_RGB_LED 48
  #endif
#endif

inline void setLedColor(uint8_t r, uint8_t g, uint8_t b) {
  neopixelWrite(PIN_RGB_LED, r, g, b);
}

#define RF_FREQUENCY     433.92
#define RF_PULSE_LENGTH  320
#define RF_CODE_LIGHT_ON   0xF1A101
#define RF_CODE_LIGHT_OFF  0xF1A102

// Hardware objects
Adafruit_AHTX0 aht;
bool ahtAvailable = false;
RCSwitch mySwitch = RCSwitch();
bool cc1101Available = false;
volatile unsigned long g_rf_edge_count = 0;

inline void enableRfReceive() {
  mySwitch.enableReceive(digitalPinToInterrupt(g_pin_cc1101_gdo0));
}

inline void disableRfReceive() {
  mySwitch.disableReceive();
}

// Режим безперервного сполучення (Pairing Mode) для надійного запису коду в реле
bool rfPairingActive = false;
unsigned long rfPairingEndTime = 0;
unsigned long lastPairSendTime = 0;

// Режим навчання/діагностики радіокодів (Learning Mode)
bool rfLearningActive = false;
unsigned long rfLearningEndTime = 0;

// 1-й поверх (локальний мікроклімат гаража AHT10)
float floor1_temp = 0.0;
float floor1_hum = 0.0;
bool floor1_valid = false;
unsigned long lastFloor1ReadTime = 0;

WebServer server(80);

// --- Device State ---
bool lightState = false;
bool fanState = false;
float temperature = 0.0;
float humidity = 0.0;

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 10000; // Telemetry push every 10 sec
unsigned long lastWifiCheckTime = 0;
unsigned long lastWifiRetryTime = 0;
unsigned long wifiDisconnectedSince = 0;
bool initialBlePollDone = false;
unsigned long lastBlePollTime = 0;
const unsigned long BLE_POLL_INTERVAL = 2UL * 60UL * 1000UL; // 2 min polling

// --- BLE Sensor Definitions ---
static BLEUUID envServiceUUID("ebe0ccb0-7a0a-4b0c-8a1a-6ff2997da3a6");
static BLEUUID envCharUUID("ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6");
static BLEUUID batServiceUUID((uint16_t)0x180f);
static BLEUUID batCharUUID((uint16_t)0x2a19);

struct BleFloorSensor {
  const char* mac;
  const char* name;
  const char* floor;
  float temp;
  float hum;
  int battery;
  bool online;
  unsigned long lastUpdated;
};

BleFloorSensor bleSensors[] = {
  {"A4:C1:38:EC:EC:6C", "2-й поверх", "floor2", 0.0, 0.0, 0, false, 0},
  {"A4:C1:38:CC:CA:49", "Підвал", "basement", 0.0, 0.0, 0, false, 0}
};
const int NUM_BLE_SENSORS = sizeof(bleSensors) / sizeof(bleSensors[0]);

BLEScan* pBLEScan = nullptr;

void initBLE() {
  if (pBLEScan == nullptr) {
    BLEDevice::init("SmartGarage-ESP32");
    pBLEScan = BLEDevice::getScan();
    pBLEScan->setActiveScan(true);
    pBLEScan->setInterval(100);
    pBLEScan->setWindow(99);
  }
}

class BleScanLogger: public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    String mac = advertisedDevice.getAddress().toString().c_str();
    mac.toUpperCase();
    String name = advertisedDevice.haveName() ? advertisedDevice.getName().c_str() : "";
    int rssi = advertisedDevice.getRSSI();
    String uuid = advertisedDevice.haveServiceUUID() ? advertisedDevice.getServiceUUID().toString().c_str() : "";
    Serial.printf("BLE_DEVICE:mac=%s|name=%s|rssi=%d|uuid=%s\n", mac.c_str(), name.c_str(), rssi, uuid.c_str());
  }
};

void runBleScan(int scanDuration = 15) {
  initBLE();
  Serial.printf("[BLE_SCAN] Starting active BLE scan for %d seconds...\n", scanDuration);
  
  BleScanLogger logger;
  pBLEScan->setAdvertisedDeviceCallbacks(&logger, false);
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);

  BLEScanResults foundDevices = pBLEScan->start(scanDuration, false);
  int count = foundDevices.getCount();
  Serial.printf("[BLE_SCAN] Completed. Total unique devices: %d\n", count);

  JsonDocument doc;
  doc["status"] = "ok";
  doc["type"] = "ble_scan";
  doc["count"] = count;
  JsonArray arr = doc["devices"].to<JsonArray>();

  for (int i = 0; i < count; i++) {
    BLEAdvertisedDevice dev = foundDevices.getDevice(i);
    JsonObject d = arr.add<JsonObject>();
    String mac = dev.getAddress().toString().c_str();
    mac.toUpperCase();
    String name = dev.haveName() ? dev.getName().c_str() : "";
    d["mac"] = mac;
    d["name"] = name;
    d["rssi"] = dev.getRSSI();
    if (dev.haveServiceUUID()) {
      d["service_uuid"] = dev.getServiceUUID().toString().c_str();
    }
  }

  String jsonResp;
  serializeJson(doc, jsonResp);
  Serial.println("RESP:" + jsonResp);

  pBLEScan->clearResults();
  pBLEScan->setAdvertisedDeviceCallbacks(nullptr, false);
}

void sendTelemetryToServer();

static BLEClient* pBleClient = nullptr;

bool readBleSensor(int idx) {
  if (idx < 0 || idx >= NUM_BLE_SENSORS) return false;
  BleFloorSensor &s = bleSensors[idx];
  initBLE();

  Serial.printf("[BLE] Connecting to %s (%s)...\n", s.name, s.mac);
  BLEAddress pAddress(s.mac);
  if (pBleClient == nullptr) {
    pBleClient = BLEDevice::createClient();
  }
  if (pBleClient == nullptr) return false;

  if (pBleClient->isConnected()) {
    pBleClient->disconnect();
    delay(100);
  }

  // Try PUBLIC address type first, then RANDOM
  bool connected = pBleClient->connect(pAddress, BLE_ADDR_TYPE_PUBLIC);
  if (!connected) {
    connected = pBleClient->connect(pAddress, BLE_ADDR_TYPE_RANDOM);
  }
  if (!connected) {
    Serial.println("[BLE] Connect failed.");
    s.online = false;
    return false;
  }

  bool gotData = false;
  // 1. Temperature & Humidity
  BLERemoteService* pRemoteService = pBleClient->getService(envServiceUUID);
  if (pRemoteService != nullptr) {
    BLERemoteCharacteristic* pRemoteChar = pRemoteService->getCharacteristic(envCharUUID);
    if (pRemoteChar != nullptr) {
      if (pRemoteChar->canRead()) {
        std::string value = pRemoteChar->readValue();
        if (value.length() >= 3) {
          int16_t temp_raw = (int16_t)((uint8_t)value[0] | ((uint8_t)value[1] << 8));
          s.temp = (float)temp_raw / 100.0f;
          s.hum = (float)(uint8_t)value[2];
          s.online = true;
          s.lastUpdated = millis();
          gotData = true;
          Serial.printf("[BLE] Read %s: %.1f C, %.0f %%\n", s.name, s.temp, s.hum);
        }
      }
      if (!gotData && pRemoteChar->canNotify()) {
        static float nTemp = 0;
        static float nHum = 0;
        static bool nReceived = false;
        nReceived = false;
        pRemoteChar->registerForNotify([](BLERemoteCharacteristic* pChar, uint8_t* pData, size_t length, bool isNotify) {
          if (length >= 3) {
            int16_t temp_raw = (int16_t)((uint8_t)pData[0] | ((uint8_t)pData[1] << 8));
            nTemp = (float)temp_raw / 100.0f;
            nHum = (float)(uint8_t)pData[2];
            nReceived = true;
          }
        });
        unsigned long tStart = millis();
        while (!nReceived && (millis() - tStart < 2500)) {
          server.handleClient();
          delay(50);
        }
        if (nReceived) {
          s.temp = nTemp;
          s.hum = nHum;
          s.online = true;
          s.lastUpdated = millis();
          gotData = true;
          Serial.printf("[BLE] Notify %s: %.1f C, %.0f %%\n", s.name, s.temp, s.hum);
        }
      }
    }
  }

  // 2. Battery
  BLERemoteService* pBatService = pBleClient->getService(batServiceUUID);
  if (pBatService != nullptr) {
    BLERemoteCharacteristic* pBatChar = pBatService->getCharacteristic(batCharUUID);
    if (pBatChar != nullptr && pBatChar->canRead()) {
      std::string batVal = pBatChar->readValue();
      if (batVal.length() >= 1) {
        s.battery = (int)(uint8_t)batVal[0];
        Serial.printf("[BLE] Battery %s: %d %%%\n", s.name, s.battery);
      }
    }
  }

  pBleClient->disconnect();

  if (!gotData) {
    s.online = false;
  }

  return gotData;
}

void pollAllBleSensors() {
  Serial.println("[BLE] Starting BLE climate poll...");
  for (int i = 0; i < NUM_BLE_SENSORS; i++) {
    server.handleClient();
    readBleSensor(i);
    server.handleClient();
    delay(100);
  }
  sendTelemetryToServer();
}

void readAht10() {
  if (!ahtAvailable) return;
  sensors_event_t hum_ev, temp_ev;
  if (aht.getEvent(&hum_ev, &temp_ev)) {
    floor1_temp = temp_ev.temperature;
    floor1_hum = hum_ev.relative_humidity;
    floor1_valid = true;
    lastFloor1ReadTime = millis();
    Serial.printf("[AHT10] Замір 1-й поверх: %.2f °C, %.1f %%\n", floor1_temp, floor1_hum);
  } else {
    Serial.println("[AHT10] Помилка зчитування даних.");
  }
}

void transmitRfCode(unsigned long code, unsigned int repeats = 10) {
  if (!cc1101Available) return;
  disableRfReceive();

  // 1. Налаштовуємо пін GDO0 на прийом модуляційних імпульсів від ESP32 (High-Z / Serial Data Input)
  ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x2E);

  // 2. Ініціалізуємо лінію передачі
  pinMode(PIN_CC1101_GDO0, OUTPUT);
  digitalWrite(PIN_CC1101_GDO0, LOW);

  // 3. Переводимо CC1101 в режим передачі TX
  ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
  delayMicroseconds(200);
  ELECHOUSE_cc1101.SpiStrobe(CC1101_STX);

  // 4. Очікуємо стабілізації та блокування частотного синтезатора (TX state = 0x13 / 19)
  unsigned long startWait = micros();
  while (((ELECHOUSE_cc1101.SpiReadStatus(0x35) & 0x1F) != 0x13) && (micros() - startWait < 5000)) {
    delayMicroseconds(50);
  }

  // 5. Передача 24-бітного ASK/OOK коду
  mySwitch.enableTransmit(PIN_CC1101_GDO0);
  mySwitch.setPulseLength(RF_PULSE_LENGTH);
  mySwitch.setRepeatTransmit(repeats);
  mySwitch.send(code, 24);
  mySwitch.disableTransmit();

  // 6. Повертаємо GDO0 в режим виходу демодулятора (0x0D = Serial Data Output)
  pinMode(PIN_CC1101_GDO0, INPUT);
  ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x0D);

  // 7. Повертаємо трансивер у режим очікування прийому RX
  ELECHOUSE_cc1101.SetRx();
  delayMicroseconds(500);
  enableRfReceive();

  Serial.printf("[RF433] Сигнал 0x%lX (%lu) надіслано в ефір (повторів=%u)\n", code, code, repeats);
}

void transmitRfLight(bool state) {
  unsigned long code = state ? RF_CODE_LIGHT_ON : RF_CODE_LIGHT_OFF;
  transmitRfCode(code, 10);
  Serial.printf("[RF433] Сигнал світла %s надіслано в ефір (код: 0x%lX)\n", state ? "ON" : "OFF", code);
}

void setRfCarrier(bool enable) {
  if (!cc1101Available) return;
  disableRfReceive();
  if (enable) {
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x2E);
    pinMode(PIN_CC1101_GDO0, OUTPUT);
    digitalWrite(PIN_CC1101_GDO0, HIGH); // Continuous carrier on 433.92 MHz
    ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
    delay(1);
    ELECHOUSE_cc1101.SpiStrobe(CC1101_STX);
    setLedColor(180, 0, 0); // Червоний: несуча активна
    Serial.println("RESP:{\"status\":\"ok\",\"carrier\":true,\"freq\":433.92}");
  } else {
    pinMode(PIN_CC1101_GDO0, INPUT);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x0D);
    ELECHOUSE_cc1101.SetRx();
    delayMicroseconds(500);
    enableRfReceive();
    setLedColor(0, 160, 255);
    Serial.println("RESP:{\"status\":\"ok\",\"carrier\":false}");
  }
}

bool autoDetectCC1101Pins() {
  // Тестуємо комбінації пінів SPI на випадок переплутаних дротів
  uint8_t perms[6][3] = {
    {11, 12, 13}, // 0: MOSI=11, SCK=12, MISO=13 (стандарт)
    {12, 11, 13}, // 1: MOSI=12, SCK=11, MISO=13 (SCK/MOSI переплутані)
    {13, 12, 11}, // 2: MOSI=13, SCK=12, MISO=11 (MISO/MOSI переплутані)
    {11, 13, 12}, // 3: MOSI=11, SCK=13, MISO=12
    {12, 13, 11}, // 4: MOSI=12, SCK=13, MISO=11
    {13, 11, 12}  // 5: MOSI=13, SCK=11, MISO=12
  };

  uint8_t csn_options[2] = {10, 7}; // Можлива перестановка CSN (10) та GDO0 (7)

  for (int c = 0; c < 2; c++) {
    uint8_t csn = csn_options[c];
    uint8_t gdo0 = (csn == 10) ? 7 : 10;

    pinMode(csn, OUTPUT);
    digitalWrite(csn, HIGH);

    for (int p = 0; p < 6; p++) {
      uint8_t mosi = perms[p][0];
      uint8_t sck  = perms[p][1];
      uint8_t miso = perms[p][2];

      pinMode(sck, OUTPUT);
      pinMode(mosi, OUTPUT);
      pinMode(miso, INPUT_PULLUP);
      digitalWrite(sck, LOW);
      digitalWrite(mosi, LOW);

      // Pull CSN low
      digitalWrite(csn, LOW);
      delayMicroseconds(50);

      // Send 0xF1 (Burst read VERSION)
      uint8_t cmd = 0xF1;
      for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, (cmd >> i) & 1);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
      }

      // Read 8 bits
      uint8_t ver = 0;
      for (int i = 7; i >= 0; i--) {
        digitalWrite(mosi, 0);
        delayMicroseconds(5);
        digitalWrite(sck, HIGH);
        delayMicroseconds(5);
        ver = (ver << 1) | digitalRead(miso);
        digitalWrite(sck, LOW);
        delayMicroseconds(5);
      }
      digitalWrite(csn, HIGH);
      delayMicroseconds(50);

      Serial.printf("[AUTO_DETECT] CSN=%d, MOSI=%d, SCK=%d, MISO=%d -> VER=0x%02X\n", csn, mosi, sck, miso, ver);

      if (ver == 0x14 || ver == 0x34 || (ver > 0 && ver != 0xFF && (ver & 0x0F) == 0x04)) {
        g_pin_cc1101_csn = csn;
        g_pin_cc1101_mosi = mosi;
        g_pin_cc1101_sck = sck;
        g_pin_cc1101_miso = miso;
        g_pin_cc1101_gdo0 = gdo0;
        Serial.printf("[AUTO_DETECT] УСПІХ! CC1101 (VER=0x%02X) знайдено на CSN=%d, MOSI=%d, SCK=%d, MISO=%d, GDO0=%d\n",
                      ver, csn, mosi, sck, miso, gdo0);
        return true;
      }
    }
  }
  return false;
}

void runRfDiagnostics() {
  disableRfReceive();

  bool detected = autoDetectCC1101Pins();

  pinMode(g_pin_cc1101_csn, OUTPUT);
  pinMode(g_pin_cc1101_sck, OUTPUT);
  pinMode(g_pin_cc1101_mosi, OUTPUT);
  pinMode(g_pin_cc1101_miso, INPUT_PULLUP);

  digitalWrite(g_pin_cc1101_csn, HIGH);
  digitalWrite(g_pin_cc1101_sck, LOW);
  digitalWrite(g_pin_cc1101_mosi, LOW);
  delayMicroseconds(50);
  int miso_idle = digitalRead(g_pin_cc1101_miso);

  digitalWrite(g_pin_cc1101_csn, LOW);
  delayMicroseconds(50);
  int miso_csn_low = digitalRead(g_pin_cc1101_miso);

  // Bit-bang 0xF1 (VERSION)
  uint8_t cmd = 0xF1;
  uint8_t status_byte = 0;
  for (int i = 7; i >= 0; i--) {
    digitalWrite(g_pin_cc1101_mosi, (cmd >> i) & 1);
    delayMicroseconds(5);
    digitalWrite(g_pin_cc1101_sck, HIGH);
    delayMicroseconds(5);
    status_byte = (status_byte << 1) | digitalRead(g_pin_cc1101_miso);
    digitalWrite(g_pin_cc1101_sck, LOW);
    delayMicroseconds(5);
  }

  uint8_t version_val = 0;
  for (int i = 7; i >= 0; i--) {
    digitalWrite(g_pin_cc1101_mosi, 0);
    delayMicroseconds(5);
    digitalWrite(g_pin_cc1101_sck, HIGH);
    delayMicroseconds(5);
    version_val = (version_val << 1) | digitalRead(g_pin_cc1101_miso);
    digitalWrite(g_pin_cc1101_sck, LOW);
    delayMicroseconds(5);
  }
  digitalWrite(g_pin_cc1101_csn, HIGH);

  if (detected) {
    ELECHOUSE_cc1101.setSpiPin(g_pin_cc1101_sck, g_pin_cc1101_miso, g_pin_cc1101_mosi, g_pin_cc1101_csn);
    ELECHOUSE_cc1101.setGDO0(g_pin_cc1101_gdo0);
    ELECHOUSE_cc1101.Init();
    ELECHOUSE_cc1101.setMHZ(RF_FREQUENCY);
    ELECHOUSE_cc1101.setModulation(2);
    ELECHOUSE_cc1101.setRxBW(270.0);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x0D);
    ELECHOUSE_cc1101.SetRx();
    enableRfReceive();
    cc1101Available = true;
    setLedColor(0, 160, 255);
  }

  Serial.printf("RESP:{\"diag\":\"spi_raw\",\"detected\":%s,\"csn\":%d,\"mosi\":%d,\"sck\":%d,\"miso\":%d,\"ver\":\"0x%02X\",\"miso_idle\":%d,\"miso_csn_low\":%d,\"gdo0\":%d,\"edges\":%lu}\n",
                detected ? "true" : "false", g_pin_cc1101_csn, g_pin_cc1101_mosi, g_pin_cc1101_sck, g_pin_cc1101_miso, version_val, miso_idle, miso_csn_low, digitalRead(g_pin_cc1101_gdo0), g_rf_edge_count);
}

void readSensors() {
  readAht10();
}

String buildTelemetryJson() {
  JsonDocument doc;
  doc["light"] = lightState;
  doc["fan"] = fanState;
  doc["distance_cm"] = nullptr;
  doc["car_present"] = nullptr;
  doc["car_sensor_installed"] = false;
  doc["motion_detected"] = nullptr;
  doc["motion_installed"] = false;
  doc["online"] = true;
  doc["wifi_ip"] = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "offline";

  float primTemp = 0.0;
  float primHum = 0.0;
  bool hasPrim = false;

  JsonObject fl = doc["floors"].to<JsonObject>();
  JsonObject f1 = fl["floor1"].to<JsonObject>();
  f1["name"] = "1-й поверх (Гараж)";
  f1["floor"] = "floor1";
  f1["mac"] = "ESP32-AHT10";
  bool f1_online = floor1_valid && (millis() - lastFloor1ReadTime < 60000UL);
  f1["online"] = f1_online;
  if (f1_online) {
    f1["temperature"] = round(floor1_temp * 10.0) / 10.0;
    f1["humidity"] = round(floor1_hum);
    f1["battery"] = nullptr;
    f1["last_read_ago_sec"] = (millis() - lastFloor1ReadTime) / 1000;
  } else {
    f1["temperature"] = nullptr;
    f1["humidity"] = nullptr;
    f1["battery"] = nullptr;
    f1["last_read_ago_sec"] = -1;
  }

  for (int i = 0; i < NUM_BLE_SENSORS; i++) {
    JsonObject item = fl[bleSensors[i].floor].to<JsonObject>();
    item["name"] = bleSensors[i].name;
    item["floor"] = bleSensors[i].floor;
    item["mac"] = bleSensors[i].mac;
    bool is_online = bleSensors[i].online && (bleSensors[i].lastUpdated > 0) && (millis() - bleSensors[i].lastUpdated < 15UL * 60UL * 1000UL);
    item["online"] = is_online;
    if (bleSensors[i].lastUpdated > 0) {
      item["last_read_ago_sec"] = (millis() - bleSensors[i].lastUpdated) / 1000;
    } else {
      item["last_read_ago_sec"] = -1;
    }
    if (is_online) {
      item["temperature"] = bleSensors[i].temp;
      item["humidity"] = bleSensors[i].hum;
      item["battery"] = bleSensors[i].battery;
      if (!hasPrim) {
        primTemp = bleSensors[i].temp;
        primHum = bleSensors[i].hum;
        hasPrim = true;
      }
    } else {
      item["temperature"] = nullptr;
      item["humidity"] = nullptr;
      item["battery"] = nullptr;
    }
  }

  doc["wifi_rssi"] = (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0;
  doc["uptime_sec"] = millis() / 1000;
  doc["poll_interval_sec"] = BLE_POLL_INTERVAL / 1000;

  if (f1_online) {
    doc["temperature"] = round(floor1_temp * 10.0) / 10.0;
    doc["humidity"] = round(floor1_hum);
  } else if (hasPrim) {
    doc["temperature"] = primTemp;
    doc["humidity"] = primHum;
  } else {
    doc["temperature"] = nullptr;
    doc["humidity"] = nullptr;
  }

  String jsonBody;
  serializeJson(doc, jsonBody);
  return jsonBody;
}

void sendTelemetryToServer() {
  String jsonBody = buildTelemetryJson();
  
  // Output to USB Serial
  Serial.print("TELEMETRY:");
  Serial.println(jsonBody);

  // Send over Wi-Fi HTTP if connected
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER_TELEMETRY_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", ESP32_API_KEY);
    http.setTimeout(2000);
    int httpCode = http.POST(jsonBody);
    if (httpCode > 0) {
      Serial.printf("[HTTP] Telemetry POST status: %d\n", httpCode);
    }
    http.end();
  }

  // Publish over MQTT if connected
  if (mqttClient.connected()) {
    mqttClient.publish(TOPIC_TELEMETRY, jsonBody.c_str(), false);
  }
}

void handleTelemetry() {
  readSensors();
  String response = buildTelemetryJson();
  server.send(200, "application/json", response);
}

bool isRequestAuthorized() {
  if (!ESP32_API_KEY || strlen(ESP32_API_KEY) == 0 ||
      strcmp(ESP32_API_KEY, "YOUR_ESP32_API_KEY") == 0 ||
      strcmp(ESP32_API_KEY, "placeholder") == 0) {
    return false; // Fail-closed when unset or default placeholder
  }
  if (server.hasHeader("X-API-Key") && server.header("X-API-Key") == ESP32_API_KEY) {
    return true;
  }
  if (server.hasArg("key") && server.arg("key") == ESP32_API_KEY) {
    return true;
  }
  return false;
}

void setLight(bool state) {
  lightState = state;
  digitalWrite(PIN_RELAY_LIGHT, state ? HIGH : LOW);
  transmitRfLight(state);
  Serial.printf("LIGHT_EVENT:%d\n", state ? 1 : 0);
}

void setFan(bool state) {
  fanState = state;
  digitalWrite(PIN_RELAY_FAN, state ? HIGH : LOW);
  Serial.printf("FAN_EVENT:%d\n", state ? 1 : 0);
}

void handleLightOn() {
  if (!isRequestAuthorized()) {
    server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
    return;
  }
  setLight(true);
  server.send(200, "application/json", "{\"status\":\"ok\",\"light\":true}");
}

void handleLightOff() {
  if (!isRequestAuthorized()) {
    server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
    return;
  }
  setLight(false);
  server.send(200, "application/json", "{\"status\":\"ok\",\"light\":false}");
}

void handleFanOn() {
  if (!isRequestAuthorized()) {
    server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
    return;
  }
  setFan(true);
  server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":true}");
}

void handleFanOff() {
  if (!isRequestAuthorized()) {
    server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
    return;
  }
  setFan(false);
  server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":false}");
}

// --- MQTT Support & Telemetry Publishing ---
void publishMqttTelemetry() {
  if (!mqttClient.connected()) return;
  String jsonBody = buildTelemetryJson();
  mqttClient.publish(TOPIC_TELEMETRY, jsonBody.c_str(), false);
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char message[length + 1];
  memcpy(message, payload, length);
  message[length] = '\0';
  Serial.printf("[MQTT RX] %s: %s\n", topic, message);

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, message);
  if (err) {
    Serial.printf("[MQTT] JSON parse error: %s\n", err.c_str());
    return;
  }

  const char* action = doc["action"] | "";
  if (strcmp(action, "light_on") == 0 || strcmp(action, "LIGHT_ON") == 0) {
    setLight(true);
  } else if (strcmp(action, "light_off") == 0 || strcmp(action, "LIGHT_OFF") == 0) {
    setLight(false);
  } else if (strcmp(action, "fan_on") == 0 || strcmp(action, "FAN_ON") == 0) {
    setFan(true);
  } else if (strcmp(action, "fan_off") == 0 || strcmp(action, "FAN_OFF") == 0) {
    setFan(false);
  } else if (strcmp(action, "get_telemetry") == 0) {
    readSensors();
  }

  // Publish updated state immediately
  publishMqttTelemetry();
}

void reconnectMqtt() {
  if (mqttClient.connected()) return;
  if (WiFi.status() != WL_CONNECTED) return;

  unsigned long now = millis();
  if (now - lastMqttRetryTime < 5000) return; // Non-blocking retry every 5 sec
  lastMqttRetryTime = now;

  Serial.print("[MQTT] Connecting to broker...");
  // LWT configuration: topic=smartgarage/esp32/status, qos=1, retain=true, payload="offline"
  if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASSWORD, TOPIC_STATUS, 1, true, "offline")) {
    Serial.println(" connected!");
    // Publish online status with retain
    mqttClient.publish(TOPIC_STATUS, "online", true);
    // Subscribe to command topic
    mqttClient.subscribe(TOPIC_COMMAND, 1);
    Serial.printf("[MQTT] Subscribed to %s (LWT configured on %s)\n", TOPIC_COMMAND, TOPIC_STATUS);
    // Publish initial telemetry
    publishMqttTelemetry();
  } else {
    Serial.printf(" failed, rc=%d. Will retry in 5s\n", mqttClient.state());
  }
}

void enterBootloader() {
  Serial.println("ENTERING_BOOTLOADER");
  delay(100);
  REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
  esp_restart();
}

void processSerialCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd.equalsIgnoreCase("LIGHT_ON") || cmd.equalsIgnoreCase("CMD:LIGHT_ON") || cmd == "{\"command\":\"light_on\"}") {
    setLight(true);
    Serial.println("RESP:{\"status\":\"ok\",\"light\":true}");
  } else if (cmd.equalsIgnoreCase("LIGHT_OFF") || cmd.equalsIgnoreCase("CMD:LIGHT_OFF") || cmd == "{\"command\":\"light_off\"}") {
    setLight(false);
    Serial.println("RESP:{\"status\":\"ok\",\"light\":false}");
  } else if (cmd.equalsIgnoreCase("LIGHT:BASEMENT:OFF") || cmd.equalsIgnoreCase("CMD:LIGHT:BASEMENT:OFF")) {
    transmitRfCode(RF_CODE_LIGHT_OFF, 10);
    Serial.println("RESP:{\"status\":\"ok\",\"zone\":\"basement_light\",\"action\":\"off\"}");
  } else if (cmd.equalsIgnoreCase("LIGHT:FLOOR2:OFF") || cmd.equalsIgnoreCase("CMD:LIGHT:FLOOR2:OFF")) {
    transmitRfCode(RF_CODE_LIGHT_OFF, 10);
    Serial.println("RESP:{\"status\":\"ok\",\"zone\":\"floor2_light\",\"action\":\"off\"}");
  } else if (cmd.equalsIgnoreCase("LIGHT:MAIN:OFF") || cmd.equalsIgnoreCase("CMD:LIGHT:MAIN:OFF")) {
    digitalWrite(PIN_RELAY_LIGHT, LOW);
    lightState = false;
    Serial.println("RESP:{\"status\":\"ok\",\"zone\":\"main_light\",\"action\":\"off\"}");
  } else if (cmd.startsWith("RF_LEARN:START") || cmd.startsWith("CMD:RF_LEARN:START")) {
    int colIdx = cmd.lastIndexOf(':');
    int durSec = 30;
    if (colIdx != -1 && colIdx < cmd.length() - 1) {
      durSec = cmd.substring(colIdx + 1).toInt();
      if (durSec <= 0) durSec = 30;
    }
    rfLearningActive = true;
    rfLearningEndTime = millis() + (unsigned long)durSec * 1000UL;
    setLedColor(140, 0, 200); // Фіолетовий: режим навчання
    Serial.printf("RESP:{\"status\":\"ok\",\"rf_learning\":true,\"duration_sec\":%d}\n", durSec);
  } else if (cmd.equalsIgnoreCase("RF_LEARN:STOP") || cmd.equalsIgnoreCase("CMD:RF_LEARN:STOP")) {
    rfLearningActive = false;
    setLedColor(0, 160, 255);
    Serial.println("RESP:{\"status\":\"ok\",\"rf_learning\":false}");
  } else if (cmd.equalsIgnoreCase("RF_LEARN:STATUS") || cmd.equalsIgnoreCase("CMD:RF_LEARN:STATUS")) {
    int remain = rfLearningActive ? (int)((rfLearningEndTime - millis()) / 1000) : 0;
    if (remain < 0) remain = 0;
    Serial.printf("RESP:{\"status\":\"ok\",\"rf_learning\":%s,\"remaining_sec\":%d}\n",
                  rfLearningActive ? "true" : "false", remain);
  } else if (cmd.equalsIgnoreCase("FAN_ON") || cmd.equalsIgnoreCase("CMD:FAN_ON") || cmd == "{\"command\":\"fan_on\"}") {
    setFan(true);
    Serial.println("RESP:{\"status\":\"ok\",\"fan\":true}");
  } else if (cmd.equalsIgnoreCase("FAN_OFF") || cmd.equalsIgnoreCase("CMD:FAN_OFF") || cmd == "{\"command\":\"fan_off\"}") {
    setFan(false);
    Serial.println("RESP:{\"status\":\"ok\",\"fan\":false}");
  } else if (cmd.startsWith("RF_SEND:") || cmd.startsWith("CMD:RF_SEND:")) {
    int colIdx = cmd.lastIndexOf(':');
    if (colIdx != -1 && colIdx < cmd.length() - 1) {
      unsigned long code = strtoul(cmd.substring(colIdx + 1).c_str(), NULL, 10);
      if (cc1101Available) {
        transmitRfCode(code, 10);
        Serial.printf("RESP:{\"status\":\"ok\",\"rf_sent\":%lu}\n", code);
      } else {
        Serial.println("RESP:{\"status\":\"error\",\"error\":\"CC1101 offline\"}");
      }
    }
  } else if (cmd.startsWith("RF_PAIR:") || cmd.startsWith("CMD:RF_PAIR:")) {
    int colIdx = cmd.lastIndexOf(':');
    int durSec = 30;
    if (colIdx != -1 && colIdx < cmd.length() - 1) {
      durSec = cmd.substring(colIdx + 1).toInt();
      if (durSec <= 0) durSec = 30;
    }
    rfPairingActive = true;
    rfPairingEndTime = millis() + (unsigned long)durSec * 1000UL;
    lastPairSendTime = 0;
    Serial.printf("RESP:{\"status\":\"ok\",\"pairing\":true,\"duration_sec\":%d,\"code\":%lu}\n", durSec, (unsigned long)RF_CODE_LIGHT_ON);
  } else if (cmd.equalsIgnoreCase("RF_PAIR_STOP") || cmd.equalsIgnoreCase("CMD:RF_PAIR_STOP")) {
    rfPairingActive = false;
    setLedColor(0, 160, 255);
    Serial.println("RESP:{\"status\":\"ok\",\"pairing\":false}");
  } else if (cmd.startsWith("RF_CARRIER:") || cmd.startsWith("CMD:RF_CARRIER:")) {
    int colIdx = cmd.lastIndexOf(':');
    int state = 1;
    if (colIdx != -1 && colIdx < cmd.length() - 1) {
      state = cmd.substring(colIdx + 1).toInt();
    }
    setRfCarrier(state != 0);
  } else if (cmd.equalsIgnoreCase("RF_DIAG") || cmd.equalsIgnoreCase("CMD:RF_DIAG")) {
    runRfDiagnostics();
  } else if (cmd.equalsIgnoreCase("GET_TELEMETRY") || cmd.equalsIgnoreCase("CMD:GET_TELEMETRY") || cmd == "{\"command\":\"get_telemetry\"}") {
    readSensors();
    Serial.println("RESP:" + buildTelemetryJson());
  } else if (cmd.equalsIgnoreCase("POLL_BLE") || cmd.equalsIgnoreCase("CMD:POLL_BLE") || cmd == "{\"command\":\"poll_ble\"}") {
    pollAllBleSensors();
    Serial.println("RESP:" + buildTelemetryJson());
  } else if (cmd.startsWith("SCAN_BLE") || cmd.startsWith("CMD:SCAN_BLE") || cmd == "{\"command\":\"scan_ble\"}") {
    int duration = 15;
    int colIdx = cmd.lastIndexOf(':');
    if (colIdx != -1 && colIdx < cmd.length() - 1) {
      int parsed = cmd.substring(colIdx + 1).toInt();
      if (parsed >= 3 && parsed <= 60) duration = parsed;
    }
    runBleScan(duration);
  } else if (cmd.equalsIgnoreCase("SCAN_WIFI") || cmd.equalsIgnoreCase("CMD:SCAN_WIFI")) {
    int n = WiFi.scanNetworks(false, true);
    Serial.printf("[WiFi Scan] Знайдено мереж: %d\n", n);
    for (int i = 0; i < n; i++) {
      Serial.printf("[WiFi Scan] #%d: SSID='%s', RSSI=%d dBm, Канал=%d, BSSID=%s\n",
                    i + 1, WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i), WiFi.BSSIDstr(i).c_str());
    }
  } else if (cmd.equalsIgnoreCase("ENTER_BOOTLOADER") || cmd.equalsIgnoreCase("CMD:ENTER_BOOTLOADER")) {
    enterBootloader();
  } else if (cmd.equalsIgnoreCase("PING") || cmd.equalsIgnoreCase("CMD:PING")) {
    Serial.println("PONG:ESP32_SMARTGARAGE");
  } else if (cmd.equalsIgnoreCase("TEST_LED") || cmd.equalsIgnoreCase("CMD:TEST_LED")) {
    setLedColor(60, 0, 0); delay(200);
    setLedColor(0, 60, 0); delay(200);
    setLedColor(0, 0, 60); delay(200);
    setLedColor(60, 30, 0); delay(200);
    setLedColor(0, 160, 255);
    Serial.println("RESP:{\"status\":\"ok\",\"led_tested\":true}");
  } else if (cmd.equalsIgnoreCase("IDENTIFY") || cmd.equalsIgnoreCase("CMD:IDENTIFY")) {
    Serial.println("RESP:{\"device\":\"esp32_smartgarage\",\"version\":\"1.0\",\"status\":\"ready\"}");
  } else if (cmd.equalsIgnoreCase("RF_STATUS") || cmd.equalsIgnoreCase("CMD:RF_STATUS")) {
    int rssi = cc1101Available ? ELECHOUSE_cc1101.getRssi() : -128;
    int mode = cc1101Available ? ELECHOUSE_cc1101.getMode() : -1;
    byte marc = cc1101Available ? ELECHOUSE_cc1101.SpiReadStatus(0x35) : 0;
    Serial.printf("RESP:{\"cc1101\":%s,\"rssi\":%d,\"mode\":%d,\"marc\":%d,\"edges\":%lu,\"freq\":433.92,\"pin_gdo0\":%d}\n",
                  cc1101Available ? "true" : "false", rssi, mode, marc, g_rf_edge_count, digitalRead(PIN_CC1101_GDO0));
  }
}

void checkWifiConnection() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiDisconnectedSince = 0;
    return;
  }

  // Якщо Wi-Fi не налаштовано або встановлено заглушку за замовчуванням, не виконуємо періодичних спроб
  if (strcmp(WIFI_SSID, "YOUR_WIFI_SSID") == 0) {
    return;
  }

  unsigned long now = millis();
  if (wifiDisconnectedSince == 0) {
    wifiDisconnectedSince = now;
  }

  // Контрольоване перепідключення кожні 20 секунд (без деструктивного WiFi.disconnect() та без перезавантаження чіпа)
  if (now - lastWifiRetryTime >= 20000) {
    lastWifiRetryTime = now;
    Serial.printf("[WiFi] Втрачено зв'язок (статус=%d, офлайн %lu с). Спроба перепідключення до %s...\n",
                  WiFi.status(), (now - wifiDisconnectedSince) / 1000, WIFI_SSID);
    if ((now - wifiDisconnectedSince) > 60000UL) {
      // Якщо офлайн понад 1 хвилину, ініціюємо пряме підключення до модему за BSSID
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6, MODEM_BSSID);
    } else {
      WiFi.reconnect();
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n[SmartGarage] ESP32-S3: Ініціалізація бездротового шлюзу мікроклімату...");

  pinMode(PIN_RELAY_DOOR, OUTPUT);
  pinMode(PIN_RELAY_LIGHT, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);

  digitalWrite(PIN_RELAY_DOOR, LOW);
  digitalWrite(PIN_RELAY_LIGHT, LOW);
  digitalWrite(PIN_RELAY_FAN, LOW);

  // 1. Ініціалізація I2C шини та датчика AHT10
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  if (aht.begin(&Wire)) {
    ahtAvailable = true;
    Serial.println("[AHT10] Датчик температури та вологості успішно знайдено.");
    readAht10();
  } else {
    Serial.println("[AHT10] Помилка: AHT10 не знайдено на шині I2C.");
  }

  // 2. Ініціалізація SPI шини та радіомодуля CC1101 (433.92 МГц) з автодетекцією пінів
  bool ccFound = autoDetectCC1101Pins();
  Serial.printf("[DBG] 1: ccFound=%d\n", ccFound);
  ELECHOUSE_cc1101.setSpiPin(g_pin_cc1101_sck, g_pin_cc1101_miso, g_pin_cc1101_mosi, g_pin_cc1101_csn);
  Serial.println("[DBG] 2: setSpiPin done");
  ELECHOUSE_cc1101.setGDO0(g_pin_cc1101_gdo0);
  Serial.println("[DBG] 3: setGDO0 done");
  if (ccFound || ELECHOUSE_cc1101.getCC1101()) {
    Serial.println("[DBG] 4: calling Init()");
    ELECHOUSE_cc1101.Init();
    Serial.println("[DBG] 5: Init() done");
    ELECHOUSE_cc1101.setMHZ(RF_FREQUENCY);
    Serial.println("[DBG] 6: setMHZ done");
    ELECHOUSE_cc1101.setModulation(2); // ASK/OOK
    Serial.println("[DBG] 7: setModulation done");
    ELECHOUSE_cc1101.setRxBW(270.0);
    Serial.println("[DBG] 8: setRxBW done");
    ELECHOUSE_cc1101.setPA(12);
    // Оптимізовані налаштування TI DN022 для стабільного прийому/передачі ASK/OOK
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_AGCCTRL2, 0x03);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_AGCCTRL1, 0x40);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_AGCCTRL0, 0x91);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_FREND1, 0x56);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_PKTCTRL0, 0x32);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x0D);
    Serial.println("[DBG] 9: SpiWriteReg done");
    ELECHOUSE_cc1101.SetRx();
    Serial.println("[DBG] 10: SetRx done");
    enableRfReceive();
    Serial.println("[DBG] 11: enableReceive done");
    mySwitch.setReceiveTolerance(80);
    cc1101Available = true;
    setLedColor(0, 160, 255); // Яскравий бірюзовий індикатор: режим очікування / слухання ефіру
    Serial.printf("[CC1101] Модуль 433.92 МГц успішно ініціалізовано (CSN=%d, MOSI=%d, SCK=%d, MISO=%d, GDO0=%d).\n",
                  g_pin_cc1101_csn, g_pin_cc1101_mosi, g_pin_cc1101_sck, g_pin_cc1101_miso, g_pin_cc1101_gdo0);
  } else {
    setLedColor(40, 0, 0); // Червоний індикатор: CC1101 не відповідає
    Serial.println("[CC1101] Помилка: CC1101 не відповідає за жодною комбінацією пінів.");
  }

  // 3. Ініціалізація BLE на старті для коректного налаштування апаратного арбітра Coexistence
  initBLE();
  Serial.println("[BLE] Підсистему BLE успішно ініціалізовано.");

  // 4. Налаштування радіотракту Wi-Fi (з режимом співіснування MIN_MODEM)
  WiFi.mode(WIFI_STA);
  esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
  WiFi.setAutoReconnect(true);

  // Фіксована конфігурація IP для миттєвого закріплення без затримок DHCP
  IPAddress staticIP(192, 168, 100, 114);
  IPAddress gateway(192, 168, 100, 1);
  IPAddress subnet(255, 255, 255, 0);
  IPAddress dns1(192, 168, 100, 1);
  IPAddress dns2(8, 8, 8, 8);

  if (!WiFi.config(staticIP, gateway, subnet, dns1, dns2)) {
    Serial.println("[WiFi] Не вдалося налаштувати статичний IP, використовується DHCP.");
  } else {
    Serial.println("[WiFi] Налаштовано статичний IP: 192.168.100.114 (Шлюз: 192.168.100.1)");
  }

  // Обробник мережевих подій Wi-Fi
  WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t info) {
    switch (event) {
      case ARDUINO_EVENT_WIFI_STA_START:
        Serial.println("[WiFi] Режим Station успішно запущено.");
        break;
      case ARDUINO_EVENT_WIFI_STA_CONNECTED:
        Serial.printf("[WiFi] З'єднано з Wi-Fi точкою '%s'!\n", WIFI_SSID);
        break;
      case ARDUINO_EVENT_WIFI_STA_GOT_IP:
        Serial.printf("[WiFi] Отримано IP: %s (Шлюз: %s, Сигнал RSSI: %d dBm)\n",
                      WiFi.localIP().toString().c_str(),
                      WiFi.gatewayIP().toString().c_str(),
                      WiFi.RSSI());
        break;
      case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
        Serial.printf("[WiFi] Відключено від мережі. Код причини: %d\n", info.wifi_sta_disconnected.reason);
        break;
      default:
        break;
    }
  });

  // Сканування ефіру 2.4GHz
  if (strcmp(WIFI_SSID, "YOUR_WIFI_SSID") != 0) {
    Serial.println("[WiFi] Сканування ефіру 2.4GHz для пошуку SmGrg...");
    int n = WiFi.scanNetworks(false, true);
    Serial.printf("[WiFi] Знайдено мереж: %d\n", n);
    int targetChannel = 6;
    bool foundSmGrg = false;
    for (int i = 0; i < n; i++) {
      Serial.printf("[WiFi Мережа] #%d: SSID='%s', RSSI=%d dBm, Канал=%d, BSSID=%s\n",
                    i + 1, WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i), WiFi.BSSIDstr(i).c_str());
      if (WiFi.SSID(i) == WIFI_SSID) {
        targetChannel = WiFi.channel(i);
        foundSmGrg = true;
      }
    }

    Serial.printf("[WiFi] Підключення до мережі SSID: %s (Канал: %d)...\n", WIFI_SSID, targetChannel);
    if (foundSmGrg) {
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD, targetChannel);
    } else {
      Serial.println("[WiFi] Пряме підключення до модему за BSSID (A0:62:56:5C:9B:FC, Канал: 6)...");
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6, MODEM_BSSID);
    }

    unsigned long startWifi = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - startWifi < 15000)) {
      delay(400);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("\n[WiFi] Успішно підключено! IP: %s, RSSI: %d dBm\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      wifiDisconnectedSince = 0;
    } else {
      Serial.printf("\n[WiFi] Первинний таймаут з'єднання (статус=%d). Фонове підключення активне.\n",
                    WiFi.status());
      wifiDisconnectedSince = millis();
    }
  } else {
    Serial.println("[WiFi] Wi-Fi SSID не налаштовано. Працює локальний режим USB Serial.");
  }

  // HTTP API Endpoints
  server.on("/api/ping", HTTP_GET, []() {
    server.send(200, "application/json", "{\"status\":\"ok\",\"pong\":true,\"wifi_ip\":\"192.168.100.114\"}");
  });

  server.on("/api/telemetry", HTTP_GET, handleTelemetry);
  server.on("/api/ble/sensors", HTTP_GET, []() {
    JsonDocument doc;
    JsonObject fl = doc["floors"].to<JsonObject>();
    for (int i = 0; i < NUM_BLE_SENSORS; i++) {
      JsonObject item = fl[bleSensors[i].floor].to<JsonObject>();
      item["name"] = bleSensors[i].name;
      item["temperature"] = bleSensors[i].temp;
      item["humidity"] = bleSensors[i].hum;
      item["battery"] = bleSensors[i].battery;
      item["online"] = bleSensors[i].online;
      item["mac"] = bleSensors[i].mac;
    }
    String resp;
    serializeJson(doc, resp);
    server.send(200, "application/json", resp);
  });
  server.on("/api/ble/refresh", HTTP_POST, []() {
    if (!isRequestAuthorized()) {
      server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
      return;
    }
    pollAllBleSensors();
    server.send(200, "application/json", "{\"status\":\"ok\",\"message\":\"BLE sensors polled by ESP32\"}");
  });
  server.on("/api/ble/scan", HTTP_GET, []() {
    if (!isRequestAuthorized()) {
      server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
      return;
    }
    int duration = 15;
    if (server.hasArg("duration")) {
      int d = server.arg("duration").toInt();
      if (d >= 3 && d <= 60) duration = d;
    }
    runBleScan(duration);
    server.send(200, "application/json", "{\"status\":\"ok\",\"message\":\"BLE scan completed\"}");
  });
  server.on("/api/light/on", HTTP_POST, handleLightOn);
  server.on("/api/light/off", HTTP_POST, handleLightOff);
  server.on("/api/fan/on", HTTP_POST, handleFanOn);
  server.on("/api/fan/off", HTTP_POST, handleFanOff);

  // Web OTA (Disabled by default for security)
#if ENABLE_WEB_OTA
  server.on("/update", HTTP_POST, []() {
    if (!isRequestAuthorized()) {
      server.send(401, "text/plain", "Unauthorized");
      return;
    }
    server.sendHeader("Connection", "close");
    server.send(200, "text/plain", (Update.hasError()) ? "FAIL" : "OK");
    ESP.restart();
  }, []() {
    HTTPUpload& upload = server.upload();
    if (upload.status == UPLOAD_FILE_START) {
      Serial.printf("Update: %s\n", upload.filename.c_str());
      if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
        Update.printError(Serial);
      }
    } else if (upload.status == UPLOAD_FILE_WRITE) {
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
        Update.printError(Serial);
      }
    } else if (upload.status == UPLOAD_FILE_END) {
      if (Update.end(true)) {
        Serial.printf("Update Success: %uB\n", upload.totalSize);
      } else {
        Update.printError(Serial);
      }
    }
  });
#else
  server.on("/update", HTTP_POST, []() {
    server.send(403, "application/json", "{\"status\":\"error\",\"error\":\"Web OTA updates disabled for security. Use USB serial flashing.\"}");
  });
#endif

  // Ініціалізація MQTT Client
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(1024);

  server.begin();
  Serial.println("[SmartGarage] Система готова до роботи (HTTP + MQTT + Serial).");
}

void loop() {
  server.handleClient();

  // Підтримка з'єднання MQTT та обробка пакетів
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      reconnectMqtt();
    }
    mqttClient.loop();
  }

  // Обробка команд з USB Serial
  while (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    processSerialCommand(input);
  }

  // Обробка режиму безперервного сполучення (Pairing Mode)
  if (rfPairingActive) {
    if (millis() < rfPairingEndTime) {
      if (millis() - lastPairSendTime >= 120) {
        lastPairSendTime = millis();
        transmitRfCode(RF_CODE_LIGHT_ON, 4);
        setLedColor(140, 0, 140); // Фіолетовий індикатор: активна постійна трансляція коду
      }
    } else {
      rfPairingActive = false;
      setLedColor(0, 160, 255);
      Serial.println("[RF_PAIR] Режим безперервного сполучення завершено (таймаут).");
    }
  }

  // Перевірка таймауту режиму навчання
  if (rfLearningActive && millis() > rfLearningEndTime) {
    rfLearningActive = false;
    setLedColor(0, 160, 255);
    Serial.println("[RF_LEARN] Режим навчання завершено (таймаут).");
  }

  // Обробка вхідних 433 МГц радіосигналів (перехоплення / слухання вимикачів)
  static unsigned long lastEdgeCount = 0;
  static unsigned long lastRssiCheck = 0;
  static unsigned long ledResetTime = 0;
  static int currentLedState = 0; // 0 = cyan (idle), 1 = orange (detected carrier), 2 = green (decoded)

  if (cc1101Available) {
    // 1. Стандартний декодер RCSwitch
    if (mySwitch.available()) {
      unsigned long val = mySwitch.getReceivedValue();
      unsigned int bits = mySwitch.getReceivedBitlength();
      unsigned int proto = mySwitch.getReceivedProtocol();
      unsigned int delay = mySwitch.getReceivedDelay();
      mySwitch.resetAvailable();
      g_rf_raw_capture.ready = false;

      if (val != 0) {
        Serial.printf("[RF_RX] Код: %lu (0x%lX) | Біти: %u | Протокол: %u | Затримка: %u\n", val, val, bits, proto, delay);
        if (rfLearningActive) {
          Serial.printf("[RF_LEARN] {\"code\":%lu,\"hex\":\"0x%lX\",\"bits\":%u,\"proto\":%u,\"delay\":%u,\"mode\":\"rcswitch\"}\n",
                        val, val, bits, proto, delay);
        }
        setLedColor(0, 200, 0); // Яскравий зелений: 100% успішно розпізнано!
        currentLedState = 2;
        ledResetTime = millis() + 1500;
      }
    }
    // 2. Адаптивний декодер універсальних ASK/OOK пульсів (EV1527 / PT2262 / 24..32 біт)
    else if (g_rf_raw_capture.ready) {
      unsigned int count = g_rf_raw_capture.count;
      unsigned int sync = g_rf_raw_capture.sync;

      unsigned long decodedCode = 0;
      unsigned int decodedBits = 0;
      bool decodeSuccess = false;

      if (count >= 16) {
        // У кожному біті 2 імпульси (High + Low)
        for (unsigned int i = 1; i + 1 < count; i += 2) {
          unsigned int t1 = g_rf_raw_capture.timings[i];
          unsigned int t2 = g_rf_raw_capture.timings[i+1];
          decodedCode <<= 1;
          if (t1 < t2) {
            // Короткий High, довгий Low -> '0'
          } else {
            // Довгий High, короткий Low -> '1'
            decodedCode |= 1;
          }
          decodedBits++;
          if (decodedBits >= 32) break;
        }
        if (decodedBits >= 16) {
          decodeSuccess = true;
        }
      }

      if (decodeSuccess) {
        Serial.printf("[RF_RX_ADAPTIVE] Код: %lu (0x%lX) | Біти: %u | Синхропауза: %u us | Імпульсів: %u\n",
                      decodedCode, decodedCode, decodedBits, sync, count);
        if (rfLearningActive) {
          Serial.printf("[RF_LEARN] {\"code\":%lu,\"hex\":\"0x%lX\",\"bits\":%u,\"sync\":%u,\"pulses\":%u,\"mode\":\"adaptive\"}\n",
                        decodedCode, decodedCode, decodedBits, sync, count);
        }
        setLedColor(0, 200, 0); // Яскравий зелений: адаптивно розпізнано!
        currentLedState = 2;
        ledResetTime = millis() + 1500;
      } else {
        Serial.printf("[RF_RX_RAW] Спіймано невідомий пакет (%u імпульсів, sync=%u us)\n", count, sync);
        setLedColor(140, 70, 0); // Помаранчевий
        currentLedState = 1;
        ledResetTime = millis() + 600;
      }

      // Виводимо виміри імпульсів у мікросекундах для детального аналізу
      Serial.print("[RF_RAW_DATA] ");
      for (unsigned int i = 0; i < count && i < 35; i++) {
        Serial.printf("%u ", g_rf_raw_capture.timings[i]);
      }
      Serial.println();

      g_rf_raw_capture.ready = false;
    }

    // 3. Моніторинг активності 433 МГц радіоефіру за рівнем RSSI (детекція передавача)
    if (millis() - lastRssiCheck >= 60) {
      lastRssiCheck = millis();
      int curRssi = ELECHOUSE_cc1101.getRssi();
      if (curRssi >= -65) {
        unsigned long curEdges = g_rf_edge_count;
        unsigned long dEdges = curEdges - lastEdgeCount;
        lastEdgeCount = curEdges;
        Serial.printf("[RF_DETECT] Сплеск 433 МГц сигналу: %d dBm (GDO0=%d, імпульсів=%lu)\n", curRssi, digitalRead(PIN_CC1101_GDO0), dEdges);
        if (currentLedState != 2 || millis() > ledResetTime) {
          setLedColor(160, 80, 0); // Помаранчевий спалах: детекція радіосигналу в ефірі
          currentLedState = 1;
          ledResetTime = millis() + 500;
        }
      } else {
        lastEdgeCount = g_rf_edge_count;
      }
    }
  }

  // Повернення світлодіода до бірюзового (cyan) режиму очікування
  if (currentLedState != 0 && millis() > ledResetTime) {
    currentLedState = 0;
    setLedColor(0, 160, 255); // Яскравий бірюзовий (Cyan)
  }

  // Періодичне зчитування BLE-датчиків вимкнено з фонового циклу (виконується за запитом CMD:POLL_BLE),
  // щоб не блокувати мікроконтролер та забезпечити миттєву реакцію 433 МГц радіосніфера.

  // Періодичне оновлення даних AHT10 кожні 10 секунд
  if (ahtAvailable && (millis() - lastFloor1ReadTime > 10000)) {
    readAht10();
  }

  // Періодична телеметрія кожні 10 секунд
  if (millis() - lastTelemetryTime > TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();
    sendTelemetryToServer();
  }

  // Контроль та підтримка Wi-Fi з'єднання кожні 15 секунд
  if (millis() - lastWifiCheckTime > 15000) {
    lastWifiCheckTime = millis();
    checkWifiConnection();
  }
}
