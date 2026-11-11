volatile unsigned long g_rf_edge_count = 0;
#include "rf_subsystem.h"
#include "gate_controller.h"

RfSubsystem rfSubsystem;

bool RfSubsystem::autoDetectPins() {
    uint8_t perms[6][3] = {
        {11, 12, 13}, // 0: MOSI=11, SCK=12, MISO=13 (стандарт)
        {12, 11, 13}, // 1: MOSI=12, SCK=11, MISO=13
        {13, 12, 11}, // 2: MOSI=13, SCK=12, MISO=11
        {11, 13, 12}, // 3: MOSI=11, SCK=13, MISO=12
        {12, 13, 11}, // 4: MOSI=12, SCK=13, MISO=11
        {13, 11, 12}  // 5: MOSI=13, SCK=11, MISO=12
    };

    uint8_t csn_options[2] = {10, 7};

    for (int c = 0; c < 2; c++) {
        uint8_t csn = csn_options[c];
        uint8_t gdo0 = (csn == 10) ? 7 : 10;

        pinMode(csn, OUTPUT);
        digitalWrite(csn, HIGH);

        for (int p = 0; p < 6; p++) {
            uint8_t mosi = perms[p][0];
            uint8_t sck  = perms[p][1];
            uint8_t miso = perms[p][2];

            pinMode(sck, OUTPUT);
            pinMode(mosi, OUTPUT);
            pinMode(miso, INPUT_PULLUP);
            digitalWrite(sck, LOW);
            digitalWrite(mosi, LOW);

            digitalWrite(csn, LOW);
            delayMicroseconds(50);

            uint8_t cmd = 0xF1;
            for (int i = 7; i >= 0; i--) {
                digitalWrite(mosi, (cmd >> i) & 1);
                delayMicroseconds(5);
                digitalWrite(sck, HIGH);
                delayMicroseconds(5);
                digitalWrite(sck, LOW);
                delayMicroseconds(5);
            }

            uint8_t ver = 0;
            for (int i = 7; i >= 0; i--) {
                digitalWrite(mosi, 0);
                delayMicroseconds(5);
                digitalWrite(sck, HIGH);
                delayMicroseconds(5);
                ver = (ver << 1) | digitalRead(miso);
                digitalWrite(sck, LOW);
                delayMicroseconds(5);
            }
            digitalWrite(csn, HIGH);
            delayMicroseconds(50);

            if (ver == 0x14 || ver == 0x34 || (ver > 0 && ver != 0xFF && (ver & 0x0F) == 0x04)) {
                pin_csn = csn;
                pin_mosi = mosi;
                pin_sck = sck;
                pin_miso = miso;
                pin_gdo0 = gdo0;
                Serial.printf("[AUTO_DETECT] CC1101 (VER=0x%02X) знайдено на CSN=%d, MOSI=%d, SCK=%d, MISO=%d, GDO0=%d\n",
                              ver, csn, mosi, sck, miso, gdo0);
                return true;
            }
        }
    }
    return false;
}

void RfSubsystem::init() {
    bool ccFound = autoDetectPins();
    ELECHOUSE_cc1101.setSpiPin(pin_sck, pin_miso, pin_mosi, pin_csn);
    ELECHOUSE_cc1101.setGDO0(pin_gdo0);

    if (ccFound || ELECHOUSE_cc1101.getCC1101()) {
        ELECHOUSE_cc1101.Init();
        ELECHOUSE_cc1101.setMHZ(RF_FREQUENCY);
        ELECHOUSE_cc1101.setModulation(2); // ASK/OOK
        ELECHOUSE_cc1101.setRxBW(650.0);   // 650 кГц смуга пропускання за TI DN022
        ELECHOUSE_cc1101.setPA(12);

        enableReceive();
        mySwitch.setReceiveTolerance(80);
        cc1101Available = true;
        gateCtrl.setLedColor(0, 160, 255); // Яскравий бірюзовий: слухання ефіру
        Serial.printf("[CC1101] Модуль 433.92 МГц ініціалізовано (CSN=%d, MOSI=%d, SCK=%d, MISO=%d, GDO0=%d).\n",
                      pin_csn, pin_mosi, pin_sck, pin_miso, pin_gdo0);
    } else {
        cc1101Available = false;
        gateCtrl.setLedColor(40, 0, 0); // Червоний: помилка CC1101
        Serial.println("[CC1101] Помилка: CC1101 не відповідає.");
    }
}

