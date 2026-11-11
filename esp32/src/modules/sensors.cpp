#include "sensors.h"

SensorsModule sensorsMod;

void SensorsModule::init() {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    if (aht.begin(&Wire)) {
        ahtAvailable = true;
        Serial.println("[AHT10] Датчик температури та вологості успішно знайдено.");
        update();
    } else {
        ahtAvailable = false;
        Serial.println("[AHT10] Помилка: AHT10 не знайдено на шині I2C.");
    }
}

void SensorsModule::update() {
    if (!ahtAvailable) return;
    unsigned long now = millis();
    if (lastReadTime != 0 && (now - lastReadTime < 5000)) return; // Мінімум 5 секунд між зчитуваннями

    sensors_event_t humidity_ev, temp_ev;
    if (aht.getEvent(&humidity_ev, &temp_ev)) {
        float t = temp_ev.temperature;
        float h = humidity_ev.relative_humidity;
        if (t >= -30.0f && t <= 70.0f && h >= 0.0f && h <= 100.0f) {
            floor1_temp = t;
            floor1_hum = h;
            floor1_valid = true;
            lastReadTime = now;
        }
    }
}