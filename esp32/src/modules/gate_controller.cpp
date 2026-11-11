#include "gate_controller.h"

GateController gateCtrl;

void GateController::init() {
    pinMode(PIN_RELAY_DOOR, OUTPUT);
    pinMode(PIN_RELAY_LIGHT, OUTPUT);
    pinMode(PIN_RELAY_FAN, OUTPUT);

    digitalWrite(PIN_RELAY_DOOR, LOW);
    digitalWrite(PIN_RELAY_LIGHT, LOW);
    digitalWrite(PIN_RELAY_FAN, LOW);

    lightState = false;
    fanState = false;

    setLedColor(0, 0, 40); // Тьмяний синій при ініціалізації
}

void GateController::setLedColor(uint8_t r, uint8_t g, uint8_t b) {
    neopixelWrite(PIN_RGB_LED, r, g, b);
}

void GateController::triggerDoor(uint16_t pulseMs) {
    digitalWrite(PIN_RELAY_DOOR, HIGH);
    delay(pulseMs);
    digitalWrite(PIN_RELAY_DOOR, LOW);
}

void GateController::setLight(bool state) {
    lightState = state;
    digitalWrite(PIN_RELAY_LIGHT, state ? HIGH : LOW);
}

void GateController::setFan(bool state) {
    fanState = state;
    digitalWrite(PIN_RELAY_FAN, state ? HIGH : LOW);
}