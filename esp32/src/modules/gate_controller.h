#pragma once

#include <Arduino.h>
#include "config.h"

class GateController {
public:
    void init();
    void setLedColor(uint8_t r, uint8_t g, uint8_t b);
    void triggerDoor(uint16_t pulseMs = 500);
    void setLight(bool state);
    void setFan(bool state);
    bool isLightOn() const { return lightState; }
    bool isFanOn() const { return fanState; }

private:
    bool lightState = false;
    bool fanState = false;
};

extern GateController gateCtrl;