void RfSubsystem::enableReceive() {
    pinMode(pin_gdo0, INPUT);
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x0D);   // GDO0 = Serial Data Output
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_MDMCFG2, 0x30);  // ASK/OOK, no sync word
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_PKTCTRL0, 0x32); // Asynchronous serial mode
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_MCSM1, 0x0C);    // RXOFF_MODE=11
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_AGCCTRL2, 0x03); // TI DN022: DVGA
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_AGCCTRL1, 0x00); // TI DN022: no CS lock
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_AGCCTRL0, 0x92); // TI DN022: 4-filter averaging, 8dB boundary
    ELECHOUSE_cc1101.SpiWriteReg(CC1101_FREND1, 0xB6);   // TI DN022: mixer opt
    ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
    ELECHOUSE_cc1101.SpiStrobe(CC1101_SFRX);
    ELECHOUSE_cc1101.SpiStrobe(CC1101_SRX);
    delayMicroseconds(1000);
    mySwitch.enableReceive(digitalPinToInterrupt(pin_gdo0));
}

void RfSubsystem::disableReceive() {
    mySwitch.disableReceive();
}

void RfSubsystem::transmitCode(unsigned long code, unsigned int repeats) {
    if (!cc1101Available) return;
    disableReceive();

    ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x2E);
    pinMode(pin_gdo0, OUTPUT);
    digitalWrite(pin_gdo0, LOW);

    ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
    delayMicroseconds(200);
    ELECHOUSE_cc1101.SpiStrobe(CC1101_STX);

    unsigned long startWait = micros();
    while (((ELECHOUSE_cc1101.SpiReadStatus(0x35) & 0x1F) != 0x13) && (micros() - startWait < 5000)) {
        delayMicroseconds(50);
    }

    mySwitch.enableTransmit(pin_gdo0);
    mySwitch.setPulseLength(RF_PULSE_LENGTH);
    mySwitch.setRepeatTransmit(repeats);
    mySwitch.send(code, 24);
    mySwitch.disableTransmit();

    pinMode(pin_gdo0, INPUT);
    enableReceive();

    Serial.printf("[RF433] Сигнал 0x%lX (%lu) надіслано в ефір (повторів=%u)\n", code, code, repeats);
}

void RfSubsystem::transmitLight(bool state) {
    unsigned long code = state ? RF_CODE_LIGHT_ON : RF_CODE_LIGHT_OFF;
    transmitCode(code, 10);
    Serial.printf("[RF433] Сигнал світла %s надіслано в ефір (код: 0x%lX)\n", state ? "ON" : "OFF", code);
}

void RfSubsystem::setCarrier(bool enable) {
    if (!cc1101Available) return;
    disableReceive();
    if (enable) {
        ELECHOUSE_cc1101.SpiWriteReg(CC1101_IOCFG0, 0x2E);
        pinMode(pin_gdo0, OUTPUT);
        digitalWrite(pin_gdo0, HIGH);
        ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
        delay(1);
        ELECHOUSE_cc1101.SpiStrobe(CC1101_STX);
        gateCtrl.setLedColor(180, 0, 0); // Червоний: несуча активна
        Serial.println("RESP:{\"status\":\"ok\",\"carrier\":true,\"freq\":433.92}");
    } else {
        pinMode(pin_gdo0, INPUT);
        enableReceive();
        gateCtrl.setLedColor(0, 160, 255);
        Serial.println("RESP:{\"status\":\"ok\",\"carrier\":false}");
    }
}

void RfSubsystem::startPairing(unsigned long code, int durationSec) {
    rfPairingCode = code;
    rfPairingActive = true;
    rfPairingEndTime = millis() + (unsigned long)durationSec * 1000UL;
    lastPairSendTime = 0;
}

void RfSubsystem::stopPairing() {
    rfPairingActive = false;
    gateCtrl.setLedColor(0, 160, 255);
}

void RfSubsystem::startLearning(int durationSec) {
    rfLearningActive = true;
    rfLearningEndTime = millis() + (unsigned long)durationSec * 1000UL;
    gateCtrl.setLedColor(140, 0, 200); // Фіолетовий: режим навчання
}

void RfSubsystem::stopLearning() {
    rfLearningActive = false;
    gateCtrl.setLedColor(0, 160, 255);
}

int RfSubsystem::getLearningRemainingSec() const {
    if (!rfLearningActive) return 0;
    long rem = (long)((rfLearningEndTime - millis()) / 1000);
    return rem > 0 ? (int)rem : 0;
}

String RfSubsystem::getDiagnosticsJson() {
    enableReceive();
    delay(10);
    byte ver = ELECHOUSE_cc1101.SpiReadStatus(0x31);
    byte marc = ELECHOUSE_cc1101.SpiReadStatus(0x35) & 0x1F;
    int rssi = ELECHOUSE_cc1101.getRssi();
    int gdo0 = digitalRead(pin_gdo0);

    char buf[256];
    snprintf(buf, sizeof(buf),
             "{\"diag\":\"spi_active\",\"ver\":\"0x%02X\",\"marc\":%d,\"rssi\":%d,\"gdo0\":%d,\"csn\":%d,\"mosi\":%d,\"sck\":%d,\"miso\":%d}",
             ver, marc, rssi, gdo0, pin_csn, pin_mosi, pin_sck, pin_miso);
    return String(buf);
}

