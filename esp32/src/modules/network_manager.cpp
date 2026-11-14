#include "network_manager.h"
#include "gate_controller.h"
#include "sensors.h"
#include "rf_subsystem.h"
#include "ble_scanner.h"

NetworkManager netManager;

bool NetworkManager::isRequestAuthorized() {
    if (!ESP32_API_KEY || strlen(ESP32_API_KEY) == 0 ||
        strcmp(ESP32_API_KEY, "YOUR_ESP32_API_KEY") == 0 ||
        strcmp(ESP32_API_KEY, "placeholder") == 0) {
        return false;
    }
    if (server.hasHeader("X-API-Key") && server.header("X-API-Key") == ESP32_API_KEY) {
        return true;
    }
    if (server.hasArg("key") && server.arg("key") == ESP32_API_KEY) {
        return true;
    }
    return false;
}

String NetworkManager::buildTelemetryJson() {
    JsonDocument doc;
    doc["door"] = "unknown";
    doc["door_is_open"] = false;
    doc["door_is_closed"] = false;
    doc["light"] = gateCtrl.isLightOn();
    doc["fan"] = gateCtrl.isFanOn();
    doc["distance_cm"] = nullptr;
    doc["car_present"] = nullptr;
    doc["car_sensor_installed"] = false;
    doc["motion_detected"] = nullptr;
    doc["motion_installed"] = false;
    doc["online"] = true;
    doc["wifi_ip"] = (WiFi.status() == WL_CONNECTED) ? WiFi.localIP().toString() : "offline";

    float primTemp = 0.0f;
    float primHum = 0.0f;
    bool hasPrim = false;

    JsonObject fl = doc["floors"].to<JsonObject>();
    JsonObject f1 = fl["floor1"].to<JsonObject>();
    f1["name"] = "1-й поверх (Гараж)";
    f1["floor"] = "floor1";
    f1["mac"] = "ESP32-AHT10";
    bool f1_online = sensorsMod.isValid();
    f1["online"] = f1_online;
    if (f1_online) {
        f1["temperature"] = round(sensorsMod.getTemperature() * 10.0f) / 10.0f;
        f1["humidity"] = round(sensorsMod.getHumidity());
        f1["battery"] = nullptr;
        f1["last_read_ago_sec"] = 0;
    } else {
        f1["temperature"] = nullptr;
        f1["humidity"] = nullptr;
        f1["battery"] = nullptr;
        f1["last_read_ago_sec"] = -1;
    }

    for (int i = 0; i < bleScanner.getSensorCount(); i++) {
        const BleFloorSensor& s = bleScanner.getSensor(i);
        JsonObject item = fl[s.floor].to<JsonObject>();
        item["name"] = s.name;
        item["floor"] = s.floor;
        item["mac"] = s.mac;
        bool is_online = s.online && (s.lastUpdated > 0) && (millis() - s.lastUpdated < 15UL * 60UL * 1000UL);
        item["online"] = is_online;
        if (s.lastUpdated > 0) {
            item["last_read_ago_sec"] = (millis() - s.lastUpdated) / 1000;
        } else {
            item["last_read_ago_sec"] = -1;
        }
        if (is_online) {
            item["temperature"] = s.temp;
            item["humidity"] = s.hum;
            item["battery"] = s.battery;
            if (!hasPrim) {
                primTemp = s.temp;
                primHum = s.hum;
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
        doc["temperature"] = round(sensorsMod.getTemperature() * 10.0f) / 10.0f;
        doc["humidity"] = round(sensorsMod.getHumidity());
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

void NetworkManager::sendTelemetryToServer() {
    String jsonBody = buildTelemetryJson();
    Serial.print("TELEMETRY:");
    Serial.println(jsonBody);

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
}

void NetworkManager::publishMqttTelemetry() {
    if (!mqttClient.connected()) return;
    String jsonBody = buildTelemetryJson();
    mqttClient.publish(TOPIC_TELEMETRY, jsonBody.c_str(), false);
}

static void onMqttMessage(char* topic, byte* payload, unsigned int length) {
    char msg[128];
    unsigned int copyLen = (length < sizeof(msg) - 1) ? length : sizeof(msg) - 1;
    memcpy(msg, payload, copyLen);
    msg[copyLen] = '\0';
    netManager.processSerialCommand(String(msg));
}

void NetworkManager::reconnectMqtt() {
    if (mqttClient.connected()) return;
    unsigned long now = millis();
    if (now - lastMqttRetryTime < 5000) return;
    lastMqttRetryTime = now;

    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(onMqttMessage);

    if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASSWORD, TOPIC_STATUS, 1, true, "offline")) {
        mqttClient.publish(TOPIC_STATUS, "online", true);
        mqttClient.subscribe(TOPIC_COMMAND);
        Serial.println("[MQTT] З'єднання успішно встановлено!");
    }
}

void NetworkManager::setupWebServer() {
    server.on("/", HTTP_GET, [this]() {
        server.send(200, "text/plain", "SmartGarage ESP32-S3 Gateway v2.0.0 Online");
    });

    server.on("/api/status", HTTP_GET, [this]() {
        String resp = buildTelemetryJson();
        server.send(200, "application/json", resp);
    });

    server.on("/api/telemetry", HTTP_GET, [this]() {
        String resp = buildTelemetryJson();
        server.send(200, "application/json", resp);
    });

    server.on("/api/door/trigger", HTTP_POST, [this]() {
        if (!isRequestAuthorized()) {
            server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
            return;
        }
        gateCtrl.triggerDoor();
        server.send(200, "application/json", "{\"status\":\"ok\",\"action\":\"door_triggered\"}");
    });

    server.on("/api/light/on", HTTP_POST, [this]() {
        if (!isRequestAuthorized()) {
            server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
            return;
        }
        gateCtrl.setLight(true);
        rfSubsystem.transmitLight(true);
        server.send(200, "application/json", "{\"status\":\"ok\",\"light\":true}");
    });

    server.on("/api/light/off", HTTP_POST, [this]() {
        if (!isRequestAuthorized()) {
            server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
            return;
        }
        gateCtrl.setLight(false);
        rfSubsystem.transmitLight(false);
        server.send(200, "application/json", "{\"status\":\"ok\",\"light\":false}");
    });

    server.on("/api/fan/on", HTTP_POST, [this]() {
        if (!isRequestAuthorized()) {
            server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
            return;
        }
        gateCtrl.setFan(true);
        server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":true}");
    });

    server.on("/api/fan/off", HTTP_POST, [this]() {
        if (!isRequestAuthorized()) {
            server.send(401, "application/json", "{\"status\":\"error\",\"error\":\"Unauthorized\"}");
            return;
        }
        gateCtrl.setFan(false);
        server.send(200, "application/json", "{\"status\":\"ok\",\"fan\":false}");
    });

    server.on("/api/rf/diagnostics", HTTP_GET, [this]() {
        String diag = rfSubsystem.getDiagnosticsJson();
        server.send(200, "application/json", diag);
    });

    server.on("/api/ble/scan", HTTP_GET, [this]() {
        bleScanner.runActiveScan(10);
        server.send(200, "application/json", "{\"status\":\"ok\",\"message\":\"scan_completed\"}");
    });

    server.begin();
}

void NetworkManager::checkWifiConnection() {
    unsigned long now = millis();
    if (now - lastWifiCheckTime < 5000) return;
    lastWifiCheckTime = now;

    if (WiFi.status() == WL_CONNECTED) {
        wifiDisconnectedSince = 0;
        return;
    }

    if (wifiDisconnectedSince == 0) {
        wifiDisconnectedSince = now;
    }

    if (now - lastWifiRetryTime >= 10000) {
        lastWifiRetryTime = now;
        Serial.println("[WiFi] Перепідключення до мережі...");
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
}

void NetworkManager::init() {
    WiFi.mode(WIFI_STA);
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
    WiFi.setAutoReconnect(true);

    IPAddress staticIP(192, 168, 100, 114);
    IPAddress gateway(192, 168, 100, 1);
    IPAddress subnet(255, 255, 255, 0);
    WiFi.config(staticIP, gateway, subnet);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    setupWebServer();
}

void NetworkManager::update() {
    server.handleClient();
    checkWifiConnection();

    if (WiFi.status() == WL_CONNECTED) {
        if (!mqttClient.connected()) {
            reconnectMqtt();
        }
        mqttClient.loop();
    }

    unsigned long now = millis();
    if (now - lastTelemetryTime >= TELEMETRY_INTERVAL) {
        lastTelemetryTime = now;
        sendTelemetryToServer();
        publishMqttTelemetry();
    }
}

void NetworkManager::processSerialCommand(String cmd) {
    cmd.trim();
    if (cmd.length() == 0) return;

    if (cmd.equalsIgnoreCase("LIGHT_ON") || cmd.equalsIgnoreCase("CMD:LIGHT_ON") || cmd == "{\"command\":\"light_on\"}") {
        gateCtrl.setLight(true);
        rfSubsystem.transmitLight(true);
        Serial.println("RESP:{\"status\":\"ok\",\"light\":true}");
    } else if (cmd.equalsIgnoreCase("LIGHT_OFF") || cmd.equalsIgnoreCase("CMD:LIGHT_OFF") || cmd == "{\"command\":\"light_off\"}") {
        gateCtrl.setLight(false);
        rfSubsystem.transmitLight(false);
        Serial.println("RESP:{\"status\":\"ok\",\"light\":false}");
    } else if (cmd.equalsIgnoreCase("FAN_ON") || cmd.equalsIgnoreCase("CMD:FAN_ON") || cmd == "{\"command\":\"fan_on\"}") {
        gateCtrl.setFan(true);
        Serial.println("RESP:{\"status\":\"ok\",\"fan\":true}");
    } else if (cmd.equalsIgnoreCase("FAN_OFF") || cmd.equalsIgnoreCase("CMD:FAN_OFF") || cmd == "{\"command\":\"fan_off\"}") {
        gateCtrl.setFan(false);
        Serial.println("RESP:{\"status\":\"ok\",\"fan\":false}");
    } else if (cmd.startsWith("RF_SEND:") || cmd.startsWith("CMD:RF_SEND:")) {
        int colIdx = cmd.lastIndexOf(':');
        if (colIdx != -1 && colIdx < cmd.length() - 1) {
            unsigned long code = strtoul(cmd.substring(colIdx + 1).c_str(), NULL, 0);
            RfTxResult res = rfSubsystem.transmitCode(code, 10);
            Serial.printf("RESP:{\"status\":\"%s\",\"rf_sent\":%lu,\"hex\":\"0x%lX\",\"tx_ok\":%s,\"tx_state\":%d,\"rx_restored\":%s}\n",
                          res.tx_ok ? "ok" : "error",
                          code, code,
                          res.tx_ok ? "true" : "false",
                          res.tx_state,
                          res.rx_restored ? "true" : "false");
        }
    } else if (cmd.startsWith("RF_REG:") || cmd.startsWith("CMD:RF_REG:")) {
        int prefixLen = cmd.startsWith("CMD:") ? 11 : 7;
        String args = cmd.substring(prefixLen);
        args.trim();
        int sep = args.indexOf(':');
        if (sep != -1) {
            uint8_t addr = (uint8_t)strtoul(args.substring(0, sep).c_str(), NULL, 16);
            uint8_t val  = (uint8_t)strtoul(args.substring(sep + 1).c_str(), NULL, 16);
            const uint8_t allowed[] = {0x10, 0x11, 0x12, 0x1B, 0x1C, 0x1D, 0x21, 0x22};
            bool isAllowed = false;
            for (uint8_t a : allowed) {
                if (a == addr) { isAllowed = true; break; }
            }
            if (isAllowed) {
                rfSubsystem.writeRegister(addr, val);
                uint8_t readBack = rfSubsystem.readRegister(addr);
                Serial.printf("RESP:{\"status\":\"ok\",\"reg\":\"0x%02X\",\"val\":\"0x%02X\",\"readback\":\"0x%02X\"}\n",
                              addr, val, readBack);
            } else {
                Serial.printf("RESP:{\"status\":\"error\",\"error\":\"address_not_allowed\",\"reg\":\"0x%02X\"}\n", addr);
            }
        }
    } else if (cmd.startsWith("RF_PAIR:") || cmd.startsWith("CMD:RF_PAIR:")) {
        int prefixLen = cmd.startsWith("CMD:") ? 12 : 8;
        String args = cmd.substring(prefixLen);
        args.trim();
        int durSec = 15;
        unsigned long pairCode = RF_CODE_LIGHT_ON;
        int sep = args.indexOf(':');
        if (sep != -1) {
            pairCode = strtoul(args.substring(0, sep).c_str(), NULL, 0);
            durSec = args.substring(sep + 1).toInt();
        } else if (args.length() > 0) {
            unsigned long val = strtoul(args.c_str(), NULL, 0);
            if (val > 120) { pairCode = val; durSec = 15; }
            else { durSec = (int)val; }
        }
        if (durSec <= 0) durSec = 15;
        rfSubsystem.startPairing(pairCode, durSec);
        Serial.printf("RESP:{\"status\":\"ok\",\"pairing\":true,\"duration_sec\":%d,\"code\":%lu}\n", durSec, pairCode);
    } else if (cmd.equalsIgnoreCase("RF_PAIR_STOP") || cmd.equalsIgnoreCase("CMD:RF_PAIR_STOP")) {
        rfSubsystem.stopPairing();
        Serial.println("RESP:{\"status\":\"ok\",\"pairing\":false}");
    } else if (cmd.startsWith("RF_LEARN:START") || cmd.startsWith("CMD:RF_LEARN:START")) {
        int colIdx = cmd.lastIndexOf(':');
        int durSec = 600;
        if (colIdx != -1 && colIdx < cmd.length() - 1) {
            durSec = cmd.substring(colIdx + 1).toInt();
            if (durSec <= 0) durSec = 600;
        }
        rfSubsystem.startLearning(durSec);
        Serial.printf("RESP:{\"status\":\"ok\",\"rf_learning\":true,\"duration_sec\":%d}\n", durSec);
    } else if (cmd.equalsIgnoreCase("RF_LEARN:STOP") || cmd.equalsIgnoreCase("CMD:RF_LEARN:STOP")) {
        rfSubsystem.stopLearning();
        Serial.println("RESP:{\"status\":\"ok\",\"rf_learning\":false}");
    } else if (cmd.equalsIgnoreCase("RF_LEARN:STATUS") || cmd.equalsIgnoreCase("CMD:RF_LEARN:STATUS")) {
        Serial.printf("RESP:{\"status\":\"ok\",\"rf_learning\":%s,\"remaining_sec\":%d}\n",
                      rfSubsystem.isLearningActive() ? "true" : "false", rfSubsystem.getLearningRemainingSec());
    } else if (cmd.equalsIgnoreCase("CARRIER_ON") || cmd.equalsIgnoreCase("CMD:CARRIER_ON")) {
        rfSubsystem.setCarrier(true);
    } else if (cmd.equalsIgnoreCase("CARRIER_OFF") || cmd.equalsIgnoreCase("CMD:CARRIER_OFF")) {
        rfSubsystem.setCarrier(false);
    } else if (cmd.equalsIgnoreCase("DIAG") || cmd.equalsIgnoreCase("CMD:DIAG") || cmd.equalsIgnoreCase("CMD:RF_DIAG") || cmd.equalsIgnoreCase("CMD:RF_STATUS") || cmd == "{\"command\":\"diagnostics\"}") {
        Serial.println("RESP:" + rfSubsystem.getDiagnosticsJson());
    } else if (cmd.equalsIgnoreCase("BLE_SCAN") || cmd.startsWith("CMD:BLE_SCAN")) {
        int duration = 15;
        int colIdx = cmd.lastIndexOf(':');
        if (colIdx != -1 && colIdx < cmd.length() - 1) {
            int d = cmd.substring(colIdx + 1).toInt();
            if (d > 0 && d <= 60) duration = d;
        }
        bleScanner.runActiveScan(duration);
    } else if (cmd.equalsIgnoreCase("STATUS") || cmd.equalsIgnoreCase("CMD:STATUS") || cmd == "{\"command\":\"status\"}") {
        Serial.println("RESP:" + buildTelemetryJson());
    } else if (cmd.equalsIgnoreCase("REBOOT") || cmd.equalsIgnoreCase("CMD:REBOOT")) {
        Serial.println("RESP:{\"status\":\"ok\",\"action\":\"rebooting\"}");
        delay(500);
        ESP.restart();
    }
}