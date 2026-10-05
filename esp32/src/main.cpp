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
#include "soc/rtc_cntl_reg.h"

// --- Wi-Fi Credentials (4G Modem Network) ---
const char* WIFI_SSID = "SmGrg";
const char* WIFI_PASSWORD = "1234567890";

// --- Smart Garage Backend Server & MQTT Broker ---
const char* SERVER_TELEMETRY_URL = "http://192.168.100.198:5000/api/esp32/telemetry";
const char* MQTT_BROKER = "192.168.100.198";
const int MQTT_PORT = 1883;
const char* MQTT_CLIENT_ID = "SmartGarage-ESP32-S3";
const char* MQTT_USER = "smartgarage";
const char* MQTT_PASSWORD = "smartgarage_secret";

const char* TOPIC_TELEMETRY = "smartgarage/esp32/telemetry";
const char* TOPIC_COMMAND   = "smartgarage/esp32/command";
const char* TOPIC_STATUS    = "smartgarage/esp32/status"; // LWT: online/offline

WiFiClient espMqttClient;
PubSubClient mqttClient(espMqttClient);
unsigned long lastMqttRetryTime = 0;

// --- Pin Definitions (Relays only, physical sensors uninstalled) ---
#if CONFIG_IDF_TARGET_ESP32S3
#define PIN_RELAY_DOOR   4   // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  5   // Garage Lighting Relay
#define PIN_RELAY_FAN    6   // Exhaust Fan Relay
#else
#define PIN_RELAY_DOOR   25  // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  26  // Garage Lighting Relay
#define PIN_RELAY_FAN    27  // Exhaust Fan Relay
#endif

WebServer server(80);

// --- Device State ---
bool lightState = false;
bool fanState = false;
String doorState = "closed";
float temperature = 0.0;
float humidity = 0.0;

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 10000; // Telemetry push every 10 sec
unsigned long lastWifiCheckTime = 0;
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
    readBleSensor(i);
    delay(200);
  }
  sendTelemetryToServer();
}

void readSensors() {
  // Physical gate/gas sensors uninstalled; ESP32 focuses on BLE climate gateway
}

