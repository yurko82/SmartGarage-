#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include "config.h"

class SensorsModule {
public:
    void init();
    void update();
    bool isAhtAvailable() const { return ahtAvailable; }
    float getTemperature() const { return floor1_temp; }
    float getHumidity() const { return floor1_hum; }
    bool isValid() const { return floor1_valid; }

private:
    Adafruit_AHTX0 aht;
    bool ahtAvailable = false;
    float floor1_temp = 0.0f;
    float floor1_hum = 0.0f;
    bool floor1_valid = false;
    unsigned long lastReadTime = 0;
};

extern SensorsModule sensorsMod;