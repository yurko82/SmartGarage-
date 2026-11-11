#pragma once

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <BLEClient.h>
#include <BLERemoteService.h>
#include <BLERemoteCharacteristic.h>
#include <ArduinoJson.h>
#include "config.h"

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

class BleScannerModule {
public:
    void init();
    void update();
    void runActiveScan(int scanDuration = 15);
    bool readSensor(int idx);
    void pollAllSensors();

    int getSensorCount() const { return NUM_SENSORS; }
    const BleFloorSensor& getSensor(int idx) const { return sensors[idx]; }

private:
    static const int NUM_SENSORS = 2;
    BleFloorSensor sensors[NUM_SENSORS] = {
        {BLE_MAC_FLOOR2, "2-й поверх", "floor2", 0.0f, 0.0f, 0, false, 0},
        {BLE_MAC_BASEMENT, "Підвал", "basement", 0.0f, 0.0f, 0, false, 0}
    };

    BLEScan* pBLEScan = nullptr;
    BLEClient* pBleClient = nullptr;
    unsigned long lastPollTime = 0;
    bool initialPollDone = false;
};

extern BleScannerModule bleScanner;