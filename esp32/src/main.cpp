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
#include "soc/rtc_cntl_reg.h"

// --- Wi-Fi Credentials (4G Modem Network) ---
const char* WIFI_SSID = "SmGrg";
const char* WIFI_PASSWORD = "1234567890";

// --- Smart Garage Backend Server ---
const char* SERVER_TELEMETRY_URL = "http://192.168.100.198:5000/api/esp32/telemetry";

// --- Pin Definitions (Compatible with ESP32-S3 and standard ESP32) ---
#if CONFIG_IDF_TARGET_ESP32S3
#define PIN_RELAY_DOOR   4   // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  5   // Garage Lighting Relay
#define PIN_RELAY_FAN    6   // Exhaust Fan Relay
#define PIN_PIR_MOTION   7   // PIR Motion Sensor Input
#define PIN_DOOR_SWITCH  8   // Reed magnetic switch (Door Closed sensor)
#define PIN_TRIG         9   // Ultrasonic HC-SR04 Trig
#define PIN_ECHO         10  // Ultrasonic HC-SR04 Echo
#define PIN_GAS_ANALOG   1   // MQ Gas/Smoke Sensor Analog Input (ADC1)
#else
#define PIN_RELAY_DOOR   25  // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  26  // Garage Lighting Relay
#define PIN_RELAY_FAN    27  // Exhaust Fan Relay
#define PIN_PIR_MOTION   14  // PIR Motion Sensor Input
#define PIN_DOOR_SWITCH  33  // Reed magnetic switch (Door Closed sensor)
#define PIN_TRIG         12  // Ultrasonic HC-SR04 Trig
#define PIN_ECHO         13  // Ultrasonic HC-SR04 Echo
#define PIN_GAS_ANALOG   34  // MQ Gas/Smoke Sensor Analog Input
#endif

WebServer server(80);

// --- Device State ---
bool lightState = false;
bool fanState = false;
String doorState = "closed";
float temperature = 21.3;
float humidity = 63.0;
int distanceCm = 240;
bool carPresent = false;
bool motionDetected = false;
int gasLevel = 35;

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 5000; // Telemetry push every 5 sec
unsigned long lastWifiCheckTime = 0;
unsigned long lastBlePollTime = 0;
const unsigned long BLE_POLL_INTERVAL = 15UL * 60UL * 1000UL; // 15 min

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
  {"A4:C1:38:EC:EC:6C", "2-й поверх", "floor2", 21.3, 63.0, 99, true, 0},
  {"A4:C1:38:CC:CA:49", "Підвал", "basement", 21.2, 65.0, 99, true, 0}
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

bool readBleSensor(int idx) {
  if (idx < 0 || idx >= NUM_BLE_SENSORS) return false;
  BleFloorSensor &s = bleSensors[idx];
  
  initBLE();
  Serial.print("[BLE] Connecting to ");
  Serial.print(s.name);
  Serial.print(" (");
  Serial.print(s.mac);
  Serial.println(")...");

  BLEAddress pAddress(s.mac);
  BLEClient* pClient = BLEDevice::createClient();
  if (pClient == nullptr) return false;

  // timeout
  bool connected = pClient->connect(pAddress);
  if (!connected) {
    Serial.println("[BLE] Connect failed.");
    delete pClient;
    return false;
  }

  // 1. Temperature & Humidity
  BLERemoteService* pRemoteService = pClient->getService(envServiceUUID);
  if (pRemoteService != nullptr) {
    BLERemoteCharacteristic* pRemoteChar = pRemoteService->getCharacteristic(envCharUUID);
    if (pRemoteChar != nullptr) {
      bool gotData = false;
      if (pRemoteChar->canRead()) {
        std::string value = pRemoteChar->readValue();
        if (value.length() >= 3) {
          int16_t temp_raw = (int16_t)((uint8_t)value[0] | ((uint8_t)value[1] << 8));
          s.temp = (float)temp_raw / 100.0f;
          s.hum = (float)(uint8_t)value[2];
          s.online = true;
          s.lastUpdated = millis();
          gotData = true;
          Serial.printf("[BLE] Read %s: %.1f C, %.0f %%%\n", s.name, s.temp, s.hum);
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
        while (!nReceived && (millis() - tStart < 3000)) {
          delay(50);
        }
        if (nReceived) {
          s.temp = nTemp;
          s.hum = nHum;
          s.online = true;
          s.lastUpdated = millis();
          Serial.printf("[BLE] Notify %s: %.1f C, %.0f %%%\n", s.name, s.temp, s.hum);
        }
      }
    }
  }

  // 2. Battery
  BLERemoteService* pBatService = pClient->getService(batServiceUUID);
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

  pClient->disconnect();
  delete pClient;

  if (idx == 0 && s.online) {
    temperature = s.temp;
    humidity = s.hum;
  }

  return true;
}

void pollAllBleSensors() {
  Serial.println("[BLE] Starting 15-min scheduled BLE sensor poll...");
  for (int i = 0; i < NUM_BLE_SENSORS; i++) {
    readBleSensor(i);
    delay(300);
  }
}

// Measure distance via Ultrasonic HC-SR04
int readDistance() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  long duration = pulseIn(PIN_ECHO, HIGH, 30000);
  if (duration == 0) return 250;
  return duration * 0.034 / 2;
}

