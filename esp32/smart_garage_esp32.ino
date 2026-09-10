/*
 * Smart Garage Infrastructure — ESP32 / ESP32-S3 Firmware
 * Hardware controller for Gate/Door Relay, Lighting, Fan, and Sensors.
 * Supports dual-channel communication: Wi-Fi HTTP API + USB Serial.
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

// --- Wi-Fi Credentials (4G Modem Network) ---
const char* WIFI_SSID = "4G-UFI-BFC";
const char* WIFI_PASSWORD = "09876543210";

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
float temperature = 21.5;
float humidity = 48.0;
int distanceCm = 240;
bool carPresent = false;
bool motionDetected = false;
int gasLevel = 35;

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 5000; // Telemetry push every 5 sec
unsigned long lastWifiCheckTime = 0;

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

// --- BLE Scanner ---
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

String runBLEScan(int scanDurationSeconds = 4) {
  initBLE();
  Serial.print("[BLE] Scanning airwaves for ");
  Serial.print(scanDurationSeconds);
  Serial.println("s...");

  BLEScanResults* foundDevices = pBLEScan->start(scanDurationSeconds, false);

  JsonDocument doc;
  doc["status"] = "ok";
  doc["source"] = "esp32";
  doc["count"] = foundDevices->getCount();
  JsonArray array = doc["devices"].to<JsonArray>();

  for (int i = 0; i < foundDevices->getCount(); i++) {
    BLEAdvertisedDevice dev = foundDevices->getDevice(i);
    JsonObject obj = array.add<JsonObject>();
    obj["address"] = dev.getAddress().toString().c_str();
    obj["name"] = dev.getName().empty() ? "Unknown" : dev.getName().c_str();
    obj["rssi"] = dev.getRSSI();
    if (dev.haveServiceUUID()) {
      obj["service_uuid"] = dev.getServiceUUID().toString().c_str();
    }
  }

  pBLEScan->clearResults();

  String output;
  serializeJson(doc, output);
  return output;
}

void handleBleScan() {
  String response = runBLEScan(4);
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
  } else if (cmd.equalsIgnoreCase("SCAN_BLE") || cmd.equalsIgnoreCase("CMD:SCAN_BLE") || cmd == "{\"command\":\"scan_ble\"}") {
    String scanJson = runBLEScan(4);
    Serial.println("RESP:" + scanJson);
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
  Serial.println("\n[SmartGarage] ESP32-S3 Initializing...");

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
  server.on("/api/ble/scan", HTTP_GET, handleBleScan);
  server.on("/api/ble/scan", HTTP_POST, handleBleScan);
  server.on("/api/door/open", HTTP_POST, handleDoorOpen);
  server.on("/api/door/close", HTTP_POST, handleDoorClose);
  server.on("/api/light/on", HTTP_POST, handleLightOn);
  server.on("/api/light/off", HTTP_POST, handleLightOff);
  server.on("/api/fan/on", HTTP_POST, handleFanOn);
  server.on("/api/fan/off", HTTP_POST, handleFanOff);


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

  // Periodic Telemetry
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
