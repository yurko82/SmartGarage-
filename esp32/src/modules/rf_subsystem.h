#pragma once

#include <Arduino.h>
#include <ELECHOUSE_CC1101_SRC_DRV.h>
#include <RCSwitch.h>
#include "config.h"

struct RfTxResult {
    bool tx_ok = false;
    uint8_t tx_state = 0;
    bool rx_restored = false;
};

class RfSubsystem {
public:
    void init();
    void update();
    
    void enableReceive();
    void disableReceive();
    
    RfTxResult transmitCode(unsigned long code, unsigned int repeats = 10);
    void transmitLight(bool state);
    void setCarrier(bool enable);
    
    void startPairing(unsigned long code, int durationSec);
    void stopPairing();
    bool isPairingActive() const { return rfPairingActive; }
    
    void startLearning(int durationSec);
    void stopLearning();
    bool isLearningActive() const { return rfLearningActive; }
    int getLearningRemainingSec() const;
    
    String getDiagnosticsJson();
    bool isAvailable() const { return cc1101Available; }
    void resetAndConfigure();

    void writeRegister(uint8_t addr, uint8_t val);
    uint8_t readRegister(uint8_t addr);

private:
    bool autoDetectPins();

    bool cc1101Available = false;
    uint8_t pin_sck  = PIN_CC1101_SCK;
    uint8_t pin_miso = PIN_CC1101_MISO;
    uint8_t pin_mosi = PIN_CC1101_MOSI;
    uint8_t pin_csn  = PIN_CC1101_CSN;
    uint8_t pin_gdo0 = PIN_CC1101_GDO0;

    RCSwitch mySwitch;

    bool rfPairingActive = false;
    unsigned long rfPairingEndTime = 0;
    unsigned long lastPairSendTime = 0;
    unsigned long rfPairingCode = RF_CODE_LIGHT_ON;

    bool rfLearningActive = false;
    unsigned long rfLearningEndTime = 0;

    unsigned long lastRxKeepAlive = 0;
    unsigned long lastRssiCheck = 0;
    unsigned long ledResetTime = 0;
    int currentLedState = 0;
};

extern RfSubsystem rfSubsystem;