void RfSubsystem::update() {
    unsigned long now = millis();

    // 1. Безперервне сполучення (Pairing Mode)
    if (rfPairingActive) {
        if (now < rfPairingEndTime) {
            if (now - lastPairSendTime >= 120) {
                lastPairSendTime = now;
                transmitCode(rfPairingCode, 4);
                gateCtrl.setLedColor(140, 0, 140);
            }
        } else {
            stopPairing();
            Serial.println("[RF_PAIR] Режим безперервного сполучення завершено (таймаут).");
        }
    }

    // 2. Таймаут навчання
    if (rfLearningActive && now > rfLearningEndTime) {
        stopLearning();
        Serial.println("[RF_LEARN] Режим навчання завершено (таймаут).");
    }

    if (!cc1101Available) return;

    // 3. Автоматичний Keep-Alive для RX режиму CC1101
    if (!rfPairingActive && (now - lastRxKeepAlive >= 200)) {
        lastRxKeepAlive = now;
        byte marc = ELECHOUSE_cc1101.SpiReadStatus(0x35) & 0x1F;
        if (marc != 0x0D) {
            ELECHOUSE_cc1101.SpiStrobe(CC1101_SIDLE);
            ELECHOUSE_cc1101.SpiStrobe(CC1101_SFRX);
            ELECHOUSE_cc1101.SpiStrobe(CC1101_SRX);
        }
    }

    // 4. Декодування через RCSwitch
    if (mySwitch.available()) {
        unsigned long val = mySwitch.getReceivedValue();
        unsigned int bits = mySwitch.getReceivedBitlength();
        unsigned int proto = mySwitch.getReceivedProtocol();
        unsigned int delayVal = mySwitch.getReceivedDelay();
        mySwitch.resetAvailable();
        g_rf_raw_capture.ready = false;

        if (val != 0) {
            Serial.printf("[RF_RX] Код: %lu (0x%lX) | Біти: %u | Протокол: %u | Затримка: %u\n", val, val, bits, proto, delayVal);
            if (rfLearningActive) {
                Serial.printf("[RF_LEARN] {\"code\":%lu,\"hex\":\"0x%lX\",\"bits\":%u,\"proto\":%u,\"delay\":%u,\"mode\":\"rcswitch\"}\n",
                              val, val, bits, proto, delayVal);
            }
            gateCtrl.setLedColor(0, 200, 0); // Зелений
            currentLedState = 2;
            ledResetTime = now + 1500;
        }
    }
    // 5. Адаптивне декодування raw пульсів
    else if (g_rf_raw_capture.ready) {
        unsigned int count = g_rf_raw_capture.count;
        unsigned int sync = g_rf_raw_capture.sync;
        unsigned long decodedCode = 0;
        unsigned int decodedBits = 0;
        bool decodeSuccess = false;

        if (count >= 16) {
            bool validPattern = true;
            for (unsigned int i = 1; i + 1 < count; i += 2) {
                unsigned int t1 = g_rf_raw_capture.timings[i];
                unsigned int t2 = g_rf_raw_capture.timings[i+1];
                unsigned int longer = (t1 > t2) ? t1 : t2;
                unsigned int shorter = (t1 > t2) ? t2 : t1;
                if (shorter < 80 || shorter > 950 || longer < 300 || longer > 2800 || (longer / shorter < 2)) {
                    validPattern = false;
                    break;
                }
                bool bitVal = (t1 > t2);
                decodedCode = (decodedCode << 1) | (bitVal ? 1 : 0);
                decodedBits++;
                if (decodedBits >= 32) break;
            }
            if (validPattern && decodedBits >= 12) {
                decodeSuccess = true;
            }
        }

        if (decodeSuccess) {
            Serial.printf("[RF_RX_RAW] Розпізнано: 0x%lX (%lu) | Біти: %u | Sync: %u us\n", decodedCode, decodedCode, decodedBits, sync);
            gateCtrl.setLedColor(0, 200, 0);
            currentLedState = 2;
            ledResetTime = now + 1500;
        } else if (rfLearningActive && count >= 16) {
            Serial.printf("[RF_RX_RAW] Спіймано імпульси в режимі навчання (%u імпульсів, sync=%u us)\n", count, sync);
        }
        g_rf_raw_capture.ready = false;
    }

    // 6. Скидання LED після індикації
    if (ledResetTime != 0 && now >= ledResetTime) {
        ledResetTime = 0;
        currentLedState = 0;
        if (!rfLearningActive && !rfPairingActive) {
            gateCtrl.setLedColor(0, 160, 255);
        }
    }
}