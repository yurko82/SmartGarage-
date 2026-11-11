/*
 * Smart Garage Infrastructure — ESP32 / ESP32-S3 Firmware v2.0.0
 * Modular Architecture: GateController, Sensors, RfSubsystem, BleScanner, NetworkManager.
 */

#include <Arduino.h>
#include "config.h"
#include "modules/gate_controller.h"
#include "modules/sensors.h"
#include "modules/rf_subsystem.h"
#include "modules/ble_scanner.h"
#include "modules/network_manager.h"

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n[SmartGarage] ESP32-S3 Firmware v2.0.0 Starting...");

    // 1. Ініціалізація актуаторів (реле, RGB LED)
    gateCtrl.init();

    // 2. Ініціалізація локальних сенсорів (I2C AHT10)
    sensorsMod.init();

    // 3. Ініціалізація радіомодуля CC1101 (433.92 МГц)
    rfSubsystem.init();

    // 4. Ініціалізація BLE стеку
    bleScanner.init();

    // 5. Ініціалізація мережі (Wi-Fi, HTTP WebServer, MQTT)
    netManager.init();

    Serial.println("[SmartGarage] Усі модулі успішно ініціалізовано.");
}

void loop() {
    // 1. Обробка команд з USB Serial
    while (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        netManager.processSerialCommand(input);
    }

    // 2. Оновлення стану сенсорів та радіо
    sensorsMod.update();
    rfSubsystem.update();

    // 3. Періодичне опитування BLE датчиків
    bleScanner.update();

    // 4. Мережева активність (HTTP клієнти, MQTT loop, телеметрія)
    netManager.update();
}