#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "esp_wifi.h"
#include "config.h"

class NetworkManager {
public:
    void init();
    void update();
    void processSerialCommand(String cmd);
    void sendTelemetryToServer();

private:
    void setupWebServer();
    void checkWifiConnection();
    void reconnectMqtt();
    void publishMqttTelemetry();
    bool isRequestAuthorized();
    String buildTelemetryJson();

    WebServer server{80};
    WiFiClient espMqttClient;
    PubSubClient mqttClient{espMqttClient};

    unsigned long lastTelemetryTime = 0;
    unsigned long lastWifiCheckTime = 0;
    unsigned long lastWifiRetryTime = 0;
    unsigned long lastMqttRetryTime = 0;
    unsigned long wifiDisconnectedSince = 0;
};

extern NetworkManager netManager;