void readSensors() {
  distanceCm = readDistance();
  carPresent = (distanceCm > 10 && distanceCm < 180);
  motionDetected = (digitalRead(PIN_PIR_MOTION) == HIGH);
  int doorSwitch = digitalRead(PIN_DOOR_SWITCH);
  doorState = (doorSwitch == LOW) ? "closed" : "open";
  gasLevel = analogRead(PIN_GAS_ANALOG);
}

String buildTelemetryJson() {
  JsonDocument doc;
  doc["door"] = doorState;
  doc["light"] = lightState;
  doc["fan"] = fanState;
  doc["temperature"] = temperature;
  doc["humidity"] = humidity;
  doc["distance_cm"] = distanceCm;
  doc["car_present"] = carPresent;
  doc["motion_detected"] = motionDetected;
  doc["gas_ppm"] = gasLevel;
  doc["online"] = true;
  doc["wifi_ip"] = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "offline";

  JsonObject fl = doc["floors"].to<JsonObject>();
  JsonObject f1 = fl["floor1"].to<JsonObject>();
  f1["name"] = "1-й поверх (Гараж)";
  f1["floor"] = "floor1";
  f1["temperature"] = temperature;
  f1["humidity"] = humidity;
  f1["battery"] = 100;
  f1["online"] = true;

  for (int i = 0; i < NUM_BLE_SENSORS; i++) {
    JsonObject item = fl[bleSensors[i].floor].to<JsonObject>();
    item["name"] = bleSensors[i].name;
    item["floor"] = bleSensors[i].floor;
    item["temperature"] = bleSensors[i].temp;
    item["humidity"] = bleSensors[i].hum;
    item["battery"] = bleSensors[i].battery;
    item["online"] = bleSensors[i].online;
    item["mac"] = bleSensors[i].mac;
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
    http.setTimeout(1500);
    http.POST(jsonBody);
    http.end();
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
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n[SmartGarage] ESP32-S3 Initializing with 15-min BLE reader...");

  pinMode(PIN_RELAY_DOOR, OUTPUT);
  pinMode(PIN_RELAY_LIGHT, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);
  pinMode(PIN_PIR_MOTION, INPUT);
  pinMode(PIN_DOOR_SWITCH, INPUT_PULLUP);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);

  digitalWrite(PIN_RELAY_DOOR, LOW);
  digitalWrite(PIN_RELAY_LIGHT, LOW);
  digitalWrite(PIN_RELAY_FAN, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

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

  server.begin();
  Serial.println("[SmartGarage] System Ready.");
}

void loop() {
  server.handleClient();

  // Handle incoming Serial commands from USB
  while (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    processSerialCommand(input);
  }

  // Initial BLE poll 5 sec after startup
  if (!lastBlePollTime && millis() > 5000) {
    lastBlePollTime = millis();
    pollAllBleSensors();
  }

  // 15-min scheduled BLE sensor poll
  if (millis() - lastBlePollTime > BLE_POLL_INTERVAL) {
    lastBlePollTime = millis();
    pollAllBleSensors();
  }

  // Periodic Telemetry every 5 sec
  if (millis() - lastTelemetryTime > TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();
    readSensors();
    sendTelemetryToServer();
  }

  // Check Wi-Fi every 30 seconds
  if (millis() - lastWifiCheckTime > 30000) {
    lastWifiCheckTime = millis();
    checkWifiConnection();
  }
}
