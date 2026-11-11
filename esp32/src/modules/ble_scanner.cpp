#include "ble_scanner.h"

BleScannerModule bleScanner;

static BLEUUID envServiceUUID("ebe0ccb0-7a0a-4b0c-8a1a-6ff2997da3a6");
static BLEUUID envCharUUID("ebe0ccc1-7a0a-4b0c-8a1a-6ff2997da3a6");
static BLEUUID batServiceUUID((uint16_t)0x180f);
static BLEUUID batCharUUID((uint16_t)0x2a19);

class BleScanLogger : public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice advertisedDevice) override {
        String mac = advertisedDevice.getAddress().toString().c_str();
        mac.toUpperCase();
        String name = advertisedDevice.haveName() ? advertisedDevice.getName().c_str() : "";
        int rssi = advertisedDevice.getRSSI();
        String uuid = advertisedDevice.haveServiceUUID() ? advertisedDevice.getServiceUUID().toString().c_str() : "";
        Serial.printf("BLE_DEVICE:mac=%s|name=%s|rssi=%d|uuid=%s\n", mac.c_str(), name.c_str(), rssi, uuid.c_str());
    }
};

void BleScannerModule::init() {
    if (pBLEScan == nullptr) {
        BLEDevice::init("SmartGarage-ESP32");
        pBLEScan = BLEDevice::getScan();
        pBLEScan->setActiveScan(true);
        pBLEScan->setInterval(100);
        pBLEScan->setWindow(99);
    }
}

void BleScannerModule::runActiveScan(int scanDuration) {
    init();
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
        d["mac"] = mac;
        d["name"] = dev.haveName() ? dev.getName().c_str() : "";
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

bool BleScannerModule::readSensor(int idx) {
    if (idx < 0 || idx >= NUM_SENSORS) return false;
    BleFloorSensor &s = sensors[idx];
    init();

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

    if (!pBleClient->connect(pAddress)) {
        Serial.printf("[BLE] Connection failed to %s\n", s.name);
        return false;
    }

    BLERemoteService* pEnvService = pBleClient->getService(envServiceUUID);
    if (pEnvService != nullptr) {
        BLERemoteCharacteristic* pEnvChar = pEnvService->getCharacteristic(envCharUUID);
        if (pEnvChar != nullptr && pEnvChar->canRead()) {
            std::string value = pEnvChar->readValue();
            if (value.length() >= 4) {
                const uint8_t* data = (const uint8_t*)value.data();
                int16_t tempRaw = (int16_t)(data[0] | (data[1] << 8));
                uint16_t humRaw = (uint16_t)(data[2] | (data[3] << 8));

                s.temp = tempRaw / 100.0f;
                s.hum = humRaw / 100.0f;
                s.online = true;
                s.lastUpdated = millis();
                Serial.printf("[BLE] %s -> Temp: %.1f C, Hum: %.1f %%\n", s.name, s.temp, s.hum);
            }
        }
    }

    BLERemoteService* pBatService = pBleClient->getService(batServiceUUID);
    if (pBatService != nullptr) {
        BLERemoteCharacteristic* pBatChar = pBatService->getCharacteristic(batCharUUID);
        if (pBatChar != nullptr && pBatChar->canRead()) {
            std::string batVal = pBatChar->readValue();
            if (batVal.length() >= 1) {
                s.battery = (uint8_t)batVal[0];
            }
        }
    }

    pBleClient->disconnect();
    return true;
}

void BleScannerModule::pollAllSensors() {
    Serial.println("[BLE] Початок періодичного опитування бездротових термометрів...");
    for (int i = 0; i < NUM_SENSORS; i++) {
        readSensor(i);
        delay(250);
    }
    lastPollTime = millis();
}

void BleScannerModule::update() {
    unsigned long now = millis();
    if (!initialPollDone && now >= 5000) {
        initialPollDone = true;
        pollAllSensors();
    } else if (initialPollDone && (now - lastPollTime >= BLE_POLL_INTERVAL)) {
        pollAllSensors();
    }
}