String buildTelemetryJson() {
  JsonDocument doc;
  doc["door"] = doorState;
  doc["door_installed"] = false;
  doc["light"] = lightState;
  doc["fan"] = fanState;
  doc["distance_cm"] = nullptr;
  doc["car_present"] = nullptr;
  doc["car_sensor_installed"] = false;
  doc["motion_detected"] = nullptr;
  doc["motion_installed"] = false;
  doc["gas_ppm"] = nullptr;
  doc["gas_installed"] = false;
  doc["online"] = true;
  doc["wifi_ip"] = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "offline";

  float primTemp = 0.0;
  float primHum = 0.0;
  bool hasPrim = false;

  JsonObject fl = doc["floors"].to<JsonObject>();
  JsonObject f1 = fl["floor1"].to<JsonObject>();
  f1["name"] = "1-й поверх (Гараж)";
  f1["floor"] = "floor1";
  f1["temperature"] = nullptr;
  f1["humidity"] = nullptr;
  f1["battery"] = nullptr;
  f1["online"] = false;

  for (int i = 0; i < NUM_BLE_SENSORS; i++) {
    JsonObject item = fl[bleSensors[i].floor].to<JsonObject>();
    item["name"] = bleSensors[i].name;
    item["floor"] = bleSensors[i].floor;
    item["mac"] = bleSensors[i].mac;
    bool is_online = bleSensors[i].online && (bleSensors[i].lastUpdated > 0) && (millis() - bleSensors[i].lastUpdated < 15UL * 60UL * 1000UL);
    item["online"] = is_online;
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

  if (hasPrim) {
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

void triggerDoorPulse(const String& targetState) {
  digitalWrite(PIN_RELAY_DOOR, HIGH);
  delay(500);
  digitalWrite(PIN_RELAY_DOOR, LOW);
  doorState = targetState;
  Serial.println("DOOR_EVENT:" + doorState);
}

void handleDoorOpen() {
  triggerDoorPulse("open");
  server.send(200, "application/json", "{\"status\":\"ok\",\"door\":\"open\"}");
}

void handleDoorClose() {
  triggerDoorPulse("closed");
  server.send(200, "application/json", "{\"status\":\"ok\",\"door\":\"closed\"}");
}

void handleLightOn() {
  lightState = true;
  digitalWrite(PIN_RELAY_LIGHT, HIGH);
  Serial.println("LIGHT_EVENT:1");
  server.send(200, "application/json", "{\"status\":\"ok\",\"light\":true}");
}

void handleLightOff() {
  lightState = false;
  digitalWrite(PIN_RELAY_LIGHT, LOW);
  Serial.println("LIGHT_EVENT:0");
  server.send(200, "application/json", "{\"status\":\"ok\",\"light\":false}");
}

void handleFanOn() {
  fanState = true;
  digitalWrite(PIN_RELAY_FAN, HIGH);
  Serial.println("FAN_EVENT:1");
  server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":true}");
}

void handleFanOff() {
  fanState = false;
  digitalWrite(PIN_RELAY_FAN, LOW);
  Serial.println("FAN_EVENT:0");
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
  if (strcmp(action, "open_door") == 0 || strcmp(action, "OPEN") == 0) {
    triggerDoorPulse("open");
  } else if (strcmp(action, "close_door") == 0 || strcmp(action, "CLOSE") == 0) {
    triggerDoorPulse("closed");
  } else if (strcmp(action, "toggle_door") == 0) {
    triggerDoorPulse(doorState == "closed" ? "open" : "closed");
  } else if (strcmp(action, "light_on") == 0 || strcmp(action, "LIGHT_ON") == 0) {
    lightState = true;
    digitalWrite(PIN_RELAY_LIGHT, HIGH);
    Serial.println("LIGHT_EVENT:1");
  } else if (strcmp(action, "light_off") == 0 || strcmp(action, "LIGHT_OFF") == 0) {
    lightState = false;
    digitalWrite(PIN_RELAY_LIGHT, LOW);
    Serial.println("LIGHT_EVENT:0");
  } else if (strcmp(action, "fan_on") == 0 || strcmp(action, "FAN_ON") == 0) {
    fanState = true;
    digitalWrite(PIN_RELAY_FAN, HIGH);
    Serial.println("FAN_EVENT:1");
  } else if (strcmp(action, "fan_off") == 0 || strcmp(action, "FAN_OFF") == 0) {
    fanState = false;
    digitalWrite(PIN_RELAY_FAN, LOW);
    Serial.println("FAN_EVENT:0");
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

  if (cmd.equalsIgnoreCase("DOOR_OPEN") || cmd.equalsIgnoreCase("CMD:DOOR_OPEN") || cmd == "{\"command\":\"door_open\"}") {
    triggerDoorPulse("open");
    Serial.println("RESP:{\"status\":\"ok\",\"door\":\"open\"}");
  } else if (cmd.equalsIgnoreCase("DOOR_CLOSE") || cmd.equalsIgnoreCase("CMD:DOOR_CLOSE") || cmd == "{\"command\":\"door_close\"}") {
    triggerDoorPulse("closed");
    Serial.println("RESP:{\"status\":\"ok\",\"door\":\"closed\"}");
  } else if (cmd.equalsIgnoreCase("LIGHT_ON") || cmd.equalsIgnoreCase("CMD:LIGHT_ON") || cmd == "{\"command\":\"light_on\"}") {
    handleLightOn();
    Serial.println("RESP:{\"status\":\"ok\",\"light\":true}");
  } else if (cmd.equalsIgnoreCase("LIGHT_OFF") || cmd.equalsIgnoreCase("CMD:LIGHT_OFF") || cmd == "{\"command\":\"light_off\"}") {
    handleLightOff();
    Serial.println("RESP:{\"status\":\"ok\",\"light\":false}");
  } else if (cmd.equalsIgnoreCase("FAN_ON") || cmd.equalsIgnoreCase("CMD:FAN_ON") || cmd == "{\"command\":\"fan_on\"}") {
    handleFanOn();
    Serial.println("RESP:{\"status\":\"ok\",\"fan\":true}");
  } else if (cmd.equalsIgnoreCase("FAN_OFF") || cmd.equalsIgnoreCase("CMD:FAN_OFF") || cmd == "{\"command\":\"fan_off\"}") {
    handleFanOff();
    Serial.println("RESP:{\"status\":\"ok\",\"fan\":false}");
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
  } else if (cmd.equalsIgnoreCase("ENTER_BOOTLOADER") || cmd.equalsIgnoreCase("CMD:ENTER_BOOTLOADER")) {
    enterBootloader();
  } else if (cmd.equalsIgnoreCase("PING")) {
    Serial.println("PONG");
  }
}

void checkWifiConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[WiFi] Disconnected (status=%d). Reconnecting to %s...\n", WiFi.status(), WIFI_SSID);
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n[SmartGarage] ESP32-S3 Initializing as Primary Wireless Climate Gateway...");

  pinMode(PIN_RELAY_DOOR, OUTPUT);
  pinMode(PIN_RELAY_LIGHT, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);

  digitalWrite(PIN_RELAY_DOOR, LOW);
  digitalWrite(PIN_RELAY_LIGHT, LOW);
  digitalWrite(PIN_RELAY_FAN, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  Serial.printf("[WiFi] Connecting to SSID: %s...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startWifi = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - startWifi < 15000)) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] Connected! IP: %s, RSSI: %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.printf("\n[WiFi] Connect timed out (status=%d). Will continue in background.\n", WiFi.status());
  }

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
    pollAllBleSensors();
    server.send(200, "application/json", "{\"status\":\"ok\",\"message\":\"BLE sensors polled by ESP32\"}");
  });
  server.on("/api/ble/scan", HTTP_GET, []() {
    int duration = 15;
    if (server.hasArg("duration")) {
      int d = server.arg("duration").toInt();
      if (d >= 3 && d <= 60) duration = d;
    }
    runBleScan(duration);
    server.send(200, "application/json", "{\"status\":\"ok\",\"message\":\"BLE scan completed\"}");
  });
  server.on("/api/door/open", HTTP_POST, handleDoorOpen);
  server.on("/api/door/close", HTTP_POST, handleDoorClose);
  server.on("/api/light/on", HTTP_POST, handleLightOn);
  server.on("/api/light/off", HTTP_POST, handleLightOff);
  server.on("/api/fan/on", HTTP_POST, handleFanOn);
  server.on("/api/fan/off", HTTP_POST, handleFanOff);

  // Web OTA
  server.on("/update", HTTP_POST, []() {
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

  // Initialize MQTT Client
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(1024);

  server.begin();
  Serial.println("[SmartGarage] System Ready (HTTP + MQTT + Serial).");
}

void loop() {
  server.handleClient();

  // Maintain MQTT connection and process incoming packets
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      reconnectMqtt();
    }
    mqttClient.loop();
  }

  // Handle incoming Serial commands from USB
  while (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    processSerialCommand(input);
  }

  // Initial BLE poll 10 sec after startup
  if (!lastBlePollTime && millis() > 10000) {
    lastBlePollTime = millis();
    pollAllBleSensors();
  }

  // Scheduled BLE sensor poll (every 2 min)
  if (millis() - lastBlePollTime > BLE_POLL_INTERVAL) {
    lastBlePollTime = millis();
    pollAllBleSensors();
  }

  // Periodic Telemetry every 10 sec
  if (millis() - lastTelemetryTime > TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();
    sendTelemetryToServer();
  }

  // Check Wi-Fi every 15 seconds
  if (millis() - lastWifiCheckTime > 15000) {
    lastWifiCheckTime = millis();
    checkWifiConnection();
  }
}
