/*
 * Smart Garage Infrastructure — ESP32 Firmware
 * Hardware controller for Gate/Door Relay, Lighting, Fan, and Sensors.
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- Wi-Fi Credentials ---
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// --- Smart Garage Backend Server ---
const char* SERVER_TELEMETRY_URL = "http://10.166.150.31:5000/api/esp32/telemetry";

// --- Pin Definitions ---
#define PIN_RELAY_DOOR   25  // Garage Door Relay (Pulse/Trigger)
#define PIN_RELAY_LIGHT  26  // Garage Lighting Relay
#define PIN_RELAY_FAN    27  // Exhaust Fan Relay
#define PIN_PIR_MOTION   14  // PIR Motion Sensor Input
#define PIN_DOOR_SWITCH  33  // Reed magnetic switch (Door Closed sensor)
#define PIN_TRIG         12  // Ultrasonic HC-SR04 Trig
#define PIN_ECHO         13  // Ultrasonic HC-SR04 Echo
#define PIN_GAS_ANALOG   34  // MQ Gas/Smoke Sensor Analog Input

WebServer server(80);

// --- Device State ---
bool lightState = false;
bool fanState = false;
String doorState = "closed";
float temperature = 22.0;
float humidity = 45.0;
int distanceCm = 250;
bool carPresent = false;
bool motionDetected = false;
int gasLevel = 40;

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 10000; // Push every 10 sec

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

void sendTelemetryToServer() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(SERVER_TELEMETRY_URL);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<300> doc;
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

  String jsonBody;
  serializeJson(doc, jsonBody);
  http.POST(jsonBody);
  http.end();
}

void handleTelemetry() {
  readSensors();
  StaticJsonDocument<300> doc;
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

  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}

void handleDoorOpen() {
  digitalWrite(PIN_RELAY_DOOR, HIGH);
  delay(500);
  digitalWrite(PIN_RELAY_DOOR, LOW);
  doorState = "open";
  server.send(200, "application/json", "{\"status\":\"ok\",\"door\":\"open\"}");
}

void handleDoorClose() {
  digitalWrite(PIN_RELAY_DOOR, HIGH);
  delay(500);
  digitalWrite(PIN_RELAY_DOOR, LOW);
  doorState = "closed";
  server.send(200, "application/json", "{\"status\":\"ok\",\"door\":\"closed\"}");
}

void handleLightOn() {
  lightState = true;
  digitalWrite(PIN_RELAY_LIGHT, HIGH);
  server.send(200, "application/json", "{\"status\":\"ok\",\"light\":true}");
}

void handleLightOff() {
  lightState = false;
  digitalWrite(PIN_RELAY_LIGHT, LOW);
  server.send(200, "application/json", "{\"status\":\"ok\",\"light\":false}");
}

void handleFanOn() {
  fanState = true;
  digitalWrite(PIN_RELAY_FAN, HIGH);
  server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":true}");
}

void handleFanOff() {
  fanState = false;
  digitalWrite(PIN_RELAY_FAN, LOW);
  server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":false}");
}

void setup() {
  Serial.begin(115200);

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
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nESP32 Connected! IP: " + WiFi.localIP().toString());

  server.on("/api/telemetry", HTTP_GET, handleTelemetry);
  server.on("/api/door/open", HTTP_POST, handleDoorOpen);
  server.on("/api/door/close", HTTP_POST, handleDoorClose);
  server.on("/api/light/on", HTTP_POST, handleLightOn);
  server.on("/api/light/off", HTTP_POST, handleLightOff);
  server.on("/api/fan/on", HTTP_POST, handleFanOn);
  server.on("/api/fan/off", HTTP_POST, handleFanOff);

  server.begin();
}

void loop() {
  server.handleClient();

  if (millis() - lastTelemetryTime > TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();
    readSensors();
    sendTelemetryToServer();
  }
}
